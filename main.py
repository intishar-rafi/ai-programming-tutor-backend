import os
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from chat_guardrail import chat_leaks_code, wants_code
from context import build_context_block
from hints.prompts import MAX_HINT_LEVEL, SYSTEM_PROMPT
from hints.service import get_hint
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


@app.get("/")
def health():
    return {"status": "ok"}


@app.get("/greeting")
def greeting():
    """The first message the frontend shows before the student has typed
    anything — matches the notebook's initial chat_display value."""
    return {"message": GREETING}


@app.get("/projects")
def projects():
    """Lets the frontend show a sidebar of existing projects to switch
    between, instead of only reaching them through the chat menu's "1"
    option. Read-only — doesn't touch session state."""
    return {"projects": list_projects()}


class SelectProjectRequest(BaseModel):
    session_id: str
    project: str


@app.post("/select_project")
def select_project(body: SelectProjectRequest):
    """Sidebar equivalent of typing "1" then the project's number in chat
    — jumps straight into tutoring on the chosen project. `project` must be
    one of the names returned by GET /projects."""
    if body.project not in list_projects():
        return {"status": "error", "message": "No such project."}
    state = get_session(body.session_id)
    project_dir = os.path.join(WORKSPACE_DIR, body.project)
    start_tutoring(state, project_dir)
    return {"status": "ok", "message": START_MESSAGE}


class UploadRequest(BaseModel):
    session_id: str
    content: str
    filename: Optional[str] = None


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

        def generate_menu_reply():
            for word in reply.split(" "):
                yield word + " "

        return StreamingResponse(generate_menu_reply(), media_type="text/plain")

    context_block = build_context_block(state)
    project_block = f"\n\nThe project the student is building (PROJECT.md):\n{state['project_spec']}"

    system_prompt = SYSTEM_PROMPT + project_block + context_block
    messages = state["history"] + [{"role": "user", "content": body.message}]

    def save_history(full_response: str):
        state["history"].append({"role": "user", "content": body.message})
        state["history"].append({"role": "assistant", "content": full_response})

    if wants_code(body.message):
        def generate_streamed():
            full_response = ""
            for delta in stream_completion(system_prompt, messages):
                full_response += delta
                yield delta
            save_history(full_response)

        return StreamingResponse(generate_streamed(), media_type="text/plain")

    def generate_checked():
        prompt = system_prompt
        full_response = ""
        for _ in range(CHAT_MAX_ATTEMPTS):
            full_response = generate_chat_completion(prompt, messages)
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


@app.post("/hint", response_model=HintResponse)
def hint(body: HintRequest):
    state = get_session(body.session_id)
    if state["phase"] != "tutoring":
        return HintResponse(level=0, hint="Finish choosing or describing a project in chat first.")

    file_context = state["file_context"]

    if file_context != state["last_hinted_file"]:
        state["hint_level"] = 0
        state["last_hinted_file"] = file_context
    state["hint_level"] = min(state["hint_level"] + 1, MAX_HINT_LEVEL)
    level = state["hint_level"]

    context_block = build_context_block(state, hint_pressed=True)

    hint_text = get_hint(context_block, level)
    return HintResponse(level=level, hint=hint_text)
