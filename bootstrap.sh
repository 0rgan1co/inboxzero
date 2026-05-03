#!/usr/bin/env bash
# Bootstrap para Oracle Cloud Ampere (Ubuntu 22.04+ ARM64).
# Instala Docker, clona el repo, levanta el bot.
#
# Uso:
#   curl -fsSL https://raw.githubusercontent.com/0rgan1co/inboxzero/main/bootstrap.sh | sudo bash
# o:
#   ssh ubuntu@<IP> "curl -fsSL https://raw.githubusercontent.com/0rgan1co/inboxzero/main/bootstrap.sh | sudo bash"
#
# Después editás /opt/inboxzero/.env con tus secrets y reiniciás el container:
#   cd /opt/inboxzero && sudo docker compose up -d

set -euo pipefail

REPO_URL="https://github.com/0rgan1co/inboxzero.git"
DEST="/opt/inboxzero"

log() { echo -e "\n\033[1;36m→ $*\033[0m"; }

if [[ $EUID -ne 0 ]]; then
    echo "Este script requiere sudo / root."
    exit 1
fi

log "Actualizando paquetes..."
apt-get update -y
apt-get install -y ca-certificates curl gnupg git

log "Instalando Docker (si falta)..."
if ! command -v docker &>/dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    UBUNTU_CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $UBUNTU_CODENAME stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
    usermod -aG docker ubuntu || true
else
    echo "Docker ya está instalado."
fi

log "Clonando el repo en $DEST..."
if [[ -d "$DEST/.git" ]]; then
    git -C "$DEST" pull --ff-only
else
    git clone "$REPO_URL" "$DEST"
fi

log "Abriendo puerto 8000 en el firewall (iptables)..."
# Oracle viene con iptables muy cerrado por default. Insertamos la regla y la persistimos.
iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT || true
mkdir -p /etc/iptables
iptables-save > /etc/iptables/rules.v4 || true
# Persistencia con netfilter-persistent (si está)
if command -v netfilter-persistent &>/dev/null; then
    netfilter-persistent save || true
fi

if [[ ! -f "$DEST/.env" ]]; then
    log "Creando .env desde .env.example. EDITALO antes de levantar el container."
    cp "$DEST/.env.example" "$DEST/.env"
    chmod 600 "$DEST/.env"
    echo
    echo "==============================================================="
    echo "  PRÓXIMO PASO MANUAL:"
    echo "    1. Editá $DEST/.env con tus secrets reales:"
    echo "         TELEGRAM_BOT_TOKEN, ALLOWED_USER_IDS, SYNC_API_KEY, etc."
    echo "    2. Levantá el bot:"
    echo "         cd $DEST && docker compose up -d"
    echo "    3. Logs:"
    echo "         docker compose logs -f"
    echo "==============================================================="
else
    log "Ya existe .env, no lo toco. Levantando el container..."
    cd "$DEST"
    docker compose up -d --build
    echo
    docker compose ps
fi

log "Listo. Si es primera vuelta editá .env y corré 'docker compose up -d'."
