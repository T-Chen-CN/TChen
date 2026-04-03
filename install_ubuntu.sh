#!/usr/bin/env bash
set -Eeuo pipefail
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
PIP_TIMEOUT="${CSG_PIP_TIMEOUT:-120}"
PIP_RETRIES="${CSG_PIP_RETRIES:-5}"
PIP_INDEX_URL="${CSG_PIP_INDEX_URL:-}"
PIP_EXTRA_INDEX_URL="${CSG_PIP_EXTRA_INDEX_URL:-}"
PIP_CANDIDATE_MIRRORS="${CSG_PIP_CANDIDATE_MIRRORS:-https://mirrors.cloud.tencent.com/pypi/simple,https://mirrors.aliyun.com/pypi/simple,https://pypi.tuna.tsinghua.edu.cn/simple,https://mirrors.ustc.edu.cn/pypi/simple,https://pypi.org/simple}"
MIHOMO_NOTICE=""
DETECTION_WARNING=""
CURRENT_STAGE="Initialization / 初始化"
STEP_INDEX=0

log_step_start() {
  STEP_INDEX=$((STEP_INDEX + 1))
  CURRENT_STAGE="$1"
  echo
  printf '[STEP %02d][RUNNING] %s\n' "$STEP_INDEX" "$CURRENT_STAGE"
}

log_info() {
  printf '[INFO] %s\n' "$1"
}

log_ok() {
  printf '[OK] %s\n' "$1"
}

log_warn() {
  printf '[WARN] %s\n' "$1"
}

on_error() {
  local exit_code=$?
  echo
  printf '[FAILED] %s\n' "$CURRENT_STAGE"
  printf '[FAILED] Installer aborted. / 安装中断，请检查上面的输出。\n'
  exit "$exit_code"
}

trap on_error ERR

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

retry_command() {
  local attempts="$1"
  local sleep_seconds="$2"
  shift 2

  local attempt=1
  while true; do
    if "$@"; then
      return 0
    fi

    local exit_code=$?
    if [[ "$attempt" -ge "$attempts" ]]; then
      return "$exit_code"
    fi

    log_warn "Command failed (attempt ${attempt}/${attempts}); retrying in ${sleep_seconds}s. / 命令执行失败（第 ${attempt}/${attempts} 次），${sleep_seconds} 秒后重试。"
    attempt=$((attempt + 1))
    sleep "$sleep_seconds"
  done
}

run_pip() {
  local -a env_args
  env_args=(
    "PIP_DISABLE_PIP_VERSION_CHECK=1"
    "PIP_DEFAULT_TIMEOUT=${PIP_TIMEOUT}"
    "PIP_PROGRESS_BAR=off"
  )

  if [[ -n "$PIP_INDEX_URL" ]]; then
    env_args+=("PIP_INDEX_URL=${PIP_INDEX_URL}")
  fi
  if [[ -n "$PIP_EXTRA_INDEX_URL" ]]; then
    env_args+=("PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL}")
  fi

  run_as_app_user env "${env_args[@]}" "$APP_DIR/.venv/bin/pip" "$@"
}

trim_whitespace() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s\n' "$value"
}

mirror_label() {
  local url="$1"
  url="${url#https://}"
  url="${url#http://}"
  url="${url%%/*}"
  printf '%s\n' "$url"
}

measure_url_ms() {
  local url="$1"
  local seconds
  seconds="$(curl \
    --output /dev/null \
    --silent \
    --show-error \
    --location \
    --connect-timeout 4 \
    --max-time 8 \
    --write-out '%{time_total}' \
    "$url" 2>/dev/null)" || return 1

  python3 - "$seconds" <<'PY'
import sys

print(round(float(sys.argv[1]) * 1000))
PY
}

