from typing import List, Dict
from google import genai
from infrastructure.utilities import secret_manager

CHAT_MODEL = "gemini-2.5-flash-lite"

_SYSTEM_CONTEXT = (
    "You are a meeting assistant. The user will ask questions about the meeting transcript provided. "
    "Answer concisely and accurately based only on the transcript content. "
    "If the answer is not in the transcript, say so clearly. "
    "Respond in the same language the user writes in."
)


def _make_client():
    creds, project_id = secret_manager.get_vertex_credentials()
    if creds:
        return genai.Client(vertexai=True, project=project_id, location="us-central1", credentials=creds)
    return genai.Client(api_key=secret_manager.get_gemini_api_key())


def chat_with_transcript(
    transcript: str,
    history: List[Dict[str, str]],
    user_message: str
) -> str:
    client = _make_client()

    # Seed the conversation with transcript as context
    contents = [
        {
            "role": "user",
            "parts": [{"text": f"{_SYSTEM_CONTEXT}\n\nMEETING TRANSCRIPT:\n\n{transcript}"}]
        },
        {
            "role": "model",
            "parts": [{"text": "Understood. I have the meeting transcript and I'm ready to answer questions about it."}]
        },
    ]

    for msg in history:
        contents.append({
            "role": msg["role"],
            "parts": [{"text": msg["content"]}]
        })

    contents.append({
        "role": "user",
        "parts": [{"text": user_message}]
    })

    response = client.models.generate_content(model=CHAT_MODEL, contents=contents)
    return response.text
