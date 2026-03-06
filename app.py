"""
Bot Portón - Servidor principal
Recibe llamadas y mensajes de WhatsApp via Twilio,
verifica autorización y activa el portón via eWeLink.
"""

import logging
import threading
from flask import Flask, request
from twilio.twiml.voice_response import VoiceResponse
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator

import config
from ewelink_controller import EWeLinkController, sync_pulse

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Validador Twilio (verifica que las requests vengan de Twilio, no de un random)
validator = RequestValidator(config.TWILIO_AUTH_TOKEN)


def esta_autorizado(numero: str) -> bool:
    """Verificar si el número está en la lista de autorizados."""
    # Normalizar: sacar espacios, guiones
    numero_limpio = numero.replace(" ", "").replace("-", "")
    for autorizado in config.NUMEROS_AUTORIZADOS:
        if autorizado.replace(" ", "").replace("-", "") in numero_limpio:
            return True
        if numero_limpio in autorizado.replace(" ", "").replace("-", ""):
            return True
    return False


def activar_porton():
    """Activar el portón en un thread separado para no bloquear la respuesta."""
    try:
        controller = EWeLinkController(
            email=config.EWELINK_EMAIL,
            password=config.EWELINK_PASSWORD,
            region=config.EWELINK_REGION,
            device_id=config.EWELINK_DEVICE_ID,
        )
        resultado = sync_pulse(controller, config.PULSE_SECONDS)
        if resultado:
            logger.info("Portón activado exitosamente")
        else:
            logger.error("Fallo al activar portón")
    except Exception as e:
        logger.error(f"Error activando portón: {e}")


# ============================================================
# WEBHOOK: LLAMADA TELEFÓNICA
# Cuando llamás al número Twilio, entra acá
# ============================================================
@app.route("/voice", methods=["POST"])
def handle_call():
    """Manejar llamada entrante."""
    caller = request.form.get("From", "")
    logger.info(f"Llamada recibida de: {caller}")

    response = VoiceResponse()

    if esta_autorizado(caller):
        logger.info(f"Número autorizado: {caller} - Abriendo portón")
        response.say(config.MSG_BIENVENIDA_LLAMADA, language="es-AR")
        # Mantener la llamada viva esperando que el usuario corte
        response.pause(length=60)

        # Activar portón (abrir)
        thread = threading.Thread(target=activar_porton)
        thread.start()
    else:
        logger.warning(f"Número NO autorizado intentó abrir: {caller}")
        response.say(config.MSG_BIENVENIDA_LLAMADA_NO_AUTH, language="es-AR")
        response.hangup()

    return str(response), 200, {"Content-Type": "text/xml"}


@app.route("/voice/status", methods=["POST"])
def handle_call_status():
    """Cuando el usuario corta la llamada, cerrar el portón."""
    call_status = request.form.get("CallStatus", "")
    caller = request.form.get("From", "")
    logger.info(f"Status de llamada de {caller}: {call_status}")

    if call_status == "completed" and esta_autorizado(caller):
        logger.info(f"Llamada cortada por {caller} - Cerrando portón")
        thread = threading.Thread(target=activar_porton)
        thread.start()

    return "", 200


# ============================================================
# WEBHOOK: WHATSAPP
# Cuando mandás un mensaje de WA al número Twilio, entra acá
# ============================================================
@app.route("/whatsapp", methods=["POST"])
def handle_whatsapp():
    """Manejar mensaje de WhatsApp entrante."""
    sender = request.form.get("From", "")
    body = request.form.get("Body", "").strip().lower()
    logger.info(f"WhatsApp de {sender}: {body}")

    response = MessagingResponse()

    if not esta_autorizado(sender):
        logger.warning(f"WhatsApp no autorizado de: {sender}")
        response.message(config.MSG_NO_AUTORIZADO)
        return str(response), 200, {"Content-Type": "text/xml"}

    # Comandos reconocidos
    comandos_abrir = ["abrir", "abrí", "abrime", "dale", "porton", "portón", "open", "1"]

    if any(cmd in body for cmd in comandos_abrir):
        logger.info(f"Comando de apertura recibido de {sender}")
        response.message(config.MSG_ABRIENDO)

        # Activar portón en background
        thread = threading.Thread(target=activar_porton)
        thread.start()

    elif body in ["estado", "status", "?"]:
        response.message("Bot activo. Mandá 'abrir' para abrir el portón.")

    elif body in ["help", "ayuda"]:
        response.message(
            "Comandos disponibles:\n"
            "• abrir / abrí / dale / 1 → Abre el portón\n"
            "• estado → Verificar que el bot funcione\n"
            "• ayuda → Este mensaje"
        )
    else:
        # Cualquier otro mensaje también abre (para máxima comodidad)
        # Si preferís que solo abra con comandos específicos, comentá estas líneas
        # y descomentá la alternativa de abajo
        logger.info(f"Mensaje genérico de usuario autorizado, abriendo portón")
        response.message(config.MSG_ABRIENDO)
        thread = threading.Thread(target=activar_porton)
        thread.start()

        # ALTERNATIVA: Solo responder con ayuda si el comando no se reconoce
        # response.message("No entendí. Mandá 'abrir' para abrir el portón o 'ayuda'.")

    return str(response), 200, {"Content-Type": "text/xml"}


# ============================================================
# HEALTH CHECK
# ============================================================
@app.route("/", methods=["GET"])
def health():
    """Endpoint de salud para que Render/Railway sepan que está vivo."""
    return {"status": "ok", "service": "porton-bot"}, 200


# ============================================================
# UTILIDAD: Listar dispositivos eWeLink
# Accedé a /devices para ver tus dispositivos y obtener el device_id
# ============================================================
@app.route("/devices", methods=["GET"])
def list_devices():
    """Listar dispositivos eWeLink (para encontrar el device_id del portón)."""
    from ewelink_controller import sync_get_devices

    controller = EWeLinkController(
        email=config.EWELINK_EMAIL,
        password=config.EWELINK_PASSWORD,
        region=config.EWELINK_REGION,
        device_id=config.EWELINK_DEVICE_ID,
    )
    devices = sync_get_devices(controller)

    if devices:
        return {"devices": devices}, 200
    else:
        return {"error": "No se pudieron obtener dispositivos. Verificá credenciales."}, 500


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Bot Portón iniciando...")
    logger.info(f"Números autorizados: {config.NUMEROS_AUTORIZADOS}")
    logger.info(f"Pulso configurado: {config.PULSE_SECONDS} segundos")
    logger.info("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True)
