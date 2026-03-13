"""
Gestor de accesos del Bot Portón.
Maneja números autorizados, accesos temporales y roles por PIN.
Guarda todo en un archivo JSON para persistencia.

v3: Sistema de roles (superadmin / habitante / temporal)
  - superadmin: todo el poder (desde .env, no se puede agregar por WhatsApp)
  - habitante: abrir, cerrar, dar temporales (se registra con PIN)
  - temporal: solo abrir/cerrar en su ventana de tiempo
"""

import json
import os
import re
import logging
from datetime import datetime, time, timedelta

import config

logger = logging.getLogger(__name__)

DATA_FILE = os.path.join(config.DATA_DIR, os.getenv("DATA_FILE", "accesos.json"))


# ============================================================
# ESTRUCTURA DE DATOS
# ============================================================
# {
#   "habitante_pin": "1234",
#   "superadmins": ["+549..."],     ← vienen del .env, no se tocan
#   "habitantes": ["+549...", ...],  ← se registran con PIN
#   "temporales": [{...}, ...],      ← accesos con ventana de tiempo
#   "invitaciones": [{...}, ...],    ← códigos grupales para eventos
# }


def _cargar_datos() -> dict:
    """Cargar datos del archivo JSON."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                datos = json.load(f)
                # Migración v2 → v3
                if "admins" in datos or "permanentes" in datos:
                    datos = _migrar_v2_a_v3(datos)
                # Asegurar que exista invitaciones
                if "invitaciones" not in datos:
                    datos["invitaciones"] = []
                return datos
        except Exception as e:
            logger.error(f"Error cargando datos: {e}")
    return {
        "habitante_pin": os.getenv("HABITANTE_PIN", os.getenv("ADMIN_PIN", "1234")),
        "superadmins": [],
        "habitantes": [],
        "temporales": [],
        "invitaciones": [],
    }


def _migrar_v2_a_v3(datos: dict) -> dict:
    """Migrar estructura v2 (admins/permanentes) a v3 (superadmins/habitantes)."""
    logger.info("Migrando datos v2 → v3...")
    nuevos = {
        "habitante_pin": datos.get("admin_pin", "1234"),
        "superadmins": datos.get("admins", []),
        "habitantes": [],
        "temporales": datos.get("temporales", []),
    }
    # Los permanentes que no eran admins pasan a habitantes
    for n in datos.get("permanentes", []):
        if n not in nuevos["superadmins"] and n not in nuevos["habitantes"]:
            nuevos["habitantes"].append(n)
    _guardar_datos(nuevos)
    logger.info(f"Migración completa: {len(nuevos['superadmins'])} superadmins, {len(nuevos['habitantes'])} habitantes")
    return nuevos


def _guardar_datos(datos: dict):
    """Guardar datos al archivo JSON."""
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(datos, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Error guardando datos: {e}")


def inicializar(superadmin_nums: list, habitante_pin: str):
    """Inicializar datos con los superadmins del .env."""
    datos = _cargar_datos()

    if habitante_pin:
        datos["habitante_pin"] = habitante_pin

    for num in superadmin_nums:
        if num and num not in datos["superadmins"]:
            datos["superadmins"].append(num)

    _guardar_datos(datos)
    return datos


# ============================================================
# NORMALIZACIÓN Y COMPARACIÓN
# ============================================================

def _normalizar_numero(numero: str) -> str:
    """Normalizar formato de número."""
    return numero.replace(" ", "").replace("-", "").replace("whatsapp:", "")


def auto_prefijo(numero: str) -> str:
    """
    Agregar prefijo de país automáticamente.
    - Si ya tiene +549, dejarlo
    - Si tiene +54 pero no +549, dejarlo (fijo)
    - Si tiene otro +XX, dejarlo (extranjero)
    - Si no tiene +, agregar PREFIJO_PAIS del config
    """
    numero = numero.strip().replace(" ", "").replace("-", "")

    if numero.startswith("+"):
        # Ya tiene prefijo internacional, no tocar
        return numero

    # Sacar 0 inicial si lo tiene (ej: 02214475215 → 2214475215)
    if numero.startswith("0"):
        numero = numero[1:]

    # Sacar 15 inicial si lo tiene (ej: 152214475215 → no, pero 1544556677 → no)
    # En arg el 15 va después del código de área, no al inicio

    return f"{config.PREFIJO_PAIS}{numero}"


def _numeros_coinciden(a: str, b: str) -> bool:
    """Verificar si dos números son el mismo (tolerante a formato)."""
    a = _normalizar_numero(a)
    b = _normalizar_numero(b)
    return a in b or b in a


# ============================================================
# CONSULTAS DE ROL
# ============================================================

def obtener_rol(numero: str) -> str:
    """
    Obtener el rol de un número.
    Retorna: "superadmin", "habitante", "temporal", o "ninguno"
    """
    datos = _cargar_datos()
    numero = _normalizar_numero(numero)

    for n in datos["superadmins"]:
        if _numeros_coinciden(n, numero):
            return "superadmin"

    for n in datos["habitantes"]:
        if _numeros_coinciden(n, numero):
            return "habitante"

    # Verificar temporales vigentes
    ahora = config.ahora()
    ahora_date = ahora.date()
    ahora_time = ahora.time()
    for acceso in datos["temporales"]:
        if not _numeros_coinciden(acceso["numero"], numero):
            continue

        try:
            fecha_desde = datetime.strptime(acceso["fecha_desde"], "%Y-%m-%d").date()
            fecha_hasta = datetime.strptime(acceso["fecha_hasta"], "%Y-%m-%d").date()
            if not (fecha_desde <= ahora_date <= fecha_hasta):
                continue

            dias_permitidos = acceso.get("dias", [0, 1, 2, 3, 4, 5, 6])
            if ahora.weekday() not in dias_permitidos:
                continue

            hora_desde_str = acceso.get("hora_desde", "00:00")
            hora_hasta_str = acceso.get("hora_hasta", "23:59")
            hora_desde_t = time.fromisoformat(hora_desde_str)
            hora_hasta_t = time.fromisoformat(hora_hasta_str)
            # "23:59" → extender a 23:59:59 para cubrir el minuto completo
            if hora_hasta_str == "23:59":
                hora_hasta_t = time(23, 59, 59)
            if hora_desde_t <= hora_hasta_t:
                # Rango normal (ej: 08:00 a 17:00)
                if not (hora_desde_t <= ahora_time <= hora_hasta_t):
                    continue
            else:
                # Rango nocturno (ej: 22:00 a 06:00)
                if not (ahora_time >= hora_desde_t or ahora_time <= hora_hasta_t):
                    continue

            return "temporal"
        except Exception:
            continue

    return "ninguno"


def esta_autorizado(numero: str) -> bool:
    """Verificar si un número está autorizado (cualquier rol)."""
    rol = obtener_rol(numero)
    if rol != "ninguno":
        return True

    _limpiar_expirados()
    return False


def es_superadmin(numero: str) -> bool:
    """Verificar si un número es superadmin."""
    return obtener_rol(numero) == "superadmin"


def es_habitante(numero: str) -> bool:
    """Verificar si un número es habitante (o superior)."""
    return obtener_rol(numero) in ("superadmin", "habitante")


def obtener_nombre_temporal(numero: str) -> str:
    """Obtener el nombre asociado a un acceso temporal."""
    datos = _cargar_datos()
    numero = _normalizar_numero(numero)
    for acceso in datos["temporales"]:
        if _numeros_coinciden(acceso["numero"], numero):
            return acceso.get("nombre", "")
    return ""


# ============================================================
# ACCIONES
# ============================================================

def verificar_pin(pin: str) -> bool:
    """Verificar si el PIN de habitante es correcto."""
    datos = _cargar_datos()
    return pin == datos["habitante_pin"]


def agregar_habitante(numero: str) -> str:
    """Agregar un número como habitante (via PIN)."""
    datos = _cargar_datos()
    numero = _normalizar_numero(numero)

    for n in datos["superadmins"]:
        if _numeros_coinciden(n, numero):
            return f"El número {numero} ya tiene permisos completos."

    for n in datos["habitantes"]:
        if _numeros_coinciden(n, numero):
            return f"El número {numero} ya está registrado como habitante."

    datos["habitantes"].append(numero)
    _guardar_datos(datos)
    return f"Número {numero} registrado como habitante."


def agregar_temporal(numero: str, fecha_desde: str, fecha_hasta: str,
                     dias: list = None, hora_desde: str = "00:00",
                     hora_hasta: str = "23:59", nombre: str = "",
                     creado_por: str = "") -> str:
    """Agregar un acceso temporal."""
    datos = _cargar_datos()
    numero = _normalizar_numero(numero)

    try:
        datetime.strptime(fecha_desde, "%Y-%m-%d")
        datetime.strptime(fecha_hasta, "%Y-%m-%d")
    except ValueError:
        return "Formato de fecha incorrecto. Usá AAAA-MM-DD."

    if dias is None:
        dias = [0, 1, 2, 3, 4, 5, 6]

    acceso = {
        "numero": numero,
        "nombre": nombre,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "dias": dias,
        "hora_desde": hora_desde,
        "hora_hasta": hora_hasta,
        "creado": config.ahora().isoformat(),
        "creado_por": creado_por,
    }

    datos["temporales"].append(acceso)
    _guardar_datos(datos)

    dias_nombres = ["LUN", "MAR", "MIE", "JUE", "VIE", "SAB", "DOM"]
    dias_str = ", ".join([dias_nombres[d] for d in dias])

    return (
        f"✅ Acceso temporal agregado:\n"
        f"Número: {numero}\n"
        f"Nombre: {nombre or 'Sin nombre'}\n"
        f"Desde: {fecha_desde} hasta {fecha_hasta}\n"
        f"Días: {dias_str}\n"
        f"Horario: {hora_desde} a {hora_hasta}"
    )


def eliminar_numero(numero: str) -> str:
    """Eliminar un número de habitantes y temporales (no toca superadmins)."""
    datos = _cargar_datos()
    numero = _normalizar_numero(numero)

    for n in datos["superadmins"]:
        if _numeros_coinciden(n, numero):
            return "⚠️ No se puede eliminar a un superadmin."

    eliminado = False
    cant_temp_antes = len(datos["temporales"])

    nuevos_hab = [n for n in datos["habitantes"] if not _numeros_coinciden(n, numero)]
    if len(nuevos_hab) != len(datos["habitantes"]):
        datos["habitantes"] = nuevos_hab
        eliminado = True

    datos["temporales"] = [
        t for t in datos["temporales"]
        if not _numeros_coinciden(t["numero"], numero)
    ]

    if eliminado or len(datos["temporales"]) != cant_temp_antes:
        _guardar_datos(datos)
        return f"Número {numero} eliminado."
    else:
        return f"Número {numero} no encontrado."


def listar_accesos(para_superadmin: bool = True) -> str:
    """Listar accesos. Superadmins ven todo, habitantes ven versión reducida."""
    datos = _cargar_datos()
    dias_nombres = ["LUN", "MAR", "MIE", "JUE", "VIE", "SAB", "DOM"]
    resultado = ""

    if para_superadmin:
        resultado += "*👑 SUPERADMINS:*\n"
        for n in datos["superadmins"]:
            resultado += f"  {n}\n"
        resultado += "\n"

    resultado += "*🏠 HABITANTES:*\n"
    if datos["habitantes"]:
        for n in datos["habitantes"]:
            resultado += f"  {n}\n"
    else:
        resultado += "  (ninguno)\n"

    resultado += "\n*⏰ TEMPORALES:*\n"
    if datos["temporales"]:
        ahora = config.ahora()
        for t in datos["temporales"]:
            try:
                fecha_hasta = datetime.strptime(t["fecha_hasta"], "%Y-%m-%d").date()
                vencido = ahora.date() > fecha_hasta
            except Exception:
                vencido = False

            estado = " ❌VENCIDO" if vencido else ""
            dias_str = ", ".join([dias_nombres[d] for d in t.get("dias", [])])
            creado_por = t.get("creado_por", "")
            creado_str = f" (por {creado_por})" if creado_por and para_superadmin else ""
            resultado += (
                f"  {t.get('nombre', 'Sin nombre')} - {t['numero']}{estado}{creado_str}\n"
                f"    {t['fecha_desde']} a {t['fecha_hasta']}\n"
                f"    {dias_str} {t.get('hora_desde', '00:00')}-{t.get('hora_hasta', '23:59')}\n"
            )
    else:
        resultado += "  (ninguno)\n"

    return resultado


def _limpiar_expirados():
    """Limpiar accesos temporales expirados."""
    datos = _cargar_datos()
    ahora = config.ahora()
    antes = len(datos["temporales"])

    nuevos = []
    for t in datos["temporales"]:
        try:
            fecha_hasta = datetime.strptime(t["fecha_hasta"], "%Y-%m-%d").date()
            if ahora.date() <= fecha_hasta:
                nuevos.append(t)
        except Exception:
            nuevos.append(t)  # Si no se puede parsear, mantener

    if len(nuevos) != antes:
        datos["temporales"] = nuevos
        _guardar_datos(datos)
        logger.info(f"Limpiados {antes - len(nuevos)} accesos expirados")


# ============================================================
# PARSER DE DÍAS
# ============================================================

def parsear_dias(dias_str: str) -> list:
    """Convertir string de días a lista de números. Tolerante a errores."""
    mapa = {
        "LUN": 0, "LUNES": 0,
        "MAR": 1, "MARTES": 1,
        "MIE": 2, "MIERCOLES": 2, "MIÉRCOLES": 2,
        "JUE": 3, "JUEVES": 3,
        "VIE": 4, "VIERNES": 4,
        "SAB": 5, "SABADO": 5, "SÁBADO": 5, "SABADOS": 5, "SÁBADOS": 5,
        "DOM": 6, "DOMINGO": 6, "DOMINGOS": 6,
        "HABILES": [0, 1, 2, 3, 4], "HÁBILES": [0, 1, 2, 3, 4],
        "LABORALES": [0, 1, 2, 3, 4], "SEMANA": [0, 1, 2, 3, 4],
        "FINDE": [5, 6], "FINESEMANA": [5, 6], "FINDESEMANA": [5, 6],
        "TODOS": [0, 1, 2, 3, 4, 5, 6],
    }

    dias_str = dias_str.upper().strip()

    if dias_str in mapa:
        resultado = mapa[dias_str]
        return resultado if isinstance(resultado, list) else [resultado]

    if "-" in dias_str and "," not in dias_str:
        partes = dias_str.split("-")
        if len(partes) == 2:
            p0 = partes[0].strip()
            p1 = partes[1].strip()
            if p0 in mapa and p1 in mapa:
                inicio = mapa[p0]
                fin = mapa[p1]
                if isinstance(inicio, int) and isinstance(fin, int):
                    return list(range(inicio, fin + 1))

    dias = []
    for d in re.split(r'[,\s]+', dias_str):
        d = d.strip()
        if d in mapa:
            val = mapa[d]
            if isinstance(val, list):
                dias.extend(val)
            else:
                dias.append(val)

    return dias if dias else [0, 1, 2, 3, 4, 5, 6]


# ============================================================
# PARSER DE LENGUAJE NATURAL PARA TEMPORALES
# ============================================================

_NUMEROS_TEXTO = {
    "un": 1, "una": 1, "uno": 1,
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "quince": 15, "veinte": 20, "treinta": 30,
}


def _extraer_numero(texto: str) -> int:
    texto = texto.strip().lower()
    if texto.isdigit():
        return int(texto)
    return _NUMEROS_TEXTO.get(texto, 0)


def parsear_temporal_natural(texto: str) -> dict | None:
    """Parsear un comando de acceso temporal en lenguaje natural."""
    texto = texto.strip()

    if texto.upper().startswith("TEMPORAL"):
        texto = texto[8:].strip()

    match_num = re.match(r'(\+?\d[\d-]{7,})', texto)
    if not match_num:
        return None

    numero = match_num.group(1).replace(" ", "").replace("-", "")
    numero = auto_prefijo(numero)

    resto = texto[match_num.end():].strip()

    match_fechas = re.match(r'(\d{4}-\d{2}-\d{2})\s+(\d{4}-\d{2}-\d{2})(.*)', resto)
    if match_fechas:
        return _parsear_clasico(numero, match_fechas)

    return _parsear_natural(numero, resto)


def _parsear_clasico(numero: str, match) -> dict:
    fecha_desde = match.group(1)
    fecha_hasta = match.group(2)
    resto = match.group(3).strip()

    partes = resto.split() if resto else []
    dias = [0, 1, 2, 3, 4, 5, 6]
    hora_desde = "00:00"
    hora_hasta = "23:59"
    nombre_partes = []
    i = 0

    while i < len(partes):
        p = partes[i].upper()
        if _es_token_dias(p):
            dias = parsear_dias(p)
            i += 1
            continue
        if re.match(r'^\d{1,2}(:\d{2})?$', partes[i]):
            hora_desde = _normalizar_hora(partes[i])
            j = i + 1
            if j < len(partes) and partes[j].lower() in ["a", "-", "hasta"]:
                j += 1
            if j < len(partes) and re.match(r'^\d{1,2}(:\d{2})?$', partes[j]):
                hora_hasta = _normalizar_hora(partes[j])
                i = j + 1
            else:
                i += 1
            continue
        nombre_partes.append(partes[i])
        i += 1

    return {
        "numero": numero, "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta,
        "dias": dias, "hora_desde": hora_desde, "hora_hasta": hora_hasta,
        "nombre": " ".join(nombre_partes),
    }


def _parsear_natural(numero: str, texto: str) -> dict:
    hoy = config.ahora().date()
    ahora_dt = config.ahora()
    texto_lower = texto.lower()

    fecha_desde = hoy
    fecha_hasta = hoy
    dias = [0, 1, 2, 3, 4, 5, 6]
    hora_desde = "00:00"
    hora_hasta = "23:59"
    periodo_tiene_dia = False
    periodo_encontrado = False

    # --- Extraer horario primero (para evitar conflictos con período) ---
    horario_match = re.search(
        r'(?:de\s+)?(\d{1,2})(?::(\d{2}))?(?:\s*(?:hs?|horas?))?\s*(?:a|-|hasta)\s*(\d{1,2})(?::(\d{2}))?(?:\s*(?:hs?|horas?))?',
        texto_lower
    )
    horario_usado = False
    if horario_match:
        h1 = int(horario_match.group(1))
        h2 = int(horario_match.group(3))
        # Verificar que no sea un rango de período (ej: "3 a 5 dias")
        after_match = texto_lower[horario_match.end():].lstrip()
        es_rango_periodo = bool(re.match(r'(?:semanas?|d[ií]as?|mes(?:es)?|horas?)', after_match))
        if not es_rango_periodo and 0 <= h1 <= 23 and 0 <= h2 <= 23 and h1 != h2:
            hora_desde = f"{h1:02d}:{horario_match.group(2) or '00'}"
            hora_hasta = f"{h2:02d}:{horario_match.group(4) or '00'}"
            horario_usado = True

    # --- Extraer período ---
    if re.search(r'\bhoy\b', texto_lower):
        fecha_desde = hoy
        fecha_hasta = hoy
        periodo_encontrado = True
    elif re.search(r'\bma[ñn]ana\b', texto_lower):
        fecha_desde = hoy + timedelta(days=1)
        fecha_hasta = hoy + timedelta(days=1)
        periodo_encontrado = True
    elif re.search(r'\besta\s+semana\b', texto_lower):
        fecha_hasta = hoy + timedelta(days=6 - hoy.weekday())
        periodo_encontrado = True
    elif re.search(r'\beste\s+mes\b', texto_lower):
        import calendar
        fecha_hasta = hoy.replace(day=calendar.monthrange(hoy.year, hoy.month)[1])
        periodo_encontrado = True
    elif m := re.search(r'\bhasta\s+(?:el\s+)?(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b', texto_lower):
        dia_target = _nombre_a_weekday(m.group(1))
        dias_hasta = (dia_target - hoy.weekday()) % 7
        if dias_hasta == 0:
            dias_hasta = 7
        fecha_hasta = hoy + timedelta(days=dias_hasta)
        periodo_tiene_dia = True
        periodo_encontrado = True
    elif m := re.search(
        r'(?:de\s+ac[aá]\s+a\s+|pr[oó]xim[ao]s?\s+)?'
        r'(\d+|un[ao]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|quince|veinte|treinta)\s+'
        r'(semanas?|d[ií]as?|mes(?:es)?|horas?)', texto_lower
    ):
        cantidad = _extraer_numero(m.group(1))
        unidad = m.group(2).lower()
        if "semana" in unidad:
            fecha_hasta = hoy + timedelta(weeks=cantidad)
        elif "dia" in unidad or "día" in unidad:
            fecha_hasta = hoy + timedelta(days=cantidad)
        elif "mes" in unidad:
            fecha_hasta = hoy + timedelta(days=30 * cantidad)
        elif "hora" in unidad:
            # Duración en horas: calcular fecha_hasta y ventana horaria
            fin = ahora_dt + timedelta(hours=cantidad)
            fecha_hasta = fin.date()
            if not horario_usado:
                hora_desde = ahora_dt.strftime("%H:%M")
                hora_hasta = fin.strftime("%H:%M")
        periodo_encontrado = True

    # Si no se encontró período:
    if not periodo_encontrado:
        if horario_usado:
            # Si especificó horario pero no período → default "hoy"
            fecha_hasta = hoy
        else:
            # Sin nada → default 1 semana
            fecha_hasta = hoy + timedelta(weeks=1)

    # Días: solo matchear keywords de grupo y listas con comas.
    # NO matchear días sueltos (ej: "mar" podría ser nombre "Martín")
    if not periodo_tiene_dia:
        if re.search(r'\bh[aá]biles?\b|\blaborales?\b', texto_lower):
            dias = [0, 1, 2, 3, 4]
        elif re.search(r'\bfinde\b|\bfin\s*de\s*semana\b', texto_lower):
            dias = [5, 6]
        elif re.search(r'\btodos(?:\s+los\s+d[ií]as)?\b', texto_lower):
            dias = [0, 1, 2, 3, 4, 5, 6]
        # Solo matchear días si vienen como lista con comas: "lun,mie,vie"
        elif m := re.search(
            r'\b((?:lun(?:es)?|mar(?:tes)?|mi[eé](?:rcoles)?|jue(?:ves)?|vie(?:rnes)?|s[aá]b(?:ados?)?|dom(?:ingos?)?)'
            r'(?:\s*,\s*(?:lun(?:es)?|mar(?:tes)?|mi[eé](?:rcoles)?|jue(?:ves)?|vie(?:rnes)?|s[aá]b(?:ados?)?|dom(?:ingos?)?))+)\b',
            texto_lower
        ):
            partes = re.split(r'\s*,\s*', m.group(1))
            dias = sorted(set(_nombre_a_weekday(d.strip()) for d in partes))

    # Nombre: quitar solo lo que realmente parseamos (período, grupos de días, horarios)
    # NO quitar nombres de días sueltos que podrían ser nombres de personas
    nombre_texto = texto
    for patron in [
        # Rangos de período (ej: "3 a 5 dias", "2 a 4 semanas")
        r'(?:\d+|un[ao]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s*(?:a|-|hasta)\s*(?:\d+|un[ao]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+(?:semanas?|d[ií]as?|mes(?:es)?|horas?)',
        # Períodos simples (incluyendo horas)
        r'(?:de\s+ac[aá]\s+a\s+|pr[oó]xim[ao]s?\s+)?(?:\d+|un[ao]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|quince|veinte|treinta)\s+(?:semanas?|d[ií]as?|mes(?:es)?|horas?)',
        r'\bhoy\b', r'\bma[ñn]ana\b', r'\besta\s+semana\b', r'\beste\s+mes\b',
        r'\bhasta\s+(?:el\s+)?(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b',
        # Solo keywords de grupo de días (no días sueltos)
        r'\bh[aá]biles?\b', r'\blaborales?\b', r'\bfinde\b', r'\bfin\s*de\s*semana\b',
        r'\btodos(?:\s+los\s+d[ií]as)?\b',
        # Listas con comas de días
        r'\b(?:lun(?:es)?|mar(?:tes)?|mi[eé](?:rcoles)?|jue(?:ves)?|vie(?:rnes)?|s[aá]b(?:ados?)?|dom(?:ingos?)?)(?:\s*,\s*(?:lun(?:es)?|mar(?:tes)?|mi[eé](?:rcoles)?|jue(?:ves)?|vie(?:rnes)?|s[aá]b(?:ados?)?|dom(?:ingos?)?))+\b',
        # Horarios
        r'(?:de\s+)?(\d{1,2})(?::\d{2})?(?:\s*(?:hs?|horas?))?\s*(?:a|-|hasta)\s*(\d{1,2})(?::\d{2})?(?:\s*(?:hs?|horas?))?',
        # Conectores sueltos
        r'\bde\s+ac[aá]\b', r'\bpr[oó]xim[ao]s?\b',
    ]:
        nombre_texto = re.sub(patron, '', nombre_texto, flags=re.IGNORECASE)
    nombre = re.sub(r'^[\s,.-]+|[\s,.-]+$', '', re.sub(r'\s+', ' ', nombre_texto).strip())

    return {
        "numero": numero,
        "fecha_desde": fecha_desde.strftime("%Y-%m-%d") if hasattr(fecha_desde, 'strftime') else str(fecha_desde),
        "fecha_hasta": fecha_hasta.strftime("%Y-%m-%d") if hasattr(fecha_hasta, 'strftime') else str(fecha_hasta),
        "dias": dias, "hora_desde": hora_desde, "hora_hasta": hora_hasta, "nombre": nombre,
    }


def _nombre_a_weekday(nombre: str) -> int:
    nombre = nombre.lower().strip()
    mapa = {
        "lun": 0, "lunes": 0, "mar": 1, "martes": 1,
        "mie": 2, "mié": 2, "miercoles": 2, "miércoles": 2,
        "jue": 3, "jueves": 3, "vie": 4, "viernes": 4,
        "sab": 5, "sáb": 5, "sabado": 5, "sábado": 5, "sabados": 5, "sábados": 5,
        "dom": 6, "domingo": 6, "domingos": 6,
    }
    return mapa.get(nombre, 0)


def _es_token_dias(token: str) -> bool:
    tokens_dias = {
        "LUN", "MAR", "MIE", "MIÉ", "JUE", "VIE", "SAB", "SÁB", "DOM",
        "LUNES", "MARTES", "MIERCOLES", "MIÉRCOLES", "JUEVES", "VIERNES",
        "SABADO", "SÁBADO", "DOMINGO",
        "HABILES", "HÁBILES", "LABORALES", "FINDE", "FINDESEMANA", "TODOS",
    }
    if re.match(r'^[A-ZÁÉÍÓÚ]{3}-[A-ZÁÉÍÓÚ]{3}$', token):
        return True
    if "," in token:
        return all(p.strip() in tokens_dias for p in token.split(","))
    return token in tokens_dias


def _normalizar_hora(hora: str) -> str:
    hora = hora.strip()
    if ":" in hora:
        partes = hora.split(":")
        return f"{int(partes[0]):02d}:{partes[1]}"
    return f"{int(hora):02d}:00"


# ============================================================
# INVITACIONES GRUPALES
# ============================================================

import random
import string


def _generar_codigo(largo: int = 6) -> str:
    """Generar código alfanumérico fácil de tipear (sin 0/O, 1/I/L)."""
    chars = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
    return "".join(random.choices(chars, k=largo))


def crear_invitacion(
    fecha_desde: str = None,
    fecha_hasta: str = None,
    horas: int = 0,
    max_usos: int = 10,
    motivo: str = "",
    creado_por: str = "",
    dias: list = None,
    hora_desde: str = "00:00",
    hora_hasta: str = "23:59",
) -> dict:
    """
    Crear una invitación grupal.
    Acepta fecha_desde/fecha_hasta explícitas O horas (backward compat).
    Retorna dict con el código generado y los detalles.
    """
    datos = _cargar_datos()

    codigo = _generar_codigo()
    codigos_existentes = {inv["codigo"] for inv in datos["invitaciones"]}
    while codigo in codigos_existentes:
        codigo = _generar_codigo()

    ahora = config.ahora()

    # Si no se pasaron fechas, calcular desde horas (backward compat)
    if not fecha_desde:
        fecha_desde = ahora.strftime("%Y-%m-%d")
    if not fecha_hasta:
        if horas > 0:
            fecha_hasta = (ahora + timedelta(hours=horas)).strftime("%Y-%m-%d")
        else:
            fecha_hasta = fecha_desde

    # Calcular expiración
    if horas > 0:
        expira = (ahora + timedelta(hours=horas)).isoformat()
    else:
        # Expira al final del último día (23:59:59)
        from zoneinfo import ZoneInfo
        fecha_hasta_dt = datetime.strptime(fecha_hasta, "%Y-%m-%d")
        expira_dt = fecha_hasta_dt.replace(
            hour=23, minute=59, second=59,
            tzinfo=ZoneInfo(config.TIMEZONE)
        )
        # Si la expiración es en el pasado (fecha_hasta es hoy pero ya pasó hora_hasta),
        # ajustar al final del día igualmente
        if expira_dt < ahora:
            expira_dt = ahora.replace(hour=23, minute=59, second=59)
        expira = expira_dt.isoformat()

    if dias is None:
        dias = [0, 1, 2, 3, 4, 5, 6]

    invitacion = {
        "codigo": codigo,
        "motivo": motivo,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "dias": dias,
        "hora_desde": hora_desde,
        "hora_hasta": hora_hasta,
        "max_usos": max_usos,
        "usos": 0,
        "numeros_usados": [],
        "creado_por": creado_por,
        "creado": ahora.isoformat(),
        "expira": expira,
    }

    datos["invitaciones"].append(invitacion)
    _guardar_datos(datos)

    return invitacion


def usar_invitacion(codigo: str, numero: str) -> tuple[bool, str]:
    """
    Usar un código de invitación para obtener acceso temporal.
    Retorna (éxito, mensaje).
    """
    datos = _cargar_datos()
    numero = _normalizar_numero(numero)
    codigo = codigo.upper().strip()
    ahora = config.ahora()

    # Buscar la invitación
    invitacion = None
    for inv in datos["invitaciones"]:
        if inv["codigo"] == codigo:
            invitacion = inv
            break

    if not invitacion:
        return False, "❌ Código no válido."

    # Verificar si expiró
    try:
        expira = datetime.fromisoformat(invitacion["expira"])
        # Hacer aware si es naive
        if expira.tzinfo is None:
            from zoneinfo import ZoneInfo
            expira = expira.replace(tzinfo=ZoneInfo(config.TIMEZONE))
        if ahora > expira:
            return False, "❌ Este código ya expiró."
    except Exception:
        pass

    # Verificar usos
    if invitacion["usos"] >= invitacion["max_usos"]:
        return False, "❌ Este código ya alcanzó el máximo de personas."

    # Verificar si ya lo usó
    for n in invitacion["numeros_usados"]:
        if _numeros_coinciden(n, numero):
            return False, "Ya tenés acceso con este código."

    # Verificar si ya está autorizado por otra vía
    rol = obtener_rol(numero)
    if rol in ("superadmin", "habitante"):
        return False, "Ya tenés acceso permanente, no necesitás código."

    # Crear acceso temporal
    resultado = agregar_temporal(
        numero,
        invitacion["fecha_desde"],
        invitacion["fecha_hasta"],
        invitacion["dias"],
        invitacion["hora_desde"],
        invitacion["hora_hasta"],
        nombre=invitacion.get("motivo", "Invitación"),
        creado_por=invitacion.get("creado_por", ""),
    )

    # Recargar datos (agregar_temporal guardó sus cambios)
    datos = _cargar_datos()

    # Buscar la invitación de nuevo
    for inv in datos["invitaciones"]:
        if inv["codigo"] == codigo:
            inv["usos"] += 1
            inv["numeros_usados"].append(numero)
            break

    _guardar_datos(datos)

    return True, resultado


def listar_invitaciones(creado_por: str = None) -> str:
    """
    Listar invitaciones activas.
    Si creado_por es None → muestra todas (admin).
    Si creado_por tiene valor → muestra solo las de ese número (habitante).
    """
    datos = _cargar_datos()
    ahora = config.ahora()

    es_admin = creado_por is None
    resultado = "*🎟️ INVITACIONES" + (" (todas):*\n\n" if es_admin else ":*\n\n")

    activas = 0
    for inv in datos["invitaciones"]:
        try:
            expira = datetime.fromisoformat(inv["expira"])
            if expira.tzinfo is None:
                from zoneinfo import ZoneInfo
                expira = expira.replace(tzinfo=ZoneInfo(config.TIMEZONE))
            expirado = ahora > expira
        except Exception:
            expirado = False

        if expirado:
            continue

        # Filtrar por creador si no es admin
        if creado_por and not _numeros_coinciden(inv.get("creado_por", ""), creado_por):
            continue

        activas += 1
        restantes = inv["max_usos"] - inv["usos"]
        creador_str = f"\n  Creada por: {inv.get('creado_por', '?')}" if es_admin else ""
        resultado += (
            f"  Código: *{inv['codigo']}*\n"
            f"  Motivo: {inv.get('motivo', '—')}\n"
            f"  Usos: {inv['usos']}/{inv['max_usos']} ({restantes} restantes)\n"
            f"  Expira: {inv['expira'][:16].replace('T', ' ')}"
            f"{creador_str}\n\n"
        )

    if activas == 0:
        resultado += "  (ninguna activa)\n"

    return resultado


def cancelar_invitacion(codigo: str, solicitado_por: str = None) -> str:
    """
    Cancelar una invitación.
    Si solicitado_por es None → superadmin, puede cancelar cualquiera.
    Si solicitado_por tiene valor → solo puede cancelar las que creó.
    """
    datos = _cargar_datos()
    codigo = codigo.upper().strip()

    for i, inv in enumerate(datos["invitaciones"]):
        if inv["codigo"] == codigo:
            if solicitado_por and not _numeros_coinciden(inv.get("creado_por", ""), solicitado_por):
                return "⛔ Solo podés cancelar invitaciones que vos creaste."
            datos["invitaciones"].pop(i)
            _guardar_datos(datos)
            return f"✅ Invitación {codigo} cancelada."

    return f"No se encontró la invitación {codigo}."


def listar_temporales_creados(creado_por: str) -> str:
    """Listar los accesos temporales que creó un número."""
    datos = _cargar_datos()
    ahora = config.ahora()
    resultado = "*⏰ TEMPORALES QUE DISTE:*\n\n"

    encontrados = 0
    for i, t in enumerate(datos["temporales"]):
        if not _numeros_coinciden(t.get("creado_por", ""), creado_por):
            continue

        try:
            fecha_hasta = datetime.strptime(t["fecha_hasta"], "%Y-%m-%d").date()
            vencido = ahora.date() > fecha_hasta
        except Exception:
            vencido = False

        if vencido:
            continue

        encontrados += 1
        dias_nombres = ["LUN", "MAR", "MIE", "JUE", "VIE", "SAB", "DOM"]
        dias_str = ", ".join([dias_nombres[d] for d in t.get("dias", [])])
        resultado += (
            f"  *#{i + 1}* {t.get('nombre', 'Sin nombre')} - {t['numero']}\n"
            f"    {t['fecha_desde']} a {t['fecha_hasta']}\n"
            f"    {dias_str} {t.get('hora_desde', '00:00')}-{t.get('hora_hasta', '23:59')}\n\n"
        )

    if encontrados == 0:
        resultado += "  (ninguno activo)\n"
    else:
        resultado += "_Para borrar, mandá:_ *BORRAR TEMPORAL #número*"

    return resultado


def borrar_temporal(indice: int, solicitado_por: str = None) -> str:
    """
    Borrar un acceso temporal por índice (1-based).
    Si solicitado_por tiene valor → solo puede borrar los que creó.
    """
    datos = _cargar_datos()
    idx = indice - 1  # Convertir a 0-based

    if idx < 0 or idx >= len(datos["temporales"]):
        return "❌ Número de temporal no válido. Mandá *MIS ACCESOS* para ver la lista."

    temporal = datos["temporales"][idx]

    if solicitado_por and not _numeros_coinciden(temporal.get("creado_por", ""), solicitado_por):
        return "⛔ Solo podés borrar temporales que vos creaste."

    nombre = temporal.get("nombre", "Sin nombre")
    numero = temporal["numero"]
    datos["temporales"].pop(idx)
    _guardar_datos(datos)
    return f"✅ Temporal de {nombre} ({numero}) eliminado."


def parsear_invitacion_natural(texto: str) -> dict:
    """
    Parsear comando INVITAR en lenguaje natural.

    Sintaxis: INVITAR [período] [personas] [horario] [motivo]
      Períodos: hoy, mañana, sábado, viernes a domingo, esta semana,
                este finde, 3 dias, 2 semanas, 6hs, 2026-03-15, etc.
      Personas: 20p, 20 personas
      Horario:  18 a 23, 10:00-14:00
    """
    hoy = config.ahora().date()
    ahora_dt = config.ahora()
    texto_lower = texto.lower().strip()

    fecha_desde = hoy
    fecha_hasta = hoy
    dias = [0, 1, 2, 3, 4, 5, 6]
    hora_desde = "00:00"
    hora_hasta = "23:59"
    max_usos = 10
    horas = 0  # >0 = modo legacy por horas

    # --- Extraer personas ---
    p_match = re.search(r'(\d+)\s*(?:personas?|p(?:ers)?|invitados?|usos?)\b', texto_lower)
    if p_match:
        max_usos = min(int(p_match.group(1)), 50)

    # --- Extraer horario (antes del período para evitar conflictos) ---
    horario_match = re.search(
        r'(?:de\s+)?(\d{1,2})(?::(\d{2}))?(?:\s*(?:hs?|horas?))?\s*(?:a|-|hasta)\s*(\d{1,2})(?::(\d{2}))?(?:\s*(?:hs?|horas?))?',
        texto_lower
    )
    horario_usado = False
    if horario_match:
        h1 = int(horario_match.group(1))
        h2 = int(horario_match.group(3))
        # Verificar que no sea un rango de período (ej: "3 a 5 dias")
        after_match = texto_lower[horario_match.end():].lstrip()
        es_rango_periodo = bool(re.match(r'(?:semanas?|d[ií]as?|mes(?:es)?|horas?)', after_match))
        if not es_rango_periodo and 0 <= h1 <= 23 and 0 <= h2 <= 23 and h1 != h2:
            hora_desde = f"{h1:02d}:{horario_match.group(2) or '00'}"
            hora_hasta = f"{h2:02d}:{horario_match.group(4) or '00'}"
            horario_usado = True

    # --- Extraer período ---
    periodo_encontrado = False

    # Fechas explícitas YYYY-MM-DD
    if m := re.search(r'(\d{4}-\d{2}-\d{2})\s+(?:a\s+|hasta\s+)?(\d{4}-\d{2}-\d{2})', texto_lower):
        try:
            fecha_desde = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            fecha_hasta = datetime.strptime(m.group(2), "%Y-%m-%d").date()
            periodo_encontrado = True
        except ValueError:
            pass
    elif m := re.search(r'(\d{4}-\d{2}-\d{2})', texto_lower):
        try:
            fecha_desde = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            fecha_hasta = fecha_desde
            periodo_encontrado = True
        except ValueError:
            pass

    if not periodo_encontrado:
        if re.search(r'\bhoy\b', texto_lower):
            fecha_desde = hoy
            fecha_hasta = hoy
            periodo_encontrado = True
        elif re.search(r'\bma[ñn]ana\b', texto_lower):
            fecha_desde = hoy + timedelta(days=1)
            fecha_hasta = hoy + timedelta(days=1)
            periodo_encontrado = True
        elif re.search(r'\besta\s+semana\b', texto_lower):
            fecha_hasta = hoy + timedelta(days=6 - hoy.weekday())
            periodo_encontrado = True
        elif re.search(r'\beste\s+mes\b', texto_lower):
            import calendar
            fecha_hasta = hoy.replace(day=calendar.monthrange(hoy.year, hoy.month)[1])
            periodo_encontrado = True
        elif re.search(r'\b(?:este\s+)?finde\b|\beste\s+fin\s*de\s*semana\b', texto_lower):
            dias_hasta_sab = (5 - hoy.weekday()) % 7
            if hoy.weekday() == 5:
                fecha_desde = hoy
            elif hoy.weekday() == 6:
                fecha_desde = hoy
                fecha_hasta = hoy
            else:
                if dias_hasta_sab == 0:
                    dias_hasta_sab = 7
                fecha_desde = hoy + timedelta(days=dias_hasta_sab)
            fecha_hasta = fecha_desde + timedelta(days=1) if fecha_desde.weekday() == 5 else fecha_desde
            dias = [5, 6]
            periodo_encontrado = True
        elif m := re.search(
            r'\b(?:el\s+)?(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)'
            r'\s+(?:a|al?|-|hasta|y)\s+'
            r'(?:el\s+)?(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b',
            texto_lower
        ):
            dia_desde = _nombre_a_weekday(m.group(1))
            dia_hasta = _nombre_a_weekday(m.group(2))
            dias_hasta_desde = (dia_desde - hoy.weekday()) % 7
            if dias_hasta_desde == 0 and hoy.weekday() != dia_desde:
                dias_hasta_desde = 7
            fecha_desde = hoy + timedelta(days=dias_hasta_desde)
            dias_rango = (dia_hasta - dia_desde) % 7
            fecha_hasta = fecha_desde + timedelta(days=dias_rango)
            periodo_encontrado = True
        elif m := re.search(
            r'\bhasta\s+(?:el\s+)?(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b',
            texto_lower
        ):
            dia_target = _nombre_a_weekday(m.group(1))
            dias_hasta = (dia_target - hoy.weekday()) % 7
            if dias_hasta == 0:
                dias_hasta = 7
            fecha_hasta = hoy + timedelta(days=dias_hasta)
            periodo_encontrado = True
        elif m := re.search(
            r'\b(?:el\s+)?(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b',
            texto_lower
        ):
            # Día suelto → ese día (próxima ocurrencia)
            dia_target = _nombre_a_weekday(m.group(1))
            dias_hasta = (dia_target - hoy.weekday()) % 7
            if dias_hasta == 0:
                fecha_desde = hoy  # Hoy es ese día
            else:
                fecha_desde = hoy + timedelta(days=dias_hasta)
            fecha_hasta = fecha_desde
            periodo_encontrado = True
        elif m := re.search(
            r'(\d+|un[ao]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|quince|veinte|treinta)\s+'
            r'(semanas?|d[ií]as?|mes(?:es)?)',
            texto_lower
        ):
            cantidad = _extraer_numero(m.group(1))
            unidad = m.group(2).lower()
            if "semana" in unidad:
                fecha_hasta = hoy + timedelta(weeks=cantidad)
            elif "dia" in unidad or "día" in unidad:
                fecha_hasta = hoy + timedelta(days=cantidad)
            elif "mes" in unidad:
                fecha_hasta = hoy + timedelta(days=30 * cantidad)
            periodo_encontrado = True

    # Horas legacy (ej: "6hs", "12 horas") → solo si no hubo período ni horario
    if not periodo_encontrado:
        h_match = re.search(r'(\d+)\s*(?:hs?|horas?)\b', texto_lower)
        if h_match and not horario_usado:
            horas = min(int(h_match.group(1)), 168)
            fecha_hasta = (ahora_dt + timedelta(hours=horas)).date()
            periodo_encontrado = True

    # --- Extraer días (solo si no fue seteado por finde) ---
    if sorted(dias) == [0, 1, 2, 3, 4, 5, 6]:
        if re.search(r'\bh[aá]biles?\b|\blaborales?\b', texto_lower):
            dias = [0, 1, 2, 3, 4]
        elif re.search(r'\btodos(?:\s+los\s+d[ií]as)?\b', texto_lower):
            dias = [0, 1, 2, 3, 4, 5, 6]
        elif m := re.search(
            r'\b((?:lun(?:es)?|mar(?:tes)?|mi[eé](?:rcoles)?|jue(?:ves)?|vie(?:rnes)?|s[aá]b(?:ados?)?|dom(?:ingos?)?)'
            r'(?:\s*,\s*(?:lun(?:es)?|mar(?:tes)?|mi[eé](?:rcoles)?|jue(?:ves)?|vie(?:rnes)?|s[aá]b(?:ados?)?|dom(?:ingos?)?))+)\b',
            texto_lower
        ):
            partes = re.split(r'\s*,\s*', m.group(1))
            dias = sorted(set(_nombre_a_weekday(d.strip()) for d in partes))

    # --- Extraer motivo (quitar todo lo parseado) ---
    motivo_texto = texto
    for patron in [
        r'(\d+)\s*(?:personas?|p(?:ers)?|invitados?|usos?)\b',
        r'(\d+)\s*(?:hs?|horas?)\b',
        r'\bhoy\b', r'\bma[ñn]ana\b', r'\besta\s+semana\b', r'\beste\s+mes\b',
        r'\b(?:este\s+)?finde\b', r'\beste\s+fin\s*de\s*semana\b',
        r'\bhasta\s+(?:el\s+)?(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b',
        r'\b(?:el\s+)?(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s+(?:a|al?|-|hasta|y)\s+(?:el\s+)?(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b',
        r'\b(?:el\s+)?(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b',
        r'(?:\d+|un[ao]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|quince|veinte|treinta)\s+(?:semanas?|d[ií]as?|mes(?:es)?)',
        r'\d{4}-\d{2}-\d{2}',
        r'\bh[aá]biles?\b', r'\blaborales?\b',
        r'\btodos(?:\s+los\s+d[ií]as)?\b',
        r'\b(?:lun(?:es)?|mar(?:tes)?|mi[eé](?:rcoles)?|jue(?:ves)?|vie(?:rnes)?|s[aá]b(?:ados?)?|dom(?:ingos?)?)(?:\s*,\s*(?:lun(?:es)?|mar(?:tes)?|mi[eé](?:rcoles)?|jue(?:ves)?|vie(?:rnes)?|s[aá]b(?:ados?)?|dom(?:ingos?)?))+\b',
        r'(?:de\s+)?(\d{1,2})(?::\d{2})?(?:\s*(?:hs?|horas?))?\s*(?:a|-|hasta)\s*(\d{1,2})(?::\d{2})?(?:\s*(?:hs?|horas?))?',
    ]:
        motivo_texto = re.sub(patron, '', motivo_texto, flags=re.IGNORECASE)
    motivo = re.sub(r'^[\s,.-]+|[\s,.-]+$', '', re.sub(r'\s+', ' ', motivo_texto).strip())

    return {
        "fecha_desde": fecha_desde.strftime("%Y-%m-%d") if hasattr(fecha_desde, 'strftime') else str(fecha_desde),
        "fecha_hasta": fecha_hasta.strftime("%Y-%m-%d") if hasattr(fecha_hasta, 'strftime') else str(fecha_hasta),
        "dias": dias,
        "hora_desde": hora_desde,
        "hora_hasta": hora_hasta,
        "max_usos": max_usos,
        "horas": horas,
        "motivo": motivo,
    }
