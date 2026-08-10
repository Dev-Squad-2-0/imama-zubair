"""Central prompt loader for the RealEstate Hub agent.

All LLM-facing instructions live in prompts/system_prompt.md. The Markdown file acts
as a small prompt registry: one BASE section plus optional NODE sections. This keeps
nodes.py free of long prompt strings while avoiding the token/conflict cost of sending
every node's instructions on every LLM call.
"""

from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PROMPT_PATH = _ROOT / "prompts" / "system_prompt.md"


class PromptSectionError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _prompt_file() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _extract_between(start_marker: str, end_marker: str) -> str:
    text = _prompt_file()
    try:
        start = text.index(start_marker) + len(start_marker)
        end = text.index(end_marker, start)
    except ValueError as exc:
        raise PromptSectionError(
            f"Missing prompt markers {start_marker!r} / {end_marker!r} in {_PROMPT_PATH}"
        ) from exc

    value = text[start:end].strip()
    if not value:
        raise PromptSectionError(f"Prompt section after {start_marker!r} is empty")
    return value


@lru_cache(maxsize=1)
def base_prompt() -> str:
    return _extract_between("<!-- BASE_START -->", "<!-- BASE_END -->")


@lru_cache(maxsize=16)
def node_instructions(name: str) -> str:
    key = name.strip().upper()
    return _extract_between(
        f"<!-- NODE:{key}_START -->",
        f"<!-- NODE:{key}_END -->",
    )


def node_prompt(
    name: str,
    *,
    include_base: bool = True,
    **values: object,
) -> str:
    section = node_instructions(name)
    if values:
        try:
            section = section.format(**values)
        except KeyError as exc:
            raise PromptSectionError(
                f"Missing template value {exc.args[0]!r} for node prompt {name!r}"
            ) from exc

    if not include_base:
        return section.strip()

    return f"{base_prompt()}\n\n{section}".strip()


def clear_prompt_cache() -> None:
    _prompt_file.cache_clear()
    base_prompt.cache_clear()
    node_instructions.cache_clear()
