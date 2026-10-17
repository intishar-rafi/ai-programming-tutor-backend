"""In-memory per-session state — decided against a DB for this project to
keep it simple. State is scoped to a session_id the frontend generates
(e.g. a UUID on page load) and sends with every request. Lost on server
restart; fine for a prototype/demo, not meant to survive redeploys.

Replaces the original notebook's module-level globals (hint_level,
own_history, hint_history, last_file_context, last_seen_file), which were
shared by every visitor — a real bug in a multi-user deployment. Keying by
session_id here means each browser tab gets independent state instead.

Now also tracks the pre-tutoring menu/scoping flow (phase, scoping_history)
and which project the session is pointed at, ported from the Shipmate
notebook's shipmate()/start_tutoring()/create_project() — projects live as
folders under WORKSPACE_DIR, each holding a main.py and a PROJECT.md, same
layout the notebook used locally.
"""

import os
import re
from typing import Optional, TypedDict

WORKSPACE_DIR = os.path.abspath(os.environ.get("WORKSPACE_DIR", "workspace"))
os.makedirs(WORKSPACE_DIR, exist_ok=True)


class SessionState(TypedDict, total=False):
    phase: str  # "menu" | "pick" | "describe" | "scoping" | "tutoring"
    scoping_history: list  # [{"role": "user"|"assistant", "content": str}, ...]
    project_dir: Optional[str]
    project_spec: str  # the project's PROJECT.md, shown to the tutor
    file_context: str
    last_seen_file: Optional[str]
    diff_text: str  # persisted unified diff, re-shown when the file hasn't changed since last time
    last_hinted_file: Optional[str]
    hint_level: int
    history: list  # [{"role": "user"|"assistant", "content": str}, ...]


_sessions: dict = {}


def get_session(session_id: str) -> SessionState:
    return _sessions.setdefault(session_id, {
        "phase": "menu",
        "scoping_history": [],
        "project_dir": None,
        "project_spec": "",
        "file_context": "",
        "last_seen_file": None,
        "diff_text": "",
        "last_hinted_file": None,
        "hint_level": 0,
        "history": [],
    })


def list_projects() -> list:
    return sorted(
        d for d in os.listdir(WORKSPACE_DIR)
        if os.path.isfile(os.path.join(WORKSPACE_DIR, d, "main.py"))
    )


def create_project(name: str, spec: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "project"
    project_dir = os.path.join(WORKSPACE_DIR, slug)
    os.makedirs(project_dir, exist_ok=True)
    with open(os.path.join(project_dir, "PROJECT.md"), "w") as f:
        f.write(spec)
    open(os.path.join(project_dir, "main.py"), "a").close()  # empty file, kept if it already exists
    return project_dir


def start_tutoring(state: SessionState, project_dir: str) -> SessionState:
    """Point a session at a project and reset its tutoring state — the
    per-session equivalent of the notebook's start_tutoring(), which reset
    module-level globals instead."""
    state["project_dir"] = project_dir
    with open(os.path.join(project_dir, "PROJECT.md")) as f:
        state["project_spec"] = f.read()
    try:
        with open(os.path.join(project_dir, "main.py")) as f:
            state["file_context"] = f.read()
    except FileNotFoundError:
        state["file_context"] = ""
    state["last_seen_file"] = None
    state["diff_text"] = ""
    state["last_hinted_file"] = None
    state["hint_level"] = 0
    state["history"] = []
    state["phase"] = "tutoring"
    return state


def set_file(session_id: str, content: str) -> SessionState:
    """Called by /upload once a project is chosen: saves the new content
    both in the session and to the project's main.py on disk (so it
    persists the same way the notebook's workspace files did), and resets
    hint progress."""
    state = get_session(session_id)
    if state.get("project_dir"):
        with open(os.path.join(state["project_dir"], "main.py"), "w") as f:
            f.write(content)
    state["last_seen_file"] = state.get("file_context")  # old content, so the next diff has something to compare against
    state["file_context"] = content
    state["last_hinted_file"] = None
    state["hint_level"] = 0
    return state
