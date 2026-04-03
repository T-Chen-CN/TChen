#!/usr/bin/env bash
set -euo pipefail
umask 027

REPO_OWNER="${REPO_OWNER:-T-Chen-CN}"
REPO_NAME="${REPO_NAME:-Clash-Socks-Server-UI}"
REPO_REF="${REPO_REF:-main}"
ARCHIVE_URL="${REPO_ARCHIVE_URL:-https://codeload.github.com/${REPO_OWNER}/${REPO_NAME}/tar.gz/${REPO_REF}}"
TMP_DIR="$(mktemp -d /tmp/clash-socks-bootstrap.XXXXXX)"

cleanup() {
  rm -rf "$TMP_DIR"
}

trap cleanup EXIT

if [[ $EUID -ne 0 ]]; then
  echo "Please run this bootstrap script with sudo." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl tar

echo "Downloading ${REPO_OWNER}/${REPO_NAME}@${REPO_REF} ..."
curl -fsSL "$ARCHIVE_URL" -o "$TMP_DIR/source.tar.gz"
mkdir -p "$TMP_DIR/src"
tar -xzf "$TMP_DIR/source.tar.gz" --strip-components=1 -C "$TMP_DIR/src"

cd "$TMP_DIR/src"
bash ./install_ubuntu.sh
