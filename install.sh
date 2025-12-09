#!/bin/bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: install.sh [options]

Options:
  --dir PATH          Install or update the repo at PATH (default: /opt/rpicamserver)
  --yes, -y           Run non-interactively, accepting defaults to prompts
  --with-nginx        Install and configure Nginx for per-camera ports
  --no-nginx          Skip Nginx installation and configuration
  --with-systemd      Install and start the systemd service
  --no-systemd        Skip systemd installation
  --no-apt            Skip apt-get package installation
  --help              Show this help message

Environment variables:
  APP_PORT            Port for the FastAPI control plane (default: 8000)
  SERVICE_USER        User to run the service as (default: current user)
EOF
}

ASSUME_YES=false
INSTALL_DIR="/opt/rpicamserver"
INSTALL_NGINX="ask"
INSTALL_SYSTEMD="ask"
SKIP_APT=false
APP_PORT="${APP_PORT:-8000}"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$(whoami)}}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)
      INSTALL_DIR="$2"
      shift 2
      ;;
    --yes|-y)
      ASSUME_YES=true
      shift
      ;;
    --with-nginx)
      INSTALL_NGINX="yes"
      shift
      ;;
    --no-nginx)
      INSTALL_NGINX="no"
      shift
      ;;
    --with-systemd)
      INSTALL_SYSTEMD="yes"
      shift
      ;;
    --no-systemd)
      INSTALL_SYSTEMD="no"
      shift
      ;;
    --no-apt)
      SKIP_APT=true
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

ask_yes_no() {
  local prompt="$1" default="$2" reply

  if [[ "$default" == "yes" ]]; then
    prompt+=" [Y/n] "
  else
    prompt+=" [y/N] "
  fi

  if [[ "$ASSUME_YES" == true ]]; then
    [[ "$default" == "yes" ]] && return 0 || return 1
  fi

  read -r -p "$prompt" reply
  case "$reply" in
    [Yy]*) return 0 ;;
    [Nn]*) return 1 ;;
    "" ) [[ "$default" == "yes" ]] && return 0 || return 1 ;;
    *) return 1 ;;
  esac
}

install_packages() {
  local packages=(python3-opencv python3-pip python3-venv git)
  if should_install_nginx; then
    packages+=(nginx)
  fi

  if [[ "$SKIP_APT" == true ]]; then
    echo "Skipping apt-get as requested; ensure dependencies are installed."
    return
  fi

  if ! command -v apt-get >/dev/null 2>&1; then
    echo "apt-get not found; please install system dependencies manually."
    return
  fi

  echo "Updating package list and installing dependencies…"
  sudo apt-get update
  sudo apt-get install -y "${packages[@]}"
}

ensure_repo() {
  echo "Ensuring repository at $INSTALL_DIR…"
  sudo mkdir -p "$INSTALL_DIR"

  if [[ -d "$INSTALL_DIR/.git" ]]; then
    echo "Existing clone detected; pulling latest changes…"
    sudo git -C "$INSTALL_DIR" fetch --all
    current_branch=$(sudo git -C "$INSTALL_DIR" rev-parse --abbrev-ref HEAD)
    sudo git -C "$INSTALL_DIR" reset --hard "origin/${current_branch}"
  elif [[ -d "$INSTALL_DIR" && -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
    echo "Directory $INSTALL_DIR exists and is not empty. Use --dir to choose a different path or clear it before running."
    exit 1
  else
    sudo git clone https://github.com/hastla007/rpicamserver.git "$INSTALL_DIR"
  fi
}

install_python_deps() {
  echo "Creating virtual environment in $INSTALL_DIR/.venv…"
  sudo python3 -m venv "$INSTALL_DIR/.venv"
  sudo "$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
  sudo "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
}

prepare_config() {
  if [[ ! -f "$INSTALL_DIR/cameras.json" ]]; then
    sudo cp "$INSTALL_DIR/cameras.example.json" "$INSTALL_DIR/cameras.json"
    echo "Created cameras.json from example."
  fi

  echo "Detecting available cameras (non-interactive)…"
  sudo "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/cli.py" devices || true
  echo "Edit $INSTALL_DIR/cameras.json to assign ports, names, and auth credentials."
}

write_systemd_service() {
  local service_path="/etc/systemd/system/rpicamserver.service"
  sudo tee "$service_path" >/dev/null <<EOF
[Unit]
Description=Raspberry Pi Camera Server
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
Environment=APP_PORT=$APP_PORT
ExecStart=$INSTALL_DIR/.venv/bin/uvicorn app:app --host 0.0.0.0 --port ${APP_PORT}
Restart=on-failure
User=$SERVICE_USER
Group=$SERVICE_USER

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  sudo systemctl enable --now rpicamserver
  echo "Systemd service installed and started."
}

should_install_nginx() {
  case "$INSTALL_NGINX" in
    yes) return 0 ;;
    no) return 1 ;;
  esac

  if ask_yes_no "Install and reload Nginx to expose per-camera ports?" "no"; then
    INSTALL_NGINX="yes"
    return 0
  fi

  INSTALL_NGINX="no"
  return 1
}

configure_nginx() {
  if ! should_install_nginx; then
    echo "Skipping Nginx installation and configuration."
    return
  fi

  echo "Copying nginx.cameras.conf to /etc/nginx/conf.d/cameras.conf…"
  sudo cp "$INSTALL_DIR/nginx.cameras.conf" /etc/nginx/conf.d/cameras.conf
  sudo systemctl reload nginx
  echo "Nginx reloaded; camera feeds available on ports 8081+."
}

should_install_systemd() {
  case "$INSTALL_SYSTEMD" in
    yes) return 0 ;;
    no) return 1 ;;
  esac

  ask_yes_no "Install systemd service so the server starts on boot?" "yes"
}

main() {
  install_packages
  ensure_repo
  install_python_deps
  prepare_config

  if should_install_systemd; then
    write_systemd_service
  else
    echo "Systemd installation skipped. Start the app manually with:"
    echo "  $INSTALL_DIR/.venv/bin/uvicorn app:app --host 0.0.0.0 --port ${APP_PORT}"
  fi

  configure_nginx
  echo "Installation complete."
}

main "$@"
