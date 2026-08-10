
"""
LLM client with a 3-tier automatic fallback chain.

Provider order:
    1. Groq       - primary, optimized for low-latency voice responses
    2. Gemini     - secondary fallback
    3. Company API - final fallback

Every LLM call in the project should go through this module rather than
instantiating a provider client directly.

Groq and the company API are OpenAI-compatible, so they share the same
tool-calling implementation. Gemini uses the google-genai SDK and has its
own tool-calling implementation.

On provider failure (timeout, authentication error, rate limit, empty
response, etc.), the request automatically moves to the next provider.

If every provider fails, a RuntimeError is raised rather than returning
an ungrounded or fabricated response.
"""

import json
import os
import time
from typing import Any, Callable, Dict, List, Optional

from dotenv import find_dotenv, load_dotenv
from openai import OpenAI
from google import genai
from google.genai import types as genai_types


load_dotenv(find_dotenv())


# ============================================================
# CONFIGURATION
# ============================================================

# ----------------------------
# Groq - PRIMARY
# ----------------------------

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


# ----------------------------
# Gemini - SECOND FALLBACK
# ----------------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")


# ----------------------------
# Company API - LAST FALLBACK
# ----------------------------

BASE_URL = os.getenv("BASE_URL")
API_KEY = os.getenv("API_KEY")
COMPANY_MODEL = os.getenv("LLM_MODEL", "fast")


# ----------------------------
# Shared timeout / retry config
# ----------------------------

LLM_REQUEST_TIMEOUT = float(
    os.getenv("LLM_REQUEST_TIMEOUT", "8")
)

LLM_MAX_RETRIES = int(
    os.getenv("LLM_MAX_RETRIES", "0")
)


# ============================================================
# LAZY CLIENTS
# ============================================================

_groq_client: Optional[OpenAI] = None
_gemini_client = None
_company_client: Optional[OpenAI] = None


def _get_groq_client() -> OpenAI:
    """Create the Groq client lazily."""

    global _groq_client

    if _groq_client is None:
        if not GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY is not set in .env"
            )

        _groq_client = OpenAI(
            base_url=GROQ_BASE_URL,
            api_key=GROQ_API_KEY,
            timeout=LLM_REQUEST_TIMEOUT,
            max_retries=LLM_MAX_RETRIES,
        )

    return _groq_client


def _get_gemini_client():
    """Create the Gemini client lazily."""

    global _gemini_client

    if _gemini_client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set in .env"
            )

        _gemini_client = genai.Client(
            api_key=GEMINI_API_KEY
        )

    return _gemini_client


def _get_company_client() -> OpenAI:
    """Create the company API client lazily."""

    global _company_client

    if _company_client is None:
        if not BASE_URL or not API_KEY:
            raise RuntimeError(
                "BASE_URL / API_KEY are not set in .env"
            )

        _company_client = OpenAI(
            base_url=BASE_URL,
            api_key=API_KEY,
            timeout=LLM_REQUEST_TIMEOUT,
            max_retries=LLM_MAX_RETRIES,
        )

    return _company_client


# ============================================================
# HISTORY CONVERSION
# ============================================================

def _history_to_messages(
    history: Optional[List[Dict[str, str]]]
) -> List[Dict[str, str]]:
    """
    Convert AgentState conversation history into OpenAI-style messages.

    Input:
        [
            {"speaker": "customer", "text": "..."},
            {"speaker": "agent", "text": "..."}
        ]

    Output:
        [
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."}
        ]
    """

    if not history:
        return []

    role_map = {
        "customer": "user",
        "agent": "assistant",
    }

    return [
        {
            "role": role_map.get(
                turn.get("speaker"),
                "user",
            ),
            "content": turn.get("text", ""),
        }
        for turn in history
        if turn.get("text")
    ]


def _history_to_gemini_contents(
    history: Optional[List[Dict[str, str]]]
) -> List["genai_types.Content"]:
    """Convert conversation history to Gemini content objects."""

    if not history:
        return []

    role_map = {
        "customer": "user",
        "agent": "model",
    }

    return [
        genai_types.Content(
            role=role_map.get(
                turn.get("speaker"),
                "user",
            ),
            parts=[
                genai_types.Part(
                    text=turn.get("text", "")
                )
            ],
        )
        for turn in history
        if turn.get("text")
    ]


