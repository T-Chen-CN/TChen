#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/clash-socks-server-ui"
SERVICE_NAME="clash-socks-webui"
APP_USER="clashui"

if [[ $EUID -ne 0 ]]; then
  echo "请使用 sudo 运行此脚本。"
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip curl ca-certificates

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

mkdir -p "$APP_DIR"
tar \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='data' \
  --exclude='runtime' \
  --exclude='logs' \
  -cf - . | tar -xf - -C "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [[ ! -f "$APP_DIR/.env" ]]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
fi

cp "$APP_DIR/systemd/$SERVICE_NAME.service" "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

cat <<EOF
安装完成。

下一步：
1. 编辑 $APP_DIR/.env
2. 执行 systemctl start $SERVICE_NAME
3. 执行 systemctl status $SERVICE_NAME
4. 在防火墙放通 WebUI 端口和 Socks5 端口
EOF
