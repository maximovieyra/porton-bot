"""
API REST del Bot Portón para la PWA.
Autenticación por JWT. Endpoints para abrir, cerrar, temporales, log, estado.
"""

import logging
import threading
import jwt
import time
from functools import wraps
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

import config
import accesos
import registro

logger = logging.getLogger(__name__)

api = Blueprint("api", __name__, url_prefix="/api")

# ============================================================
# JWT
# ============================================================

JWT_SECRET = config.JWT_SECRET
JWT_EXPIRY = 60 * 60 * 24 * 30  # 30 días


def _generar_token(numero: str, rol: str) -> str:
    """Generar JWT para un usuario."""
    payload = {
        "numero": numero,
        "rol": rol,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRY,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _verificar_token(token: str) -> dict | None:
    """Verificar y decodear JWT. Retorna payload o None."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def requiere_auth(f):
    """Decorator que requiere JWT válido."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Token requerido"}), 401

        token = auth[7:]
        payload = _verificar_token(token)
        if not payload:
            return jsonify({"error": "Token inválido o expirado"}), 401

        # Verificar que el usuario sigue autorizado
        rol_actual = accesos.obtener_rol(payload["numero"])
        if rol_actual == "ninguno":
            return jsonify({"error": "Ya no tenés acceso"}), 403

        request.usuario = payload
        request.usuario["rol"] = rol_actual  # Rol actualizado
        return f(*args, **kwargs)
    return decorated


def requiere_superadmin(f):
    """Decorator que requiere rol superadmin."""
    @wraps(f)
    @requiere_auth
    def decorated(*args, **kwargs):
        if request.usuario["rol"] != "superadmin":
            return jsonify({"error": "Solo superadmins"}), 403
        return f(*args, **kwargs)
    return decorated


def requiere_habitante(f):
    """Decorator que requiere rol habitante o superior."""
    @wraps(f)
    @requiere_auth
    def decorated(*args, **kwargs):
        if request.usuario["rol"] not in ("superadmin", "habitante"):
            return jsonify({"error": "Solo habitantes y superadmins"}), 403
        return f(*args, **kwargs)
    return decorated


# ============================================================
# LOGIN
# ============================================================

@api.route("/login", methods=["POST"])
def login():
    """Login con número + PIN."""
    data = request.get_json() or {}
    numero = data.get("numero", "").strip()
    pin = data.get("pin", "").strip()

    if not numero or not pin:
        return jsonify({"error": "Número y PIN requeridos"}), 400

    numero = accesos.auto_prefijo(numero)

    # Verificar PIN
    if not accesos.verificar_pin(pin):
        return jsonify({"error": "PIN incorrecto"}), 401

    # Verificar o registrar como habitante
    rol = accesos.obtener_rol(numero)
    if rol == "ninguno":
        # PIN correcto + número nuevo = registrar como habitante
        accesos.agregar_habitante(numero)
        rol = "habitante"
        registro.registrar(numero, "pin_ok", "app", detalle="registrado como habitante via app")
    elif rol in ("superadmin", "habitante"):
        registro.registrar(numero, "login", "app")
    # temporales no pueden loguearse con PIN en la app
    # (su acceso es solo por WhatsApp/llamada)

    token = _generar_token(numero, rol)

    return jsonify({
        "token": token,
        "rol": rol,
        "numero": numero,
        "barrio": config.NOMBRE_BARRIO,
    })


# ============================================================
# PORTÓN
# ============================================================

def _activar_porton_api(accion: str, usuario: str):
    """Activar portón en background thread."""
    # Importar aquí para evitar circular import
    from app import activar_porton
    activar_porton(accion, usuario, notificar_error=False)


@api.route("/abrir", methods=["POST"])
@requiere_auth
def abrir():
    """Abrir el portón."""
    from app import _esta_bloqueado

    if _esta_bloqueado() and request.usuario["rol"] != "superadmin":
        return jsonify({"error": "Portón bloqueado por administrador"}), 403

    numero = request.usuario["numero"]
    nombre = accesos.obtener_nombre_temporal(numero)
    registro.registrar(numero, "abrir", "app", nombre=nombre)

    thread = threading.Thread(target=_activar_porton_api, args=("abrir", numero))
    thread.start()

    return jsonify({
        "ok": True,
        "mensaje": "Abriendo portón...",
    })


@api.route("/cerrar", methods=["POST"])
@requiere_auth
def cerrar():
    """Cerrar el portón."""
    from app import _esta_bloqueado

    if _esta_bloqueado() and request.usuario["rol"] != "superadmin":
        return jsonify({"error": "Portón bloqueado por administrador"}), 403

    numero = request.usuario["numero"]
    nombre = accesos.obtener_nombre_temporal(numero)
    registro.registrar(numero, "cerrar", "app", nombre=nombre)

    thread = threading.Thread(target=_activar_porton_api, args=("cerrar", numero))
    thread.start()

    return jsonify({
        "ok": True,
        "mensaje": "Cerrando portón...",
    })


@api.route("/estado", methods=["GET"])
@requiere_auth
def estado():
    """Estado actual del portón."""
    from app import _get_estado, _get_bloqueo

    est = _get_estado()
    bloq = _get_bloqueo()

    return jsonify({
        "ultima_accion": est.get("ultima_accion"),
        "ultimo_cambio": est["ultimo_cambio"],
        "ultimo_usuario": est["ultimo_usuario"],
        "bloqueado": bloq["activo"],
        "bloqueado_por": bloq.get("activado_por"),
    })


# ============================================================
# TEMPORALES
# ============================================================

