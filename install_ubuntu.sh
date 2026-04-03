#!/usr/bin/env bash
set -euo pipefail
umask 027

APP_DIR="/opt/clash-socks-server-ui"
SERVICE_NAME="clash-socks-webui"
APP_USER="clashui"
PUBLIC_HTTP_PORT="${CSG_PUBLIC_PORT:-18080}"
ENABLE_PORT_80="${CSG_ENABLE_PORT_80:-1}"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="${CSG_INTERNAL_PORT:-18081}"
DEFAULT_ALLOWED_C_PORTS="${CSG_DEFAULT_ALLOWED_C_PORTS:-10808-10999}"
ADMIN_USERNAME="${CSG_ADMIN_USERNAME:-admin}"
MIHOMO_NOTICE=""
DETECTION_WARNING=""

if [[ $EUID -ne 0 ]]; then
  echo "Please run this installer with sudo." >&2
  exit 1
fi

if [[ ! -r /etc/os-release ]]; then
  echo "Unable to detect the current Linux distribution." >&2
  exit 1
fi

. /etc/os-release
if [[ "${ID:-}" != "ubuntu" ]]; then
  echo "This installer currently supports Ubuntu only." >&2
  exit 1
fi

if [[ "$PUBLIC_HTTP_PORT" == "$BACKEND_PORT" ]]; then
  echo "CSG_PUBLIC_PORT and CSG_INTERNAL_PORT must use different ports." >&2
  exit 1
fi

random_token() {
  python3 - "$1" <<'PY'
import secrets
import sys

length = int(sys.argv[1])
print(secrets.token_urlsafe(length)[:length])
PY
}

run_as_app_user() {
  runuser -u "$APP_USER" -- "$@"
}

get_env_value() {
  local file="$1"
  local key="$2"
  local line
  line="$(grep -E "^${key}=" "$file" 2>/dev/null | tail -n 1 || true)"
  printf '%s' "${line#*=}"
}

set_env_value() {
  local file="$1"
  local key="$2"
  local value="$3"
  local temp_file
  temp_file="$(mktemp)"
  if [[ -f "$file" ]]; then
    awk -F= -v key="$key" -v value="$value" '
      BEGIN { written = 0 }
      $1 == key { print key "=" value; written = 1; next }
      { print }
      END { if (!written) print key "=" value }
    ' "$file" > "$temp_file"
  else
    printf '%s=%s\n' "$key" "$value" > "$temp_file"
  fi
  cat "$temp_file" > "$file"
  rm -f "$temp_file"
}

