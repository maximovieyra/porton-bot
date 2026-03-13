"""
Controlador eWeLink v3.1 - Maneja autenticación y control del portón.

Mejoras sobre v1:
- Singleton: una sola instancia global
- Token cacheado: no hace login en cada operación (12hs de vida)
- Auto-retry: si el token expiró, re-login y reintenta
- PulseResult: retorna detalle de qué pasó para avisar al usuario

Usa un event loop nuevo por operación (como antes) porque
run_coroutine_threadsafe + thread dedicado causa timeouts en Render.
"""

import hashlib
import hmac
import base64
import asyncio
import json
import logging
import os
import time as _time
import threading
import aiohttp

logger = logging.getLogger(__name__)

# Endpoints por región
API_URLS = {
    "us": "https://us-apia.coolkit.cc",
    "eu": "https://eu-apia.coolkit.cc",
    "cn": "https://cn-apia.coolkit.cn",
    "as": "https://as-apia.coolkit.cc",
}

APP_ID = os.getenv("EWELINK_APP_ID", "R8Oq3y0eSZSYdKccHlrQzT1ACCOUT9Gv")
APP_SECRET = os.getenv("EWELINK_APP_SECRET", "1ve5Qk9GXfUhKAn1svnKwpAlxXkMarru")

# Token dura ~30 días en eWeLink, refrescamos cada 12 horas por seguridad
TOKEN_REFRESH_SECONDS = 12 * 60 * 60


class PulseResult:
    """Resultado de una operación del portón."""

    def __init__(self, ok: bool, error: str = "", detalle: str = ""):
        self.ok = ok
        self.error = error      # Mensaje corto para el usuario
        self.detalle = detalle  # Detalle técnico para el log

    def __bool__(self):
        return self.ok

    def __repr__(self):
        return f"PulseResult(ok={self.ok}, error='{self.error}')"


