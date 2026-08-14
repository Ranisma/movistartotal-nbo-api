# app/chatbot.py

import anthropic


# ============================================================
# CONFIGURACIÓN DE CLAUDE
# ============================================================

# El SDK buscará automáticamente la variable:
# ANTHROPIC_API_KEY
client = anthropic.Anthropic()


# ============================================================
# RESTRICCIONES DEL ASISTENTE FOCO
# ============================================================

SYSTEM_PROMPT = """
Eres FOCO Assistant, un copiloto comercial inteligente diseñado
para ayudar a los asesores de Movistar durante conversaciones
con clientes.

Tu función es ayudar al asesor a comunicar correctamente las
ofertas previamente recomendadas por el motor Next Best Offer
(NBO) de FOCO.

IMPORTANTE:
Tú NO decides qué producto debe ofrecerse.
La decisión de la oferta corresponde exclusivamente al motor NBO.
Tu función es ayudar al asesor a comunicar esa recomendación.


FUNCIONES PERMITIDAS:

- Ayudar a explicar planes y ofertas de Movistar.
- Explicar Movistar Total cuando exista información disponible.
- Generar diálogos comerciales breves.
- Ayudar al asesor a responder objeciones del cliente.
- Generar argumentos de rebate.
- Explicar por qué una oferta puede ser conveniente.
- Ayudar a comunicar la recomendación realizada por el motor NBO.
- Comparar ofertas únicamente utilizando información proporcionada
  por el sistema.
- Generar ejemplos de respuestas que el asesor pueda utilizar
  directamente durante una conversación.


REGLAS OBLIGATORIAS:

1. Responde únicamente consultas relacionadas con:

   - Movistar.
   - Movistar Total.
   - Planes y servicios Movistar.
   - Ofertas disponibles para el cliente.
   - Atención comercial.
   - Objeciones comerciales.
   - Comunicación entre asesor y cliente.

2. NO inventes:

   - Precios.
   - Descuentos.
   - Promociones.
   - Beneficios.
   - Condiciones comerciales.
   - Características de productos.
   - Planes que no aparezcan en el contexto.

3. Utiliza únicamente la información proporcionada
   en el contexto del cliente y en las ofertas disponibles.

4. Si no existe información suficiente para responder
   correctamente, debes indicarlo claramente.

5. NO cambies la oferta recomendada por el motor NBO.

6. NO recomiendes una oferta diferente por iniciativa propia.

7. El motor NBO decide QUÉ ofrecer.
   Tú ayudas al asesor a decidir CÓMO comunicarlo.

8. Si el asesor realiza una consulta que no está relacionada
   con Movistar o con la atención comercial, responde únicamente:

   "Solo puedo ayudarte con consultas comerciales relacionadas
   con Movistar y las ofertas disponibles para el cliente."

9. No inventes información personal del cliente.

10. No solicites información personal sensible innecesaria.

11. Mantén las respuestas breves, claras y prácticas.

12. Recuerda que el asesor puede estar utilizando el sistema
    mientras conversa en tiempo real con un cliente.

13. Cuando el asesor solicite ayuda frente a una objeción,
    proporciona primero una respuesta breve que pueda utilizar
    directamente con el cliente.

14. Mantén siempre un tono:

    - Profesional.
    - Claro.
    - Amable.
    - Respetuoso.
    - No agresivo.

15. No presiones al cliente.

16. No recomiendes ocultar información o engañar al cliente.

17. Si un precio, promoción o beneficio no aparece explícitamente
    en el contexto, indica que esa información debe verificarse
    antes de comunicársela al cliente.

18. Si el asesor pregunta algo como:
    "¿Qué le digo?"
    "¿Cómo respondo?"
    "El cliente dice que es caro"
    "No quiere aceptar la oferta"

    responde con un diálogo breve y natural que el asesor pueda
    utilizar directamente.
"""


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def consultar_chatbot(
    pregunta: str,
    contexto_cliente: str = ""
) -> str:
    """
    Consulta FOCO Assistant utilizando Claude.

    Parámetros
    ----------
    pregunta:
        Consulta realizada por el asesor.

    contexto_cliente:
        Información proporcionada por FOCO sobre el cliente.

        Puede incluir:
        - Plan actual.
        - Consumo.
        - Facturación.
        - Oferta recomendada.
        - Score NBO.
        - Motivo de recomendación.
        - Ofertas alternativas.
        - Beneficios disponibles.
        - Historial comercial.

    Retorna
    -------
    str:
        Respuesta generada para ayudar al asesor.
    """

    # --------------------------------------------------------
    # VALIDACIÓN
    # --------------------------------------------------------

    if not pregunta or not pregunta.strip():
        return "Ingresa una consulta para poder ayudarte."

    if contexto_cliente:
        contexto = contexto_cliente
    else:
        contexto = (
            "No se proporcionó información específica "
            "del cliente."
        )


    # --------------------------------------------------------
    # MENSAJE QUE RECIBE CLAUDE
    # --------------------------------------------------------

    mensaje = f"""
<cliente>

{contexto}

</cliente>


<consulta_asesor>

{pregunta}

</consulta_asesor>


<instruccion>

Ayuda al asesor utilizando únicamente la información
proporcionada anteriormente.

No inventes información.

Si falta información necesaria, indícalo claramente.

</instruccion>
"""


    # --------------------------------------------------------
    # LLAMADA A CLAUDE
    # --------------------------------------------------------

    try:

        response = client.messages.create(
            model="claude-opus-5",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": mensaje
                }
            ]
        )


        # ----------------------------------------------------
        # EXTRAER RESPUESTA DE TEXTO
        # ----------------------------------------------------

        textos = []

        for bloque in response.content:

            if bloque.type == "text":
                textos.append(bloque.text)

        if not textos:
            return (
                "FOCO Assistant no pudo generar una "
                "respuesta en este momento."
            )

        return "\n".join(textos)


    # --------------------------------------------------------
    # MANEJO DE ERRORES
    # --------------------------------------------------------

    except anthropic.AuthenticationError:

        print("Error: API Key de Anthropic inválida.")

        return (
            "No fue posible autenticar FOCO Assistant."
        )


    except anthropic.RateLimitError:

        print("Error: límite de uso de Claude alcanzado.")

        return (
            "FOCO Assistant ha alcanzado temporalmente "
            "su límite de consultas. Inténtalo nuevamente."
        )


    except anthropic.APIConnectionError:

        print("Error de conexión con Anthropic.")

        return (
            "No fue posible conectarse con FOCO Assistant "
            "en este momento."
        )


    except Exception as e:

        print(f"Error al consultar Claude: {e}")

        return (
            "No fue posible consultar a FOCO Assistant "
            "en este momento. Inténtalo nuevamente."
        )
    