"""
Day 5 - LLM client with GEMINI_API_KEY fallback.

Every LLM call in this project goes through here rather than instantiating
an OpenAI client directly (Day 4's pattern) - the primary "smart" model
(BASE_URL/API_KEY, same endpoint Day 4 already used) is tried first; on
ANY exception (timeout, auth failure, rate limit, empty response, ...) it
falls back to Gemini via the already-installed google-genai SDK. Raises
only if both fail, with both error messages included - same "honest
failure, not a silent guess" convention api.py's module docstring
describes for Day 4.

generate_with_tools() does real LLM tool-calling (used by nodes.py's rag
and recommendation nodes) - on primary failure it falls back to Gemini
WITH real tool access too (_call_gemini_with_tools), not an answer-only
guess, then to answer-only Gemini as a last resort before raising.
"""

import json
import os
import time
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv, find_dotenv
from openai import OpenAI
from google import genai
from google.genai import types as genai_types

load_dotenv(find_dotenv())

BASE_URL = os.getenv("BASE_URL")
API_KEY = os.getenv("API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
PRIMARY_MODEL = os.getenv("LLM_MODEL", "smart")

# The primary call must fail over to Gemini fast enough that the turn still
# has a shot at the <2s voice budget (Day 3's target). Without an explicit
# timeout the OpenAI SDK's own default is far longer than a phone call can
# tolerate - observed live as 30s+ single turns with no fallback triggered
# at all, since a slow-but-eventually-successful response never raises.
LLM_REQUEST_TIMEOUT = float(os.getenv("LLM_REQUEST_TIMEOUT", "8"))

# The OpenAI SDK retries failed/timed-out requests automatically
# (default max_retries=2) BEFORE raising - so a timeout alone doesn't bound
# elapsed time, it multiplies it: an 8s timeout with the SDK default retry
# count means up to 3 attempts (~24s) before this even reaches the Gemini
# fallback, plus Gemini's own latency on top. That's what actually produced
# the 30-40s turns seen live even after LLM_REQUEST_TIMEOUT was added - the
# timeout was working exactly as configured, the retry count on top of it
# wasn't. Explicitly zeroing retries here means one slow/failed attempt
# fails over to Gemini immediately instead of trying the same slow endpoint
# 2 more times first.
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "0"))

_primary_client: Optional[OpenAI] = None
_gemini_client = None


def _get_primary_client() -> OpenAI:
    global _primary_client
    if _primary_client is None:
        if not BASE_URL or not API_KEY:
            raise RuntimeError("BASE_URL / API_KEY are not set in .env")
        _primary_client = OpenAI(
            base_url=BASE_URL, api_key=API_KEY,
            timeout=LLM_REQUEST_TIMEOUT, max_retries=LLM_MAX_RETRIES,
        )
    return _primary_client


