# Guía Paso a Paso: Bot Portón — Fase 1: Llamadas

## Qué vamos a hacer

```
VOS (manos libres del Ka: "Llamar a Portón")
    ↓
TWILIO (recibe la llamada en tu número argentino)
    ↓
TU BOT (Python en la nube, verifica que seas vos)
    ↓
eWeLINK API (manda la orden al dispositivo)
    ↓
PORTÓN (se abre)
```

Costo: ~8 USD/mes el número argentino + centavos por uso. Tu plan de Personal no te cobra extra (llamada nacional).

---

## Requisitos previos

- Computadora con Windows, Mac o Linux
- Tu cuenta de eWeLink (la del portón)
- Tarjeta de débito/crédito (para Twilio, te dan crédito gratis)
- Tu número de celular con código de país (ej: +5492211234567)

---

## Paso 1 — Crear cuenta en Twilio (~10 min)

1. Andá a **https://www.twilio.com/try-twilio**
2. Registrate con nombre, email, contraseña
3. Verificá tu email (revisá spam)
4. Verificá tu celular (te mandan un SMS con código)
5. Respondé las preguntas:
   - "Which product?" → **Phone Numbers**
   - "What to build?" → **Other**
   - "How to build?" → **With code**
   - "Language?" → **Python**
6. En el Dashboard vas a ver:
   - **Account SID** (empieza con "AC") → COPIALO
   - **Auth Token** (hacé clic en "Show") → COPIALO
7. Guardalos en un .txt por ahora

> Twilio te da ~15 USD de crédito gratis. Alcanza para probar todo.

---

## Paso 2 — Comprar número argentino en Twilio (~5 min)

1. Dashboard → **Phone Numbers** → **Manage** → **Buy a number**
2. País: **Argentina**
3. Asegurate que tenga **Voice** marcado como capability
4. **Search** → elegí uno → **Buy** (~8 USD/mes, usa el crédito gratis)
5. Anotá el número completo (ej: +5411XXXXXXXX)

**En tu celular:** creá un contacto nuevo:
- Nombre: **Portón**
- Número: el que compraste

> NOTA: Twilio te puede pedir verificar una dirección argentina para el número. Es un formulario simple con tu nombre y dirección.

---

## Paso 3 — Preparar tu compu (~15 min)

### Python
Si ya lo tenés por la facu, verificá:
```bash
python --version
```
Necesitás 3.10+. Si no: https://www.python.org/downloads/
> Windows: MARCÁ "Add Python to PATH" al instalar.

### Git
https://git-scm.com/downloads — Instalá con opciones por defecto.
```bash
git --version
```

### VS Code (recomendado)
https://code.visualstudio.com/ — Instalá la extensión de Python.

### ngrok (para probar localmente)
1. Creá cuenta gratis en https://ngrok.com/
2. Descargá ngrok para tu sistema
3. Conectá tu cuenta:
```bash
ngrok config add-authtoken TU_TOKEN_DE_NGROK
```

---

## Paso 4 — Configurar el proyecto (~10 min)

### 4.1 Crear carpeta
```bash
mkdir porton-bot
cd porton-bot
```

### 4.2 Copiar los archivos
Descargá los archivos que te pasé y ponelos en la carpeta. Debería quedar:
```
porton-bot/
├── app.py
├── ewelink_controller.py
├── config.py
├── requirements.txt
├── Procfile
├── .env.example
└── .gitignore
```

### 4.3 Entorno virtual
```bash
python -m venv venv
```
Activar:
- **Windows:** `venv\Scripts\activate`
- **Mac/Linux:** `source venv/bin/activate`

Vas a ver `(venv)` al inicio de la línea.

### 4.4 Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4.5 Configurar credenciales
```bash
cp .env.example .env
```
(Windows: `copy .env.example .env`)

Abrí `.env` con VS Code y completá:
```
TWILIO_ACCOUNT_SID=ACxxxxxxxx          ← Del Dashboard de Twilio
TWILIO_AUTH_TOKEN=tu_auth_token         ← Del Dashboard de Twilio
TWILIO_PHONE_NUMBER=+5411XXXXXXXX      ← El número que compraste

EWELINK_EMAIL=tu@email.com              ← Email de eWeLink
EWELINK_PASSWORD=tu_password            ← Contraseña de eWeLink
EWELINK_REGION=us                       ← Dejá "us" para Argentina
EWELINK_DEVICE_ID=                      ← Lo obtenemos en el paso 5

NUMERO_PRINCIPAL=+5492211234567         ← TU celular
PULSE_SECONDS=3                         ← Segundos del pulso
```

> FORMATO DE TU NÚMERO: +549 + código de área sin 0 + número sin 15.
> Ejemplo: (0221) 15-123-4567 → +5492211234567

---

## Paso 5 — Obtener el Device ID del portón (~5 min)

1. Levantá el bot:
```bash
python app.py
```

2. Abrí en el navegador: **http://localhost:5000/devices**

3. Vas a ver algo como:
```json
{
  "devices": [
    {
      "id": "1000abcdef",
      "name": "Portón Barrio",
      "online": true,
      "state": "off"
    }
  ]
}
```

4. Copiá el `"id"` del portón y ponelo en `.env`:
```
EWELINK_DEVICE_ID=1000abcdef
```

5. Reiniciá el bot (Ctrl+C → `python app.py`)

---

## Paso 6 — Probar localmente con ngrok (~10 min)