select_pip_index_url() {
  if [[ -n "$PIP_INDEX_URL" ]]; then
    log_info "Using user-provided pip index: ${PIP_INDEX_URL} / 正在使用用户指定的 pip 源：${PIP_INDEX_URL}"
    return 0
  fi

  local best_url=""
  local best_ms=""
  local raw_candidate=""
  local candidate=""
  local probe_url=""
  local candidate_ms=""
  local label=""

  log_info "Probing pip mirrors before dependency install. / 正在为 Python 依赖安装测速多个 pip 源。"

  while IFS= read -r raw_candidate; do
    candidate="$(trim_whitespace "$raw_candidate")"
    if [[ -z "$candidate" ]]; then
      continue
    fi

    probe_url="${candidate%/}/pip/"
    label="$(mirror_label "$candidate")"

    if candidate_ms="$(measure_url_ms "$probe_url")"; then
      log_info "pip mirror ${label}: ${candidate_ms} ms / pip 源 ${label}：${candidate_ms} 毫秒"
      if [[ -z "$best_ms" || "$candidate_ms" -lt "$best_ms" ]]; then
        best_ms="$candidate_ms"
        best_url="$candidate"
      fi
    else
      log_warn "pip mirror ${label} is unavailable. / pip 源 ${label} 当前不可用。"
    fi
  done < <(printf '%s\n' "$PIP_CANDIDATE_MIRRORS" | tr ',;' '\n\n')

  if [[ -n "$best_url" ]]; then
    PIP_INDEX_URL="$best_url"
    log_ok "Selected pip mirror: ${best_url} (${best_ms} ms). / 已选择 pip 源：${best_url}（${best_ms} 毫秒）。"
    return 0
  fi

  log_warn "No pip mirror probe succeeded; falling back to pip defaults. / 没有测速成功的 pip 源，将回退到 pip 默认源。"
  return 0
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
      log_ok "${label} is reachable. / ${label} 已就绪。"
      return 0
    fi
    if [[ "$attempt" -eq 1 || $((attempt % 5)) -eq 0 ]]; then
      log_info "Waiting for ${label} (${attempt}/60). / 正在等待 ${label} 就绪（${attempt}/60）。"
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
  log_info "Initializing default application state. / 正在初始化默认应用状态。"
  run_as_app_user bash -lc "cd '$APP_DIR' && '$APP_DIR/.venv/bin/python' -c \"from app.gateway_multi import load_settings; settings = load_settings(); print(settings.export_host)\""

  log_info "Trying to preinstall mihomo. / 正在尝试预下载 mihomo。"
  if ! run_as_app_user bash -lc "cd '$APP_DIR' && '$APP_DIR/.venv/bin/python' -c \"from app.gateway_multi import ensure_mihomo; print(ensure_mihomo())\""; then
    MIHOMO_NOTICE="mihomo was not preinstalled automatically. You can install it later from the UI."
    log_warn "${MIHOMO_NOTICE}"
  fi
}

export DEBIAN_FRONTEND=noninteractive
log_info "Installer started on Ubuntu ${VERSION_ID:-unknown}. / 安装器已在 Ubuntu ${VERSION_ID:-unknown} 上启动。"

log_step_start "Install system packages / 安装系统依赖"
apt-get update
apt-get install -y python3 python3-venv python3-pip curl ca-certificates nginx
log_ok "System packages installed. / 系统依赖安装完成。"

log_step_start "Create application user / 创建运行用户"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi
log_ok "Application user ready. / 运行用户已就绪。"

log_step_start "Sync project files / 同步项目文件"
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
log_ok "Project files copied to ${APP_DIR}. / 项目文件已同步到 ${APP_DIR}。"

log_step_start "Prepare Python environment / 准备 Python 运行环境"
if [[ ! -d "$APP_DIR/.venv" ]]; then
  run_as_app_user python3 -m venv "$APP_DIR/.venv"
fi
select_pip_index_url
log_info "Installing Python dependencies. / 正在安装 Python 依赖。"
log_info "pip timeout=${PIP_TIMEOUT}s, retries=${PIP_RETRIES}. / pip 超时=${PIP_TIMEOUT} 秒，重试次数=${PIP_RETRIES}。"
if [[ -n "$PIP_INDEX_URL" ]]; then
  log_info "Using custom pip index: ${PIP_INDEX_URL} / 正在使用自定义 pip 源：${PIP_INDEX_URL}"
fi
if ! retry_command 3 5 run_pip install --retries "$PIP_RETRIES" --timeout "$PIP_TIMEOUT" -r "$APP_DIR/requirements.txt"; then
  log_warn "Python dependency installation failed after retries. / Python 依赖安装在多次重试后仍然失败。"
  log_warn "If your server reaches PyPI slowly, rerun with CSG_PIP_INDEX_URL set to a reachable mirror. / 如果服务器访问 PyPI 较慢，请设置 CSG_PIP_INDEX_URL 为可访问的镜像后重试。"
  false
fi
log_ok "Python environment is ready. / Python 运行环境已就绪。"

