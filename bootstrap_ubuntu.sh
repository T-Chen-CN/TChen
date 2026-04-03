#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

REPO_OWNER="${REPO_OWNER:-T-Chen-CN}"
REPO_NAME="${REPO_NAME:-Clash-Socks-Server-UI}"
REPO_REF="${REPO_REF:-main}"
REPO_ARCHIVE_URL="${REPO_ARCHIVE_URL:-}"
REPO_FETCH_TIMEOUT="${CSG_REPO_FETCH_TIMEOUT:-15}"
REPO_DOWNLOAD_TIMEOUT="${CSG_REPO_DOWNLOAD_TIMEOUT:-300}"
REPO_CANDIDATE_CHANNELS="${CSG_REPO_CANDIDATE_CHANNELS:-archive-branch,archive-tag,api-tarball,codeload,git-clone}"
HTTP_USER_AGENT="${HTTP_USER_AGENT:-Clash-Socks-Server-UI-bootstrap}"
TMP_DIR="$(mktemp -d /tmp/clash-socks-bootstrap.XXXXXX)"
CURRENT_STAGE="Bootstrap initialization / 引导初始化"
STEP_INDEX=0
SELECTED_SOURCE_LABEL=""
SELECTED_SOURCE_TYPE=""
SELECTED_SOURCE_VALUE=""
SELECTED_SOURCE_MS=""

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

timestamp_ms() {
  date +%s%3N
}

measure_http_url_ms() {
  local url="$1"
  local start_ms end_ms
  start_ms="$(timestamp_ms)"
  if curl -fsSIL --retry 1 --retry-all-errors --connect-timeout 5 --max-time "$REPO_FETCH_TIMEOUT" \
    -H "User-Agent: ${HTTP_USER_AGENT}" "$url" >/dev/null 2>&1; then
    end_ms="$(timestamp_ms)"
    printf '%s' "$((end_ms - start_ms))"
    return 0
  fi
  return 1
}

measure_git_url_ms() {
  local url="$1"
  local start_ms end_ms
  start_ms="$(timestamp_ms)"
  if timeout "${REPO_FETCH_TIMEOUT}s" env GIT_TERMINAL_PROMPT=0 git ls-remote "$url" HEAD >/dev/null 2>&1; then
    end_ms="$(timestamp_ms)"
    printf '%s' "$((end_ms - start_ms))"
    return 0
  fi
  return 1
}

record_probe_result() {
  local label="$1"
  local probe_mode="$2"
  local source_value="$3"
  local result_ms

  if [[ "$probe_mode" == "git" ]]; then
    if result_ms="$(measure_git_url_ms "$source_value")"; then
      log_info "${label}: ${result_ms} ms"
    else
      log_warn "${label}: unavailable"
      return 1
    fi
  else
    if result_ms="$(measure_http_url_ms "$source_value")"; then
      log_info "${label}: ${result_ms} ms"
    else
      log_warn "${label}: unavailable"
      return 1
    fi
  fi

  if [[ -z "$SELECTED_SOURCE_TYPE" || "$result_ms" -lt "${SELECTED_SOURCE_MS:-999999999}" ]]; then
    SELECTED_SOURCE_MS="$result_ms"
    SELECTED_SOURCE_LABEL="$label"
    SELECTED_SOURCE_TYPE="$probe_mode"
    SELECTED_SOURCE_VALUE="$source_value"
  fi
}