def _history_to_messages(history: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    """Converts AgentState's conversation_history shape
    ([{"speaker": "customer"|"agent", "text": ...}]) into OpenAI-style chat
    messages, so the model sees actual prior turns instead of only this
    turn's text in isolation - without this, every reply reads like the
    start of a fresh call no matter how far into the conversation it is.
    Caller is responsible for trimming to a reasonable window (see
    nodes.py's _recent_history())."""
    if not history:
        return []
    role_map = {"customer": "user", "agent": "assistant"}
    return [
        {"role": role_map.get(turn.get("speaker"), "user"), "content": turn.get("text", "")}
        for turn in history if turn.get("text")
    ]


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set in .env")
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client


def _call_gemini(system_prompt: Optional[str], user_prompt: str) -> str:
    client = _get_gemini_client()
    config = genai_types.GenerateContentConfig(system_instruction=system_prompt) if system_prompt else None
    resp = client.models.generate_content(model=GEMINI_MODEL, contents=user_prompt, config=config)
    return resp.text or ""


def _openai_tool_to_gemini_declaration(openai_tool: Dict[str, Any]) -> "genai_types.FunctionDeclaration":
    """Reuses the SAME OpenAI-format schema tools.py already builds via
    langchain_core's convert_to_openai_tool - no second, hand-maintained
    Gemini-specific schema to drift out of sync with the real tool
    signature. parameters_json_schema accepts a raw JSON-schema dict
    directly (confirmed against the installed google-genai SDK's
    FunctionDeclaration fields), so this is a reshape, not a lossy manual
    conversion into Gemini's own Schema object type."""
    fn = openai_tool["function"]
    return genai_types.FunctionDeclaration(
        name=fn["name"], description=fn.get("description", ""),
        parameters_json_schema=fn.get("parameters", {}),
    )


def _history_to_gemini_contents(history: Optional[List[Dict[str, str]]]) -> List["genai_types.Content"]:
    if not history:
        return []
    role_map = {"customer": "user", "agent": "model"}  # Gemini uses "model", not "assistant"
    return [
        genai_types.Content(role=role_map.get(turn.get("speaker"), "user"),
                             parts=[genai_types.Part(text=turn.get("text", ""))])
        for turn in history if turn.get("text")
    ]


def _call_gemini_with_tools(system_prompt: Optional[str], user_prompt: str,
                             openai_tools: List[Dict[str, Any]],
                             tool_executor: Callable[[str, Dict[str, Any]], Any],
                             history: Optional[List[Dict[str, str]]] = None,
                             max_rounds: int = 3) -> str:
    """Real Gemini function-calling, not an answer-only fallback -
    confirmed a real gap: recommendation_node needs the fallback path to
    actually be able to call search_property_tool with the right filters
    (e.g. property_type), not just answer from the model's own knowledge
    with no data to ground it in. UNTESTED against a live API in the
    sandbox this was written in (no network path to Gemini) - verify
    against a real run before trusting this in production; if the
    function-calling shape is wrong for the installed SDK version, this
    raises and generate_with_tools()'s caller falls through to the
    older answer-only Gemini call, then finally to nodes.py's own
    deterministic template - never a silent failure, same convention as
    every other fallback in this module."""
    client = _get_gemini_client()
    declarations = [_openai_tool_to_gemini_declaration(t) for t in openai_tools]
    config = genai_types.GenerateContentConfig(
        system_instruction=system_prompt, tools=[genai_types.Tool(function_declarations=declarations)],
    )

    contents = _history_to_gemini_contents(history)
    contents.append(genai_types.Content(role="user", parts=[genai_types.Part(text=user_prompt)]))

    for _ in range(max_rounds):
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=contents, config=config)
        candidate = resp.candidates[0]
        parts = candidate.content.parts or []
        function_calls = [p.function_call for p in parts if p.function_call is not None]
        if not function_calls:
            return resp.text or ""

        contents.append(candidate.content)  # the model's own turn, including the function_call part(s)
        response_parts = [
            genai_types.Part(function_response=genai_types.FunctionResponse(
                name=fc.name, response={"result": tool_executor(fc.name, fc.args or {})},
            ))
            for fc in function_calls
        ]
        contents.append(genai_types.Content(role="user", parts=response_parts))

    # ran out of tool-call rounds - force a final answer, no tools offered
    final_config = genai_types.GenerateContentConfig(system_instruction=system_prompt)
    resp = client.models.generate_content(model=GEMINI_MODEL, contents=contents, config=final_config)
    return resp.text or ""


def generate_reply(system_prompt: Optional[str], user_prompt: str,
                    history: Optional[List[Dict[str, str]]] = None) -> str:
    """Plain (non-tool-calling) generation with automatic provider fallback.
    `history` (optional) is prior conversation turns, inserted as real chat
    messages before user_prompt so the model has actual conversational
    context - see nodes.py's recommendation_node/rag_node for why this
    matters (a reply generated without it re-greets the customer every
    turn, since the model has no signal a call is already in progress)."""
    t0 = time.monotonic()
    try:
        client = _get_primary_client()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(_history_to_messages(history))
        messages.append({"role": "user", "content": user_prompt})
        resp = client.chat.completions.create(model=PRIMARY_MODEL, messages=messages)
        content = resp.choices[0].message.content
        if not content:
            raise RuntimeError("primary model returned an empty response")
        print(f"  [llm_client] primary ({PRIMARY_MODEL}) answered in {time.monotonic() - t0:.1f}s")
        return content
    except Exception as primary_err:
        print(f"  [llm_client] primary ({PRIMARY_MODEL}) failed after "
              f"{time.monotonic() - t0:.1f}s ({primary_err}), falling back to Gemini")
        t1 = time.monotonic()
        try:
            reply = _call_gemini(system_prompt, user_prompt)
            print(f"  [llm_client] Gemini fallback answered in {time.monotonic() - t1:.1f}s")
            return reply
        except Exception as fallback_err:
            raise RuntimeError(
                f"Both LLM providers failed. Primary ({PRIMARY_MODEL}): {primary_err}. "
                f"Gemini fallback ({GEMINI_MODEL}): {fallback_err}."
            ) from fallback_err


