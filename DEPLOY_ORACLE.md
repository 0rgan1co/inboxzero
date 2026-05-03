# Deploy en Oracle Cloud Always Free

VPS gratis para siempre con 4 ARM OCPUs + 24GB RAM + 200GB block storage.

## Paso 1 — Crear cuenta Oracle Cloud (~10 min)

1. https://cloud.oracle.com/free → "Start for free".
2. Te pide tarjeta de crédito **solo para verificación**. No se cobra mientras estés en Always Free.
3. Elegí región (preferí la más cercana: São Paulo, Querétaro, San Jose, Madrid).
4. Confirmá email y completá datos.

## Paso 2 — Crear la instance Ampere ARM

1. Compute → Instances → "Create Instance".
2. **Image**: Canonical Ubuntu 22.04 (ARM64). **Importante**: que sea ARM64, no amd64.
3. **Shape**: "Change shape" → "Ampere" → `VM.Standard.A1.Flex`.
4. **Configuración Always Free total**: 4 OCPUs + 24 GB RAM (podés usar todo o partir en menos).
5. **Networking**: deja la VCN default. Asignar IP pública = sí.
6. **SSH keys**: subí tu pubkey (la de tu Mac: `~/.ssh/id_ed25519.pub` o equivalente). Si no tenés, "Generate a key pair" y bajá la privada.
7. Boot volume: 200 GB (incluido en Always Free).
8. **Create**. Tarda 1-2 min.

⚠️ **Si te dice "Out of capacity"**: es común con A1.Flex. Soluciones:
- Esperá 5-30 min y retry.
- Cambiá región.
- Reducí a 2 OCPU + 12 GB (también Always Free).

## Paso 3 — Abrir el puerto 8000 en la VCN

Por default Oracle bloquea todo excepto SSH:

1. Networking → Virtual Cloud Networks → tu VCN → Security Lists → "Default Security List".
2. "Add Ingress Rule":
   - Source CIDR: `0.0.0.0/0`
   - IP Protocol: TCP
   - Destination Port Range: `8000`
3. Save.

## Paso 4 — Conectarte y deployar

Desde tu Mac:

```bash
ssh ubuntu@<IP-PÚBLICA>
```

Una vez adentro, corré el bootstrap:

```bash
curl -fsSL https://raw.githubusercontent.com/0rgan1co/inboxzero/main/bootstrap.sh | sudo bash
```

El script:
- Instala Docker
- Clona el repo en `/opt/inboxzero/`
- Crea `.env` desde el ejemplo
- Abre el puerto 8000 en iptables

## Paso 5 — Configurar `.env`

```bash
sudo nano /opt/inboxzero/.env
```

Pegá tus valores reales:
```bash
TELEGRAM_BOT_TOKEN=<token nuevo de @BotFather>
ALLOWED_USER_IDS=<tu_user_id>
SYNC_API_KEY=<openssl rand -hex 32>
DB_PATH=/data/inboxzero.db
PORT=8000

# Opcionales
ANTHROPIC_API_KEY=
DIGEST_ENABLED=true
DIGEST_HOUR=8
DIGEST_CHAT_ID=<tu_chat_id>
DIGEST_TZ=America/Argentina/Buenos_Aires
WEB_UI_ENABLED=true
```

## Paso 6 — Levantar el container

```bash
cd /opt/inboxzero
sudo docker compose up -d --build
```

Verificar:
```bash
sudo docker compose logs -f
# Buscás: "Bot de Telegram corriendo en modo polling."
```

## Paso 7 — Probar

Desde tu navegador o curl:
```bash
curl http://<IP-PÚBLICA>:8000/healthz
```

En Telegram:
- `/start` al bot
- `/idea probando desde Oracle`
- `/recordar en 1m test`

## Paso 8 — Sync local Mac → vault

Igual que antes (ver `sync/README.md`), pero apuntando a la nueva URL:

```bash
INBOXZERO_API_URL=http://<IP-PÚBLICA>:8000
INBOXZERO_API_KEY=<misma SYNC_API_KEY>
OBSIDIAN_VAULT_PATH=/Users/roldanjorgex/second-brain
```

## Mantenimiento

**Updates de código**:
```bash
cd /opt/inboxzero
sudo git pull
sudo docker compose up -d --build
```

**Ver logs**:
```bash
sudo docker compose logs -f --tail 100
```

**Backup de SQLite** (la DB vive en el volumen `inboxzero_data`):
```bash
sudo docker run --rm -v inboxzero_inboxzero_data:/data -v $(pwd):/backup alpine \
    cp /data/inboxzero.db /backup/inboxzero-$(date +%Y%m%d).db
```

## Hardening recomendado (después que ande)

1. **HTTPS con Caddy o Traefik** + dominio propio (gratis con DuckDNS o cualquier dominio que tengas).
2. **fail2ban** para SSH brute force.
3. **ufw** en lugar de iptables crudo (más fácil de mantener).
4. **Disable password SSH login** (solo keys).
5. **Auto-updates de Ubuntu**: `unattended-upgrades`.
