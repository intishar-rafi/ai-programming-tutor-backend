# This file generates hints.
# It asks the model for a hint at the right level, checks it for leaked code,
# and retries or falls back to a safe hint if needed.

from hints.leak_check import leaks_code, leaks_inline_code
from hints.prompts import HINT_TEMPERATURE, MAX_HINT_LEVEL, build_hint_system_prompt
from llm.client import generate_chat_completion

MAX_ATTEMPTS = 3
FALLBACK_HINT = "Try reviewing this part of your code again, step by step."
HINT_USER_MESSAGE = "I pressed the hint button."  # same text the notebook's on_hint() sends


# Asks the model for a hint at the given level.
# If a level 1-3 hint contains code, it asks again (up to 3 tries) and finally falls back to a safe generic hint.
def get_hint(context_block: str, level: int, hint_history: list) -> str:
    """Guardrail-checked hint generation. Same retry pattern as before:
    generate, check with leaks_code(), and if it leaked at levels 1-3,
    tighten the prompt and retry (up to MAX_ATTEMPTS), falling back to a
    static hint rather than ever showing a leak. Level 4 may contain code.

    `hint_history` is the notebook's hint_history: the hint bot's own earlier
    hints for the current round, passed back as conversation turns so it can
    stay on the SAME problem across levels 1-4 (the hint prompt tells it to).
    The caller appends to it and clears it when the file changes."""
    system_prompt = build_hint_system_prompt(level, context_block)
    messages = list(hint_history) + [{"role": "user", "content": HINT_USER_MESSAGE}]

    for _ in range(MAX_ATTEMPTS):
        candidate = generate_chat_completion(system_prompt, messages, temperature=HINT_TEMPERATURE)
        if level == MAX_HINT_LEVEL or not (leaks_code(candidate) or leaks_inline_code(candidate, context_block)):
            return candidate
        system_prompt += (
            "\n\nYour previous response included code or a code-like "
            "statement. Do not include any code this time — describe it "
            "in plain English only."
        )

    return FALLBACK_HINT