@api.route("/temporales", methods=["GET"])
@requiere_habitante
def listar_temporales():
    """Listar accesos temporales."""
    datos = accesos._cargar_datos()
    ahora = config.ahora()

    temporales = []
    for t in datos["temporales"]:
        try:
            fecha_hasta = datetime.strptime(t["fecha_hasta"], "%Y-%m-%d")
            vencido = ahora.date() > fecha_hasta.date()
        except Exception:
            vencido = False

        temporales.append({
            "numero": t["numero"],
            "nombre": t.get("nombre", ""),
            "fecha_desde": t["fecha_desde"],
            "fecha_hasta": t["fecha_hasta"],
            "dias": t.get("dias", []),
            "hora_desde": t.get("hora_desde", "00:00"),
            "hora_hasta": t.get("hora_hasta", "23:59"),
            "creado_por": t.get("creado_por", ""),
            "vencido": vencido,
        })

    return jsonify({"temporales": temporales})


@api.route("/temporales", methods=["POST"])
@requiere_habitante
def crear_temporal():
    """Crear acceso temporal."""
    data = request.get_json() or {}
    numero = data.get("numero", "").strip()
    nombre = data.get("nombre", "").strip()
    fecha_desde = data.get("fecha_desde", "")
    fecha_hasta = data.get("fecha_hasta", "")
    dias = data.get("dias", [0, 1, 2, 3, 4, 5, 6])
    hora_desde = data.get("hora_desde", "00:00")
    hora_hasta = data.get("hora_hasta", "23:59")

    if not numero or not fecha_desde or not fecha_hasta:
        return jsonify({"error": "Número, fecha_desde y fecha_hasta requeridos"}), 400

    numero = accesos.auto_prefijo(numero)
    creado_por = request.usuario["numero"]

    resultado = accesos.agregar_temporal(
        numero, fecha_desde, fecha_hasta,
        dias, hora_desde, hora_hasta,
        nombre, creado_por=creado_por,
    )
    registro.registrar(
        creado_por, "temporal_creado", "app",
        detalle=f"{numero} | {nombre} | {fecha_desde} a {fecha_hasta}"
    )

    # Bienvenida al temporal via WhatsApp
    from app import _enviar_whatsapp
    dias_nombres = ["LUN", "MAR", "MIE", "JUE", "VIE", "SAB", "DOM"]
    es_mismo_dia = fecha_desde == fecha_hasta

    info_dias = ""
    if not es_mismo_dia:
        if sorted(dias) == [0, 1, 2, 3, 4, 5, 6]:
            info_dias = "\n📆 Días: Todos"
        elif sorted(dias) == [0, 1, 2, 3, 4]:
            info_dias = "\n📆 Días: Lunes a Viernes"
        elif sorted(dias) == [5, 6]:
            info_dias = "\n📆 Días: Fines de semana"
        else:
            info_dias = f"\n📆 Días: {', '.join([dias_nombres[d] for d in dias])}"

    horario = ""
    if hora_desde != "00:00" or hora_hasta != "23:59":
        horario = f"\n🕐 Horario: {hora_desde} a {hora_hasta}"

    bienvenida = (
        f"👋 Hola! Te dieron acceso al portón de *{config.NOMBRE_BARRIO}*.\n\n"
        f"📅 {'Fecha: ' + fecha_desde if es_mismo_dia else 'Desde ' + fecha_desde + ' hasta ' + fecha_hasta}"
        f"{info_dias}{horario}\n\n"
        f"Para abrir mandá *ABRIR*\n"
        f"Para cerrar mandá *CERRAR*"
    )
    _enviar_whatsapp(numero, bienvenida)

    return jsonify({"ok": True, "mensaje": resultado})


@api.route("/temporales/<numero>", methods=["DELETE"])
@requiere_superadmin
def eliminar_temporal(numero):
    """Eliminar un acceso temporal (solo superadmin)."""
    numero = accesos.auto_prefijo(numero)
    resultado = accesos.eliminar_numero(numero)
    registro.registrar(request.usuario["numero"], "numero_eliminado", "app", detalle=numero)
    return jsonify({"ok": True, "mensaje": resultado})


# ============================================================
# ADMIN (solo superadmin)
# ============================================================

@api.route("/log", methods=["GET"])
@requiere_superadmin
def ver_log():
    """Ver registros de actividad."""
    n = request.args.get("n", 20, type=int)
    n = min(n, 100)

    import json
    import os
    LOG_FILE = os.getenv("LOG_FILE", "registro.json")
    registros = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f:
                registros = json.load(f)
        except Exception:
            pass

    ultimos = registros[-n:] if len(registros) >= n else registros
    ultimos.reverse()

    return jsonify({"registros": ultimos})


@api.route("/accesos", methods=["GET"])
@requiere_superadmin
def ver_accesos():
    """Ver todos los accesos (superadmin)."""
    datos = accesos._cargar_datos()
    return jsonify({
        "superadmins": datos.get("superadmins", []),
        "habitantes": datos.get("habitantes", []),
        "temporales": datos.get("temporales", []),
    })


@api.route("/bloquear", methods=["POST"])
@requiere_superadmin
def bloquear():
    """Bloquear portón."""
    from app import _set_bloqueo
    _set_bloqueo(True, request.usuario["numero"])
    registro.registrar(request.usuario["numero"], "bloquear", "app")
    return jsonify({"ok": True, "mensaje": "Portón bloqueado"})


@api.route("/desbloquear", methods=["POST"])
@requiere_superadmin
def desbloquear():
    """Desbloquear portón."""
    from app import _set_bloqueo
    _set_bloqueo(False)
    registro.registrar(request.usuario["numero"], "desbloquear", "app")
    return jsonify({"ok": True, "mensaje": "Portón desbloqueado"})


@api.route("/resumen", methods=["GET"])
@requiere_superadmin
def resumen_dia():
    """Resumen del día."""
    texto = registro.resumen_dia()
    return jsonify({"resumen": texto})
