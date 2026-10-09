import ast
import difflib


def number_lines(code_text: str) -> str:
    """Prefix every line with its line number, e.g. ' 7 | x = 1'."""
    lines = code_text.splitlines()
    width = len(str(len(lines))) if lines else 1
    return "\n".join(f"{i:>{width}} | {line}" for i, line in enumerate(lines, 1))


def _function_ranges(code_text: str) -> list[tuple[int, int, str]]:
    """Returns (start_line, end_line, name) for every top-level/nested
    function def in the file, 1-indexed inclusive, so a changed line can be
    matched to the function it's actually inside. Returns [] on invalid
    syntax (e.g. a student's file mid-edit) rather than raising."""
    try:
        tree = ast.parse(code_text)
    except SyntaxError:
        return []
    ranges = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", None) or node.lineno
            ranges.append((node.lineno, end, node.name))
    return ranges


def _enclosing_function(line_no: int, ranges: list[tuple[int, int, str]]) -> str | None:
    """Innermost (smallest) matching range wins, so a nested def beats its
    containing function."""
    best = None
    for start, end, name in ranges:
        if start <= line_no <= end:
            if best is None or (end - start) < (best[1] - best[0]):
                best = (start, end, name)
    return best[2] if best else None


def describe_changes(old: str, new: str, max_chars: int = 2000) -> str:
    """Plain-language list of what changed between two versions of the file.
    Each span is tagged with its enclosing function, if any, so the model
    can't attribute a change to the wrong function when summarizing it."""
    old_lines, new_lines = old.splitlines(), new.splitlines()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    new_ranges = _function_ranges(new)
    old_ranges = _function_ranges(old)

    def span(a, b):
        return f"line {a + 1}" if b - a == 1 else f"lines {a + 1}-{b}"

    def tag(line_no: int, ranges: list[tuple[int, int, str]]) -> str:
        name = _enclosing_function(line_no, ranges)
        return f" (inside `{name}`)" if name else ""

    parts = []
    for op_tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if op_tag == "equal":
            continue
        before = "\n".join(f"    {l}" for l in old_lines[i1:i2])
        after = "\n".join(f"  {n} | {l}" for n, l in enumerate(new_lines[j1:j2], j1 + 1))
        if op_tag == "replace":
            where = tag(j1 + 1, new_ranges)
            parts.append(f"Changed {span(j1, j2)}{where}.\n  Before:\n{before}\n  Now:\n{after}")
        elif op_tag == "insert":
            where = tag(j1 + 1, new_ranges)
            parts.append(f"Added {span(j1, j2)}{where}:\n{after}")
        elif op_tag == "delete":
            where_txt = "at the start of the file" if j1 == 0 else f"just after current line {j1}"
            where_fn = tag(i1 + 1, old_ranges)
            parts.append(f"Removed {i2 - i1} line(s) {where_txt}{where_fn}:\n{before}")

    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (more changes not shown)"
    return text


def build_context_block(file_context: str, last_seen_file: str | None) -> str:
    """Macro view (full numbered file) + micro view (diff since last
    message), same idea as the original notebook's context-building logic."""
    context_block = (
        "\n\nCurrent content of the student's Python file. Line numbers are added "
        "for reference only and are NOT part of the code; never include them in code you write.\n"
        + number_lines(file_context)
    )
    if last_seen_file is not None:
        if file_context == last_seen_file:
            context_block += "\n\nThe file has NOT changed since the student's previous message."
        else:
            context_block += (
                "\n\nChanges the student made since their previous message "
                "(line numbers refer to the current file above):\n"
                + describe_changes(last_seen_file, file_context)
            )
    return context_block