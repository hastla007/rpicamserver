#!/usr/bin/env bash
set -euo pipefail

REPO_URL_DEFAULT="https://github.com/rpicamserver/rpicamserver.git"
INSTALL_DIR="/opt/rpicamserver"
USE_APT=1
INSTALL_NGINX=1
INSTALL_SYSTEMD=1
NON_INTERACTIVE=0
BRANCH=""
VENV_PATH=""
NO_CLONE=0

usage() {
  cat <<USAGE
Usage: $0 [options]

Options:
  --install-dir DIR     Target directory (default: /opt/rpicamserver)
  --repo URL            Git repository to clone (default: ${REPO_URL_DEFAULT})
  --branch BRANCH       Git branch or tag to checkout
  --no-apt              Skip apt-get dependency installation
  --no-nginx            Skip Nginx installation and config copy
  --no-systemd          Do not install or start the systemd unit
  --non-interactive     Run without prompts (assume yes to defaults)
  --venv PATH           Use/create a virtualenv at PATH (default: INSTALL_DIR/.venv)
  --from-local          Copy the current working tree instead of cloning
  -h, --help            Show this help

Examples:
  $0 --non-interactive --no-nginx --install-dir /srv/rpicamserver
  $0 --repo https://github.com/example/rpicamserver.git --branch v1.2.0
USAGE
}

REPO_URL="$REPO_URL_DEFAULT"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir)
      INSTALL_DIR="$2"; shift 2;;
    --repo)
      REPO_URL="$2"; shift 2;;
    --branch)
      BRANCH="$2"; shift 2;;
    --no-apt)
      USE_APT=0; shift;;
    --no-nginx)
      INSTALL_NGINX=0; shift;;
    --no-systemd)
      INSTALL_SYSTEMD=0; shift;;
    --non-interactive|--yes)
      NON_INTERACTIVE=1; shift;;
    --venv)
      VENV_PATH="$2"; shift 2;;
    --from-local)
      NO_CLONE=1; shift;;
    -h|--help)
      usage; exit 0;;
    *)
      echo "Unknown option: $1" >&2; usage; exit 1;;
  esac
done

VENV_PATH=${VENV_PATH:-"$INSTALL_DIR/.venv"}

prompt_yes() {
  local msg="$1"
  if [[ $NON_INTERACTIVE -eq 1 ]]; then
    return 0
  fi
  read -r -p "$msg [y/N] " reply || true
  [[ "$reply" =~ ^[Yy]$ ]]
}

ensure_dir() {
  mkdir -p "$INSTALL_DIR"
}

maybe_apt_install() {
  if [[ $USE_APT -eq 0 ]]; then
    echo "Skipping apt-get install per user request"
    return
  fi
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "apt-get not found; skipping system package installation"
    return
  fi
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv git ${INSTALL_NGINX:+nginx}
}

sync_repo() {
  if [[ $NO_CLONE -eq 1 ]]; then
    echo "Copying current working tree to $INSTALL_DIR"
    if command -v rsync >/dev/null 2>&1; then
      rsync -a --exclude '.git' ./ "$INSTALL_DIR"/
    else
      tar -C . --exclude='.git' -cf - . | tar -C "$INSTALL_DIR" -xf -
    fi
    return
  fi

  if [[ -d "$INSTALL_DIR/.git" ]]; then
    echo "Updating existing repository in $INSTALL_DIR"
    git -C "$INSTALL_DIR" fetch --all
    git -C "$INSTALL_DIR" checkout ${BRANCH:-"$(git -C "$INSTALL_DIR" rev-parse --abbrev-ref HEAD)"}
    git -C "$INSTALL_DIR" pull --ff-only
    return
  fi

  if [[ -d "$INSTALL_DIR" && -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
    echo "Install directory $INSTALL_DIR exists and is not a git repo; remove it or choose --install-dir elsewhere." >&2
    exit 1
  fi

  echo "Cloning $REPO_URL into $INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
  if [[ -n "$BRANCH" ]]; then
    git -C "$INSTALL_DIR" checkout "$BRANCH"
  fi
}

setup_venv() {
  if [[ ! -d "$VENV_PATH" ]]; then
    python3 -m venv "$VENV_PATH"
  fi
  # shellcheck disable=SC1091
  source "$VENV_PATH/bin/activate"
  python3 -m pip install --upgrade pip
  python3 -m pip install -r "$INSTALL_DIR/requirements.txt"
}

install_systemd_unit() {
  if [[ $INSTALL_SYSTEMD -eq 0 ]]; then
    echo "Skipping systemd setup"
    return
  fi
  if [[ $EUID -ne 0 ]]; then
    echo "Systemd installation requires root; rerun with sudo or use --no-systemd"
    return
  fi
  local unit_src="$INSTALL_DIR/systemd/rpicamserver.service"
  local unit_dest="/etc/systemd/system/rpicamserver.service"
  if [[ ! -f "$unit_src" ]]; then
    echo "Systemd unit template not found at $unit_src"
    return
  fi
  sed "s#ExecStart=.*#ExecStart=$VENV_PATH/bin/uvicorn app:app --host 0.0.0.0 --port ${APP_PORT:-8000}#" "$unit_src" | sudo tee "$unit_dest" >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable --now rpicamserver
}

copy_nginx() {
  if [[ $INSTALL_NGINX -eq 0 ]]; then
    echo "Skipping Nginx copy"
    return
  fi
  if [[ ! -f "$INSTALL_DIR/nginx.cameras.conf" ]]; then
    echo "Generated nginx.cameras.conf not found; start the app once to generate it."
    return
  fi
  if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo to copy nginx configuration, or copy manually."
    return
  fi
  sudo cp "$INSTALL_DIR/nginx.cameras.conf" /etc/nginx/conf.d/cameras.conf
  sudo systemctl reload nginx
}

echo "Installing to $INSTALL_DIR"
ensure_dir
maybe_apt_install
sync_repo
setup_venv
install_systemd_unit
copy_nginx

echo "Installation complete. Activate the venv with: source $VENV_PATH/bin/activate"
if [[ $INSTALL_SYSTEMD -eq 0 ]]; then
  echo "Start the app manually with: $VENV_PATH/bin/uvicorn app:app --host 0.0.0.0 --port ${APP_PORT:-8000}"
fi
