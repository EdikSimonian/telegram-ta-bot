import re
import time
from bot.clients import ai
from bot.config import MODEL, HF_SPACE_ID
from bot.preferences import get_provider

# HF Gradio knobs — hardcoded defaults for ArmGPT
HF_LENGTH = 150
HF_TEMPERATURE = 0.8
HF_TOP_K = 40
HF_HISTORY_TURNS = 3  # last N turns flattened into the prompt


def _call_openai(messages: list, retries: int = 3):
    """Call the OpenAI-compatible API with exponential backoff retry."""
    for attempt in range(retries):
        try:
            response = ai.chat.completions.create(model=MODEL, messages=messages)
            return response.choices[0].message.content
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt  # 1s, 2s
            print(f"AI call failed (attempt {attempt + 1}/{retries}): {e} — retrying in {wait}s")
            time.sleep(wait)


def _flatten_messages(messages: list, turns: int = HF_HISTORY_TURNS) -> str:
    """Flatten the last N turns of a messages array into a single prompt string.

    Skips system messages. ArmGPT has no concept of roles, so we use simple
    "User:" / "Assistant:" labels.
    """
    convo = [m for m in messages if m.get("role") in ("user", "assistant")]
    convo = convo[-(turns * 2):]  # each turn = user + assistant
    lines = []
    for m in convo:
        label = "User" if m["role"] == "user" else "Assistant"
        lines.append(f"{label}: {m['content']}")
    lines.append("Assistant:")
    return "\n".join(lines)


def _strip_html(text: str) -> str:
    """Remove HTML tags from Gradio output."""
    return re.sub(r"<[^>]+>", "", text).strip()


def _call_hf(messages: list) -> str:
    """Call the Hugging Face Gradio space. No retry — HF is slow."""
    from gradio_client import Client

    prompt = _flatten_messages(messages)
    client = Client(HF_SPACE_ID)
    result = client.predict(
        prompt,
        HF_LENGTH,
        HF_TEMPERATURE,
        HF_TOP_K,
        api_name="/generate",
    )
    # Gradio predict returns the final yielded value. For this space it's a
    # tuple (html_output, status_text). We only want the text.
    if isinstance(result, (tuple, list)) and len(result) >= 1:
        text = result[0]
    else:
        text = result
    text = _strip_html(str(text))
    # Remove the echoed prompt if the model includes it
    if text.startswith(prompt):
        text = text[len(prompt):].strip()
    return text or "(empty response from ArmGPT)"


def generate(user_id: int, messages: list) -> str:
    """Dispatch to the user's chosen AI provider and return a reply string."""
    provider = get_provider(user_id)
    if provider == "hf":
        return _call_hf(messages)
    return _call_openai(messages)
