import re

from hints.leak_check import leaks_code

# NEW — fixes a real gap found by testing: /chat had NO guardrail at all,
# unlike /hint. The model would give full code ("return a + b") for a
# question like "how should I implement add?", even though SYSTEM_PROMPT
# says code should only be given if the student EXPLICITLY asks for it.
# Prompt wording alone wasn't enough (same lesson as the hint guardrail).

# Rough heuristic for "the student explicitly asked for code" — if this
# matches, we skip the leak check entirely and let the model answer freely,
# since showing code in that case is allowed by SYSTEM_PROMPT.
_EXPLICIT_CODE_REQUEST = re.compile(
    r"\b(code|snippet|write (it|the|a)\b|show me|example|implementation)\b",
    re.IGNORECASE,
)


def wants_code(message: str) -> bool:
    return bool(_EXPLICIT_CODE_REQUEST.search(message))


def chat_leaks_code(response_text: str) -> bool:
    """Reuses the same detector as hints (code fence or code-shaped line)."""
    return leaks_code(response_text)
