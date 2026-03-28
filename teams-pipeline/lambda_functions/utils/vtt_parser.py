import re


def parse_vtt(vtt_content: str) -> str:
    """
    Parses a Teams .vtt transcript and returns clean plain text.
    Preserves speaker names and removes timestamps/metadata.
    """
    lines = vtt_content.splitlines()
    result = []
    current_speaker = None
    current_text = []

    timestamp_re = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}")
    speaker_re = re.compile(r"^<v ([^>]+)>(.*)$")

    for line in lines:
        line = line.strip()

        if not line or line == "WEBVTT" or timestamp_re.match(line):
            continue

        # Remove cue identifiers (numeric or UUID lines)
        if re.match(r"^[\da-f-]+$", line):
            continue

        speaker_match = speaker_re.match(line)
        if speaker_match:
            speaker = speaker_match.group(1).strip()
            text = speaker_match.group(2).strip()
            if speaker != current_speaker:
                if current_speaker and current_text:
                    result.append(f"{current_speaker}: {' '.join(current_text)}")
                current_speaker = speaker
                current_text = [text] if text else []
            else:
                if text:
                    current_text.append(text)
        else:
            # Plain text line (no speaker tag)
            if line:
                current_text.append(line)

    # Flush last speaker
    if current_speaker and current_text:
        result.append(f"{current_speaker}: {' '.join(current_text)}")

    return "\n".join(result)
