"""
Registro de accesos del Bot Portón.
Guarda un log persistente de cada apertura/cierre con timestamp,
quién lo hizo, por qué medio y qué acción.
"""

import json
import os
import logging
from datetime import datetime

import config

logger = logging.getLogger(__name__)

LOG_FILE = os.path.join(config.DATA_DIR, os.getenv("LOG_FILE", "registro.json"))
MAX_REGISTROS = 500  # Máximo de registros a mantener en memoria


def _cargar_log() -> list:
    """Cargar log del archivo JSON."""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error cargando log: {e}")
    return []


def _guardar_log(registros: list):
    """Guardar log al archivo JSON (mantiene los últimos MAX_REGISTROS)."""
    try:
        # Recortar si hay demasiados
        if len(registros) > MAX_REGISTROS:
            registros = registros[-MAX_REGISTROS:]
        with open(LOG_FILE, "w") as f:
            json.dump(registros, f, indent=2, default=str, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error guardando log: {e}")


def registrar(numero: str, accion: str, medio: str, nombre: str = "", detalle: str = ""):
    """
    Registrar una acción en el log.

    Args:
        numero: Número de teléfono
        accion: "abrir", "cerrar", "acceso_denegado", "pin_ok", "pin_fail", etc.
        medio: "whatsapp", "llamada", "sistema"
        nombre: Nombre asociado (si lo tiene)
        detalle: Info extra
    """
    registros = _cargar_log()

    entrada = {
        "timestamp": config.ahora().isoformat(),
        "numero": numero,
        "nombre": nombre,
        "accion": accion,
        "medio": medio,
        "detalle": detalle,
    }

    registros.append(entrada)
    _guardar_log(registros)
    logger.info(f"LOG: {accion} | {numero} | {medio} | {detalle}")


def obtener_ultimos(n: int = 10) -> str:
    """Obtener los últimos N registros como texto formateado."""
    registros = _cargar_log()
    ultimos = registros[-n:] if len(registros) >= n else registros
    ultimos.reverse()  # Más reciente primero

    if not ultimos:
        return "No hay registros todavía."

    resultado = f"*ÚLTIMOS {len(ultimos)} REGISTROS:*\n\n"
    for r in ultimos:
        ts = r.get("timestamp", "?")
        try:
            dt = datetime.fromisoformat(ts)
            ts_fmt = dt.strftime("%d/%m %H:%M")
        except Exception:
            ts_fmt = ts

        emoji = _emoji_accion(r.get("accion", ""))
        nombre = r.get("nombre", "")
        nombre_str = f" ({nombre})" if nombre else ""
        numero = r.get("numero", "?")
        medio = r.get("medio", "?")
        accion = r.get("accion", "?")
        detalle = r.get("detalle", "")
        detalle_str = f" - {detalle}" if detalle else ""

        resultado += f"{emoji} {ts_fmt} | {accion.upper()} | {numero}{nombre_str} | {medio}{detalle_str}\n"

    return resultado


def resumen_dia() -> str:
    """Resumen de accesos del día actual."""
    registros = _cargar_log()
    hoy = config.ahora().date()

    del_dia = []
    for r in registros:
        try:
            dt = datetime.fromisoformat(r.get("timestamp", ""))
            if dt.date() == hoy:
                del_dia.append(r)
        except Exception:
            continue

    if not del_dia:
        return "No hubo actividad hoy."

    aperturas = sum(1 for r in del_dia if r.get("accion") == "abrir")
    cierres = sum(1 for r in del_dia if r.get("accion") == "cerrar")
    denegados = sum(1 for r in del_dia if r.get("accion") == "acceso_denegado")

    resultado = (
        f"*RESUMEN DE HOY ({hoy.strftime('%d/%m/%Y')}):*\n"
        f"Aperturas: {aperturas}\n"
        f"Cierres: {cierres}\n"
        f"Denegados: {denegados}\n"
        f"Total eventos: {len(del_dia)}"
    )
    return resultado


def _emoji_accion(accion: str) -> str:
    """Emoji según la acción."""
    emojis = {
        "abrir": "🔓",
        "cerrar": "🔒",
        "acceso_denegado": "🚫",
        "pin_ok": "🔑",
        "pin_fail": "❌",
        "temporal_creado": "⏰",
        "numero_agregado": "➕",
        "numero_eliminado": "➖",
    }
    return emojis.get(accion, "📋")
