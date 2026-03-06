"""
Configuración del Bot Portón
Completá cada valor con tus credenciales reales antes de deployar.
"""

import os
from dotenv import load_dotenv
load_dotenv()

# ============================================================
# TWILIO - Para recibir llamadas y WhatsApp
# Registrate en https://www.twilio.com y obtené estos datos
# ============================================================
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "tu_auth_token_aca")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "+541112345678")

# ============================================================
# EWELINK - Para controlar el portón
# ============================================================
EWELINK_EMAIL = os.getenv("EWELINK_EMAIL", "tu_email@ejemplo.com")
EWELINK_PASSWORD = os.getenv("EWELINK_PASSWORD", "tu_password")
EWELINK_REGION = os.getenv("EWELINK_REGION", "us")
EWELINK_DEVICE_ID = os.getenv("EWELINK_DEVICE_ID", "")

# ============================================================
# SEGURIDAD - Solo estos números pueden abrir el portón
# Formato: "+5492211234567"
# ============================================================
NUMEROS_AUTORIZADOS = [
    os.getenv("NUMERO_PRINCIPAL", "+5492211234567"),
    os.getenv("NUMERO_2", "+5492215597433"),
    # Agregá más si querés:
    # os.getenv("NUMERO_2", ""),
]
# Filtrar vacíos
NUMEROS_AUTORIZADOS = [n for n in NUMEROS_AUTORIZADOS if n]

# ============================================================
# PORTÓN - Configuración del pulso
# ============================================================
PULSE_SECONDS = int(os.getenv("PULSE_SECONDS", "3"))

# ============================================================
# MENSAJES
# ============================================================
MSG_ABRIENDO = "Abriendo portón..."
MSG_ERROR = "Error al abrir el portón. Intentá de nuevo."
MSG_NO_AUTORIZADO = "No estás autorizado para usar este servicio."
MSG_BIENVENIDA_LLAMADA = "Abriendo el portón. Chau."
MSG_BIENVENIDA_LLAMADA_NO_AUTH = "No estás autorizado. Chau."
