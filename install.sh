#!/bin/bash
set -e

install_packages() {
  echo "Updating package list and installing dependencies…"
  sudo apt-get update
  sudo apt-get install -y python3-opencv python3-pip git nginx
}

clone_repo() {
  echo "Cloning rpicamserver to /opt/rpicamserver…"
  sudo mkdir -p /opt
  sudo git clone https://github.com/hastla007/rpicamserver.git /opt/rpicamserver
}

install_python_deps() {
  echo "Installing Python packages…"
  sudo pip3 install -r /opt/rpicamserver/requirements.txt
}

setup_cameras_json() {
  if [ ! -f /opt/rpicamserver/cameras.json ]; then
    sudo cp /opt/rpicamserver/cameras.example.json /opt/rpicamserver/cameras.json
    echo "Created cameras.json from example."
  fi
  echo "Detecting available cameras…"
  sudo python3 /opt/rpicamserver/cli.py devices
  echo "You can edit /opt/rpicamserver/cameras.json now to assign ports and names."
  read -p "Edit cameras.json now? [y/N] " ans
  if [[ $ans =~ ^[Yy]$ ]]; then
    sudo nano /opt/rpicamserver/cameras.json
  fi
}

setup_systemd_service() {
  read -p "Install systemd service so the server starts on boot? [y/N] " ans
  if [[ $ans =~ ^[Yy]$ ]]; then
    sudo cp /opt/rpicamserver/systemd/rpicamserver.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now rpicamserver
    echo "Service installed and started."
  fi
}

start_server() {
  echo "Starting server manually…"
  cd /opt/rpicamserver
  uvicorn app:app --host 0.0.0.0 --port 8000 &
  echo "Server started on http://<your‑pi>:8000"
}

configure_nginx() {
  read -p "Generate and install nginx.cameras.conf? [y/N] " ans
  if [[ $ans =~ ^[Yy]$ ]]; then
    sudo cp /opt/rpicamserver/nginx.cameras.conf /etc/nginx/conf.d/cameras.conf
    sudo systemctl reload nginx
    echo "Nginx reloaded; camera feeds available on ports 8081+"
  fi
}

main() {
  install_packages
  clone_repo
  install_python_deps
  setup_cameras_json
  start_server
  configure_nginx
  setup_systemd_service
}

main "$@"
