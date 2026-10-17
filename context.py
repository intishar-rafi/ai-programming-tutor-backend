import difflib


def number_lines(code_text: str) -> str:
    """Prefix every line with its line number, e.g. ' 7 | x = 1'."""
    lines = code_text.splitlines()
    width = len(str(len(lines))) if lines else 1
    return "\n".join(f"{i:>{width}} | {line}" for i, line in enumerate(lines, 1))


def make_diff(old: str, new: str) -> str:
    """Unified diff between two versions of the file — ported directly
    from the Shipmate notebook's make_diff(): '-' lines were removed,
    '+' lines were added, same as `git diff` / `diff -u` output."""
    diff = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile="previous", tofile="current", lineterm="",
    )
    return "\n".join(diff)


def build_context_block(state: dict, hint_pressed: bool = False) -> str:
    """Macro view (full numbered file) + micro view (unified diff),
    ported from the notebook's chatbot() context-building logic — including
    the detail that a hint call never sees the diff text (only the tutor
    chat does), and that when nothing changed since last time, the OLD
    diff is shown again rather than nothing. `state` is the session dict
    from sessions.py; this mutates its `last_seen_file` and `diff_text`
    fields in place, same as the notebook mutated its globals."""
    file_context = state["file_context"]
    last_seen_file = state.get("last_seen_file")

    context_block = (
        "\n\nCurrent content of the student's Python file. Line numbers are added "
        "for reference only and are NOT part of the code; never include them in code you write.\n"
        + number_lines(file_context)
    )

    if last_seen_file is not None:
        if file_context != last_seen_file:
            state["diff_text"] = make_diff(last_seen_file, file_context)
            if not hint_pressed:  # only the tutor gets the diff
                context_block += (
                    "\n\nThe file HAS changed since the previous message "
                    "(unified diff: '-' lines were removed, '+' lines were added):\n"
                    + state["diff_text"]
                )
        elif not hint_pressed and state.get("diff_text"):
            context_block += (
                "\n\nThe file HAS NOT changed since the previous message. These are the old changes "
                "(unified diff: '-' lines were removed, '+' lines were added):\n"
                + state["diff_text"]
            )

    state["last_seen_file"] = file_context
    return context_block
