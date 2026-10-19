# This file is the web server and the entry point of the backend.
# The Lovable frontend talks to the app through the endpoints defined here:
# /greeting, /projects, /select_project, /upload, /chat and /hint.
# It receives each request, finds the student's session, and calls the other files to do the work.

import os
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from chat_guardrail import chat_leaks_code, wants_code
from context import build_context_block
from hints.prompts import MAX_HINT_LEVEL, SYSTEM_PROMPT, TUTOR_TEMPERATURE
from hints.service import HINT_USER_MESSAGE, get_hint
from llm.client import generate_chat_completion, stream_completion
from scoping import GREETING, START_MESSAGE, handle_menu
from sessions import WORKSPACE_DIR, get_session, list_projects, set_file, start_tutoring

CHAT_MAX_ATTEMPTS = 3

app = FastAPI()

# Lovable's dev/preview origins vary; lock this down to your actual
# frontend domain once it's deployed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Simple check that the server is alive. Render and browsers can call this.
@app.get("/")
def health():
    return {"status": "ok"}


# Returns the first message the chat shows (the 1/2 menu), before the student types anything.
@app.get("/greeting")
def greeting():
    """The first message the frontend shows before the student has typed
    anything — matches the notebook's initial chat_display value."""
    return {"message": GREETING}


# Returns the list of saved projects so the frontend can show them in the sidebar.
@app.get("/projects")
def projects():
    """Lets the frontend show a sidebar of existing projects to switch
    between, instead of only reaching them through the chat menu's "1"
    option. Read-only — doesn't touch session state."""
    return {"projects": list_projects()}


class SelectProjectRequest(BaseModel):
    session_id: str
    project_name: str


# Opens an existing project from the sidebar.
# Starts tutoring on it and returns its saved code so the editor can show it.
@app.post("/select_project")
def select_project(body: SelectProjectRequest):
    """Sidebar equivalent of typing "1" then the project's number in chat
    — jumps straight into tutoring on the chosen project. `project_name` must be
    one of the names returned by GET /projects."""
    if body.project_name not in list_projects():
        return {"status": "error", "message": "No such project."}
    state = get_session(body.session_id)
    project_dir = os.path.join(WORKSPACE_DIR, body.project_name)
    start_tutoring(state, project_dir)
    # `content` is the project's saved main.py, so the frontend can load it
    # into the editor — without it, switching projects shows an empty editor.
    return {
        "status": "ok",
        "message": START_MESSAGE,
        "content": state["file_context"],
        "project_name": body.project_name,
    }


class UploadRequest(BaseModel):
    session_id: str
    content: str
    filename: Optional[str] = None


# Receives the student's current code from the editor and stores it in the session.
# Only allowed once a project has been chosen or created.
@app.post("/upload")
def upload_file(body: UploadRequest):
    """Replaces the original notebook's Google-Drive-mounted file. The
    frontend reads the student's file client-side (e.g. a file input +
    FileReader) and sends its text content here once; it's cached in the
    session, not re-read from disk on every message.

    Only valid once a project has been chosen or created via /chat's menu
    flow — before that there's no project folder to save into."""
    state = get_session(body.session_id)
    if state["phase"] != "tutoring":
        return {
            "status": "error",
            "message": "Finish choosing or describing a project in chat first.",
        }
    set_file(body.session_id, body.content)
    return {
        "status": "ok",
        "filename": body.filename,
        "lines": len(body.content.splitlines()),
    }


class ChatRequest(BaseModel):
    session_id: str
    message: str


