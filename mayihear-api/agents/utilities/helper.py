import os


def read_prompt_file(filename: str) -> str:
    """Read a prompt file from the agents/prompts directory."""
    prompt_path = os.path.join(
        os.path.dirname(__file__), '..', 'prompts', filename
    )
    with open(os.path.normpath(prompt_path), 'r', encoding='utf-8') as f:
        return f.read()
