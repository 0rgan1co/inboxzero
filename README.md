# InboxZero (v2)

Capturador inteligente para tu second-brain, vía Telegram.

## Qué hace (v2)

1. **Bot 24/7 en Railway** (`@ceroinbox_bot`) recibe mensajes de Telegram.
2. **Clasifica** cada mensaje como `idea | pedido | tarea | nota`. Usa Claude haiku si tenés `ANTHROPIC_API_KEY`; si no, heurística.
3. **Recordatorios programables**: `/recordar en 2h llamar a Juan`, `/recordar mañana 9am revisar mail`. Un scheduler interno (mismo proceso) dispara cuando vence.
4. **Digest diario opcional**: cada día a la hora que configures, te manda un resumen al chat (capturas pendientes + próximos recordatorios + stats).
5. **Web UI mínima** en `/ui` para revisar/editar capturas y cancelar recordatorios sin abrir Telegram. Auth con la misma `SYNC_API_KEY`.
6. **Script local en tu Mac** (vía launchd) sincroniza capturas Y recordatorios al vault de Obsidian.
7. **Soberanía de datos**: SQLite local en el contenedor Railway, en volumen persistente. Sin servicios de terceros para tus datos. Las únicas dependencias externas: Telegram (mensajería) y Anthropic (opcional, sólo para clasificar).

## Arquitectura

```
┌──────────┐      polling       ┌────────────────────────┐         ┌──────────────┐
│ Telegram │◀──────────────────▶│        Railway         │◀──HTTP──│  Mac local   │
│  (vos)   │                    │  ┌──────────────────┐  │         │  sync.py     │
└──────────┘                    │  │  bot.py (PTB)    │  │         │  → Obsidian  │
                                │  │  reminders loop  │  │         └──────────────┘
                                │  │  digest loop     │  │
                                │  │  FastAPI /ui /api│  │
                                │  └──────────────────┘  │
                                │  SQLite en /data/      │
                                └────────────────────────┘
                                  Tu servidor, tus datos.
```

## Estructura del repo

```
inboxzero/
├── README.md                 ← este archivo
├── requirements.txt
├── runtime.txt
├── Procfile
├── railway.json
├── .env.example
├── .gitignore
├── app/
│   ├── main.py               ← FastAPI + lifespan + schedulers
│   ├── bot.py                ← handlers de Telegram (incluye /recordar /digest /id)
│   ├── classify.py           ← cascada: comando → LLM → heurística
│   ├── llm.py                ← llamadas opcionales a Claude API (urllib stdlib)
│   ├── duration.py           ← parser español 'en 2h', 'mañana 9am', etc.
│   ├── reminders.py          ← scheduler async de recordatorios
│   ├── digest.py             ← scheduler async + builder del digest
│   ├── db.py                 ← SQLite (messages + reminders)
│   ├── api.py                ← endpoints /pending /mark-synced /stats /reminders/...
│   ├── web.py                ← UI HTML+JS inline en /ui
│   └── config.py             ← env vars
└── sync/
    ├── sync_to_obsidian.py   ← script para tu Mac (sincroniza ambos)
    ├── .env.example
    ├── com.inboxzero.sync.plist
    └── README.md
```

## Variables de entorno

### v1 (obligatorias)
| Var | Descripción |
|---|---|
| `TELEGRAM_BOT_TOKEN` | De `@BotFather`. |
| `ALLOWED_USER_IDS` | IDs autorizados, coma-separados. Hablale a `@userinfobot` para conseguir el tuyo. |
| `SYNC_API_KEY` | API key para los endpoints HTTP. `openssl rand -hex 32`. |
| `DB_PATH` | Path a la SQLite. En Railway: `/data/inboxzero.db` (con volumen montado). |

