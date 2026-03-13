"""
Bot Portón v3.1 - Servidor principal

Roles:
  👑 superadmin → todo (definido en .env)
  🏠 habitante  → abrir, cerrar, dar temporales (se registra con PIN)
  ⏰ temporal   → solo abrir y cerrar (en su ventana)
  🚫 ninguno    → nada (puede registrarse con PIN)

v3.1:
  - Controller singleton (no crea instancia nueva cada vez)
  - Token cacheado (no hace login en cada operación)
  - Solo avisa al usuario si el pulso falló
  - Modo bloqueo para superadmins
"""

import logging
import os
import re
import threading
from datetime import datetime
from flask import Flask, request, send_from_directory
from twilio.twiml.voice_response import VoiceResponse
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator

import config
import accesos
import registro
from ewelink_controller import get_controller

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder=os.path.join(_BASE_DIR, "static"))

# Validador de firma Twilio
_twilio_validator = RequestValidator(config.TWILIO_AUTH_TOKEN)

def _validar_twilio():
    """Valida que el request venga realmente de Twilio."""
    # En desarrollo local se puede desactivar con SKIP_TWILIO_VALIDATION=true
    if os.getenv("SKIP_TWILIO_VALIDATION", "false").lower() == "true":
        return True
    signature = request.headers.get("X-Twilio-Signature", "")
    url = request.url
    params = request.form.to_dict()
    return _twilio_validator.validate(url, params, signature)

# Registrar API Blueprint
from api import api as api_blueprint
app.register_blueprint(api_blueprint)

# Inicializar superadmins desde .env
accesos.inicializar(config.NUMEROS_SUPERADMIN, config.HABITANTE_PIN)

# Pre-inicializar controller (hace login temprano para detectar problemas)
try:
    _ctrl = get_controller()
    logger.info("Controller eWeLink inicializado")
except Exception as e:
    logger.error(f"Error inicializando controller eWeLink: {e}")

# ============================================================
# ESTADO PERSISTENTE (sobrevive restarts)
# ============================================================
import json as _json

_STATE_FILE = os.path.join(config.DATA_DIR, "estado.json")
_state_lock = threading.Lock()


def _load_state() -> dict:
    """Cargar estado del disco."""
    try:
        if os.path.exists(_STATE_FILE):
            with open(_STATE_FILE, "r") as f:
                return _json.load(f)
    except Exception:
        pass
    return {
        "ultima_accion": None,
        "ultimo_cambio": None,
        "ultimo_usuario": None,
        "bloqueado": False,
        "bloqueado_por": None,
        "bloqueado_timestamp": None,
    }


def _save_state(state: dict):
    """Guardar estado al disco."""
    try:
        with open(_STATE_FILE, "w") as f:
            _json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Error guardando estado: {e}")


def _set_estado(accion: str, usuario: str = ""):
    with _state_lock:
        state = _load_state()
        state["ultima_accion"] = accion
        state["ultimo_cambio"] = config.ahora().isoformat()
        state["ultimo_usuario"] = usuario
        _save_state(state)


def _get_estado() -> dict:
    with _state_lock:
        state = _load_state()
        return {
            "ultima_accion": state.get("ultima_accion"),
            "ultimo_cambio": state.get("ultimo_cambio"),
            "ultimo_usuario": state.get("ultimo_usuario"),
        }


def _esta_bloqueado() -> bool:
    with _state_lock:
        return _load_state().get("bloqueado", False)


def _set_bloqueo(activo: bool, usuario: str = ""):
    with _state_lock:
        state = _load_state()
        state["bloqueado"] = activo
        state["bloqueado_por"] = usuario if activo else None
        state["bloqueado_timestamp"] = config.ahora().isoformat() if activo else None
        _save_state(state)


def _get_bloqueo() -> dict:
    with _state_lock:
        state = _load_state()
        return {
            "activo": state.get("bloqueado", False),
            "activado_por": state.get("bloqueado_por"),
            "timestamp": state.get("bloqueado_timestamp"),
        }


# ============================================================
# RATE LIMITING (en memoria, se resetea en restart, está bien)
# ============================================================
from collections import defaultdict
import time as _time_mod

_rate_limit = defaultdict(list)  # número → [timestamps]
_rate_lock = threading.Lock()


