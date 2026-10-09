"""In-memory per-session state — decided against a DB for this project to
keep it simple. State is scoped to a session_id the frontend generates
(e.g. a UUID on page load) and sends with every request. Lost on server
restart; fine for a prototype/demo, not meant to survive redeploys.

Replaces the original notebook's module-level globals (hint_level,
own_history, hint_history, last_file_context, last_seen_file), which were
shared by every visitor — a real bug in a multi-user deployment. Keying by
session_id here means each browser tab gets independent state instead.
"""

from typing import Optional, TypedDict


class SessionState(TypedDict, total=False):
    file_context: str
    last_seen_file: Optional[str]
    last_hinted_file: Optional[str]
    hint_level: int
    history: list[dict]  # [{"role": "user"|"assistant", "content": str}, ...]


_sessions: dict[str, SessionState] = {}


def get_session(session_id: str) -> SessionState:
    return _sessions.setdefault(session_id, {
        "file_context": "",
        "last_seen_file": None,
        "last_hinted_file": None,
        "hint_level": 0,
        "history": [],
    })


def set_file(session_id: str, content: str) -> SessionState:
    state = get_session(session_id)
    state["last_seen_file"] = state.get("file_context")  # old content, so the next diff has something to compare against
    state["file_context"] = content
    state["last_hinted_file"] = None
    state["hint_level"] = 0
    return state