### 6.1 Levantar ngrok
En **otra terminal** (dejá el bot corriendo):
```bash
ngrok http 5000
```
Te da una URL tipo: `https://abc123.ngrok-free.app` → COPIALA.

### 6.2 Configurar Twilio
1. Dashboard de Twilio → **Phone Numbers** → clic en tu número
2. Sección **"A call comes in"**:
   - Webhook
   - URL: `https://abc123.ngrok-free.app/voice`
   - POST
3. Guardá

### 6.3 Probar
Llamá desde tu celu al contacto "Portón". Si todo funciona:
- Escuchás "Abriendo el portón. Chau."
- En la terminal del bot ves que procesó la llamada
- El portón se abre

> Si no funciona, saltá a la sección de Troubleshooting al final.

---

## Paso 7 — Subir a GitHub (~5 min)

1. Creá cuenta en https://github.com (si no tenés)
2. New repository → nombre: `porton-bot` → **Private** → Create
3. En la terminal:
```bash
git init
git add .
git commit -m "Primer commit - Bot Portón"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/porton-bot.git
git push -u origin main
```

> VERIFICÁ que `.env` NO se suba. El `.gitignore` lo excluye automáticamente.

---

## Paso 8 — Deploy en Render (~10 min)

### 8.1 Cuenta
https://render.com — Podés registrarte con GitHub.

### 8.2 Nuevo Web Service
**"New +"** → **"Web Service"** → Conectá GitHub → Seleccioná `porton-bot`

### 8.3 Configurar
- **Name**: `porton-bot`
- **Branch**: `main`
- **Runtime**: Python 3
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT`
- **Instance Type**: **Free**

### 8.4 Variables de entorno
Agregá todas en **"Environment Variables"**:

| Key | Value |
|-----|-------|
| TWILIO_ACCOUNT_SID | ACxxxxxxxx... |
| TWILIO_AUTH_TOKEN | tu_auth_token |
| TWILIO_PHONE_NUMBER | +5411XXXXXXXX |
| EWELINK_EMAIL | tu@email.com |
| EWELINK_PASSWORD | tu_password |
| EWELINK_REGION | us |
| EWELINK_DEVICE_ID | 1000abcdef |
| NUMERO_PRINCIPAL | +5492211234567 |
| PULSE_SECONDS | 3 |

### 8.5 Deploy
**"Create Web Service"** → esperá 2-5 min.

Te da una URL tipo: `https://porton-bot-xxxx.onrender.com`

Probá: `https://porton-bot-xxxx.onrender.com/` → debería devolver `{"status": "ok"}`

> RENDER FREE TIER: Se duerme a los 15 min de inactividad. La primera llamada tarda ~30 seg en despertar. Solución gratis: usá UptimeRobot (uptimerobot.com, gratis) para hacer ping a tu URL cada 10 min y que nunca se duerma.

---

## Paso 9 — Conectar Twilio con tu bot (~2 min)

1. Twilio → **Phone Numbers** → tu número
2. **"A call comes in"**: Webhook → `https://porton-bot-xxxx.onrender.com/voice` → POST
3. Guardá

---

## Paso 10 — Prueba final

- [ ] Llamar a "Portón" desde el celu → Se abre
- [ ] Llamar desde el manos libres del Ford Ka → Se abre
- [ ] Llamar desde número NO autorizado → "No estás autorizado", NO abre
- [ ] Abrir tu URL /  → Status ok

Si todo funciona, ya tenés tu portón automatizado. 

---

## Fase 2 (después): WhatsApp

Una vez que las llamadas funcionen bien, vamos a agregar WhatsApp Business al mismo número. Eso requiere:
1. Crear cuenta en Meta Business (business.facebook.com)
2. Registrar tu número como WhatsApp Business via Twilio
3. Esperar aprobación de Meta (~días)
4. Agregar el webhook de WhatsApp al bot

Lo hacemos juntos cuando estés listo. El mismo número sirve para llamadas Y WhatsApp.

---

## Troubleshooting

**"El bot no responde cuando llamo"**
- ¿El bot está corriendo? Abrí la URL / en el navegador
- ¿El webhook en Twilio apunta a tu URL con /voice al final?
- ¿Render free tier? Esperá 30 seg, puede estar dormido

**"El bot responde pero el portón no se abre"**
- Verificá EWELINK_DEVICE_ID
- Verificá credenciales de eWeLink
- Revisá logs en Render (Dashboard → tu servicio → Logs)
- ¿El dispositivo está online en la app eWeLink?

**"Error de autenticación con eWeLink"**
- Probá región "eu" además de "us"
- Si usás login con Google/Facebook en eWeLink, creá contraseña directa

**"Mi número no se reconoce como autorizado"**
- Formato: +549 + área sin 0 + número sin 15
- (0221) 15-123-4567 → +5492211234567
- Sin espacios ni guiones

**"Tarda mucho"**
- Render free tier dormido (~30 seg) + pulso (3 seg) = hasta 33 seg
- Solución: UptimeRobot (gratis) o Render Starter ($7 USD/mes)

---

## Costos mensuales

| Concepto | Costo |
|----------|-------|
| Twilio — Número argentino | ~8 USD/mes |
| Twilio — Llamadas entrantes | ~0.01 USD/llamada |
| Personal — Tu plan | $0 extra (nacional) |
| Render — Free tier | Gratis |
| **Total** | **~8 USD/mes** |