def _check_rate_limit(numero: str) -> bool:
    """
    Verificar si un número puede hacer otra operación.
    Retorna True si está dentro del límite.
    """
    with _rate_lock:
        ahora = _time_mod.time()
        # Limpiar timestamps viejos (> 60 segundos)
        _rate_limit[numero] = [t for t in _rate_limit[numero] if ahora - t < 60]
        if len(_rate_limit[numero]) >= config.RATE_LIMIT_POR_MINUTO:
            return False
        _rate_limit[numero].append(ahora)
        return True


# ============================================================
# ACTIVAR PORTÓN (con feedback de errores)
# ============================================================

def activar_porton(accion: str = "abrir", usuario: str = "", notificar_error: bool = True):
    """
    Activar el portón usando el controller singleton.
    Si falla y notificar_error=True, manda WhatsApp al usuario avisando.
    """
    controller = get_controller()
    result = controller.pulse(config.PULSE_SECONDS)

    if result.ok:
        _set_estado(accion, usuario=usuario)
        logger.info(f"Portón: {accion} por {usuario}")
    else:
        logger.error(f"Fallo al {accion} portón: {result.detalle}")
        registro.registrar(
            usuario, f"error_{accion}", "sistema",
            detalle=result.detalle
        )

        # Mandar mensaje de error al usuario via Twilio REST API
        if notificar_error and usuario:
            _enviar_whatsapp(
                usuario,
                f"❌ No se pudo {accion} el portón.\n{result.error}"
            )


def _enviar_whatsapp(destinatario: str, mensaje: str):
    """Enviar un WhatsApp proactivo via Twilio REST API. Falla silenciosamente."""
    try:
        from twilio.rest import Client
        client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)

        to_num = destinatario.strip()
        if not to_num.startswith("whatsapp:"):
            to_num = f"whatsapp:{to_num}"

        from_num = f"whatsapp:{config.TWILIO_WHATSAPP_NUMBER}"

        client.messages.create(
            body=mensaje,
            from_=from_num,
            to=to_num,
        )
        logger.info(f"WhatsApp enviado OK a {to_num}")
    except Exception as e:
        logger.warning(f"No se pudo enviar WhatsApp proactivo: {e}")


def _notificar_superadmins(mensaje: str):
    """Notificar a todos los superadmins via WhatsApp."""
    datos = accesos._cargar_datos()
    for num in datos["superadmins"]:
        _enviar_whatsapp(num, mensaje)


# ============================================================
# COMANDOS
# ============================================================

COMANDOS_ABRIR = [
    "abrir", "abrí", "abrime", "abrilo",
    "dale", "porton", "portón", "open",
    "afuera", "salgo", "entro", "llegue", "llegué",
    "estoy", "estoy afuera", "estoy en la puerta",
    "abri", "abrí porton", "abrí portón",
]

COMANDOS_CERRAR = [
    "cerrar", "cerrá", "cerralo", "cerrar portón", "cerrar porton",
    "close", "cerrame", "cerrá el portón",
    "cerra", "cerrá porton", "cerrá portón",
]


def _es_comando(texto: str, comandos: list) -> bool:
    texto = texto.lower().strip()
    for cmd in comandos:
        if texto == cmd or texto.startswith(cmd + " ") or texto.endswith(" " + cmd):
            return True
    return False


def _es_comando_abrir(texto: str) -> bool:
    return texto.strip() == "1" or _es_comando(texto, COMANDOS_ABRIR)


def _es_comando_cerrar(texto: str) -> bool:
    return texto.strip() == "2" or _es_comando(texto, COMANDOS_CERRAR)


# ============================================================
# WEBHOOK: LLAMADA TELEFÓNICA
# ============================================================
@app.route("/voice", methods=["POST"])
def handle_call():
    if not _validar_twilio():
        logger.warning("Llamada rechazada: firma Twilio inválida")
        return "", 403

    caller = request.form.get("From", "")
    logger.info(f"Llamada recibida de: {caller}")

    response = VoiceResponse()

    if _esta_bloqueado() and not accesos.es_superadmin(caller):
        response.say("El portón está bloqueado. Contactá al administrador.", language="es-AR")
        response.hangup()
        registro.registrar(caller, "bloqueado", "llamada")
        return str(response), 200, {"Content-Type": "text/xml"}

    if accesos.esta_autorizado(caller):
        logger.info(f"Número autorizado: {caller} - Abriendo portón")
        response.say(config.MSG_BIENVENIDA_LLAMADA, language="es-AR")
        response.pause(length=60)

        nombre = accesos.obtener_nombre_temporal(caller)
        registro.registrar(caller, "abrir", "llamada", nombre=nombre)

        thread = threading.Thread(
            target=activar_porton,
            args=("abrir", caller),
            kwargs={"notificar_error": False},  # No podemos mandar WA a quien llama
        )
        thread.start()
    else:
        logger.warning(f"Número NO autorizado intentó abrir: {caller}")
        response.say(config.MSG_BIENVENIDA_LLAMADA_NO_AUTH, language="es-AR")
        response.hangup()
        registro.registrar(caller, "acceso_denegado", "llamada")

    return str(response), 200, {"Content-Type": "text/xml"}


