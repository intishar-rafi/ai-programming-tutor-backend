from hints.leak_check import leaks_code
from hints.prompts import MAX_HINT_LEVEL, build_hint_system_prompt
from llm.client import generate_completion

MAX_ATTEMPTS = 3
FALLBACK_HINT = "Try reviewing this part of your code again, step by step."


def get_hint(context_block: str, level: int) -> str:
    """Guardrail-checked hint generation — same retry pattern as
    shipmate-ai-tutor's hints/service.py: generate, check with
    leaks_code(), and if it leaked at levels 1-3, tighten the prompt and
    retry (up to MAX_ATTEMPTS), falling back to a static hint rather than
    ever showing a leak. Level 4 is allowed to contain code and always
    returns immediately."""
    system_prompt = build_hint_system_prompt(level, context_block)

    for _ in range(MAX_ATTEMPTS):
        candidate = generate_completion(system_prompt, "Give me a hint.")
        if level == MAX_HINT_LEVEL or not leaks_code(candidate):
            return candidate
        system_prompt += (
            "\n\nYour previous response included code or a code-like "
            "statement. Do not include any code this time — describe it "
            "in plain English only."
        )

    return FALLBACK_HINT
