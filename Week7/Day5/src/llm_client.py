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

generate_with_tools() is the one function that does real LLM tool-calling
(used by nodes.py's RAG node) - see its docstring for why the Gemini
fallback there is answer-only, not tool-calling itself.
"""

import json
import os
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

_primary_client: Optional[OpenAI] = None
_gemini_client = None


def _get_primary_client() -> OpenAI:
    global _primary_client
    if _primary_client is None:
        if not BASE_URL or not API_KEY:
            raise RuntimeError("BASE_URL / API_KEY are not set in .env")
        _primary_client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
    return _primary_client


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


def generate_reply(system_prompt: Optional[str], user_prompt: str) -> str:
    """Plain (non-tool-calling) generation with automatic provider fallback."""
    try:
        client = _get_primary_client()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        resp = client.chat.completions.create(model=PRIMARY_MODEL, messages=messages)
        content = resp.choices[0].message.content
        if not content:
            raise RuntimeError("primary model returned an empty response")
        return content
    except Exception as primary_err:
        try:
            return _call_gemini(system_prompt, user_prompt)
        except Exception as fallback_err:
            raise RuntimeError(
                f"Both LLM providers failed. Primary ({PRIMARY_MODEL}): {primary_err}. "
                f"Gemini fallback ({GEMINI_MODEL}): {fallback_err}."
            ) from fallback_err


def generate_with_tools(system_prompt: Optional[str], user_prompt: str,
                         openai_tools: List[Dict[str, Any]],
                         tool_executor: Callable[[str, Dict[str, Any]], Any],
                         max_rounds: int = 3) -> str:
    """Manual tool-calling loop against the primary model: it either asks
    for a tool call or gives a final answer; tool_executor(name, args) runs
    the requested tool and the result is fed back in, up to max_rounds.

    The Gemini fallback here is answer-only (system_prompt + user_prompt,
    no tool access), used only if the PRIMARY call fails outright before
    ever producing a response. This project's tool schemas are defined
    once (langchain_core @tool + convert_to_openai_tool, see tools.py) in
    OpenAI's function-calling format; duplicating that translation for
    Gemini's function-calling shape just to cover an already-rare "primary
    provider is down AND the customer needs a tool-backed answer at that
    exact moment" case isn't worth the added surface for this checkpoint -
    the fallback still answers from the model's own knowledge/persona
    rather than leaving the turn silent, it just can't look anything up."""
    try:
        client = _get_primary_client()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        for _ in range(max_rounds):
            resp = client.chat.completions.create(
                model=PRIMARY_MODEL, messages=messages, tools=openai_tools,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
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
        return resp.choices[0].message.content or ""
    except Exception as primary_err:
        try:
            return _call_gemini(system_prompt, user_prompt)
        except Exception as fallback_err:
            raise RuntimeError(
                f"Both LLM providers failed for a tool-calling request. "
                f"Primary ({PRIMARY_MODEL}): {primary_err}. "
                f"Gemini fallback ({GEMINI_MODEL}, no tool access): {fallback_err}."
            ) from fallback_err


if __name__ == "__main__":
    print(generate_reply("You are a terse assistant.", "Say 'ok' and nothing else."))