@app.route("/voice/status", methods=["POST"])
def handle_call_status():
    call_status = request.form.get("CallStatus", "")
    caller = request.form.get("From", "")
    logger.info(f"Status de llamada de {caller}: {call_status}")

    if call_status == "completed" and accesos.esta_autorizado(caller):
        logger.info(f"Llamada cortada por {caller} - Cerrando portón")
        nombre = accesos.obtener_nombre_temporal(caller)
        registro.registrar(caller, "cerrar", "llamada", nombre=nombre, detalle="corte de llamada")
        thread = threading.Thread(
            target=activar_porton,
            args=("cerrar", caller),
            kwargs={"notificar_error": False},
        )
        thread.start()

    return "", 200


# ============================================================
# WEBHOOK: WHATSAPP
# ============================================================
@app.route("/whatsapp", methods=["POST"])
def handle_whatsapp():
    if not _validar_twilio():
        logger.warning("WhatsApp rechazado: firma Twilio inválida")
        return "", 403

    sender = request.form.get("From", "")
    body = request.form.get("Body", "").strip()
    body_lower = body.lower()
    logger.info(f"WhatsApp de {sender}: {body}")

    response = MessagingResponse()
    rol = accesos.obtener_rol(sender)

    # ----------------------------------------------------------
    # PIN: cualquier número puede registrarse como habitante
    # ----------------------------------------------------------
    if body_lower.startswith("pin "):
        pin = body.split(" ", 1)[1].strip()
        if accesos.verificar_pin(pin):
            numero_limpio = sender.replace("whatsapp:", "")
            resultado = accesos.agregar_habitante(numero_limpio)
            response.message(
                f"🔑 PIN correcto. {resultado}\n\n"
                f"Comandos disponibles:\n"
                f"• *ABRIR* - Abrir el portón\n"
                f"• *CERRAR* - Cerrar el portón\n"
                f"• *TEMPORAL* - Dar acceso temporal\n"
                f"• *AYUDA* - Ver todos los comandos"
            )
            registro.registrar(sender, "pin_ok", "whatsapp", detalle=f"registrado como habitante")
            _notificar_superadmins(f"🔑 Nuevo habitante registrado: {numero_limpio}")
        else:
            response.message("❌ PIN incorrecto.")
            registro.registrar(sender, "pin_fail", "whatsapp")
        return str(response), 200, {"Content-Type": "text/xml"}

    # ----------------------------------------------------------
    # CÓDIGO DE INVITACIÓN: cualquier número puede usarlo
    # ----------------------------------------------------------
    if body_lower.startswith("codigo ") or body_lower.startswith("código "):
        codigo = body.split(" ", 1)[1].strip()
        numero_limpio = sender.replace("whatsapp:", "")
        ok, mensaje = accesos.usar_invitacion(codigo, numero_limpio)

        if ok:
            registro.registrar(sender, "invitacion_usada", "whatsapp", detalle=f"código: {codigo}")
            # Bienvenida
            response.message(
                f"✅ {mensaje}\n\n"
                f"Bienvenido al portón de *{config.NOMBRE_BARRIO}*.\n"
                f"Para abrir mandá *ABRIR*\n"
                f"Para cerrar mandá *CERRAR*"
            )
        else:
            response.message(mensaje)

        return str(response), 200, {"Content-Type": "text/xml"}

    # ----------------------------------------------------------
    # No autorizado → solo puede usar PIN o CODIGO
    # ----------------------------------------------------------
    if rol == "ninguno":
        logger.warning(f"WhatsApp no autorizado de: {sender}")
        response.message(
            config.MSG_NO_AUTORIZADO + "\n\n"
            "Si tenés un *PIN*, mandá: *PIN xxxx*\n"
            "Si tenés un *código de invitación*, mandá: *CODIGO xxxx*"
        )
        registro.registrar(sender, "acceso_denegado", "whatsapp", detalle=body[:50])
        return str(response), 200, {"Content-Type": "text/xml"}

    # ----------------------------------------------------------
    # MODO BLOQUEO: solo superadmins pueden operar
    # ----------------------------------------------------------
    if _esta_bloqueado() and not accesos.es_superadmin(sender):
        response.message("🔴 El portón está *BLOQUEADO* por un administrador. No se puede operar.")
        return str(response), 200, {"Content-Type": "text/xml"}

    # ----------------------------------------------------------
    # ABRIR (todos los roles autorizados)
    # ----------------------------------------------------------
    if _es_comando_abrir(body_lower):
        if not _check_rate_limit(sender):
            response.message("⏳ Demasiados intentos. Esperá un minuto.")
            return str(response), 200, {"Content-Type": "text/xml"}

        nombre = accesos.obtener_nombre_temporal(sender)
        logger.info(f"Comando ABRIR de {sender} (rol: {rol})")
        response.message(f"🔓 {config.MSG_ABRIENDO}")
        registro.registrar(sender, "abrir", "whatsapp", nombre=nombre)

        thread = threading.Thread(target=activar_porton, args=("abrir", sender))
        thread.start()
        return str(response), 200, {"Content-Type": "text/xml"}

    # ----------------------------------------------------------
    # CERRAR (todos los roles autorizados)
    # ----------------------------------------------------------
    if _es_comando_cerrar(body_lower):
        if not _check_rate_limit(sender):
            response.message("⏳ Demasiados intentos. Esperá un minuto.")
            return str(response), 200, {"Content-Type": "text/xml"}

        nombre = accesos.obtener_nombre_temporal(sender)
        logger.info(f"Comando CERRAR de {sender} (rol: {rol})")
        response.message(f"🔒 {config.MSG_CERRANDO}")
        registro.registrar(sender, "cerrar", "whatsapp", nombre=nombre)

        thread = threading.Thread(target=activar_porton, args=("cerrar", sender))
        thread.start()
        return str(response), 200, {"Content-Type": "text/xml"}

    # ----------------------------------------------------------
    # TEMPORAL (habitante + superadmin)
    # ----------------------------------------------------------
    if body_lower.startswith("temporal "):
        if rol == "temporal":
            response.message("⛔ Solo habitantes y admins pueden dar accesos temporales.")
            return str(response), 200, {"Content-Type": "text/xml"}

        parsed = accesos.parsear_temporal_natural(body)

        if not parsed:
            response.message(
                "No pude entender el comando. Ejemplos:\n\n"
                "TEMPORAL 2211234567 una semana Pintor\n"
                "TEMPORAL 2211234567 2 semanas habiles 8 a 17 Electricista\n"
                "TEMPORAL 2211234567 hasta el viernes 9 a 18 Gasista\n"
                "TEMPORAL 2211234567 3 dias Delivery\n"
                "TEMPORAL 2211234567 hoy 10 a 14 Plomero\n\n"
                "_Si es número extranjero, poné el prefijo: +1..., +55..._"
            )
            return str(response), 200, {"Content-Type": "text/xml"}

        creado_por = sender.replace("whatsapp:", "")
        resultado = accesos.agregar_temporal(
            parsed["numero"], parsed["fecha_desde"], parsed["fecha_hasta"],
            parsed["dias"], parsed["hora_desde"], parsed["hora_hasta"],
            parsed["nombre"], creado_por=creado_por,
        )
        response.message(
            resultado + "\n\n"
            "⚠️ *Se le va a enviar un mensaje al número invitado* "
            "avisándole que tiene acceso al portón. "
            "Tené cuidado a quién le das acceso."
        )
        registro.registrar(
            sender, "temporal_creado", "whatsapp",
            detalle=f"{parsed['numero']} | {parsed['nombre']} | {parsed['fecha_desde']} a {parsed['fecha_hasta']}"
        )

        # Mensaje de bienvenida al número temporal
        dias_nombres = ["LUN", "MAR", "MIE", "JUE", "VIE", "SAB", "DOM"]

        # Armar info de días de forma inteligente
        info_dias = ""
        es_mismo_dia = parsed["fecha_desde"] == parsed["fecha_hasta"]
        if not es_mismo_dia:
            # Solo mostrar días si el período es más de un día
            if sorted(parsed["dias"]) == [0, 1, 2, 3, 4, 5, 6]:
                info_dias = "\n📆 Días: Todos"
            elif sorted(parsed["dias"]) == [0, 1, 2, 3, 4]:
                info_dias = "\n📆 Días: Lunes a Viernes"
            elif sorted(parsed["dias"]) == [5, 6]:
                info_dias = "\n📆 Días: Fines de semana"
            else:
                dias_str = ", ".join([dias_nombres[d] for d in parsed["dias"]])
                info_dias = f"\n📆 Días: {dias_str}"

        horario = ""
        if parsed["hora_desde"] != "00:00" or parsed["hora_hasta"] != "23:59":
            horario = f"\n🕐 Horario: {parsed['hora_desde']} a {parsed['hora_hasta']}"

        bienvenida = (
            f"👋 Hola! Te dieron acceso al portón de *{config.NOMBRE_BARRIO}*.\n\n"
            f"📅 {'Fecha: ' + parsed['fecha_desde'] if es_mismo_dia else 'Desde ' + parsed['fecha_desde'] + ' hasta ' + parsed['fecha_hasta']}"
            f"{info_dias}{horario}\n\n"
            f"Para abrir mandá *ABRIR*\n"
            f"Para cerrar mandá *CERRAR*"
        )
        _enviar_whatsapp(parsed["numero"], bienvenida)

        # Notificar a superadmins si lo hizo un habitante
        if rol == "habitante":
            _notificar_superadmins(
                f"⏰ Acceso temporal creado por {creado_por}:\n"
                f"Para: {parsed['numero']} ({parsed['nombre'] or 'sin nombre'})\n"
                f"Período: {parsed['fecha_desde']} a {parsed['fecha_hasta']}"
            )
        return str(response), 200, {"Content-Type": "text/xml"}

    # ----------------------------------------------------------
    # INVITAR: crear código de invitación grupal (habitante + superadmin)
    # ----------------------------------------------------------
    if body_lower.startswith("invitar"):
        if rol == "temporal":
            response.message("⛔ Solo habitantes y admins pueden crear invitaciones.")
            return str(response), 200, {"Content-Type": "text/xml"}

        # Parsear con lenguaje natural: INVITAR [período] [personas] [horario] [motivo]
        resto = body[len("invitar"):].strip() if len(body) > 7 else ""
        parsed = accesos.parsear_invitacion_natural(resto)

        creado_por = sender.replace("whatsapp:", "")
        inv = accesos.crear_invitacion(
            fecha_desde=parsed["fecha_desde"],
            fecha_hasta=parsed["fecha_hasta"],
            horas=parsed["horas"],
            max_usos=parsed["max_usos"],
            motivo=parsed["motivo"],
            creado_por=creado_por,
            dias=parsed["dias"],
            hora_desde=parsed["hora_desde"],
            hora_hasta=parsed["hora_hasta"],
        )

        # Armar info de período para el mensaje
        dias_nombres = ["LUN", "MAR", "MIE", "JUE", "VIE", "SAB", "DOM"]
        es_mismo_dia = inv["fecha_desde"] == inv["fecha_hasta"]
        hora_d = inv["hora_desde"]
        hora_h = inv["hora_hasta"]
        tiene_horario = hora_d != "00:00" or hora_h != "23:59"

        if es_mismo_dia:
            if tiene_horario:
                periodo_str = f"Fecha: {inv['fecha_desde']} de {hora_d} a {hora_h}hs"
            else:
                periodo_str = f"Fecha: {inv['fecha_desde']}"
        else:
            if tiene_horario:
                periodo_str = (
                    f"Desde: {inv['fecha_desde']} {hora_d}hs\n"
                    f"Hasta: {inv['fecha_hasta']} {hora_h}hs"
                )
            else:
                periodo_str = f"Desde {inv['fecha_desde']} hasta {inv['fecha_hasta']}"

        info_dias = ""
        if not es_mismo_dia and not tiene_horario:
            if sorted(inv["dias"]) == [0, 1, 2, 3, 4, 5, 6]:
                info_dias = ""
            elif sorted(inv["dias"]) == [0, 1, 2, 3, 4]:
                info_dias = "\nDías: Lunes a Viernes"
            elif sorted(inv["dias"]) == [5, 6]:
                info_dias = "\nDías: Fines de semana"
            else:
                info_dias = f"\nDías: {', '.join([dias_nombres[d] for d in inv['dias']])}"

        response.message(
            f"🎟️ *Invitación creada*\n\n"
            f"Código: *{inv['codigo']}*\n"
            f"Motivo: {parsed['motivo'] or '—'}\n"
            f"{periodo_str}{info_dias}\n"
            f"Máximo: {parsed['max_usos']} personas\n\n"
            f"Compartí este mensaje:\n\n"
            f"_Para acceder al portón de {config.NOMBRE_BARRIO}, "
            f"mandá un WhatsApp al {config.TWILIO_WHATSAPP_NUMBER} con el texto:_\n"
            f"*CODIGO {inv['codigo']}*"
        )
        registro.registrar(
            sender, "invitacion_creada", "whatsapp",
            detalle=f"código: {inv['codigo']} | {periodo_str} | max {parsed['max_usos']} | {parsed['motivo']}"
        )
        return str(response), 200, {"Content-Type": "text/xml"}

    # ----------------------------------------------------------
    # INVITACIONES: listar activas
    #   - superadmin ve todas
    #   - habitante ve solo las que creó
    # ----------------------------------------------------------
    if body_lower in ["invitaciones", "codigos", "códigos"]:
        if rol == "temporal":
            response.message("⛔ No tenés permisos para ver invitaciones.")
            return str(response), 200, {"Content-Type": "text/xml"}

        if rol == "superadmin":
            resultado = accesos.listar_invitaciones()  # todas
        else:
            resultado = accesos.listar_invitaciones(creado_por=sender.replace("whatsapp:", ""))
        response.message(resultado)
        return str(response), 200, {"Content-Type": "text/xml"}

    # ----------------------------------------------------------
    # CANCELAR invitación (habitante: solo las suyas, admin: todas)
    # ----------------------------------------------------------
    if body_lower.startswith("cancelar "):
        if rol == "temporal":
            response.message("⛔ No tenés permisos para cancelar invitaciones.")
            return str(response), 200, {"Content-Type": "text/xml"}

        codigo = body.split(" ", 1)[1].strip()
        if rol == "superadmin":
            resultado = accesos.cancelar_invitacion(codigo)
        else:
            resultado = accesos.cancelar_invitacion(codigo, solicitado_por=sender.replace("whatsapp:", ""))
        response.message(resultado)
        registro.registrar(sender, "invitacion_cancelada", "whatsapp", detalle=f"código: {codigo}")
        return str(response), 200, {"Content-Type": "text/xml"}

    # ----------------------------------------------------------
    # MIS ACCESOS: ver temporales que creaste (habitante + admin)
    # ----------------------------------------------------------
    if body_lower in ["mis accesos", "mis temporales", "mis invitados"]:
        if rol == "temporal":
            response.message("⛔ No tenés permisos para ver esto.")
            return str(response), 200, {"Content-Type": "text/xml"}

        creado_por = sender.replace("whatsapp:", "")
        temporales = accesos.listar_temporales_creados(creado_por)
        invitaciones = accesos.listar_invitaciones(creado_por=creado_por)
        response.message(f"{temporales}\n{invitaciones}")
        return str(response), 200, {"Content-Type": "text/xml"}

    # ----------------------------------------------------------
    # BORRAR TEMPORAL: borrar un acceso temporal que creaste
    # ----------------------------------------------------------
    if body_lower.startswith("borrar temporal ") or body_lower.startswith("eliminar temporal "):
        if rol == "temporal":
            response.message("⛔ No tenés permisos para borrar temporales.")
            return str(response), 200, {"Content-Type": "text/xml"}

        # Extraer número de índice (ej: "borrar temporal #3" o "borrar temporal 3")
        resto = body.split("temporal", 1)[1].strip().lstrip("#")
        if resto.isdigit():
            indice = int(resto)
            if rol == "superadmin":
                resultado = accesos.borrar_temporal(indice)
            else:
                resultado = accesos.borrar_temporal(indice, solicitado_por=sender.replace("whatsapp:", ""))
            response.message(resultado)
            registro.registrar(sender, "temporal_borrado", "whatsapp", detalle=f"índice: {indice}")
        else:
            response.message("Usá: *BORRAR TEMPORAL #número*\nMandá *MIS ACCESOS* para ver la lista con números.")
        return str(response), 200, {"Content-Type": "text/xml"}

    # ----------------------------------------------------------
    # AYUDA (todos)
    # ----------------------------------------------------------
    if body_lower in ["ayuda", "help", "?"]:
        msg = (
            f"*Portón de {config.NOMBRE_BARRIO}*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "*ABRIR Y CERRAR EL PORTÓN:*\n"
            "Mandá *ABRIR* para abrir\n"
            "Mandá *CERRAR* para cerrar\n"
            "También podés llamar a este número\n"
        )

        if rol in ("habitante", "superadmin"):
            msg += (
                "\n━━━━━━━━━━━━━━━━━━━━\n"
                "*DARLE ACCESO A ALGUIEN*\n"
                "(ej: un plomero, delivery, visita)\n\n"
                "Mandá: *TEMPORAL* + número + cuánto tiempo + nombre\n\n"
                "Ejemplos:\n"
                "  TEMPORAL 2211234567 hoy Plomero\n"
                "  TEMPORAL 2211234567 3 dias Pintor\n"
                "  TEMPORAL 2211234567 una semana 8 a 17 Electricista\n\n"
                "⚠️ _Se le manda un mensaje automático al invitado._\n"
                "\n━━━━━━━━━━━━━━━━━━━━\n"
                "*INVITAR A MUCHAS PERSONAS*\n"
                "(ej: un cumpleaños, asado, reunión)\n\n"
                "Mandá: *INVITAR* + cuándo + cuántas personas + motivo\n\n"
                "Ejemplos:\n"
                "  INVITAR sábado 20p Cumpleaños\n"
                "  INVITAR este finde 15p Asado\n"
                "  INVITAR viernes 18 a 23 30p Fiesta\n\n"
                "Te va a dar un código para compartir.\n"
                "Los invitados mandan: *CODIGO xxxx*\n"
                "\n━━━━━━━━━━━━━━━━━━━━\n"
                "*VER Y CANCELAR:*\n"
                "• *MIS ACCESOS* - Ver a quién le diste acceso\n"
                "• *INVITACIONES* - Ver tus invitaciones activas\n"
                "• *CANCELAR* código - Cancelar una invitación\n"
                "• *BORRAR TEMPORAL #n* - Borrar un acceso temporal\n"
            )

        if rol == "superadmin":
            msg += (
                "\n━━━━━━━━━━━━━━━━━━━━\n"
                "*ADMINISTRACIÓN:*\n"
                "• *AGREGAR* número - Nuevo habitante\n"
                "• *ELIMINAR* número - Sacar acceso\n"
                "• *LISTAR* - Ver todos los accesos\n"
                "• *LOG* - Últimos movimientos\n"
                "• *RESUMEN* - Resumen del día\n"
                "• *ESTADO* - Estado del portón\n"
                "• *BLOQUEAR* / *DESBLOQUEAR* - Emergencia\n"
                "• *CAMBIARPIN* xxxx - Cambiar PIN\n"
            )

        response.message(msg)
        return str(response), 200, {"Content-Type": "text/xml"}

    # ==========================================================
    # COMANDOS SOLO SUPERADMIN
    # ==========================================================

    if rol != "superadmin":
        response.message(
            "No entendí el comando.\n"
            "Mandá *ABRIR*, *CERRAR* o *AYUDA* para ver opciones."
        )
        return str(response), 200, {"Content-Type": "text/xml"}

    # --- A partir de acá, solo superadmin ---

    # BLOQUEAR
    if body_lower in ["bloquear", "bloqueo", "lock"]:
        _set_bloqueo(True, sender.replace("whatsapp:", ""))
        response.message(
            "🔴 Portón *BLOQUEADO*.\n"
            "Nadie puede abrir ni cerrar salvo superadmins.\n"
            "Para desbloquear mandá *DESBLOQUEAR*."
        )
        registro.registrar(sender, "bloquear", "whatsapp")
        return str(response), 200, {"Content-Type": "text/xml"}

    # DESBLOQUEAR
    if body_lower in ["desbloquear", "desbloqueo", "unlock"]:
        _set_bloqueo(False)
        response.message("🟢 Portón *DESBLOQUEADO*. Operación normal.")
        registro.registrar(sender, "desbloquear", "whatsapp")
        return str(response), 200, {"Content-Type": "text/xml"}

    # AGREGAR habitante
    if body_lower.startswith("agregar "):
        numero = body.split(" ", 1)[1].strip()
        numero = accesos.auto_prefijo(numero)
        resultado = accesos.agregar_habitante(numero)
        response.message(resultado)
        registro.registrar(sender, "numero_agregado", "whatsapp", detalle=f"habitante: {numero}")
        return str(response), 200, {"Content-Type": "text/xml"}

    # ELIMINAR número (no atrapar "borrar temporal" que ya se maneja arriba)
    if body_lower.startswith(("eliminar ", "sacar ")) or (body_lower.startswith("borrar ") and not body_lower.startswith("borrar temporal")):
        numero = body.split(" ", 1)[1].strip()
        numero = accesos.auto_prefijo(numero)
        resultado = accesos.eliminar_numero(numero)
        response.message(resultado)
        registro.registrar(sender, "numero_eliminado", "whatsapp", detalle=numero)
        return str(response), 200, {"Content-Type": "text/xml"}

    # LISTAR accesos
    if body_lower in ["listar", "lista", "accesos", "números", "numeros"]:
        resultado = accesos.listar_accesos(para_superadmin=True)
        response.message(resultado)
        return str(response), 200, {"Content-Type": "text/xml"}

    # LOG / REGISTRO
    if body_lower.startswith("log") or body_lower.startswith("registro"):
        partes = body.split()
        n = 10
        if len(partes) > 1 and partes[1].isdigit():
            n = min(int(partes[1]), 50)
        resultado = registro.obtener_ultimos(n)
        response.message(resultado)
        return str(response), 200, {"Content-Type": "text/xml"}

    # RESUMEN del día
    if body_lower in ["resumen", "resumen dia", "resumen día"]:
        resultado = registro.resumen_dia()
        response.message(resultado)
        return str(response), 200, {"Content-Type": "text/xml"}

    # ESTADO del portón
    if body_lower in ["estado", "status"]:
        estado = _get_estado()
        bloqueo = _get_bloqueo()

        if bloqueo["activo"]:
            bloqueo_str = f"\n🔴 *BLOQUEADO* por {bloqueo['activado_por']}"
        else:
            bloqueo_str = ""

        if estado["ultimo_cambio"]:
            try:
                dt = datetime.fromisoformat(estado["ultimo_cambio"])
                ts = dt.strftime("%d/%m %H:%M")
            except Exception:
                ts = estado["ultimo_cambio"]
            accion = estado["ultima_accion"] or "?"
            emoji = "🔓" if accion == "abrir" else "🔒"
            msg = (
                f"{emoji} Última acción: *{accion.upper()}*\n"
                f"Cuándo: {ts}\n"
                f"Por: {estado['ultimo_usuario'] or '?'}"
                f"{bloqueo_str}"
            )
        else:
            msg = f"📋 Sin actividad desde que arrancó el bot.{bloqueo_str}"
        response.message(msg)
        return str(response), 200, {"Content-Type": "text/xml"}

    # CAMBIAR PIN
    if body_lower.startswith("cambiarpin ") or body_lower.startswith("nuevopin "):
        nuevo_pin = body.split(" ", 1)[1].strip()
        if len(nuevo_pin) < 4:
            response.message("El PIN tiene que tener al menos 4 caracteres.")
        else:
            datos = accesos._cargar_datos()
            datos["habitante_pin"] = nuevo_pin
            accesos._guardar_datos(datos)
            response.message(f"✅ PIN de habitante cambiado a: {nuevo_pin}")
            registro.registrar(sender, "pin_cambiado", "whatsapp")
        return str(response), 200, {"Content-Type": "text/xml"}

    # Mensaje no reconocido
    response.message(
        "No entendí el comando. Mandá *AYUDA* para ver opciones."
    )
    return str(response), 200, {"Content-Type": "text/xml"}


# ============================================================
# PWA + HEALTH CHECK
# ============================================================
@app.route("/", methods=["GET"])
def serve_pwa():
    """Servir la PWA."""
    return send_from_directory(os.path.join(_BASE_DIR, "static"), "index.html")


@app.route("/health", methods=["GET", "HEAD"])
def health():
    estado = _get_estado()
    bloqueo = _get_bloqueo()
    return {
        "status": "ok",
        "service": "porton-bot",
        "ultima_accion": estado.get("ultima_accion"),
        "bloqueado": bloqueo["activo"],
        "ultimo_cambio": estado["ultimo_cambio"],
    }, 200


# ============================================================
# LISTAR DISPOSITIVOS EWELINK
# ============================================================
@app.route("/devices", methods=["GET"])
def list_devices():
    controller = get_controller()
    devices = controller.get_devices()

    if devices:
        return {"devices": devices}, 200
    else:
        return {"error": "No se pudieron obtener dispositivos."}, 500


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Bot Portón v3.1 iniciando...")
    logger.info(f"Pulso configurado: {config.PULSE_SECONDS} segundos")
    logger.info("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
