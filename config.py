"""
Configuración del Bot Portón v4
"""

import os
from dotenv import load_dotenv
load_dotenv()

# ============================================================
# ALMACENAMIENTO PERSISTENTE
# ============================================================
# En Render: crear disco persistente y montarlo en /var/data
# Todos los JSON se guardan acá para sobrevivir restarts/deploys
DATA_DIR = os.getenv("DATA_DIR", ".")

# Crear directorio si no existe
os.makedirs(DATA_DIR, exist_ok=True)

# ============================================================
# TWILIO
# ============================================================
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "tu_auth_token_aca")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "+541112345678")

# Número de WhatsApp para mensajes proactivos
# IMPORTANTE: tiene que ser el número exacto como Twilio lo conoce
# Para Argentina móvil suele ser +549XXXXXXXXXX (con el 9)
# Verificalo en Twilio Console > WhatsApp Senders
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", TWILIO_PHONE_NUMBER)

# ============================================================
# EWELINK
# ============================================================
EWELINK_EMAIL = os.getenv("EWELINK_EMAIL", "tu_email@ejemplo.com")
EWELINK_PASSWORD = os.getenv("EWELINK_PASSWORD", "tu_password")
EWELINK_REGION = os.getenv("EWELINK_REGION", "us")
EWELINK_DEVICE_ID = os.getenv("EWELINK_DEVICE_ID", "")

# ============================================================
# JWT (para la PWA)
# ============================================================
JWT_SECRET = os.getenv("JWT_SECRET", TWILIO_AUTH_TOKEN)  # Fallback al token de Twilio si no se configura

# ============================================================
# ROLES Y SEGURIDAD
# ============================================================
HABITANTE_PIN = os.getenv("HABITANTE_PIN", os.getenv("ADMIN_PIN", "1234"))

NUMEROS_SUPERADMIN = [
    os.getenv("SUPERADMIN_1", os.getenv("NUMERO_PRINCIPAL", "")),
    os.getenv("SUPERADMIN_2", os.getenv("NUMERO_2", "")),
    os.getenv("SUPERADMIN_3", os.getenv("NUMERO_3", "")),
    os.getenv("SUPERADMIN_4", os.getenv("NUMERO_4", "")),
]
NUMEROS_SUPERADMIN = [n for n in NUMEROS_SUPERADMIN if n]

# ============================================================
# PORTÓN
# ============================================================
PULSE_SECONDS = int(os.getenv("PULSE_SECONDS", "3"))
NOMBRE_BARRIO = os.getenv("NOMBRE_BARRIO", "Barrio Nirvana")
PREFIJO_PAIS = os.getenv("PREFIJO_PAIS", "+549")

# Rate limit: máximo de pulsos por número por minuto
RATE_LIMIT_POR_MINUTO = int(os.getenv("RATE_LIMIT_POR_MINUTO", "6"))

# ============================================================
# ZONA HORARIA
# ============================================================
TIMEZONE = os.getenv("TIMEZONE", "America/Argentina/Buenos_Aires")

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def ahora():
    """Datetime actual en la zona horaria configurada."""
    return datetime.now(ZoneInfo(TIMEZONE))

# ============================================================
# MENSAJES
# ============================================================
MSG_ABRIENDO = "Abriendo portón..."
MSG_CERRANDO = "Cerrando portón..."
MSG_ERROR = "Error al operar el portón. Intentá de nuevo."
MSG_NO_AUTORIZADO = "⛔ No estás autorizado para usar este servicio."
MSG_BIENVENIDA_LLAMADA = "Abriendo el portón. Chau."
MSG_BIENVENIDA_LLAMADA_NO_AUTH = "No estás autorizado. Chau."
