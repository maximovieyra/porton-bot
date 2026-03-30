# 🚪 Portón Bot

**Abrí el portón de tu edificio con una llamada o un mensaje de WhatsApp.**

Bot que conecta Twilio (llamadas/WhatsApp) con un relay Sonoff vía eWeLink API para controlar un portón eléctrico de forma remota. Ideal para edificios, consorcios o casas con acceso vehicular.

---

## Cómo funciona

```
📱 Llamada / WhatsApp  →  Twilio (webhook)  →  Flask Bot (Render)
                                                    │
                                              ¿Autorizado?
                                              /          \
                                            ✅ Sí        ❌ No
                                            │              │
                                     eWeLink API      "No autorizado"
                                            │
                                     Sonoff Relay
                                            │
                                     🚪 Portón se abre
```

## Características

- **Control por llamada telefónica** — llamás al número y el portón se abre automáticamente
- **Control por WhatsApp** — mandás un mensaje y listo
- **Control de accesos** — solo números autorizados pueden abrir
- **Panel de administración web** — dashboard para gestionar accesos y ver el registro de aperturas
- **Registro de actividad** — log de quién abrió y cuándo
- **Deploy gratuito** — corre en Render free tier

## Tech Stack

| Componente | Tecnología |
|---|---|
| Backend | Python · Flask |
| Telefonía | Twilio (Voice + WhatsApp) |
| IoT | eWeLink API · Sonoff Relay |
| Deploy | Render (free tier) |
| Frontend | HTML + CSS (panel admin) |

## Estructura del proyecto

```
porton-bot/
├── app.py                  # Servidor Flask + webhooks de Twilio
├── ewelink_controller.py   # Integración con eWeLink API
├── config.py               # Variables de entorno y configuración
├── accesos.py              # Gestión de números autorizados
├── registro.py             # Log de aperturas
├── api.py                  # Endpoints del panel de administración
├── static/                 # Frontend del dashboard
├── requirements.txt        # Dependencias Python
├── Procfile                # Config de Render
└── _env.example            # Template de variables de entorno
```

## Instalación

### Requisitos previos

- Python 3.10+
- Cuenta en [Twilio](https://www.twilio.com/) (número argentino con Voice)
- Cuenta en [eWeLink](https://www.ewelink.cc/) (con el relay Sonoff configurado)
- Cuenta en [Render](https://render.com/) (para deploy)

### Setup local

```bash
# Clonar el repo
git clone https://github.com/maximovieyra/porton-bot.git
cd porton-bot

# Entorno virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Dependencias
pip install -r requirements.txt

# Configurar credenciales
cp _env.example .env
# Editar .env con tus credenciales de Twilio y eWeLink

# Correr
python app.py
```

### Variables de entorno

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=tu_auth_token
TWILIO_PHONE_NUMBER=+5411XXXXXXXX

EWELINK_EMAIL=tu@email.com
EWELINK_PASSWORD=tu_password
EWELINK_REGION=us
EWELINK_DEVICE_ID=1000abcdef

NUMERO_PRINCIPAL=+5492211234567
PULSE_SECONDS=3
```

### Deploy en Render

1. Conectá tu repo de GitHub en [render.com](https://render.com)
2. Configurá como **Web Service** con Python runtime
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app --bind 0.0.0.0:$PORT`
5. Agregá las variables de entorno
6. En Twilio, apuntá el webhook de tu número a `https://tu-app.onrender.com/voice`

> 💡 **Tip:** usá [UptimeRobot](https://uptimerobot.com/) (gratis) para evitar que Render free tier se duerma.

## Costo mensual

| Concepto | Costo |
|---|---|
| Twilio — Número argentino | ~8 USD/mes |
| Twilio — Llamadas entrantes | ~0.01 USD/llamada |
| Render — Free tier | Gratis |
| **Total** | **~8 USD/mes** |

## Documentación adicional

- [📖 Guía paso a paso (setup completo)](GUIA_PASO_A_PASO.md)
- [📱 Guía de WhatsApp Business](GUIA_WHATSAPP_v3.md)

## Autor

**Maxi Vieyra** — Estudiante de Ingeniería en Inteligencia Artificial @ Universidad de Palermo

---

*Proyecto pensado para resolver un problema real: abrir el portón del edificio sin bajar del auto.*