### v2 (opcionales)
| Var | Default | Descripción |
|---|---|---|
| `ANTHROPIC_API_KEY` | _vacío_ | Si está, clasificación usa Claude. Si no, heurística. |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Modelo. Haiku es barato y suficiente para clasificar. |
| `DIGEST_ENABLED` | `false` | Activar digest diario. |
| `DIGEST_HOUR` | `8` | Hora local del envío. |
| `DIGEST_MINUTE` | `0` | Minuto. |
| `DIGEST_TZ` | `America/Argentina/Buenos_Aires` | Zona horaria IANA. |
| `DIGEST_CHAT_ID` | `0` | A qué chat mandar (`/id` te lo dice). |
| `WEB_UI_ENABLED` | `true` | Servir `/ui`. |

## Setup paso a paso

### 0. Conseguí tus IDs
- Hablale a [@userinfobot](https://t.me/userinfobot) → te da tu `user_id`.
- Andá a tu chat con `@ceroinbox_bot`, mandale `/id` después del primer deploy → te da tu `chat_id` (que para chat privado coincide con el user_id).

### 1. Subí a un repo Git privado
```bash
cd inboxzero/
git init && git add . && git commit -m "init: InboxZero v2"
# push a GitHub/GitLab privado
```

### 2. Deploy en Railway
1. [railway.app](https://railway.app) → "New Project" → "Deploy from GitHub repo".
2. Seleccioná el repo.
3. **Volumen persistente (importante)**: Settings → Volumes → mount path `/data`.
4. **Variables**:
   - `TELEGRAM_BOT_TOKEN`
   - `ALLOWED_USER_IDS=<tu_user_id>`
   - `SYNC_API_KEY=<openssl rand -hex 32>`
   - `DB_PATH=/data/inboxzero.db`
   - (opcional) `ANTHROPIC_API_KEY`
   - (opcional) `DIGEST_ENABLED=true`, `DIGEST_CHAT_ID=<tu_chat_id>`
5. Deploy. En logs deberías ver: `Bot de Telegram corriendo en modo polling.` + `Schedulers arrancados`.

### 3. Verificá

```bash
# health
curl https://TU-URL/healthz

# por TG
/start              # bienvenida
/id                 # tus ids
/idea probando v2   # captura
/recordar en 1m test   # se dispara en 1 min
/recordatorios      # debería listarlo
/digest             # forzar digest ahora
/stats              # contadores
```

### 4. Web UI

Visitá `https://TU-URL/ui` desde el browser. Pegá la `SYNC_API_KEY` y entrás. Podés:
- Editar texto/clasificación de cualquier captura.
- Marcar synced manualmente (útil si no tenés Mac al lado).
- Borrar capturas que sean ruido.
- Cancelar recordatorios.

### 5. Sync local en Mac

Ver [`sync/README.md`](sync/README.md). Resumen:

```bash
mkdir -p ~/inboxzero/sync
cp sync/* ~/inboxzero/sync/
cp sync/.env.example ~/inboxzero/sync/.env
$EDITOR ~/inboxzero/sync/.env

# probar
python3 ~/inboxzero/sync/sync_to_obsidian.py

# automatizar
$EDITOR sync/com.inboxzero.sync.plist
cp sync/com.inboxzero.sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.inboxzero.sync.plist
```

## Comandos del bot

| Comando | Acción |
|---|---|
| `/start`, `/help` | Bienvenida + lista de comandos |
| `/id` | Devuelve tu user_id y chat_id |
| `/stats` | Capturas pending/synced/total + reminders pending |
| `/idea <texto>` | Captura como idea |
| `/pedido <texto>` | Captura como pedido |
| `/tarea <texto>` | Captura como tarea |
| `/nota <texto>` | Captura como nota |
| `/recordar <duración> <texto>` | Programa recordatorio |
| `/recordatorios` | Lista pendientes con id |
| `/cancelar <id>` | Cancela un recordatorio |
| `/digest` | Pide el digest ahora |
| (cualquier texto) | Autoclasifica |

### Sintaxis de duración
- Relativa: `en 30m`, `en 2h`, `en 3 días`, `en 1 semana`
- Absoluta hoy: `hoy 18:00`, `hoy 6pm`
- Mañana: `mañana 9am`, `mañana 14:30`, `mañana` (default 9am)

## Endpoints HTTP

Todos requieren `X-Api-Key: <SYNC_API_KEY>`, salvo `/healthz`, `/`, y los de `/ui` (que usan cookie).

| Método | Path | Body | Devuelve |
|---|---|---|---|
| GET | `/healthz` | — | `{status, bot_running, config_errors, features}` |
| GET | `/pending?limit=500` | — | `{count, items}` |
| POST | `/mark-synced` | `{ids:[...]}` | `{updated}` |
| GET | `/stats` | — | `{pending, synced, total, reminders_pending}` |
| GET | `/reminders/unsynced?limit=200` | — | `{count, items}` |
| POST | `/reminders/mark-synced` | `{ids:[...]}` | `{updated}` |
| GET | `/ui` | — | HTML SPA |

## Formato de notas

### Capturas (`_Inbox/`, configurable con `INBOXZERO_SUBDIR`)

```yaml
---
source: telegram
type: tarea
captured_at: 2026-05-02T22:15:00
telegram_msg_id: 12345
chat_id: 67890
user_id: 11111
local_id: 42
status: new
tags: [inbox-zero, captura]
---
```

### Recordatorios (`_Inbox/`, configurable con `INBOXZERO_REMINDERS_SUBDIR`)

```yaml
---
source: telegram
type: recordatorio
reminder_status: fired
created_at: 2026-05-02T20:00:00
due_at: 2026-05-02T22:00:00+00:00
fired_at: 2026-05-02T22:00:01
local_id: 7
tags: [inbox-zero, recordatorio]
---
```

## Costos

- Railway free tier: ~$5/mes de crédito. Este servicio consume ~$1-3/mes.
- Telegram: gratis.
- Anthropic Claude haiku: ~$0.80/M input tokens. Clasificar 1000 mensajes ≈ $0.05.

## Seguridad

1. **Token expuesto en chat → rotar.** `@BotFather` → `/revoke` → `/token`.
2. **Whitelist por user_id** (`ALLOWED_USER_IDS`).
3. **API key para sync** (header `X-Api-Key`). Cookie HttpOnly para la UI web.
4. **Sin secrets en código**, todo por env vars en Railway.

## Roadmap (v3+)

- Comandos de acción real con OAuth: `/agendar` → Google Calendar, `/email` → Gmail.
- Conexión bidireccional con Obsidian: editar la nota local mueve el estado en SQLite.
- Multi-usuario: hoy es single-user con whitelist; con poco se vuelve multi-tenant.
- Búsqueda semántica sobre capturas (embeddings + LanceDB).
- Tareas recurrentes (`/recordar todos los lunes 9am ...`).

## Troubleshooting

**El bot no responde.**
- Logs en Railway: ¿`Bot de Telegram corriendo en modo polling.`?
- ¿`TELEGRAM_BOT_TOKEN` correcto? `curl https://api.telegram.org/bot<TOKEN>/getMe`.
- ¿Tu user_id está en `ALLOWED_USER_IDS`?

**Recordatorios no se disparan.**
- `/recordatorios` ¿los ve el bot? Si están listados, el scheduler corre.
- Logs: ¿`Reminders scheduler arrancado`?
- Verificá la zona horaria: `/recordar en 1m test` debería dispararse en 1 min.

**Digest no llega.**
- `DIGEST_ENABLED=true`?
- `DIGEST_CHAT_ID` correcto? `/id` te lo da.
- `DIGEST_TZ` válida? IANA name (ej: `America/Argentina/Buenos_Aires`, `Europe/Madrid`).

**Web UI no entra.**
- `WEB_UI_ENABLED=true`?
- ¿Estás pegando exacto la `SYNC_API_KEY`?
- Si Railway no es HTTPS la cookie no se setea como Secure — debería igual andar con `samesite=lax` y sin `secure`. Verificá la URL que usás.

**Clasificación con Claude no se usa.**
- `/healthz` debe mostrar `features.llm: true`.
- Si está en false, falta `ANTHROPIC_API_KEY`.
- Si los logs muestran `Claude API HTTP 401` → la key es inválida.
- Si muestra HTTP 429 → rate limit, no es bloqueante: cae a heurística.
