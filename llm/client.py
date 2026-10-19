# This file is the only place that talks to the AI model (OpenAI gpt-4o-mini).
# Other files call its functions to get an answer, either all at once or streamed word by word.

import os

from dotenv import load_dotenv
from openai import OpenAI

# Reads a local .env file (if present) into os.environ — without this,
# putting OPENAI_API_KEY in a .env file does nothing, since Python doesn't
# load .env files automatically. In production (e.g. Render), the real
# environment variable takes precedence and this is a harmless no-op since
# there's no .env file deployed.
load_dotenv()

# Provider-agnostic client config, same pattern as shipmate-ai-tutor's
# llm/client.py. Points at OpenAI directly (gpt-4o-mini) by default;
# switching providers later is a config change (set LLM_BASE_URL + LLM_MODEL),
# not a code change.
LLM_API_KEY = os.environ.get("OPENAI_API_KEY")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL")  # None = OpenAI's default endpoint
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

_client: OpenAI | None = None


# Creates the OpenAI connection the first time it is needed and reuses it afterwards.
def _get_client() -> OpenAI:
    global _client
    if _client is None:
        kwargs = {"api_key": LLM_API_KEY}
        if LLM_BASE_URL:
            kwargs["base_url"] = LLM_BASE_URL
        _client = OpenAI(**kwargs)
    return _client


# Simple one-shot model call: one system prompt, one user message, returns the text.
def generate_completion(system_prompt: str, user_prompt: str) -> str:
    """Non-streaming call, used for hints (the leak-check guardrail needs
    the full text before deciding whether to show it)."""
    response = _get_client().chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
        max_tokens=400,
    )
    return (response.choices[0].message.content or "").strip()


# Model call with a whole conversation. Waits for the full answer and returns it as text.
# Used when the answer must be checked before the student sees it.
def generate_chat_completion(system_prompt: str, messages: list[dict], temperature: float = 0.4) -> str:
    """Non-streaming, multi-turn version — used for /chat when a leak-check
    needs to inspect the full response before it's shown (see
    chat_guardrail.py), and for hints (which need the hint history as
    earlier turns). Same shape as stream_completion but stream=False.
    `temperature` is per call: the notebook uses 0.3 for hints, 0.7 for chat."""
    response = _get_client().chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "system", "content": system_prompt}] + messages,
        temperature=temperature,
        max_tokens=700,
    )
    return (response.choices[0].message.content or "").strip()


# Same as above, but yields the answer in small pieces as the model produces them (typing effect).
def stream_completion(system_prompt: str, messages: list[dict], temperature: float = 0.4):
    """Streaming generator, used for ordinary tutor chat (no leak-check
    needed there, so streaming is fine)."""
    stream = _get_client().chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "system", "content": system_prompt}] + messages,
        temperature=temperature,
        max_tokens=700,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
