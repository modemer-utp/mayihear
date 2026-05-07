from langchain_google_genai import ChatGoogleGenerativeAI
from infrastructure.utilities import secret_manager

# Model index reference:
# 0 = gemini-2.5-flash-lite  (fast, cheap, good for structured outputs)
# 1 = gemini-2.5-pro         (most capable, better reasoning)


def model_inicialization(selected_model: int, temperature: float, max_tokens: int):
    model_names = {
        0: "gemini-2.5-flash-lite",
        1: "gemini-2.5-pro"
    }

    if selected_model not in model_names:
        raise ValueError(f"Unknown model selection: {selected_model}")

    model_name = model_names[selected_model]

    creds, project_id = secret_manager.get_vertex_credentials()
    if creds:
        model = ChatGoogleGenerativeAI(
            model=model_name,
            credentials=creds,
            project=project_id,
            location="us-central1",
            temperature=temperature,
            max_tokens=max_tokens,
        )
    else:
        model = ChatGoogleGenerativeAI(
            api_key=secret_manager.get_gemini_api_key(),
            model=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    return model, model_name
