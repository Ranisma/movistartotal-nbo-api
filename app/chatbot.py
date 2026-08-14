# app/chatbot.py

import os
from google import genai


# ============================================================
# CONFIGURACIÓN DE GEMINI
# ============================================================

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


# ============================================================
# RESTRICCIONES DEL ASISTENTE FOCO
# ============================================================

SYSTEM_PROMPT = """
Eres FOCO Assistant, un copiloto comercial inteligente diseñado
para ayudar a asesores de Movistar durante conversaciones con clientes.

Tu objetivo es ayudar al asesor a comunicar correctamente las
ofertas previamente recomendadas por el motor Next Best Offer (NBO).

FUNCIONES PERMITIDAS:

- Explicar planes y ofertas de Movistar.
- Explicar Movistar Total y sus beneficios cuando la información
  haya sido proporcionada por el sistema.
- Generar diálogos comerciales breves.
- Sugerir respuestas frente a objeciones del cliente.
- Generar argumentos de rebate.
- Explicar por qué una oferta puede ser conveniente.
- Ayudar al asesor a comunicar la recomendación del motor NBO.
- Comparar ofertas solo con información proporcionada por el sistema.

REGLAS OBLIGATORIAS:

1. Responde únicamente sobre Movistar, Movistar Total, planes,
   ofertas y conversaciones comerciales relacionadas.

2. NO inventes precios, promociones, descuentos, condiciones,
   beneficios ni características.

3. Utiliza únicamente la información incluida en el contexto.

4. Si falta información, indícalo claramente.

5. NO cambies ni reemplaces la oferta recomendada por el motor NBO.

6. El motor NBO decide QUÉ ofrecer.
   Tú ayudas al asesor a decidir CÓMO comunicarlo.

7. Si la consulta está fuera del ámbito comercial de Movistar, responde:

   "Solo puedo ayudarte con consultas comerciales relacionadas
   con Movistar y las ofertas disponibles para el cliente."

8. No inventes información personal del cliente.

9. No solicites información sensible innecesaria.

10. Mantén las respuestas breves, claras y prácticas.

11. Cuando exista una objeción del cliente, entrega una respuesta
    que el asesor pueda utilizar directamente.

12. Mantén un tono profesional, claro y respetuoso.

13. No presiones al cliente ni sugieras ocultar información.

14. Si un precio, promoción o beneficio no aparece expresamente
    en el contexto, indica que debe verificarse antes de comunicarlo.
"""


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def consultar_chatbot(
    pregunta: str,
    contexto_cliente: str = ""
) -> str:

    if not pregunta or not pregunta.strip():
        return "Ingresa una consulta para poder ayudarte."

    contexto = contexto_cliente if contexto_cliente else (
        "No se proporcionó información específica del cliente."
    )

    mensaje = f"""
INFORMACIÓN DISPONIBLE DEL CLIENTE:

{contexto}


CONSULTA DEL ASESOR:

{pregunta}


INSTRUCCIÓN:

Ayuda al asesor utilizando únicamente la información proporcionada.
Si falta información necesaria, indícalo claramente.
"""

    try:

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=mensaje,
            config={
                "system_instruction": SYSTEM_PROMPT
            }
        )

        return response.text

    except Exception as e:

        print(f"Error al consultar Gemini: {e}")

        return (
            "No fue posible consultar a FOCO Assistant "
            "en este momento. Inténtalo nuevamente."
        )
    