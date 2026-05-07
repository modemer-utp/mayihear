import time
from datetime import date

from google import genai
from infrastructure.utilities import secret_manager
from infrastructure.utilities.secret_manager import get_gemini_api_key
from domain.models.output.meeting_act_result import MeetingActResult

MODEL = "gemini-2.5-flash-lite"

_PROMPT_TEMPLATE = """Eres un asistente especializado en generar actas de reunión en español.

Fecha de hoy: {today_date}

Contexto adicional:
{user_context}

== PLANTILLA DEL USUARIO — SIGUE ESTE FORMATO EXACTAMENTE ==
{acta_template}
==

Genera el acta de reunión siguiendo estrictamente la plantilla de arriba.
Usa Markdown para el formato: ## para secciones, ### para subsecciones, - para listas, **texto** para negrita.
Responde SOLO con el contenido del acta, sin explicaciones adicionales.

Transcripción:
{transcript}
"""


class GenerateMeetingActFreeform:

    def execute(self, transcript: str, user_context: str, acta_template: str) -> MeetingActResult:
        start = time.perf_counter()
        today = date.today().strftime("%d/%m/%Y")

        creds, project_id = secret_manager.get_vertex_credentials()
        if creds:
            client = genai.Client(vertexai=True, project=project_id, location="us-central1", credentials=creds)
        else:
            client = genai.Client(api_key=get_gemini_api_key())

        prompt = _PROMPT_TEMPLATE.format(
            today_date=today,
            user_context=user_context or "No se proporcionó contexto adicional.",
            acta_template=acta_template,
            transcript=transcript,
        )

        response = client.models.generate_content(model=MODEL, contents=prompt)
        text = response.text or ""

        processing_time = round(time.perf_counter() - start, 2)
        return MeetingActResult(
            is_freeform=True,
            free_form_text=text,
            processing_time_seconds=processing_time,
        )
