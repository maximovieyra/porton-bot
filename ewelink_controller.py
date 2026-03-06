"""
Controlador eWeLink - Maneja autenticación y control del portón.

Usa la API de CoolKit (backend de eWeLink) directamente via HTTP.
No depende de librerías de terceros que pueden romperse.
"""

import hashlib
import hmac
import base64
import time
import asyncio
import logging
import os
import aiohttp

logger = logging.getLogger(__name__)

# Endpoints por región
API_URLS = {
    "us": "https://us-apia.coolkit.cc",
    "eu": "https://eu-apia.coolkit.cc",
    "cn": "https://cn-apia.coolkit.cn",
    "as": "https://as-apia.coolkit.cc",
}

# APP ID/SECRET públicos de eWeLink (los mismos que usa la app oficial)
APP_ID = "R8Oq3y0eSZSYdKccHlrQzT1ACCOUT9Gv"
APP_SECRET = "1ve5Qk9GXfUhKAn1svnKwpAlxXkMarru"


class EWeLinkController:
    """Controlador para dispositivos eWeLink via API Cloud."""

    def __init__(self, email: str, password: str, region: str = "us", device_id: str = ""):
        self.email = email
        self.password = password
        self.region = region
        self.device_id = device_id
        self.api_url = API_URLS.get(region, API_URLS["us"])
        self.token = None
        self.user_apikey = None
        self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def login(self) -> bool:
        """Autenticarse con eWeLink y obtener token."""
        try:
            session = await self._get_session()
            url = f"{self.api_url}/v2/user/login"

            payload = {
                "email": self.email,
                "password": self.password,
                "countryCode": "+86",
            }

            import json
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
                logger.info("Login exitoso en eWeLink")
                return True
            else:
                logger.error(f"Error login eWeLink: {data}")
                return False

        except Exception as e:
            logger.error(f"Excepción en login: {e}")
            return False
            async with session.post(url, data=body, headers=headers) as resp:
                data = await resp.json()

            async with session.post(url, json=payload, headers=headers) as resp:
                data = await resp.json()

            if data.get("error") == 0:
                self.token = data["data"]["at"]
                self.user_apikey = data["data"]["user"]["apikey"]
                logger.info("Login exitoso en eWeLink")
                return True
            else:
                logger.error(f"Error login eWeLink: {data}")
                return False

        except Exception as e:
            logger.error(f"Excepción en login: {e}")
            return False

    async def get_devices(self) -> list:
        """Obtener lista de dispositivos."""
        try:
            session = await self._get_session()
            url = f"{self.api_url}/v2/device/thing"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
                "X-CK-Appid": APP_ID,
                "X-CK-Nonce": os.urandom(4).hex(),
            }

            payload = {"thingList": []}

            # Primero obtener la lista de familias/hogares
            family_url = f"{self.api_url}/v2/family"
            async with session.get(family_url, headers=headers) as resp:
                family_data = await resp.json()

            if family_data.get("error") != 0:
                logger.error(f"Error obteniendo familias: {family_data}")
                return []

            # Obtener dispositivos
            device_url = f"{self.api_url}/v2/device/thing"
            async with session.get(
                f"{self.api_url}/v2/device/thing?num=0&beginIndex=-9999999",
                headers=headers,
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

    async def set_switch(self, state: str, device_id: str = None) -> bool:
        """
        Cambiar estado del switch.
        state: "on" o "off"
        """
        device_id = device_id or self.device_id
        if not device_id:
            logger.error("No se especificó device_id")
            return False

        try:
            session = await self._get_session()
            url = f"{self.api_url}/v2/device/thing/status"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
                "X-CK-Appid": APP_ID,
                "X-CK-Nonce": os.urandom(4).hex(),
            }

            payload = {
                "type": 1,
                "id": device_id,
                "params": {"switch": state},
            }

            async with session.post(url, json=payload, headers=headers) as resp:
                data = await resp.json()

            if data.get("error") == 0:
                logger.info(f"Switch {device_id} -> {state}")
                return True
            else:
                logger.error(f"Error cambiando switch: {data}")
                return False

        except Exception as e:
            logger.error(f"Excepción en set_switch: {e}")
            return False

    async def pulse(self, seconds: int = 3, device_id: str = None) -> bool:
        """
        Pulso: enciende, espera X segundos, apaga.
        Simula apretar un botón del portón.
        """
        device_id = device_id or self.device_id

        logger.info(f"Ejecutando pulso de {seconds}s en {device_id}")

        # Encender
        result = await self.set_switch("on", device_id)
        if not result:
            return False

        # Esperar
        await asyncio.sleep(seconds)

        # Apagar
        result = await self.set_switch("off", device_id)
        return result


# --- Funciones helper para usar desde código sincrónico (Flask) ---

_controller = None


def get_controller(email: str, password: str, region: str, device_id: str) -> EWeLinkController:
    """Obtener instancia del controlador (singleton)."""
    global _controller
    if _controller is None:
        _controller = EWeLinkController(email, password, region, device_id)
    return _controller


def sync_pulse(controller: EWeLinkController, seconds: int = 3) -> bool:
    """Ejecutar pulso de forma sincrónica (para usar desde Flask)."""
    loop = asyncio.new_event_loop()
    try:
        # Login si no hay token
        if not controller.token:
            success = loop.run_until_complete(controller.login())
            if not success:
                return False

        result = loop.run_until_complete(controller.pulse(seconds))
        return result
    except Exception as e:
        logger.error(f"Error en sync_pulse: {e}")
        return False
    finally:
        loop.run_until_complete(controller.close())
        loop.close()


def sync_get_devices(controller: EWeLinkController) -> list:
    """Obtener dispositivos de forma sincrónica."""
    loop = asyncio.new_event_loop()
    try:
        if not controller.token:
            success = loop.run_until_complete(controller.login())
            if not success:
                return []

        devices = loop.run_until_complete(controller.get_devices())
        return devices
    except Exception as e:
        logger.error(f"Error en sync_get_devices: {e}")
        return []
    finally:
        loop.run_until_complete(controller.close())
        loop.close()