# ============================================================
# GEMINI - NORMAL GENERATION
# ============================================================

def _call_gemini(
    system_prompt: Optional[str],
    user_prompt: str,
    history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Generate a normal response using Gemini."""

    client = _get_gemini_client()

    contents = _history_to_gemini_contents(history)

    contents.append(
        genai_types.Content(
            role="user",
            parts=[
                genai_types.Part(
                    text=user_prompt
                )
            ],
        )
    )

    config = None

    if system_prompt:
        config = genai_types.GenerateContentConfig(
            system_instruction=system_prompt
        )

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=config,
    )

    return response.text or ""


# ============================================================
# GEMINI TOOL DECLARATION
# ============================================================

def _openai_tool_to_gemini_declaration(
    openai_tool: Dict[str, Any],
) -> "genai_types.FunctionDeclaration":
    """
    Convert an OpenAI-format tool schema into Gemini's function
    declaration format.

    This allows the same tools created by tools.py to be used by
    both OpenAI-compatible providers and Gemini.
    """

    function = openai_tool["function"]

    return genai_types.FunctionDeclaration(
        name=function["name"],
        description=function.get(
            "description",
            "",
        ),
        parameters_json_schema=function.get(
            "parameters",
            {},
        ),
    )


# ============================================================
# GEMINI - TOOL CALLING
# ============================================================

def _call_gemini_with_tools(
    system_prompt: Optional[str],
    user_prompt: str,
    openai_tools: List[Dict[str, Any]],
    tool_executor: Callable[
        [str, Dict[str, Any]],
        Any,
    ],
    history: Optional[List[Dict[str, str]]] = None,
    max_rounds: int = 3,
) -> str:
    """
    Gemini generation with real function calling.

    Gemini can call the same property/RAG/business tools used by
    the OpenAI-compatible providers.
    """

    client = _get_gemini_client()

    declarations = [
        _openai_tool_to_gemini_declaration(tool)
        for tool in openai_tools
    ]

    config = genai_types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[
            genai_types.Tool(
                function_declarations=declarations
            )
        ],
    )

    contents = _history_to_gemini_contents(history)

    contents.append(
        genai_types.Content(
            role="user",
            parts=[
                genai_types.Part(
                    text=user_prompt
                )
            ],
        )
    )

    for _ in range(max_rounds):

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=config,
        )

        candidate = response.candidates[0]
        parts = candidate.content.parts or []

        function_calls = [
            part.function_call
            for part in parts
            if part.function_call is not None
        ]

        # Normal final response
        if not function_calls:
            return response.text or ""

        # Preserve Gemini's function-call message
        contents.append(candidate.content)

        response_parts = []

        for function_call in function_calls:

            result = tool_executor(
                function_call.name,
                function_call.args or {},
            )

            response_parts.append(
                genai_types.Part(
                    function_response=genai_types.FunctionResponse(
                        name=function_call.name,
                        response={
                            "result": result
                        },
                    )
                )
            )

        contents.append(
            genai_types.Content(
                role="user",
                parts=response_parts,
            )
        )

    # Tool loop exhausted. Ask Gemini for a final answer without tools.
    final_config = genai_types.GenerateContentConfig(
        system_instruction=system_prompt
    )

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=final_config,
    )

    return response.text or ""


# ============================================================
# OPENAI-COMPATIBLE TOOL LOOP
# ============================================================

def _run_tool_call_loop(
    client: OpenAI,
    model: str,
    messages: List[Dict[str, Any]],
    openai_tools: List[Dict[str, Any]],
    tool_executor: Callable[
        [str, Dict[str, Any]],
        Any,
    ],
    max_rounds: int = 3,
) -> str:
    """
    Shared tool-calling implementation for Groq and the company API.

    Both providers expose an OpenAI-compatible API.
    """

    for _ in range(max_rounds):

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=openai_tools,
        )

        message = response.choices[0].message

        if not message.tool_calls:
            return message.content or ""

        messages.append(
            message.model_dump(
                exclude_none=True
            )
        )

        for tool_call in message.tool_calls:

            try:
                arguments = json.loads(
                    tool_call.function.arguments or "{}"
                )
            except json.JSONDecodeError:
                arguments = {}

            result = tool_executor(
                tool_call.function.name,
                arguments,
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(
                        result,
                        default=str,
                    ),
                }
            )

    # Tool-call limit reached.
    # Force a final response without tools.
    response = client.chat.completions.create(
        model=model,
        messages=messages,
    )

    return response.choices[0].message.content or ""


# ============================================================
# NORMAL GENERATION
# ============================================================

def generate_reply(
    system_prompt: Optional[str],
    user_prompt: str,
    history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """
    Generate a response using the 3-tier fallback chain:

        1. Groq
        2. Gemini
        3. Company API

    This is the non-tool-calling path.
    """

    messages = []

    if system_prompt:
        messages.append(
            {
                "role": "system",
                "content": system_prompt,
            }
        )

    messages.extend(
        _history_to_messages(history)
    )

    messages.append(
        {
            "role": "user",
            "content": user_prompt,
        }
    )

    errors = []

    # ========================================================
    # 1. GROQ - PRIMARY
    # ========================================================

    start = time.monotonic()

    try:

        client = _get_groq_client()

        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
        )

        content = response.choices[0].message.content

        if not content:
            raise RuntimeError(
                "Groq returned an empty response"
            )

        elapsed = time.monotonic() - start

        print(
            f"  [llm_client] Groq PRIMARY "
            f"({GROQ_MODEL}) answered in {elapsed:.1f}s"
        )

        return content

    except Exception as error:

        elapsed = time.monotonic() - start

        print(
            f"  [llm_client] Groq PRIMARY failed "
            f"after {elapsed:.1f}s: {error}"
        )

        errors.append(
            f"Groq ({GROQ_MODEL}): {error}"
        )

    # ========================================================
    # 2. GEMINI - SECOND FALLBACK
    # ========================================================

    start = time.monotonic()

    try:

        content = _call_gemini(
            system_prompt,
            user_prompt,
            history,
        )

        if not content:
            raise RuntimeError(
                "Gemini returned an empty response"
            )

        elapsed = time.monotonic() - start

        print(
            f"  [llm_client] Gemini SECONDARY "
            f"({GEMINI_MODEL}) answered in {elapsed:.1f}s"
        )

        return content

    except Exception as error:

        elapsed = time.monotonic() - start

        print(
            f"  [llm_client] Gemini SECONDARY failed "
            f"after {elapsed:.1f}s: {error}"
        )

        errors.append(
            f"Gemini ({GEMINI_MODEL}): {error}"
        )

    # ========================================================
    # 3. COMPANY API - LAST FALLBACK
    # ========================================================

    start = time.monotonic()

    try:

        client = _get_company_client()

        response = client.chat.completions.create(
            model=COMPANY_MODEL,
            messages=messages,
        )

        content = response.choices[0].message.content

        if not content:
            raise RuntimeError(
                "Company API returned an empty response"
            )

        elapsed = time.monotonic() - start

        print(
            f"  [llm_client] Company API LAST FALLBACK "
            f"({COMPANY_MODEL}) answered in {elapsed:.1f}s"
        )

        return content

    except Exception as error:

        elapsed = time.monotonic() - start

        print(
            f"  [llm_client] Company API LAST FALLBACK failed "
            f"after {elapsed:.1f}s: {error}"
        )

        errors.append(
            f"Company API ({COMPANY_MODEL}): {error}"
        )

    # ========================================================
    # ALL PROVIDERS FAILED
    # ========================================================

    raise RuntimeError(
        "All LLM providers failed. "
        + " | ".join(errors)
    )


# ============================================================
# TOOL-CALLING GENERATION
# ============================================================

def generate_with_tools(
    system_prompt: Optional[str],
    user_prompt: str,
    openai_tools: List[Dict[str, Any]],
    tool_executor: Callable[
        [str, Dict[str, Any]],
        Any,
    ],
    history: Optional[List[Dict[str, str]]] = None,
    max_rounds: int = 3,
) -> str:
    """
    Generate a response with tools using the 3-tier fallback chain:

        1. Groq tool calling
        2. Gemini tool calling
        3. Company API tool calling

    All three providers have access to the same logical tools.
    """

    base_messages = []

    if system_prompt:
        base_messages.append(
            {
                "role": "system",
                "content": system_prompt,
            }
        )

    base_messages.extend(
        _history_to_messages(history)
    )

    base_messages.append(
        {
            "role": "user",
            "content": user_prompt,
        }
    )

    errors = []

    # ========================================================
    # 1. GROQ - PRIMARY
    # ========================================================

    start = time.monotonic()

    try:

        client = _get_groq_client()

        reply = _run_tool_call_loop(
            client=client,
            model=GROQ_MODEL,
            messages=list(base_messages),
            openai_tools=openai_tools,
            tool_executor=tool_executor,
            max_rounds=max_rounds,
        )

        if not reply:
            raise RuntimeError(
                "Groq returned an empty response"
            )

        elapsed = time.monotonic() - start

        print(
            f"  [llm_client] Groq PRIMARY "
            f"({GROQ_MODEL}) tool-calling answered "
            f"in {elapsed:.1f}s"
        )

        return reply

    except Exception as error:

        elapsed = time.monotonic() - start

        print(
            f"  [llm_client] Groq PRIMARY tool-calling "
            f"failed after {elapsed:.1f}s: {error}"
        )

        errors.append(
            f"Groq ({GROQ_MODEL}): {error}"
        )

    # ========================================================
    # 2. GEMINI - SECOND FALLBACK
    # ========================================================

    start = time.monotonic()

    try:

        reply = _call_gemini_with_tools(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            openai_tools=openai_tools,
            tool_executor=tool_executor,
            history=history,
            max_rounds=max_rounds,
        )

        if not reply:
            raise RuntimeError(
                "Gemini returned an empty response"
            )

        elapsed = time.monotonic() - start

        print(
            f"  [llm_client] Gemini SECONDARY "
            f"({GEMINI_MODEL}) tool-calling answered "
            f"in {elapsed:.1f}s"
        )

        return reply

    except Exception as error:

        elapsed = time.monotonic() - start

        print(
            f"  [llm_client] Gemini SECONDARY "
            f"tool-calling failed after {elapsed:.1f}s: {error}"
        )

        errors.append(
            f"Gemini ({GEMINI_MODEL}): {error}"
        )

    # ========================================================
    # 3. COMPANY API - LAST FALLBACK
    # ========================================================

    start = time.monotonic()

    try:

        client = _get_company_client()

        reply = _run_tool_call_loop(
            client=client,
            model=COMPANY_MODEL,
            messages=list(base_messages),
            openai_tools=openai_tools,
            tool_executor=tool_executor,
            max_rounds=max_rounds,
        )

        if not reply:
            raise RuntimeError(
                "Company API returned an empty response"
            )

        elapsed = time.monotonic() - start

        print(
            f"  [llm_client] Company API LAST FALLBACK "
            f"({COMPANY_MODEL}) tool-calling answered "
            f"in {elapsed:.1f}s"
        )

        return reply

    except Exception as error:

        elapsed = time.monotonic() - start

        print(
            f"  [llm_client] Company API LAST FALLBACK "
            f"tool-calling failed after {elapsed:.1f}s: {error}"
        )

        errors.append(
            f"Company API ({COMPANY_MODEL}): {error}"
        )

    # ========================================================
    # ALL PROVIDERS FAILED
    # ========================================================

    raise RuntimeError(
        "All LLM providers failed for a tool-calling request. "
        + " | ".join(errors)
    )


# ============================================================
# QUICK MANUAL TEST
# ============================================================

if __name__ == "__main__":

    print(
        generate_reply(
            "You are a terse assistant.",
            "Say 'ok' and nothing else.",
        )
    )