log_step_start "Initialize application settings / 初始化应用配置"
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
log_ok "Environment file and runtime directories are ready. / 环境文件与运行目录已就绪。"

log_step_start "Initialize runtime data / 初始化运行时数据"
initialize_app_state
log_ok "Runtime data initialized. / 运行时数据初始化完成。"

log_step_start "Enable systemd service / 启用 systemd 服务"
cp "$APP_DIR/systemd/$SERVICE_NAME.service" "/etc/systemd/system/$SERVICE_NAME.service"
chmod 644 "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
wait_for_http "http://${BACKEND_HOST}:${BACKEND_PORT}/login" "backend service"
log_ok "systemd service is healthy. / systemd 服务运行正常。"

log_step_start "Configure nginx reverse proxy / 配置 nginx 反向代理"
write_nginx_config
systemctl enable nginx
systemctl restart nginx
wait_for_http "http://127.0.0.1:${PUBLIC_HTTP_PORT}/login" "nginx proxy"
log_ok "nginx reverse proxy is healthy. / nginx 反向代理运行正常。"

log_step_start "Check local firewall rules / 检查本机防火墙规则"
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "^Status: active"; then
  ufw allow "${PUBLIC_HTTP_PORT}/tcp" >/dev/null 2>&1 || true
  if [[ "$ENABLE_PORT_80" == "1" && "$PUBLIC_HTTP_PORT" != "80" ]]; then
    ufw allow "80/tcp" >/dev/null 2>&1 || true
  fi
  log_ok "ufw rules updated for WebUI ports. / 已为 WebUI 端口更新本机 ufw 规则。"
else
  log_info "ufw is inactive or unavailable; cloud firewall still needs manual checks. / ufw 未启用或不可用，云防火墙仍需手动检查。"
fi

ADMIN_PASSWORD="$(get_env_value "$ENV_PATH" "CSG_ADMIN_PASSWORD")"
log_ok "All critical services are ready. / 关键服务已就绪。"

cat <<EOF

Deployment completed. / 部署完成。

WebUI URLs / WebUI 访问地址:
- ${PUBLIC_HTTP_URL}
EOF

if [[ "$ENABLE_PORT_80" == "1" && "$PUBLIC_HTTP_PORT" != "80" ]]; then
  cat <<EOF
- $(build_http_url "$PUBLIC_HOST" "80")
EOF
fi

cat <<EOF

Admin login / 管理员登录:
- username / 用户名: ${ADMIN_USERNAME}
- password / 密码: ${ADMIN_PASSWORD}

What is already prepared / 已完成的初始化:
- the app now runs behind nginx / 应用现在运行在 nginx 反向代理后面
- uvicorn only listens on ${BACKEND_HOST}:${BACKEND_PORT} / uvicorn 仅监听 ${BACKEND_HOST}:${BACKEND_PORT}
- FastAPI docs are disabled by default / FastAPI 文档默认关闭
- initial settings.json is created / 初始 settings.json 已创建
- the default export host is ${PUBLIC_HOST} / 默认导出主机是 ${PUBLIC_HOST}
- the default allowed C port pool is ${DEFAULT_ALLOWED_C_PORTS} / 默认允许的 C 端口池是 ${DEFAULT_ALLOWED_C_PORTS}

Next steps in the UI / 接下来在 UI 里要做的事:
1. Log in to the WebUI. / 登录 WebUI。
2. Fill in your Clash subscription A. / 填写 Clash 订阅 A。
3. Fill in your upstream Socks5 B. / 填写上游 Socks5 B。
4. Refresh the subscription and start the default route. / 刷新订阅并启动默认路由。

Firewall reminder / 防火墙提醒:
- Please open the WebUI port in your cloud firewall or security group now. / 请立即在云防火墙或安全组中放行 WebUI 端口。
- WebUI / 面板入口: ${PUBLIC_HTTP_PORT}/tcp
EOF

if [[ "$ENABLE_PORT_80" == "1" && "$PUBLIC_HTTP_PORT" != "80" ]]; then
  cat <<EOF
- WebUI optional IP entry / WebUI 可选 IP 入口: 80/tcp
EOF
fi

cat <<EOF
- C export port pool / C 导出端口池: ${DEFAULT_ALLOWED_C_PORTS}/tcp
- Open only the C ports you actually use. / C 端口建议只放行你真正会使用的范围。
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
