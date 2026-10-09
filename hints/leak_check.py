import re

# Reused as-is from shipmate-ai-tutor's hints/leak_check.py. Run every hint
# through this before returning it at levels 1-3 — prompt instructions
# alone aren't reliable enough to guarantee the model never shows code.
_CODE_LINE_PATTERN = re.compile(
    r"^\s*(def |class |return\b|self\.\w+\s*=|elif\b|else:|for .+ in .+:|if .+:|while .+:)"
)


def leaks_code(hint: str) -> bool:
    if "```" in hint:
        return True
    return any(_CODE_LINE_PATTERN.match(line) for line in hint.splitlines())