class EWeLinkController:
    """Controlador singleton para dispositivos eWeLink via API Cloud."""

    def __init__(self, email: str, password: str, region: str = "us", device_id: str = ""):
        self.email = email
        self.password = password
        self.region = region
        self.device_id = device_id
        self.api_url = API_URLS.get(region, API_URLS["us"])

        # Estado de autenticación (persiste entre operaciones)
        self.token = None
        self.user_apikey = None
        self._token_timestamp = 0

        # Lock para operaciones (evita pulsos simultáneos)
        self._op_lock = threading.Lock()

        logger.info(f"EWeLinkController inicializado (región: {region}, device: {device_id})")

    # ── Token management ──

    def _token_vigente(self) -> bool:
        """Verificar si el token todavía es válido."""
        if not self.token:
            return False
        return (_time.time() - self._token_timestamp) < TOKEN_REFRESH_SECONDS

    # ── Operaciones async internas ──

    async def _login(self, session: aiohttp.ClientSession) -> bool:
        """Autenticarse con eWeLink y obtener token."""
        try:
            url = f"{self.api_url}/v2/user/login"

            payload = {
                "email": self.email,
                "password": self.password,
                "countryCode": os.getenv("EWELINK_COUNTRY_CODE", "+54"),
            }

            body = json.dumps(payload, separators=(',', ':'))

            sign = base64.b64encode(
                hmac.new(
                    APP_SECRET.encode(),
                    body.encode(),
                    hashlib.sha256,
                ).digest()
            ).decode()

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Sign {sign}",
                "X-CK-Appid": APP_ID,
            }

            async with session.post(url, data=body, headers=headers) as resp:
                data = await resp.json()

            if data.get("error") == 0:
                self.token = data["data"]["at"]
                self.user_apikey = data["data"]["user"]["apikey"]
                self._token_timestamp = _time.time()
                logger.info("Login exitoso en eWeLink")
                return True
            else:
                error_code = data.get("error", "?")
                error_msg = data.get("msg", "desconocido")
                logger.error(f"Error login eWeLink: código {error_code} - {error_msg}")
                return False

        except aiohttp.ClientError as e:
            logger.error(f"Error de conexión en login: {e}")
            return False
        except Exception as e:
            logger.error(f"Excepción en login: {e}")
            return False

    def _auth_headers(self) -> dict:
        """Headers para requests autenticados."""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
            "X-CK-Appid": APP_ID,
            "X-CK-Nonce": os.urandom(4).hex(),
        }

    async def _set_switch(self, session: aiohttp.ClientSession, state: str, device_id: str = None) -> PulseResult:
        """Cambiar estado del switch."""
        device_id = device_id or self.device_id
        if not device_id:
            return PulseResult(False, "Sin device_id configurado", "No se especificó device_id")

        try:
            url = f"{self.api_url}/v2/device/thing/status"

            payload = {
                "type": 1,
                "id": device_id,
                "params": {"switch": state},
            }

            async with session.post(url, json=payload, headers=self._auth_headers()) as resp:
                data = await resp.json()

            error_code = data.get("error", -1)

            if error_code == 0:
                logger.info(f"Switch {device_id} -> {state}")
                return PulseResult(True)

            # Token expirado → re-login y reintentar
            if error_code == 401:
                logger.warning("Token expirado, re-login...")
                if await self._login(session):
                    async with session.post(url, json=payload, headers=self._auth_headers()) as resp:
                        data = await resp.json()
                    if data.get("error") == 0:
                        logger.info(f"Switch {device_id} -> {state} (retry OK)")
                        return PulseResult(True)
                return PulseResult(False, "Error de autenticación con eWeLink", "401 persistente")

            # Dispositivo offline
            if error_code == 500:
                return PulseResult(
                    False,
                    "⚠️ El dispositivo del portón está offline. Verificá la conexión WiFi del relay.",
                    f"Device {device_id} offline (error 500)"
                )

            return PulseResult(False, f"Error de eWeLink (código {error_code})", f"{data}")

        except aiohttp.ClientError as e:
            return PulseResult(
                False,
                "⚠️ No se pudo conectar con eWeLink. Puede ser un problema de internet del servidor.",
                f"ClientError: {e}"
            )
        except asyncio.TimeoutError:
            return PulseResult(
                False,
                "⚠️ eWeLink no respondió a tiempo. Intentá de nuevo.",
                "Timeout en set_switch"
            )
        except Exception as e:
            return PulseResult(False, f"Error inesperado: {e}", f"Excepción: {e}")

    async def _pulse_async(self, seconds: int = 3, device_id: str = None) -> PulseResult:
        """Pulso completo: login si hace falta, on, wait, off."""
        device_id = device_id or self.device_id
        timeout = aiohttp.ClientTimeout(total=20)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Login si hace falta
            if not self._token_vigente():
                logger.info("Token expirado o inexistente, haciendo login...")
                if not await self._login(session):
                    return PulseResult(
                        False,
                        "⚠️ No se pudo conectar con eWeLink. Verificá las credenciales o la conexión.",
                        "Login fallido"
                    )

            logger.info(f"Ejecutando pulso de {seconds}s en {device_id}")

            # Encender
            result = await self._set_switch(session, "on", device_id)
            if not result:
                return result

            # Esperar
            await asyncio.sleep(seconds)

            # Apagar
            result_off = await self._set_switch(session, "off", device_id)
            if not result_off:
                logger.error(f"ALERTA: relay quedó encendido en {device_id}")
                return PulseResult(
                    False,
                    "⚠️ El portón se activó pero hubo un error al apagar el relay. Puede que haya quedado encendido.",
                    "Encendido OK, apagado FALLÓ"
                )

            return PulseResult(True)

    async def _get_devices_async(self) -> list:
        """Obtener lista de dispositivos."""
        timeout = aiohttp.ClientTimeout(total=15)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            if not self._token_vigente():
                if not await self._login(session):
                    return []

            try:
                async with session.get(
                    f"{self.api_url}/v2/device/thing?num=0&beginIndex=-9999999",
                    headers=self._auth_headers(),
                ) as resp:
                    device_data = await resp.json()

                if device_data.get("error") == 0:
                    things = device_data.get("data", {}).get("thingList", [])
                    devices = []
                    for thing in things:
                        item = thing.get("itemData", {})
                        devices.append({
                            "id": item.get("deviceid"),
                            "name": item.get("name"),
                            "online": item.get("online"),
                            "state": item.get("params", {}).get("switch"),
                        })
                    return devices
                else:
                    logger.error(f"Error obteniendo dispositivos: {device_data}")
                    return []

            except Exception as e:
                logger.error(f"Excepción obteniendo dispositivos: {e}")
                return []

    # ── API pública (sincrónica, thread-safe) ──

    def pulse(self, seconds: int = 3, device_id: str = None) -> PulseResult:
        """Ejecutar pulso. Thread-safe (usa lock para evitar pulsos simultáneos)."""
        with self._op_lock:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._pulse_async(seconds, device_id))
            except Exception as e:
                logger.error(f"Error en pulse: {e}")
                return PulseResult(False, f"Error inesperado: {e}", str(e))
            finally:
                loop.close()

    def get_devices(self) -> list:
        """Obtener dispositivos. Thread-safe."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._get_devices_async())
        except Exception as e:
            logger.error(f"Error en get_devices: {e}")
            return []
        finally:
            loop.close()

    def force_login(self) -> bool:
        """Forzar re-login (para debug)."""
        self.token = None
        self._token_timestamp = 0

        async def _do_login():
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                return await self._login(session)

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_do_login())
        except Exception as e:
            logger.error(f"Error en force_login: {e}")
            return False
        finally:
            loop.close()


# ============================================================
# SINGLETON GLOBAL
# ============================================================

_instance = None
_instance_lock = threading.Lock()


def get_controller() -> EWeLinkController:
    """Obtener la instancia singleton del controller."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                import config
                _instance = EWeLinkController(
                    email=config.EWELINK_EMAIL,
                    password=config.EWELINK_PASSWORD,
                    region=config.EWELINK_REGION,
                    device_id=config.EWELINK_DEVICE_ID,
                )
    return _instance
