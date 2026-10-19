# This file detects code in a piece of text (code blocks, code-looking lines, or code in backticks).
# It is used to stop hints and chat answers from giving away the solution.

import re

# Reused as-is from shipmate-ai-tutor's hints/leak_check.py. Run every hint
# through this before returning it at levels 1-3 — prompt instructions
# alone aren't reliable enough to guarantee the model never shows code.
_CODE_LINE_PATTERN = re.compile(
    r"^\s*(def |class |return\b|self\.\w+\s*=|elif\b|else:|for .+ in .+:|if .+:|while .+:)"
)


# Returns True if a text contains code: a ``` block, or a line that starts like code (def, return, if...).
def leaks_code(hint: str) -> bool:
    if "```" in hint:
        return True
    return any(_CODE_LINE_PATTERN.match(line) for line in hint.splitlines())


_INLINE_SPAN = re.compile(r"`([^`\n]+)`")
_CODE_CHARS = re.compile(r"[=()\[\]+\-*/%<>:,.]")


# Returns True if a hint contains code written between single backticks that is NOT already in the student's file.
# Quoting the student's own wrong line is fine; writing a corrected line is not.
def leaks_inline_code(hint: str, context_block: str) -> bool:
    """Hint-only check for levels 1-3: catches `inline code` the line-based
    check misses. A backticked span counts as a leak when it looks like code
    (operators/brackets/spaces, not a bare name like `b` or `while`) AND it
    is not already in the student's own file. Quoting the student's wrong
    line is fine; writing a corrected one is not."""
    for span in _INLINE_SPAN.findall(hint):
        span = span.strip()
        if not _CODE_CHARS.search(span):
            continue
        if span in context_block:
            continue
        return True
    return False
