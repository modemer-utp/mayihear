# Gemini API pricing — USD per million tokens
# Source: https://ai.google.dev/gemini-api/docs/pricing

_AUDIO_INPUT_PRICE = {
    "gemini-2.5-pro":   1.25,
    "gemini-2.5-flash": 1.00,
    "gemini-2.0-flash": 0.70,
}

_TEXT_INPUT_PRICE = {
    "gemini-2.5-pro":   1.25,
    "gemini-2.5-flash": 0.30,
    "gemini-2.0-flash": 0.10,
}

_OUTPUT_PRICE = {
    "gemini-2.5-pro":   10.00,
    "gemini-2.5-flash":  2.50,
    "gemini-2.0-flash":  0.40,
}

_PER_MILLION = 1_000_000


def compute_cost(model: str, input_tokens: int, output_tokens: int, audio_input: bool = False) -> float:
    input_price = (_AUDIO_INPUT_PRICE if audio_input else _TEXT_INPUT_PRICE).get(model, 1.25)
    output_price = _OUTPUT_PRICE.get(model, 10.00)
    return round(
        (input_tokens * input_price + output_tokens * output_price) / _PER_MILLION,
        6
    )