looks_like_ipv4() {
  local value="$1"
  [[ "$value" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]
}

is_private_or_loopback_host() {
  local value="$1"
  python3 - "$value" <<'PY'
import ipaddress
import sys

value = sys.argv[1].strip()
if value.startswith("[") and value.endswith("]"):
    value = value[1:-1]

try:
    ip = ipaddress.ip_address(value)
except ValueError:
    raise SystemExit(1)

raise SystemExit(0 if (ip.is_private or ip.is_loopback or ip.is_link_local) else 1)
PY
}

format_http_host() {
  local host="$1"
  if [[ "$host" == *:* && "$host" != \[*\] ]]; then
    printf '[%s]\n' "$host"
    return
  fi
  printf '%s\n' "$host"
}

build_http_url() {
  local host="$1"
  local port="$2"
  local formatted_host
  formatted_host="$(format_http_host "$host")"
  if [[ "$port" == "80" ]]; then
    printf 'http://%s/\n' "$formatted_host"
    return
  fi
  printf 'http://%s:%s/\n' "$formatted_host" "$port"
}

detect_public_host() {
  local configured="${CSG_PUBLIC_HOST:-}"
  local candidate=""
  if [[ -n "$configured" ]]; then
    printf '%s\n' "$configured"
    return
  fi

  for source in \
    "https://api.ipify.org" \
    "https://ipv4.icanhazip.com" \
    "https://ifconfig.me/ip"
  do
    candidate="$(curl -fsSL --max-time 8 "$source" 2>/dev/null | tr -d '[:space:]' || true)"
    if looks_like_ipv4 "$candidate"; then
      printf '%s\n' "$candidate"
      return
    fi
  done

  candidate="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  if [[ -n "$candidate" ]]; then
    printf '%s\n' "$candidate"
    return
  fi

  printf '127.0.0.1\n'
}

wait_for_http() {
  local url="$1"
  local label="$2"
  local attempt
  for attempt in $(seq 1 60); do
    if curl -fsS -o /dev/null "$url"; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for ${label}: ${url}" >&2
  return 1
}

write_default_env() {
  local env_path="$1"
  local public_host="$2"
  local base_url="$3"
  local admin_password="${CSG_ADMIN_PASSWORD:-$(random_token 20)}"
  local session_secret="${CSG_SESSION_SECRET:-$(random_token 32)}"

  cat > "$env_path" <<EOF
CSG_HOST=${BACKEND_HOST}
CSG_PORT=${BACKEND_PORT}
CSG_APP_NAME=Clash Socks Server UI
CSG_ADMIN_USERNAME=${ADMIN_USERNAME}
CSG_ADMIN_PASSWORD=${admin_password}
CSG_SESSION_SECRET=${session_secret}
CSG_BASE_URL=${base_url}
CSG_ENABLE_DOCS=false
CSG_TEST_URL=https://www.gstatic.com/generate_204
CSG_TEST_TIMEOUT_MS=5000
CSG_DEFAULT_EXPORT_HOST=${public_host}
CSG_DEFAULT_ALLOWED_C_PORTS=${DEFAULT_ALLOWED_C_PORTS}
EOF
}

sync_managed_env() {
  local env_path="$1"
  local public_host="$2"
  local base_url="$3"
  local admin_password
  local session_secret
  local current_base_url
  local current_export_host

  set_env_value "$env_path" "CSG_HOST" "$BACKEND_HOST"
  set_env_value "$env_path" "CSG_PORT" "$BACKEND_PORT"
  set_env_value "$env_path" "CSG_ENABLE_DOCS" "false"

  if [[ -z "$(get_env_value "$env_path" "CSG_APP_NAME")" ]]; then
    set_env_value "$env_path" "CSG_APP_NAME" "Clash Socks Server UI"
  fi
  if [[ -z "$(get_env_value "$env_path" "CSG_ADMIN_USERNAME")" ]]; then
    set_env_value "$env_path" "CSG_ADMIN_USERNAME" "$ADMIN_USERNAME"
  fi

  admin_password="$(get_env_value "$env_path" "CSG_ADMIN_PASSWORD")"
  if [[ -z "$admin_password" || "$admin_password" == "change-me-now" ]]; then
    set_env_value "$env_path" "CSG_ADMIN_PASSWORD" "${CSG_ADMIN_PASSWORD:-$(random_token 20)}"
  fi

  session_secret="$(get_env_value "$env_path" "CSG_SESSION_SECRET")"
  if [[ -z "$session_secret" || "$session_secret" == "change-me-session-secret" ]]; then
    set_env_value "$env_path" "CSG_SESSION_SECRET" "${CSG_SESSION_SECRET:-$(random_token 32)}"
  fi

  current_base_url="$(get_env_value "$env_path" "CSG_BASE_URL")"
  if [[ -z "$current_base_url" || "$current_base_url" == http://127.0.0.1* || "$current_base_url" == http://0.0.0.0* ]]; then
    set_env_value "$env_path" "CSG_BASE_URL" "$base_url"
  fi

  current_export_host="$(get_env_value "$env_path" "CSG_DEFAULT_EXPORT_HOST")"
  if [[ -z "$current_export_host" || "$current_export_host" == "127.0.0.1" || "$current_export_host" == "0.0.0.0" ]]; then
    set_env_value "$env_path" "CSG_DEFAULT_EXPORT_HOST" "$public_host"
  fi

  if [[ -z "$(get_env_value "$env_path" "CSG_DEFAULT_ALLOWED_C_PORTS")" ]]; then
    set_env_value "$env_path" "CSG_DEFAULT_ALLOWED_C_PORTS" "$DEFAULT_ALLOWED_C_PORTS"
  fi
}

write_nginx_config() {
  local config_path="/etc/nginx/sites-available/${SERVICE_NAME}.conf"
  {
    echo "server {"
    echo "    listen ${PUBLIC_HTTP_PORT} default_server;"
    echo "    listen [::]:${PUBLIC_HTTP_PORT} default_server;"
    if [[ "$ENABLE_PORT_80" == "1" && "$PUBLIC_HTTP_PORT" != "80" ]]; then
      echo "    listen 80;"
      echo "    listen [::]:80;"
    fi
    echo "    server_name _;"
    echo "    client_max_body_size 16m;"
    echo
    echo "    location / {"
    echo "        proxy_pass http://${BACKEND_HOST}:${BACKEND_PORT};"
    echo "        proxy_http_version 1.1;"
    echo "        proxy_set_header Host \$host;"
    echo "        proxy_set_header X-Real-IP \$remote_addr;"
    echo "        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;"
    echo "        proxy_set_header X-Forwarded-Proto \$scheme;"
    echo "        proxy_set_header Upgrade \$http_upgrade;"
    echo '        proxy_set_header Connection "upgrade";'
    echo "    }"
    echo "}"
  } > "$config_path"

  rm -f /etc/nginx/sites-enabled/default
  ln -sfn "$config_path" "/etc/nginx/sites-enabled/${SERVICE_NAME}.conf"
  nginx -t
}

initialize_app_state() {
  run_as_app_user bash -lc "cd '$APP_DIR' && '$APP_DIR/.venv/bin/python' -c \"from app.gateway_multi import load_settings; settings = load_settings(); print(settings.export_host)\""

  if ! run_as_app_user bash -lc "cd '$APP_DIR' && '$APP_DIR/.venv/bin/python' -c \"from app.gateway_multi import ensure_mihomo; print(ensure_mihomo())\""; then
    MIHOMO_NOTICE="mihomo was not preinstalled automatically. You can install it later from the UI."
  fi
}

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip curl ca-certificates nginx

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

install -d -m 750 -o "$APP_USER" -g "$APP_USER" "$APP_DIR"
tar \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='data' \
  --exclude='runtime' \
  --exclude='logs' \
  -cf - . | tar -xf - -C "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

if [[ ! -d "$APP_DIR/.venv" ]]; then
  run_as_app_user python3 -m venv "$APP_DIR/.venv"
fi
run_as_app_user "$APP_DIR/.venv/bin/pip" install --upgrade pip
run_as_app_user "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

PUBLIC_HOST="$(detect_public_host)"
PUBLIC_HTTP_URL="$(build_http_url "$PUBLIC_HOST" "$PUBLIC_HTTP_PORT")"
BASE_URL="${CSG_BASE_URL_OVERRIDE:-${PUBLIC_HTTP_URL%/}}"
ENV_PATH="$APP_DIR/.env"

if is_private_or_loopback_host "$PUBLIC_HOST"; then
  DETECTION_WARNING="Detected export host ${PUBLIC_HOST}, which looks like a private or loopback address. If this server has a different public IP, pass CSG_PUBLIC_HOST during installation or update the export host in the WebUI after deployment."
fi

if [[ ! -f "$ENV_PATH" ]]; then
  write_default_env "$ENV_PATH" "$PUBLIC_HOST" "$BASE_URL"
fi
sync_managed_env "$ENV_PATH" "$PUBLIC_HOST" "$BASE_URL"

chown "$APP_USER:$APP_USER" "$ENV_PATH"
chmod 640 "$ENV_PATH"
install -d -m 750 -o "$APP_USER" -g "$APP_USER" "$APP_DIR/data" "$APP_DIR/runtime" "$APP_DIR/logs"

initialize_app_state

cp "$APP_DIR/systemd/$SERVICE_NAME.service" "/etc/systemd/system/$SERVICE_NAME.service"
chmod 644 "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
wait_for_http "http://${BACKEND_HOST}:${BACKEND_PORT}/login" "backend service"

write_nginx_config
systemctl enable nginx
systemctl restart nginx
wait_for_http "http://127.0.0.1:${PUBLIC_HTTP_PORT}/login" "nginx proxy"

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "^Status: active"; then
  ufw allow "${PUBLIC_HTTP_PORT}/tcp" >/dev/null 2>&1 || true
  if [[ "$ENABLE_PORT_80" == "1" && "$PUBLIC_HTTP_PORT" != "80" ]]; then
    ufw allow "80/tcp" >/dev/null 2>&1 || true
  fi
fi

ADMIN_PASSWORD="$(get_env_value "$ENV_PATH" "CSG_ADMIN_PASSWORD")"

cat <<EOF

Deployment completed.

WebUI URLs:
- ${PUBLIC_HTTP_URL}
EOF

if [[ "$ENABLE_PORT_80" == "1" && "$PUBLIC_HTTP_PORT" != "80" ]]; then
  cat <<EOF
- $(build_http_url "$PUBLIC_HOST" "80")
EOF
fi

cat <<EOF

Admin login:
- username: ${ADMIN_USERNAME}
- password: ${ADMIN_PASSWORD}

What is already prepared:
- the app now runs behind nginx
- uvicorn only listens on ${BACKEND_HOST}:${BACKEND_PORT}
- FastAPI docs are disabled by default
- initial settings.json is created
- the default export host is ${PUBLIC_HOST}
- the default allowed C port pool is ${DEFAULT_ALLOWED_C_PORTS}

Next steps in the UI:
1. Log in to the WebUI.
2. Fill in your Clash subscription A.
3. Fill in your upstream Socks5 B.
4. Refresh the subscription and start the default route.

Remember to open these ports in your cloud firewall or security group:
- ${PUBLIC_HTTP_PORT}/tcp
EOF

if [[ "$ENABLE_PORT_80" == "1" && "$PUBLIC_HTTP_PORT" != "80" ]]; then
  cat <<EOF
- 80/tcp
EOF
fi

cat <<EOF
- 10808/tcp (or whichever C port you use later)
EOF

if [[ -n "$MIHOMO_NOTICE" ]]; then
  cat <<EOF

Note:
- ${MIHOMO_NOTICE}
EOF
fi

if [[ -n "$DETECTION_WARNING" ]]; then
  cat <<EOF

Warning:
- ${DETECTION_WARNING}
EOF
fi
