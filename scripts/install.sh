#!/usr/bin/env bash
# ============================================================================
# ARC Agent Framework — Debian/Ubuntu Install Script
#
# Usage:
#   sudo bash scripts/install.sh
#
# What this script does:
#   1. Installs system dependencies (Python 3.11+, git, curl)
#   2. Installs Ollama and pulls recommended models
#   3. Creates a dedicated 'arc' system user
#   4. Clones the repository to /opt/arc
#   5. Creates a Python virtual environment and installs dependencies
#   6. Sets up .env from .env.example
#   7. Installs and enables the systemd service
#
# This script is idempotent — safe to re-run.
# ============================================================================

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────

ARC_REPO="https://github.com/BitsofJeremy/my_agent_arc.git"
INSTALL_DIR="/opt/arc"
ARC_USER="arc"
ARC_GROUP="arc"
OLLAMA_MODEL="minimax-m2.5"
EMBED_MODEL="nomic-embed-text"

# ── Colours ────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[ARC]${NC} $*"; }
warn()  { echo -e "${YELLOW}[ARC]${NC} $*"; }
error() { echo -e "${RED}[ARC]${NC} $*" >&2; }

# ── Preflight ──────────────────────────────────────────────────

if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (use sudo)."
    exit 1
fi

info "Starting ARC installation..."

# ── 1. System dependencies ─────────────────────────────────────

info "Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl >/dev/null

# Check Python version
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 11 ]]; then
    warn "Python $PYTHON_VERSION found — ARC requires 3.11+."
    info "Installing Python 3.11 from deadsnakes PPA..."
    apt-get install -y -qq software-properties-common >/dev/null
    add-apt-repository -y ppa:deadsnakes/ppa >/dev/null 2>&1
    apt-get update -qq
    apt-get install -y -qq python3.11 python3.11-venv python3.11-dev >/dev/null
    PYTHON_BIN="python3.11"
else
    PYTHON_BIN="python3"
    info "Python $PYTHON_VERSION — OK"
fi

# ── 2. Ollama ──────────────────────────────────────────────────

if command -v ollama &>/dev/null; then
    info "Ollama already installed — $(ollama --version)"
else
    info "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

# Ensure Ollama service is running
if systemctl is-active --quiet ollama 2>/dev/null; then
    info "Ollama service is running"
else
    info "Starting Ollama service..."
    systemctl enable ollama 2>/dev/null || true
    systemctl start ollama 2>/dev/null || true
    sleep 3
fi

info "Pulling models (this may take a while)..."
ollama pull "$OLLAMA_MODEL" || warn "Failed to pull $OLLAMA_MODEL — pull it manually later"
ollama pull "$EMBED_MODEL"  || warn "Failed to pull $EMBED_MODEL — pull it manually later"

# ── 3. System user ─────────────────────────────────────────────

if id "$ARC_USER" &>/dev/null; then
    info "User '$ARC_USER' already exists"
else
    info "Creating system user '$ARC_USER'..."
    useradd --system --shell /usr/sbin/nologin --home-dir "$INSTALL_DIR" \
        --create-home "$ARC_USER"
fi

# ── 4. Clone / update repository ──────────────────────────────

if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Repository exists — pulling latest..."
    cd "$INSTALL_DIR"
    sudo -u "$ARC_USER" git pull --ff-only || warn "Git pull failed — using existing code"
else
    info "Cloning repository to $INSTALL_DIR..."
    if [[ -d "$INSTALL_DIR" ]]; then
        # Directory exists but isn't a git repo — back it up
        mv "$INSTALL_DIR" "${INSTALL_DIR}.bak.$(date +%s)"
    fi
    git clone "$ARC_REPO" "$INSTALL_DIR"
    chown -R "$ARC_USER:$ARC_GROUP" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# ── 5. Python virtual environment ─────────────────────────────

if [[ -d "$INSTALL_DIR/.venv" ]]; then
    info "Virtual environment exists"
else
    info "Creating Python virtual environment..."
    sudo -u "$ARC_USER" "$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
fi

info "Installing Python dependencies..."
sudo -u "$ARC_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet \
    --upgrade pip
sudo -u "$ARC_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet \
    -r "$INSTALL_DIR/requirements.txt"

# ── 6. Environment configuration ──────────────────────────────

if [[ -f "$INSTALL_DIR/.env" ]]; then
    info ".env already exists — not overwriting"
else
    info "Creating .env from .env.example..."
    sudo -u "$ARC_USER" cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    warn "Edit $INSTALL_DIR/.env to configure your Telegram token and preferences"
fi

# Ensure data directory exists and is writable
sudo -u "$ARC_USER" mkdir -p "$INSTALL_DIR/data"

# ── 7. systemd service ────────────────────────────────────────

info "Installing systemd service..."
cp "$INSTALL_DIR/scripts/arc.service" /etc/systemd/system/arc.service
systemctl daemon-reload
systemctl enable arc

info ""
info "════════════════════════════════════════════════════════════"
info "  ARC installation complete!"
info "════════════════════════════════════════════════════════════"
info ""
info "  Install directory:  $INSTALL_DIR"
info "  Config file:        $INSTALL_DIR/.env"
info "  Service name:       arc"
info ""
info "  Next steps:"
info "    1. Edit the config:    sudo -u $ARC_USER nano $INSTALL_DIR/.env"
info "    2. Start the service:  sudo systemctl start arc"
info "    3. View logs:          sudo journalctl -u arc -f"
info "    4. Admin dashboard:    http://localhost:8080"
info ""
info "  To add a Telegram bot token:"
info "    - Get a token from @BotFather on Telegram"
info "    - Set ARC_TELEGRAM_BOT_TOKEN in $INSTALL_DIR/.env"
info "    - Restart: sudo systemctl restart arc"
info ""
