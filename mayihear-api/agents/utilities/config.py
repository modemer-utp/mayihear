# Model selection: 0 = gemini-2.5-flash, 1 = gemini-2.5-pro (see model_init.py)
INSIGHTS_SELECTED_MODEL = 0
INSIGHTS_TEMPERATURE = 0.2
INSIGHTS_MAX_TOKENS = 1024

# Meeting act has a much larger nested schema — needs more room
MEETING_ACT_SELECTED_MODEL = 0
MEETING_ACT_TEMPERATURE = 0.2
MEETING_ACT_MAX_TOKENS = 4096

# Whisper transcription language — set None for auto-detect
TRANSCRIPTION_LANGUAGE = "es"

# Prompt file separator (same pattern as experto-tematico)
PROMPT_DIVISOR = "<divisor>"
