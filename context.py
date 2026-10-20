# This file builds the extra information sent to the model with every message:
# the project spec, the student's current code, and a diff showing what changed since last time.

import difflib

# The notebook turned line numbers off ("Trying without number lines"). Set
# this to True to send numbered lines again — hint level 2 points at a line
# number, and models count raw lines unreliably, so this is the first thing
# to flip if level-2 hints name the wrong line.
NUMBER_LINES = False
# Hint calls only: number the lines so level 2 can name the right one. The
# tutor chat stays on the notebook's raw file.
HINT_NUMBER_LINES = True


# Puts a line number in front of every line of code, e.g. ' 7 | x = 1'.
def number_lines(code_text: str) -> str:
    """Prefix every line with its line number, e.g. ' 7 | x = 1'."""
    lines = code_text.splitlines()
    width = len(str(len(lines))) if lines else 1
    return "\n".join(f"{i:>{width}} | {line}" for i, line in enumerate(lines, 1))


# Compares the old and new version of the code and returns the differences
# ('-' = removed line, '+' = added line).
def make_diff(old: str, new: str) -> str:
    """Unified diff between two versions of the file — ported directly
    from the Shipmate notebook's make_diff(): '-' lines were removed,
    '+' lines were added, same as `git diff` / `diff -u` output."""
    diff = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile="previous", tofile="current", lineterm="",
    )
    return "\n".join(diff)


# Builds the extra information given to the model: the project spec, the student's current code,
# and what changed since last time. The hint bot never gets the diff, only the tutor does.
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

    # macro view: PROJECT.md + the whole file. Same as the notebook's chatbot(),
    # which sends the spec to BOTH the tutor and the hint bot, and (after
    # "Trying without number lines") sends the file without line numbers.
    if NUMBER_LINES or (hint_pressed and HINT_NUMBER_LINES):
        file_view = number_lines(file_context)
        heading = (
            "\n\nCurrent updated content of the student's python project. Line numbers are added "
            "for reference only and are NOT part of the code; never include them in code you write:\n"
        )
    else:
        file_view = file_context
        heading = "\n\nCurrent updated content of the student's python project:\n"
    context_block = (
        "\n\nThe project the student is building (PROJECT.md):\n" + state.get("project_spec", "")
        + heading
        + file_view
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

    # the tutor (not the hint bot) is told which hints the student has seen. They are given here,
    # in the system prompt, instead of as chat turns, so the tutor can't copy their format.
    if not hint_pressed:
        shown = [m["content"] for m in state.get("hint_history", []) if m["role"] == "assistant"]
        if shown:
            context_block += (
                "\n\nHints so far for the current problem (the student saw them one at a time, most recent last):\n"
                + "\n".join(f"Hint {i}/4: {h}" for i, h in enumerate(shown, 1))
            )
            if state.get("last_was_hint"):
                context_block += (
                    "\n\nThe student's last action was pressing the Hint button, so the most recent hint above is "
                    "the one they are looking at now."
                )

    state["last_seen_file"] = file_context
    return context_block
