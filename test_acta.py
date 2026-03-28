"""
Test acta generation with the Teams transcript.
"""
import sys, os
from datetime import date
sys.path.insert(0, 'mayihear-api')
from dotenv import load_dotenv
load_dotenv('mayihear-api/.env')

import google.genai as genai
from infrastructure.utilities.secret_manager import get_gemini_api_key

TRANSCRIPT = """
Sebastian Julon Chamana: Empezo la grabacion, bueno.
Sebastian Julon Chamana: Debido a que segun lo que hemos hablado sobre este proceso nuevo de transcripcion, creo que es una buena idea que empecemos a verlas.
Sebastian Julon Chamana: las ventajas y desventajas de usar Teams para poder transcribir, por que motivos lo digo, porque nosotros teniamos una idea distinta de que podria funcionar con una aplicacion de escritorio, pero
Sebastian Julon Chamana: Al ver que hay este tipo de escalabilidad, adopcion y seguridad, vale la pena muchisimo adoptar.
Sebastian Julon Chamana: Esta forma de hacerlo con Teams, porque a la larga nos va a facilitar.
Sebastian Julon Chamana: Todo un mundo.
"""

PROMPT_TEMPLATE = open('mayihear-api/agents/prompts/generate_meeting_act.prompt', encoding='utf-8').read()

prompt = (PROMPT_TEMPLATE
    .replace('{transcript}', TRANSCRIPT)
    .replace('{user_context}', 'Equipo de desarrollo evaluando opciones de transcripcion para reuniones institucionales en UTP.')
    .replace('{today_date}', str(date.today())))

client = genai.Client(api_key=get_gemini_api_key())
response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)

print("=== ACTA OUTPUT ===\n")
print(response.text)
