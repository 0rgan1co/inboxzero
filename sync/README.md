# Sync local — InboxZero → Obsidian

Este script vive en tu Mac. Cada vez que corre, jala los mensajes pendientes del
bot (que está 24/7 en Railway) y los escribe como notas markdown dentro del
vault de Obsidian.

## Requisitos

- Python 3.9+ (macOS trae 3.9 de fábrica; está bien).
- Sin dependencias externas: el script usa solo `urllib` de la stdlib.

## Setup rápido

```bash
# 1. Copiá el script a una carpeta estable en tu Mac
mkdir -p ~/inboxzero/sync
cp sync_to_obsidian.py ~/inboxzero/sync/
cp .env.example ~/inboxzero/sync/.env

# 2. Editá .env con tus valores reales
$EDITOR ~/inboxzero/sync/.env

# 3. Probalo a mano
python3 ~/inboxzero/sync/sync_to_obsidian.py
```

## Automatizar con launchd (macOS)

Para que corra cada 5 min mientras la Mac está prendida:

```bash
# 1. Editá com.inboxzero.sync.plist (rutas y env vars)
# 2. Copialo a LaunchAgents
cp com.inboxzero.sync.plist ~/Library/LaunchAgents/

# 3. Cargalo
launchctl load ~/Library/LaunchAgents/com.inboxzero.sync.plist

# Ver si corre
launchctl list | grep inboxzero

# Logs
tail -f ~/Library/Logs/inboxzero-sync.log
tail -f ~/Library/Logs/inboxzero-sync.err.log

# Para descargarlo
launchctl unload ~/Library/LaunchAgents/com.inboxzero.sync.plist
```

## Variables de entorno

| Variable | Descripción |
|---|---|
| `INBOXZERO_API_URL` | URL del bot en Railway, sin trailing slash. Ej: `https://inboxzero.up.railway.app` |
| `INBOXZERO_API_KEY` | El `SYNC_API_KEY` que pusiste en Railway. |
| `OBSIDIAN_VAULT_PATH` | Path absoluto a tu vault. |
| `INBOXZERO_SUBDIR` | Carpeta dentro del vault para capturas. Default: `_Inbox`. |
| `INBOXZERO_REMINDERS_SUBDIR` | Carpeta para recordatorios. Default: `_Inbox` (mismo). |

## Qué pasa cuando corre

1. Pega `GET /pending` al bot.
2. Por cada mensaje recibido, escribe `_Inbox/YYYY-MM-DD-HHMMSS-<tipo>-<slug>.md` con frontmatter.
3. Pega `POST /mark-synced` con los IDs escritos.
4. Si algo falla a mitad, los mensajes que NO se escribieron quedan como `pending` y se vuelven a intentar la próxima.

## Idempotencia

- El bot NO borra mensajes después del sync, los marca `synced`. Quedan ahí hasta que vos los borres a mano.
- El script no reescribe notas: solo crea las nuevas que están `pending`.
