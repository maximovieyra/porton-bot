# Guía de WhatsApp - Bot Portón v3

## Roles

| Rol | Quién es | Qué puede hacer |
|-----|----------|-----------------|
| 👑 **Superadmin** | Definido en `.env` | Todo: abrir, cerrar, temporales, eliminar, logs, estado, listar, cambiar PIN |
| 🏠 **Habitante** | Se registra con PIN | Abrir, cerrar, dar temporales |
| ⏰ **Temporal** | Agregado por habitante/superadmin | Solo abrir y cerrar (en su ventana) |
| 🚫 **Sin acceso** | Cualquier otro | Solo puede registrarse con PIN |

---

## Registrarse como habitante
Mandá el PIN del barrio por WhatsApp:
```
PIN 1234
```

---

## Comandos de todos los autorizados

| Comando | Qué hace |
|---------|----------|
| `ABRIR` | Abre el portón |
| `CERRAR` | Cierra el portón |
| `AYUDA` | Muestra los comandos según tu rol |

Variantes aceptadas: `abrí`, `dale`, `afuera`, `llegué`, `cerrá`, `cerralo`, etc.

---

## Comandos de habitantes (y superadmins)

### Dar acceso temporal
```
TEMPORAL +5492211234567 una semana Pintor Juan
TEMPORAL +5492211234567 2 semanas habiles 8 a 17 Electricista
TEMPORAL +5492211234567 hasta el viernes 9 a 18 Gasista
TEMPORAL +5492211234567 3 dias Delivery
TEMPORAL +5492211234567 hoy 10 a 14 Plomero
TEMPORAL +5492211234567 proximas 2 semanas habiles Albañil
TEMPORAL +5492211234567 este mes habiles 8 a 17 Obra
```

---

## Comandos solo para superadmins

| Comando | Qué hace |
|---------|----------|
| `AGREGAR +número` | Agregar un habitante directamente |
| `ELIMINAR +número` | Eliminar un habitante o temporal |
| `LISTAR` | Ver todos los accesos (con quién creó cada temporal) |
| `LOG` / `LOG 20` | Ver últimos registros de actividad |
| `RESUMEN` | Resumen del día |
| `ESTADO` | Ver si el portón está abierto o cerrado |
| `BLOQUEAR` | Bloquea el portón para todos menos superadmins |
| `DESBLOQUEAR` | Desbloquea el portón |
| `CAMBIARPIN xxxx` | Cambiar el PIN de registro de habitantes |

---

## Notas técnicas

- **Si el pulso falla** (eWeLink caído, dispositivo offline, sin internet), el usuario recibe un segundo WhatsApp con el error. No se queda sin saber qué pasó.
- **Cuando un habitante crea un temporal**, el número temporal recibe un WhatsApp de bienvenida con las instrucciones y sus días/horarios.
- **Token cacheado**: el bot no hace login en cada operación, reutiliza el token por 12 horas.

---

## Configuración en `.env`

```env
# Superadmins (solo se definen acá, no por WhatsApp)
SUPERADMIN_1=+5492211234567
SUPERADMIN_2=+5492219876543

# PIN para que vecinos se registren como habitantes
HABITANTE_PIN=1234
```