probe_repo_source_channels() {
  local repo_git_url repo_branch_archive_url repo_tag_archive_url repo_api_archive_url repo_codeload_url
  local channel trimmed_channel

  if [[ -n "$REPO_ARCHIVE_URL" ]]; then
    SELECTED_SOURCE_LABEL="Custom archive URL / 自定义归档地址"
    SELECTED_SOURCE_TYPE="archive"
    SELECTED_SOURCE_VALUE="$REPO_ARCHIVE_URL"
    log_info "Using REPO_ARCHIVE_URL override. / 检测到 REPO_ARCHIVE_URL，跳过自动选源。"
    return 0
  fi

  repo_git_url="https://github.com/${REPO_OWNER}/${REPO_NAME}.git"
  repo_branch_archive_url="https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/heads/${REPO_REF}.tar.gz"
  repo_tag_archive_url="https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/tags/${REPO_REF}.tar.gz"
  repo_api_archive_url="https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/tarball/${REPO_REF}"
  repo_codeload_url="https://codeload.github.com/${REPO_OWNER}/${REPO_NAME}/tar.gz/${REPO_REF}"

  log_info "Probing GitHub source channels before download. / 下载前正在探测 GitHub 源码通道。"

  IFS=',' read -r -a requested_channels <<< "$REPO_CANDIDATE_CHANNELS"
  for channel in "${requested_channels[@]}"; do
    trimmed_channel="$(trim_whitespace "$channel")"
    [[ -z "$trimmed_channel" ]] && continue

    case "$trimmed_channel" in
      archive-branch)
        record_probe_result \
          "GitHub archive (branch ref) / GitHub 归档下载（分支）" \
          "archive" \
          "$repo_branch_archive_url" || true
        ;;
      archive-tag)
        record_probe_result \
          "GitHub archive (tag ref) / GitHub 归档下载（标签）" \
          "archive" \
          "$repo_tag_archive_url" || true
        ;;
      api-tarball)
        record_probe_result \
          "GitHub REST tarball / GitHub REST 归档接口" \
          "archive" \
          "$repo_api_archive_url" || true
        ;;
      codeload)
        record_probe_result \
          "GitHub codeload direct / GitHub codeload 直连" \
          "archive" \
          "$repo_codeload_url" || true
        ;;
      git-clone)
        record_probe_result \
          "Git clone over HTTPS / HTTPS git clone" \
          "git" \
          "$repo_git_url" || true
        ;;
      *)
        log_warn "Unknown repo source channel '${trimmed_channel}'. / 未知的源码通道：${trimmed_channel}"
        ;;
    esac
  done

  if [[ -z "$SELECTED_SOURCE_TYPE" ]]; then
    log_warn "No GitHub source channel is currently reachable. / 当前没有可用的 GitHub 源码通道。"
    log_warn "You can override the source URL with REPO_ARCHIVE_URL. / 也可以通过 REPO_ARCHIVE_URL 手动指定源码地址。"
    return 1
  fi

  log_info "Selected GitHub source channel: ${SELECTED_SOURCE_LABEL} (${SELECTED_SOURCE_MS} ms) / 已选择最快可用的 GitHub 源码通道。"
}

download_repo_source() {
  mkdir -p "$TMP_DIR/src"
  echo "Downloading ${REPO_OWNER}/${REPO_NAME}@${REPO_REF} ..."

  case "$SELECTED_SOURCE_TYPE" in
    archive)
      curl -fL --retry 3 --retry-all-errors --connect-timeout 10 --max-time "$REPO_DOWNLOAD_TIMEOUT" \
        -H "User-Agent: ${HTTP_USER_AGENT}" \
        "$SELECTED_SOURCE_VALUE" -o "$TMP_DIR/source.tar.gz"
      ;;
    git)
      timeout "${REPO_DOWNLOAD_TIMEOUT}s" env GIT_TERMINAL_PROMPT=0 \
        git clone --depth 1 --branch "$REPO_REF" "$SELECTED_SOURCE_VALUE" "$TMP_DIR/src"
      ;;
    *)
      log_warn "Unsupported source type '${SELECTED_SOURCE_TYPE}'. / 不支持的源码类型：${SELECTED_SOURCE_TYPE}"
      return 1
      ;;
  esac
}

extract_repo_source_if_needed() {
  if [[ "$SELECTED_SOURCE_TYPE" == "archive" ]]; then
    tar -xzf "$TMP_DIR/source.tar.gz" --strip-components=1 -C "$TMP_DIR/src"
    log_ok "Repository source prepared. / 仓库源码已就绪。"
    return 0
  fi

  log_ok "Repository source prepared via git clone. / 已通过 git clone 准备好仓库源码。"
}

if [[ $EUID -ne 0 ]]; then
  echo "Please run this bootstrap script with sudo." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

log_step_start "Install bootstrap prerequisites / 安装引导依赖"
apt-get update
apt-get install -y ca-certificates curl tar git
log_ok "Bootstrap prerequisites installed. / 引导依赖安装完成。"

log_step_start "Probe repository source channels / 探测仓库源码通道"
probe_repo_source_channels
log_ok "Repository source channel selected. / 仓库源码通道已选定。"

log_step_start "Download repository source / 下载仓库源码"
download_repo_source
log_ok "Repository source downloaded. / 仓库源码下载完成。"

log_step_start "Prepare repository workspace / 准备仓库工作目录"
extract_repo_source_if_needed

log_step_start "Run Ubuntu installer / 运行 Ubuntu 安装器"
cd "$TMP_DIR/src"
bash ./install_ubuntu.sh
log_ok "Bootstrap finished. / 一键部署引导完成。"