def generate_with_tools(system_prompt: Optional[str], user_prompt: str,
                         openai_tools: List[Dict[str, Any]],
                         tool_executor: Callable[[str, Dict[str, Any]], Any],
                         history: Optional[List[Dict[str, str]]] = None,
                         max_rounds: int = 3) -> str:
    """Manual tool-calling loop against the primary model: it either asks
    for a tool call or gives a final answer; tool_executor(name, args) runs
    the requested tool and the result is fed back in, up to max_rounds.

    On primary failure, falls back to Gemini WITH real tool access
    (_call_gemini_with_tools) - confirmed live this mattered: a
    tool-calling node's Gemini fallback used to be answer-only, so on
    primary failure it could never actually call search_property_tool at
    all, silently losing filters like property_type. If the tool-calling
    Gemini path itself fails (untested against a live API - see its
    docstring), falls through to the old answer-only Gemini call as a
    second safety net, then finally raises so nodes.py's own deterministic
    template takes over - the cascade only ever adds a fallback, never
    removes the one that was already here."""
    t0 = time.monotonic()
    try:
        client = _get_primary_client()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(_history_to_messages(history))
        messages.append({"role": "user", "content": user_prompt})

        for _ in range(max_rounds):
            resp = client.chat.completions.create(
                model=PRIMARY_MODEL, messages=messages, tools=openai_tools,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                print(f"  [llm_client] primary ({PRIMARY_MODEL}) tool-calling "
                      f"answered in {time.monotonic() - t0:.1f}s")
                return msg.content or ""

            messages.append(msg.model_dump(exclude_none=True))
            for call in msg.tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = tool_executor(call.function.name, args)
                messages.append({
                    "role": "tool", "tool_call_id": call.id,
                    "content": json.dumps(result, default=str),
                })

        # ran out of tool-call rounds - force a final answer, no more tools offered
        resp = client.chat.completions.create(model=PRIMARY_MODEL, messages=messages)
        print(f"  [llm_client] primary ({PRIMARY_MODEL}) tool-calling "
              f"answered in {time.monotonic() - t0:.1f}s (forced final round)")
        return resp.choices[0].message.content or ""
    except Exception as primary_err:
        print(f"  [llm_client] primary ({PRIMARY_MODEL}) tool-calling failed after "
              f"{time.monotonic() - t0:.1f}s ({primary_err}), falling back to Gemini (with tool access)")
        t1 = time.monotonic()
        try:
            reply = _call_gemini_with_tools(system_prompt, user_prompt, openai_tools, tool_executor, history=history)
            print(f"  [llm_client] Gemini tool-calling fallback answered in {time.monotonic() - t1:.1f}s")
            return reply
        except Exception as gemini_tools_err:
            print(f"  [llm_client] Gemini tool-calling fallback failed ({gemini_tools_err}), "
                  f"trying answer-only Gemini as a last resort")
            t2 = time.monotonic()
            try:
                reply = _call_gemini(system_prompt, user_prompt)
                print(f"  [llm_client] Gemini answer-only fallback answered in {time.monotonic() - t2:.1f}s")
                return reply
            except Exception as fallback_err:
                raise RuntimeError(
                    f"All LLM fallback tiers failed for a tool-calling request. "
                    f"Primary ({PRIMARY_MODEL}): {primary_err}. "
                    f"Gemini with tools ({GEMINI_MODEL}): {gemini_tools_err}. "
                    f"Gemini answer-only: {fallback_err}."
                ) from fallback_err


if __name__ == "__main__":
    print(generate_reply("You are a terse assistant.", "Say 'ok' and nothing else."))