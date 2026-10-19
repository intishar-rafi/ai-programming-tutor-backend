# This file handles everything BEFORE tutoring begins: the 1/2 welcome menu,
# picking an existing project, describing a new one, and agreeing on a short project spec with the student.
# It also holds the greeting and the "Great! Let's get started" message.

"""Project scoping flow, ported from the Shipmate notebook's shipmate()/
scope() functions: lets a student pick an existing project or describe a
new one before tutoring starts. Same SCOPING_SYSTEM_PROMPT / SPEC_SYSTEM_
PROMPT / phase state machine as the notebook, adapted from notebook globals
to per-session state so multiple students can be at different points of
this flow at once.
"""

import os
import re

from llm.client import generate_chat_completion
from sessions import WORKSPACE_DIR, create_project, list_projects, start_tutoring

SCOPING_SYSTEM_PROMPT = """You are Little by little, a programming tutor helping a student scope a new Python project. \
The student will write ALL the code themselves later, so NEVER write code, function names or implementation details. \
Your only job is a short specification of a small version of their idea that fits in a single .py file under 1000 lines of code.

Reply in exactly this format and nothing else. Put ONE EMPTY LINE between every block below, \
and write each bullet on its own line starting with "* ":

Name: some_snake_case_name

Goal: one sentence

Features:

* first feature
* second feature
* (3-5 features in total)

Out of scope:

* first item
* second item
* (2-3 items in total)

Type yes to start, or tell me what to change.

If the student asks for changes, reply with an updated specification in the same format, \
with the same empty lines between blocks. End every reply with: Type yes to start, or tell me what to change."""

SPEC_SYSTEM_PROMPT = """Write a PROJECT.md for the project that was just agreed on. It is read by a tutor LLM, not the student, \
so keep it short. Use exactly these sections: # name, ## Goal, ## Features, ## Out of scope, \
## Constraints (single main.py, under 1000 lines, standard library only). Output only the markdown."""

GREETING = """Hello, I am Little by little. What can I help you with today?

1: I want to continue work on an existing project
2: I want to start a new project

Type 1 or 2 to make your choice."""

START_MESSAGE = """Great! Let's get started with the programming. You know where to find me if you need any help, \
just press the "Hint" button or type a question!"""


# Adds blank lines between the sections of the project spec (Goal, Features, Out of scope...).
# The model doesn't always format them nicely, so we fix the spacing here. Display only.
def format_spec(text: str) -> str:
    """Guarantees a blank line between the spec's sections, whatever the
    model returned. The chat display merges single line breaks into one
    paragraph, and the model doesn't reliably follow a layout instruction,
    so the spacing is enforced here instead of in the prompt. Display only
    — scoping_history keeps the model's raw reply."""
    text = re.sub(r"(?m)^[ \t]*(Goal:|Features:|Out of scope:|Type yes to start)", r"\n\1", text)
    text = re.sub(r"(?m)^(Features:|Out of scope:)[ \t]*\n(?!\n)", r"\1\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Runs the conversation BEFORE tutoring starts: menu -> pick/describe -> scoping -> tutoring.
# Reads the session's current phase, decides what to reply, and moves the session to the next phase.
def handle_menu(state: dict, text: str) -> str:
    """The pre-tutoring conversation (menu -> pick / describe -> scoping ->
    tutoring). Returns the reply text and mutates state in place — the
    per-session equivalent of the notebook's shipmate()/scope()."""
    phase = state["phase"]
    stripped = text.strip()

    if phase == "menu":
        if stripped == "1":
            projects = list_projects()
            if not projects:
                state["phase"] = "describe"
                return "You don't have any existing projects yet. Describe your new project."
            state["phase"] = "pick"
            return (
                "Which project?\n\n"
                + "\n".join(f"{i}: {p}" for i, p in enumerate(projects, 1))
                + "\n\nType the number."
            )
        elif stripped == "2":
            state["phase"] = "describe"
            return "Describe your project."
        else:
            return "Type 1 or 2 to make your choice."

    elif phase == "pick":
        projects = list_projects()
        if stripped.isdigit() and 1 <= int(stripped) <= len(projects):
            project_dir = os.path.join(WORKSPACE_DIR, projects[int(stripped) - 1])
            start_tutoring(state, project_dir)
            return START_MESSAGE
        return "Type the number of a project."

    elif phase == "describe":
        state["scoping_history"].clear()
        state["phase"] = "scoping"
        state["scoping_history"].append({"role": "user", "content": text})
        reply = generate_chat_completion(SCOPING_SYSTEM_PROMPT, state["scoping_history"])
        state["scoping_history"].append({"role": "assistant", "content": reply})
        return format_spec(reply)

    elif phase == "scoping":
        if stripped.lower() != "yes":
            state["scoping_history"].append({"role": "user", "content": text})
            reply = generate_chat_completion(SCOPING_SYSTEM_PROMPT, state["scoping_history"])
            state["scoping_history"].append({"role": "assistant", "content": reply})
            return format_spec(reply)
        spec = generate_chat_completion(SPEC_SYSTEM_PROMPT, state["scoping_history"])
        name_match = re.search(r"Name:\s*(\S+)", state["scoping_history"][-1]["content"])
        project_dir = create_project(name_match.group(1) if name_match else "my_project", spec)
        start_tutoring(state, project_dir)
        return START_MESSAGE

    return "Something went wrong — type 1 or 2 to make your choice."