# Handles a chat message.
# Before a project exists: runs the menu/scoping flow. After: the tutor answers.
# Unless the student asks for code, the answer is checked for code leaks and regenerated if needed.
@app.post("/chat")
def chat(body: ChatRequest):
    """Before a project is chosen, routes through the menu/scoping flow
    (ported from the notebook's shipmate()/scope()) instead of the tutor.

    Once tutoring has started, behaves as before: FIXED after testing found
    a real leak — the model would give full code for a question like "how
    should I implement add?" even though SYSTEM_PROMPT says code should
    only be given if explicitly asked. Prompt wording alone wasn't reliable
    enough — same lesson as the hint guardrail.

    If the student's message looks like an explicit code request
    (wants_code()), we skip the check and stream normally — code is
    allowed there. Otherwise we generate the full response first
    (non-streaming, so it can be checked), run it through the same
    leaks_code() detector used for hints, and retry with a tightened
    prompt if it leaked (up to CHAT_MAX_ATTEMPTS) — then stream the
    validated text out to the client in chunks, so the typing effect is
    kept even though generation itself wasn't streamed."""
    state = get_session(body.session_id)

    if state["phase"] != "tutoring":
        reply = handle_menu(state, body.message)

        # Sends the menu/scoping reply word by word, so it looks like it is being typed.
        def generate_menu_reply():
            for word in reply.split(" "):
                yield word + " "

        return StreamingResponse(generate_menu_reply(), media_type="text/plain")

    # the PROJECT.md spec is now part of build_context_block (as in the notebook)
    context_block = build_context_block(state)

    system_prompt = SYSTEM_PROMPT + context_block
    messages = state["history"] + [{"role": "user", "content": body.message}]

    # Saves the student's message and the tutor's answer, so the tutor remembers the conversation.
    def save_history(full_response: str):
        state["history"].append({"role": "user", "content": body.message})
        state["history"].append({"role": "assistant", "content": full_response})

    if wants_code(body.message):
        # Streams the tutor's answer live as it is generated (used when the student asked for code).
        def generate_streamed():
            full_response = ""
            for delta in stream_completion(system_prompt, messages, temperature=TUTOR_TEMPERATURE):
                full_response += delta
                yield delta
            save_history(full_response)

        return StreamingResponse(generate_streamed(), media_type="text/plain")

    # Generates the full answer first, checks it for leaked code and retries if needed,
    # then sends it out word by word.
    def generate_checked():
        prompt = system_prompt
        full_response = ""
        for _ in range(CHAT_MAX_ATTEMPTS):
            full_response = generate_chat_completion(prompt, messages, temperature=TUTOR_TEMPERATURE)
            if not chat_leaks_code(full_response):
                break
            prompt += (
                "\n\nYour previous response included code or a code-like "
                "statement, but the student did not explicitly ask for "
                "code. Explain the idea in plain English only, with no code."
            )
        else:
            full_response = (
                "I can walk you through the idea in words — would you like "
                "me to explain it step by step, or press the Hint button "
                "for a guided nudge?"
            )
        # fake the typing effect in word-sized chunks, since the content
        # was already fully generated and validated above
        for word in full_response.split(" "):
            yield word + " "
        save_history(full_response)

    return StreamingResponse(generate_checked(), media_type="text/plain")


class HintRequest(BaseModel):
    session_id: str


class HintResponse(BaseModel):
    level: int
    hint: str


# Handles the Hint button.
# Moves up one hint level (1-4), asks the hint bot for a hint, and records it in both histories.
@app.post("/hint", response_model=HintResponse)
def hint(body: HintRequest):
    state = get_session(body.session_id)
    if state["phase"] != "tutoring":
        return HintResponse(level=0, hint="Finish choosing or describing a project in chat first.")

    file_context = state["file_context"]

    if file_context != state["last_hinted_file"]:
        state["hint_level"] = 0
        state["hint_history"] = []  # file changed -> hints start over
        state["last_hinted_file"] = file_context
    state["hint_level"] = min(state["hint_level"] + 1, MAX_HINT_LEVEL)
    level = state["hint_level"]

    context_block = build_context_block(state, hint_pressed=True)

    # the hint bot sees only the code + its own earlier hints this round,
    # which is what keeps levels 1-4 on the same problem
    hint_text = get_hint(context_block, level, state["hint_history"])

    # same bookkeeping as the notebook's chatbot(): the hint goes into the
    # hint bot's history, and (with the notebook's prefix) into the tutor's
    # conversation, so the tutor can see the hints it is told to explain
    hint_prompt = HINT_USER_MESSAGE
    state["hint_history"].append({"role": "user", "content": hint_prompt})
    state["hint_history"].append({"role": "assistant", "content": hint_text})
    state["history"].append({"role": "user", "content": hint_prompt})
    state["history"].append({
        "role": "assistant",
        "content": f"I see you pressed the hint button, so here's hint {level}/4:\n\n{hint_text}",
    })
    return HintResponse(level=level, hint=hint_text)
