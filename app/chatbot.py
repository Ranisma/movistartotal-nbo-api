# app/chatbot.py

import os
from openai import OpenAI


# ============================================================
# CONFIGURACIÓN DE OPENAI
# ============================================================

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)


# ============================================================
# INSTRUCCIONES DEL ASISTENTE FOCO
# ============================================================

SYSTEM_PROMPT = """
Eres FOCO Assistant, un copiloto comercial inteligente diseñado
para ayudar a los asesores de Movistar durante sus conversaciones
con clientes.

Tu objetivo es ayudar al asesor a comunicar correctamente las
ofertas previamente recomendadas por el motor Next Best Offer
(NBO) de FOCO.

FUNCIONES PERMITIDAS:

- Ayudar a explicar planes y ofertas de Movistar.
- Explicar Movistar Total y sus beneficios cuando dicha información
  haya sido proporcionada por el sistema.
- Generar diálogos comerciales breves para el asesor.
- Sugerir cómo responder ante objeciones del cliente.
- Generar argumentos de rebate.
- Explicar por qué una oferta puede ser conveniente para el cliente.
- Ayudar al asesor a comunicar una recomendación realizada por
  el motor Next Best Offer.
- Comparar ofertas únicamente cuando la información necesaria
  haya sido proporcionada por el sistema.


REGLAS OBLIGATORIAS:

1. Responde únicamente consultas relacionadas con Movistar,
   Movistar Total, planes, ofertas y conversaciones comerciales
   relacionadas.

2. NO inventes precios, promociones, descuentos, condiciones,
   beneficios ni características de productos.

3. Utiliza únicamente la información proporcionada en el contexto.

4. Si no tienes información suficiente para responder con seguridad,
   indícalo claramente.

5. NO cambies ni reemplaces la oferta recomendada por el motor NBO.

6. El motor NBO decide QUÉ ofrecer.
   Tu función es ayudar al asesor a decidir CÓMO comunicarlo.

7. Si el asesor realiza una consulta que no está relacionada con
   Movistar o con la atención comercial, responde:

   "Solo puedo ayudarte con consultas comerciales relacionadas
   con Movistar y las ofertas disponibles para el cliente."

8. No inventes información personal del cliente.

9. No solicites información personal sensible innecesaria.

10. Mantén las respuestas breves, claras y prácticas, ya que serán
    utilizadas por un asesor durante una conversación en tiempo real.

11. Cuando el asesor solicite ayuda frente a una objeción del cliente,
    proporciona una respuesta que pueda utilizar directamente durante
    la conversación.

12. Mantén siempre un tono profesional, claro y respetuoso.

13. No presiones al cliente ni recomiendes ocultar información.

14. Si una promoción, precio o beneficio no aparece explícitamente
    en el contexto proporcionado, indica al asesor que debe verificar
    esa información antes de comunicársela al cliente.
"""


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def consultar_chatbot(
    pregunta: str,
    contexto_cliente: str = ""
) -> str:
    """
    Envía una consulta a FOCO Assistant.

    Parámetros:
    - pregunta:
        Consulta realizada por el asesor.

    - contexto_cliente:
        Información proporcionada por FOCO sobre el cliente.
        Puede incluir:
        * Plan actual
        * Consumo
        * Oferta recomendada
        * Score NBO
        * Motivo de recomendación
        * Ofertas alternativas
        * Beneficios disponibles

    Retorna:
    - Respuesta generada para ayudar al asesor.
    """

    # --------------------------------------------------------
    # VALIDAR LA PREGUNTA
    # --------------------------------------------------------

    if not pregunta or not pregunta.strip():
        return "Ingresa una consulta para poder ayudarte."


    # --------------------------------------------------------
    # CONSTRUIR CONTEXTO
    # --------------------------------------------------------

    if contexto_cliente:
        contexto = contexto_cliente
    else:
        contexto = (
            "No se proporcionó información específica "
            "del cliente."
        )


    mensaje = f"""
==================================================
INFORMACIÓN DISPONIBLE DEL CLIENTE
==================================================

{contexto}


==================================================
CONSULTA DEL ASESOR
==================================================

{pregunta}


==================================================
INSTRUCCIÓN
==================================================

Ayuda al asesor utilizando únicamente la información disponible.
Si falta información necesaria, indícalo claramente.
"""


    # --------------------------------------------------------
    # CONSULTAR OPENAI
    # --------------------------------------------------------

    try:

        response = client.responses.create(
            model="gpt-5-mini",
            instructions=SYSTEM_PROMPT,
            input=mensaje
        )

        return response.output_text


    # --------------------------------------------------------
    # MANEJO DE ERRORES
    # --------------------------------------------------------

    except Exception as e:

        print(f"Error al consultar OpenAI: {e}")

        return (
            "No fue posible consultar a FOCO Assistant "
            "en este momento. Inténtalo nuevamente."
        )