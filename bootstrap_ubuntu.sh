#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

REPO_OWNER="${REPO_OWNER:-T-Chen-CN}"
REPO_NAME="${REPO_NAME:-Clash-Socks-Server-UI}"
REPO_REF="${REPO_REF:-main}"
ARCHIVE_URL="${REPO_ARCHIVE_URL:-https://codeload.github.com/${REPO_OWNER}/${REPO_NAME}/tar.gz/${REPO_REF}}"
TMP_DIR="$(mktemp -d /tmp/clash-socks-bootstrap.XXXXXX)"
CURRENT_STAGE="Bootstrap initialization / 引导初始化"
STEP_INDEX=0

log_step_start() {
  STEP_INDEX=$((STEP_INDEX + 1))
  CURRENT_STAGE="$1"
  echo
  printf '[BOOTSTRAP %02d][RUNNING] %s\n' "$STEP_INDEX" "$CURRENT_STAGE"
}

log_ok() {
  printf '[OK] %s\n' "$1"
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

if [[ $EUID -ne 0 ]]; then
  echo "Please run this bootstrap script with sudo." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
log_step_start "Install bootstrap prerequisites / 安装引导依赖"
apt-get update
apt-get install -y ca-certificates curl tar
log_ok "Bootstrap prerequisites installed. / 引导依赖安装完成。"

log_step_start "Download repository archive / 下载仓库压缩包"
echo "Downloading ${REPO_OWNER}/${REPO_NAME}@${REPO_REF} ..."
curl -fsSL "$ARCHIVE_URL" -o "$TMP_DIR/source.tar.gz"
log_ok "Repository archive downloaded. / 仓库压缩包下载完成。"

log_step_start "Extract repository archive / 解压仓库内容"
mkdir -p "$TMP_DIR/src"
tar -xzf "$TMP_DIR/source.tar.gz" --strip-components=1 -C "$TMP_DIR/src"
log_ok "Repository archive extracted. / 仓库内容解压完成。"

log_step_start "Run Ubuntu installer / 运行 Ubuntu 安装器"
cd "$TMP_DIR/src"
bash ./install_ubuntu.sh
log_ok "Bootstrap finished. / 一键部署引导完成。"
