#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

REPO_OWNER="${REPO_OWNER:-T-Chen-CN}"
REPO_NAME="${REPO_NAME:-Clash-Socks-Server-UI}"
REPO_REF="${REPO_REF:-main}"
REPO_ARCHIVE_URL="${REPO_ARCHIVE_URL:-}"
REPO_FETCH_TIMEOUT="${CSG_REPO_FETCH_TIMEOUT:-15}"
REPO_DOWNLOAD_TIMEOUT="${CSG_REPO_DOWNLOAD_TIMEOUT:-300}"
REPO_FETCH_STRATEGIES="${CSG_REPO_FETCH_STRATEGIES:-${CSG_REPO_CANDIDATE_CHANNELS:-raw-files,git-clone,api-tarball,codeload}}"
HTTP_USER_AGENT="${HTTP_USER_AGENT:-Clash-Socks-Server-UI-bootstrap}"
TMP_DIR="$(mktemp -d /tmp/clash-socks-bootstrap.XXXXXX)"
CURRENT_STAGE="Bootstrap initialization / 引导初始化"
STEP_INDEX=0

RAW_SYNC_FILES=(
  "install_ubuntu.sh"
  "requirements.txt"
  "app/__init__.py"
  "app/auth.py"
  "app/config.py"
  "app/gateway_multi.py"
  "app/main.py"
  "static/app.js"
  "static/style.css"
  "templates/index.html"
  "templates/login.html"
  "systemd/clash-socks-webui.service"
)

log_step_start() {
  STEP_INDEX=$((STEP_INDEX + 1))
  CURRENT_STAGE="$1"
  echo
  printf '[BOOTSTRAP %02d][RUNNING] %s\n' "$STEP_INDEX" "$CURRENT_STAGE"
}

log_ok() {
  printf '[OK] %s\n' "$1"
}

log_info() {
  printf '[INFO] %s\n' "$1"
}

log_warn() {
  printf '[WARN] %s\n' "$1"
}

on_error() {
  local exit_code=$?
  echo
  printf '[FAILED] %s\n' "$CURRENT_STAGE"
  printf '[FAILED] Bootstrap aborted. / 一键部署引导中断，请检查上面的输出。\n'
  exit "$exit_code"
}

trap on_error ERR

cleanup() {
  rm -rf "$TMP_DIR"
}

trap cleanup EXIT

trim_whitespace() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

download_to_file() {
  local url="$1"
  local destination="$2"
  curl -fL \
    --retry 3 \
    --retry-all-errors \
    --connect-timeout 10 \
    --max-time "$REPO_DOWNLOAD_TIMEOUT" \
    -H "User-Agent: ${HTTP_USER_AGENT}" \
    "$url" \
    -o "$destination"
}

prepare_source_dir() {
  rm -rf "$TMP_DIR/src"
  mkdir -p "$TMP_DIR/src"
}

download_via_raw_files() {
  local raw_base_url destination path
  raw_base_url="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${REPO_REF}"

  log_info "Trying GitHub raw file sync first. / 优先尝试通过 GitHub raw 同步精简源码。"
  prepare_source_dir

  for path in "${RAW_SYNC_FILES[@]}"; do
    destination="$TMP_DIR/src/$path"
    mkdir -p "$(dirname "$destination")"
    download_to_file "${raw_base_url}/${path}" "$destination"
  done
}

download_via_git_clone() {
  local repo_git_url
  repo_git_url="https://github.com/${REPO_OWNER}/${REPO_NAME}.git"

  log_info "Trying git clone over HTTPS. / 正在尝试通过 HTTPS git clone 获取源码。"
  prepare_source_dir
  timeout "${REPO_DOWNLOAD_TIMEOUT}s" env GIT_TERMINAL_PROMPT=0 \
    git clone --depth 1 --branch "$REPO_REF" "$repo_git_url" "$TMP_DIR/src"
}

download_via_archive() {
  local archive_url="$1"

  prepare_source_dir
  download_to_file "$archive_url" "$TMP_DIR/source.tar.gz"
  tar -xzf "$TMP_DIR/source.tar.gz" --strip-components=1 -C "$TMP_DIR/src"
}

try_fetch_strategy() {
  local strategy="$1"

  case "$strategy" in
    raw-files)
      download_via_raw_files
      ;;
    git-clone)
      download_via_git_clone
      ;;
    api-tarball)
      log_info "Trying GitHub REST tarball. / 正在尝试通过 GitHub REST 归档接口获取源码。"
      download_via_archive "https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/tarball/${REPO_REF}"
      ;;
    codeload)
      log_info "Trying GitHub codeload archive. / 正在尝试通过 GitHub codeload 归档获取源码。"
      download_via_archive "https://codeload.github.com/${REPO_OWNER}/${REPO_NAME}/tar.gz/${REPO_REF}"
      ;;
    *)
      log_warn "Unknown fetch strategy: ${strategy} / 未知的源码获取策略：${strategy}"
      return 1
      ;;
  esac
}

fetch_repo_source() {
  local strategy=""
  local trimmed_strategy=""

  if [[ -n "$REPO_ARCHIVE_URL" ]]; then
    log_info "Using REPO_ARCHIVE_URL override. / 检测到 REPO_ARCHIVE_URL，跳过默认策略。"
    download_via_archive "$REPO_ARCHIVE_URL"
    return 0
  fi

  IFS=',' read -r -a strategies <<< "$REPO_FETCH_STRATEGIES"
  for strategy in "${strategies[@]}"; do
    trimmed_strategy="$(trim_whitespace "$strategy")"
    [[ -z "$trimmed_strategy" ]] && continue

    if try_fetch_strategy "$trimmed_strategy"; then
      log_ok "Repository source is ready via ${trimmed_strategy}. / 已通过 ${trimmed_strategy} 准备好仓库源码。"
      return 0
    fi

    log_warn "Fetch strategy failed: ${trimmed_strategy}. / 当前策略失败，准备尝试下一个：${trimmed_strategy}"
  done

  return 1
}

if [[ $EUID -ne 0 ]]; then
  echo "Please run this bootstrap script with sudo." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

log_step_start "Install bootstrap prerequisites / 安装引导依赖"
apt-get update -qq
apt-get install -y -o Dpkg::Use-Pty=0 ca-certificates curl git tar
log_ok "Bootstrap prerequisites installed. / 引导依赖安装完成。"

log_step_start "Fetch minimal application source / 获取精简应用源码"
fetch_repo_source

log_step_start "Run Ubuntu installer / 运行 Ubuntu 安装器"
cd "$TMP_DIR/src"
bash ./install_ubuntu.sh
log_ok "Bootstrap finished. / 一键部署引导完成。"
