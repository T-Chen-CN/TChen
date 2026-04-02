from __future__ import annotations

import gzip
import http.client
import ipaddress
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
RUNTIME_DIR = ROOT_DIR / "runtime"
LOG_DIR = ROOT_DIR / "logs"
PROVIDER_DIR = DATA_DIR / "proxy_providers"
SETTINGS_PATH = DATA_DIR / "settings.json"
CONFIG_PATH = DATA_DIR / "config.yaml"
PID_PATH = DATA_DIR / "mihomo.pid"
VERSION_PATH = RUNTIME_DIR / "mihomo.version"
MIHOMO_BIN = RUNTIME_DIR / "mihomo"
LOG_PATH = LOG_DIR / "mihomo.log"
SUBSCRIPTION_CACHE_PATH = PROVIDER_DIR / "a-sub.yaml"

GITHUB_LATEST_RELEASE = "https://api.github.com/repos/MetaCubeX/mihomo/releases/latest"
HEALTH_CHECK_URL = "https://www.gstatic.com/generate_204"
DEFAULT_DELAY_TIMEOUT_MS = 5000
NON_PROXY_HINTS = (
    "剩余流量",
    "下次重置",
    "套餐到期",
    "流量",
    "到期",
    "重置",
    "官网",
    "公告",
)


def ensure_directories() -> None:
    for path in (DATA_DIR, RUNTIME_DIR, LOG_DIR, PROVIDER_DIR):
        path.mkdir(parents=True, exist_ok=True)


def random_secret(length: int = 32) -> str:
    return secrets.token_urlsafe(length)[:length]


def detect_primary_ipv4() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        pass

    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


@dataclass
class GatewaySettings:
    subscription_url: str = ""
    landing_socks_url: str = ""
    landing_host: str = ""
    landing_port: int = 0
    landing_username: str = ""
    landing_password: str = ""
    listen_host: str = "0.0.0.0"
    listen_port: int = 10808
    export_host: str = ""
    gateway_username: str = "cuser"
    gateway_password: str = "cpass"
    controller_port: int = 19090
    controller_secret: str = ""
    selected_proxy: str = ""

    @classmethod
    def defaults(cls) -> "GatewaySettings":
        return cls(export_host=detect_primary_ipv4(), controller_secret=random_secret())

    @classmethod
    def load(cls) -> "GatewaySettings":
        ensure_directories()
        if not SETTINGS_PATH.exists():
            settings = cls.defaults()
            settings.save()
            return settings

        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        settings = cls.defaults()
        for key, value in raw.items():
            if hasattr(settings, key):
                setattr(settings, key, value)

        if not settings.export_host:
            settings.export_host = detect_primary_ipv4()
        if not settings.controller_secret:
            settings.controller_secret = random_secret()
        return settings

    def save(self) -> None:
        ensure_directories()
        SETTINGS_PATH.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    def normalized(self) -> "GatewaySettings":
        cloned = GatewaySettings(**asdict(self))
        if cloned.landing_socks_url.strip():
            parsed = parse_socks5_url(cloned.landing_socks_url.strip())
            cloned.landing_host = parsed["host"]
            cloned.landing_port = parsed["port"]
            cloned.landing_username = parsed["username"]
            cloned.landing_password = parsed["password"]

        cloned.subscription_url = cloned.subscription_url.strip()
        cloned.landing_host = cloned.landing_host.strip()
        cloned.landing_username = cloned.landing_username.strip()
        cloned.landing_password = cloned.landing_password.strip()
        cloned.listen_host = cloned.listen_host.strip() or "0.0.0.0"
        cloned.export_host = cloned.export_host.strip() or detect_primary_ipv4()
        cloned.gateway_username = cloned.gateway_username.strip()
        cloned.gateway_password = cloned.gateway_password.strip()
        cloned.controller_secret = cloned.controller_secret.strip() or random_secret()
        cloned.selected_proxy = cloned.selected_proxy.strip()
        return cloned


def parse_socks5_url(url: str) -> dict[str, str | int]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in {"socks5", "socks"}:
        raise ValueError("B 链接必须是 socks5:// 或 socks:// 开头。")
    if not parsed.hostname or not parsed.port:
        raise ValueError("B 链接缺少主机或端口。")
    return {
        "host": parsed.hostname,
        "port": parsed.port,
        "username": urllib.parse.unquote(parsed.username or ""),
        "password": urllib.parse.unquote(parsed.password or ""),
    }


def validate_settings(settings: GatewaySettings) -> GatewaySettings:
    normalized = settings.normalized()
    if not normalized.subscription_url:
        raise ValueError("请填写 Clash 订阅链接 A。")
    if not normalized.landing_host:
        raise ValueError("请填写落地 Socks5 的主机，或者粘贴完整的 B 链接。")
    if normalized.landing_port <= 0 or normalized.landing_port > 65535:
        raise ValueError("落地 Socks5 的端口不合法。")
    if normalized.listen_port <= 0 or normalized.listen_port > 65535:
        raise ValueError("新 Socks5 的监听端口不合法。")
    if normalized.controller_port <= 0 or normalized.controller_port > 65535:
        raise ValueError("控制器端口不合法。")
    if normalized.controller_port == normalized.listen_port:
        raise ValueError("SOCKS5 端口和控制器端口不能相同。")
    return normalized


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_config(settings: GatewaySettings) -> str:
    normalized = validate_settings(settings)
    bind_address = "*" if normalized.listen_host in {"0.0.0.0", "*"} else normalized.listen_host
    lines = [
        "allow-lan: true",
        f"bind-address: {yaml_quote(bind_address)}",
        f"socks-port: {normalized.listen_port}",
        f'external-controller: {yaml_quote(f"127.0.0.1:{normalized.controller_port}")}',
        f"secret: {yaml_quote(normalized.controller_secret)}",
        "mode: rule",
        "log-level: info",
        "ipv6: false",
        "profile:",
        "  store-selected: true",
        "  store-fake-ip: false",
        "proxies:",
        "  - name: b-resi",
        "    type: socks5",
        f"    server: {yaml_quote(normalized.landing_host)}",
        f"    port: {normalized.landing_port}",
    ]

    if normalized.landing_username:
        lines.append(f"    username: {yaml_quote(normalized.landing_username)}")
    if normalized.landing_password:
        lines.append(f"    password: {yaml_quote(normalized.landing_password)}")

    lines.extend(
        [
            "    udp: false",
            "    dialer-proxy: a-select",
            "proxy-providers:",
            "  a-sub:",
            "    type: http",
            f"    url: {yaml_quote(normalized.subscription_url)}",
            "    path: ./proxy_providers/a-sub.yaml",
            "    interval: 3600",
            "    proxy: DIRECT",
            "    health-check:",
            "      enable: true",
            f"      url: {yaml_quote(HEALTH_CHECK_URL)}",
            "      interval: 300",
            "proxy-groups:",
            "  - name: a-select",
            "    type: select",
            "    use:",
            "      - a-sub",
            "rules:",
            "  - MATCH,b-resi",
            "",
        ]
    )
    return "\n".join(lines)


def write_config(settings: GatewaySettings) -> GatewaySettings:
    normalized = validate_settings(settings)
    ensure_directories()
    CONFIG_PATH.write_text(render_config(normalized), encoding="utf-8")
    normalized.save()
    return normalized


def refresh_subscription_cache(
    settings: GatewaySettings,
    progress: Callable[[str], None] | None = None,
) -> Path:
    normalized = validate_settings(settings)
    ensure_directories()
    request = urllib.request.Request(
        normalized.subscription_url,
        headers={
            "User-Agent": "ClashSocksServerUI",
            "Accept": "*/*",
            "Accept-Encoding": "gzip",
        },
    )
    if progress:
        progress("正在直连拉取订阅 A，并同步到本地 provider 文件。")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                payload = gzip.decompress(payload)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"刷新订阅 A 失败，HTTP {exc.code}。{detail or '请检查订阅链接是否可访问。'}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"刷新订阅 A 失败：{exc.reason}") from exc

    if not payload.strip():
        raise RuntimeError("刷新订阅 A 失败：订阅返回为空。")

    temp_path = SUBSCRIPTION_CACHE_PATH.with_suffix(".tmp")
    temp_path.write_bytes(payload)
    temp_path.replace(SUBSCRIPTION_CACHE_PATH)
    if progress:
        progress(f"订阅 A 已写入 {SUBSCRIPTION_CACHE_PATH.name}，大小 {len(payload)} 字节。")
    return SUBSCRIPTION_CACHE_PATH


def github_request(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ClashSocksServerUI", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def choose_linux_asset(assets: list[dict]) -> dict:
    preferred_prefixes = [
        "mihomo-linux-amd64-compatible-",
        "mihomo-linux-amd64-v1-",
        "mihomo-linux-amd64-v1.",
        "mihomo-linux-amd64-v2-",
        "mihomo-linux-amd64-v3-",
        "mihomo-linux-amd64-",
    ]
    for prefix in preferred_prefixes:
        for asset in assets:
            name = asset.get("name", "")
            if not name.endswith(".gz"):
                continue
            if "-go" in name:
                continue
            if name.startswith(prefix):
                return asset
    raise RuntimeError("没有找到适用于 Linux amd64 的 mihomo 发布包。")


def ensure_mihomo(progress: Callable[[str], None] | None = None) -> str:
    ensure_directories()
    release = github_request(GITHUB_LATEST_RELEASE)
    tag_name = release["tag_name"]
    asset = choose_linux_asset(release.get("assets", []))

    if MIHOMO_BIN.exists() and VERSION_PATH.exists():
        current_version = VERSION_PATH.read_text(encoding="utf-8").strip()
        if current_version == tag_name:
            if progress:
                progress(f"mihomo 已是最新稳定版 {tag_name}。")
            return tag_name

    archive_path = RUNTIME_DIR / asset["name"]
    request = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "ClashSocksServerUI"})
    if progress:
        progress(f"正在下载 mihomo {tag_name}: {asset['name']}")
    with urllib.request.urlopen(request, timeout=120) as response, open(archive_path, "wb") as output:
        shutil.copyfileobj(response, output)

    with tempfile.TemporaryDirectory(prefix="mihomo_extract_") as temp_dir_str:
        temp_bin = Path(temp_dir_str) / "mihomo"
        with gzip.open(archive_path, "rb") as gz_file, open(temp_bin, "wb") as output:
            shutil.copyfileobj(gz_file, output)
        temp_bin.chmod(0o755)
        if MIHOMO_BIN.exists():
            MIHOMO_BIN.unlink()
        shutil.move(str(temp_bin), str(MIHOMO_BIN))

    VERSION_PATH.write_text(tag_name, encoding="utf-8")
    if progress:
        progress(f"mihomo 已更新到 {tag_name}。")
    return tag_name


def read_pid() -> int | None:
    if not PID_PATH.exists():
        return None
    try:
        payload = json.loads(PID_PATH.read_text(encoding="utf-8"))
        return int(payload["pid"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return None


def write_pid(pid: int) -> None:
    PID_PATH.write_text(json.dumps({"pid": pid}), encoding="utf-8")


def clear_pid() -> None:
    if PID_PATH.exists():
        PID_PATH.unlink()


def is_pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def pid_matches_mihomo(pid: int | None) -> bool:
    if not pid or not is_pid_running(pid):
        return False
    try:
        process_path = Path(os.readlink(f"/proc/{pid}/exe")).resolve()
    except OSError:
        return False
    return process_path == MIHOMO_BIN.resolve()


def controller_request(
    settings: GatewaySettings,
    path: str,
    method: str = "GET",
    payload: dict | None = None,
) -> dict:
    normalized = validate_settings(settings)
    url = f"http://127.0.0.1:{normalized.controller_port}{path}"
    body = None
    headers: dict[str, str] = {}
    if normalized.controller_secret:
        headers["Authorization"] = f"Bearer {normalized.controller_secret}"
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"控制器请求失败，HTTP {exc.code}。{detail or '请检查订阅配置和 mihomo 日志。'}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接本机控制器 127.0.0.1:{normalized.controller_port}。请先启动网关。") from exc


def is_selectable_proxy_name(name: str) -> bool:
    clean_name = (name or "").strip()
    return bool(clean_name) and not any(hint in clean_name for hint in NON_PROXY_HINTS)


def wait_for_controller(settings: GatewaySettings, timeout: int = 20) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            controller_request(settings, "/proxies")
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"mihomo 控制器未在 {timeout} 秒内就绪：{last_error}")


def list_upstream_proxies(settings: GatewaySettings) -> dict[str, object]:
    proxies = controller_request(settings, "/proxies")
    group = proxies.get("proxies", {}).get("a-select", {})
    all_names = list(group.get("all", []))
    candidates = [name for name in all_names if is_selectable_proxy_name(name)]
    details = proxies.get("proxies", {})
    alive_candidates = [name for name in candidates if details.get(name, {}).get("alive")]
    health = {name: bool(details.get(name, {}).get("alive")) for name in candidates}
    return {
        "now": group.get("now", ""),
        "raw_all": all_names,
        "all": candidates,
        "alive": alive_candidates,
        "health": health,
    }


def test_proxy_delay(
    settings: GatewaySettings,
    proxy_name: str,
    test_url: str = HEALTH_CHECK_URL,
    timeout_ms: int = DEFAULT_DELAY_TIMEOUT_MS,
) -> dict[str, object]:
    normalized = validate_settings(settings)
    encoded_name = urllib.parse.quote(proxy_name, safe="")
    encoded_url = urllib.parse.quote(test_url, safe="")
    path = f"/proxies/{encoded_name}/delay?url={encoded_url}&timeout={timeout_ms}"
    try:
        response = controller_request(normalized, path)
    except RuntimeError as exc:
        message = str(exc)
        if "HTTP 503" in message or "HTTP 504" in message:
            return {"name": proxy_name, "alive": False, "delay": None, "status": "timeout"}
        raise
    delay = response.get("delay")
    return {
        "name": proxy_name,
        "alive": delay is not None,
        "delay": int(delay) if delay is not None else None,
        "status": "ok" if delay is not None else "timeout",
    }


def test_group_delays(
    settings: GatewaySettings,
    test_url: str = HEALTH_CHECK_URL,
    timeout_ms: int = DEFAULT_DELAY_TIMEOUT_MS,
) -> dict[str, object]:
    normalized = validate_settings(settings)
    upstream = list_upstream_proxies(normalized)
    encoded_group = urllib.parse.quote("a-select", safe="")
    encoded_url = urllib.parse.quote(test_url, safe="")
    response = controller_request(normalized, f"/group/{encoded_group}/delay?url={encoded_url}&timeout={timeout_ms}")
    results: dict[str, dict[str, object]] = {}
    for name in upstream.get("all", []):
        delay = response.get(name)
        results[name] = {
            "name": name,
            "alive": delay is not None,
            "delay": int(delay) if delay is not None else None,
            "status": "ok" if delay is not None else "timeout",
        }
    return {"current": upstream.get("now", ""), "results": results}


def select_upstream_proxy(settings: GatewaySettings, proxy_name: str) -> None:
    normalized = validate_settings(settings)
    encoded_group = urllib.parse.quote("a-select", safe="")
    controller_request(normalized, f"/proxies/{encoded_group}", method="PUT", payload={"name": proxy_name})
    normalized.selected_proxy = proxy_name
    normalized.save()


def apply_saved_proxy_choice(settings: GatewaySettings, progress: Callable[[str], None] | None = None) -> None:
    normalized = validate_settings(settings)
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            upstream = list_upstream_proxies(normalized)
            candidates = upstream.get("all", [])
            alive_candidates = upstream.get("alive", [])
            current_proxy = str(upstream.get("now", ""))
            if normalized.selected_proxy and normalized.selected_proxy in candidates:
                select_upstream_proxy(normalized, normalized.selected_proxy)
                if progress:
                    progress(f"已恢复上游节点选择: {normalized.selected_proxy}")
                return
            if current_proxy in candidates:
                return
            fallback = alive_candidates[0] if alive_candidates else (candidates[0] if candidates else "")
            if fallback:
                select_upstream_proxy(normalized, fallback)
                if progress:
                    progress(f"已自动切换到可用节点: {fallback}")
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)


def start_gateway(settings: GatewaySettings, progress: Callable[[str], None] | None = None) -> GatewaySettings:
    refresh_subscription_cache(settings, progress)
    normalized = write_config(settings)
    ensure_mihomo(progress)
    pid = read_pid()
    if pid_matches_mihomo(pid):
        stop_gateway()
        if progress:
            progress("已停止旧的 mihomo 进程。")
    elif pid and not pid_matches_mihomo(pid):
        clear_pid()

    log_handle = open(LOG_PATH, "a", encoding="utf-8")
    process = subprocess.Popen(
        [str(MIHOMO_BIN), "-d", str(DATA_DIR), "-f", str(CONFIG_PATH)],
        cwd=str(ROOT_DIR),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    write_pid(process.pid)
    log_handle.close()
    if progress:
        progress(f"mihomo 已启动，PID={process.pid}。")
    wait_for_controller(normalized)
    apply_saved_proxy_choice(normalized, progress)
    return normalized


def stop_gateway() -> None:
    pid = read_pid()
    if not pid:
        return
    if not pid_matches_mihomo(pid):
        clear_pid()
        return
    try:
        os.killpg(pid, 15)
    except OSError:
        pass
    deadline = time.time() + 5
    while time.time() < deadline and is_pid_running(pid):
        time.sleep(0.2)
    if is_pid_running(pid):
        try:
            os.killpg(pid, 9)
        except OSError:
            pass
    clear_pid()


def build_socks5_link(host: str, port: int, username: str, password: str) -> str:
    safe_host = host.strip()
    if ":" in safe_host and not safe_host.startswith("["):
        safe_host = f"[{safe_host}]"
    user = urllib.parse.quote(username, safe="")
    secret = urllib.parse.quote(password, safe="")
    if username or password:
        return f"socks5://{user}:{secret}@{safe_host}:{port}"
    return f"socks5://{safe_host}:{port}"


def build_import_link(settings: GatewaySettings) -> str:
    normalized = settings.normalized()
    listen_port = normalized.listen_port if 0 < normalized.listen_port <= 65535 else 10808
    host = normalized.export_host or detect_primary_ipv4()
    return build_socks5_link(host, listen_port, normalized.gateway_username, normalized.gateway_password)


def local_gateway_host(settings: GatewaySettings) -> str:
    normalized = settings.normalized()
    host = normalized.listen_host.strip()
    if not host or host in {"0.0.0.0", "*", "::"}:
        return "127.0.0.1"
    return host


def recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RuntimeError("SOCKS5 连接意外关闭。")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def open_socks5_tunnel(
    proxy_host: str,
    proxy_port: int,
    username: str,
    password: str,
    target_host: str,
    target_port: int,
    timeout_s: float,
) -> socket.socket:
    sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout_s)
    sock.settimeout(timeout_s)
    methods = [0x00]
    if username or password:
        methods.append(0x02)
    sock.sendall(bytes([0x05, len(methods), *methods]))
    version, method = recv_exact(sock, 2)
    if version != 0x05:
        raise RuntimeError("SOCKS5 协议版本不正确。")
    if method == 0xFF:
        raise RuntimeError("SOCKS5 服务器拒绝了认证方式。")

    if method == 0x02:
        user_bytes = username.encode("utf-8")
        pass_bytes = password.encode("utf-8")
        sock.sendall(bytes([0x01, len(user_bytes)]) + user_bytes + bytes([len(pass_bytes)]) + pass_bytes)
        auth_version, auth_status = recv_exact(sock, 2)
        if auth_version != 0x01 or auth_status != 0x00:
            raise RuntimeError("SOCKS5 用户名或密码错误。")

    try:
        ip_obj = ipaddress.ip_address(target_host)
        atyp = 0x01 if ip_obj.version == 4 else 0x04
        addr = ip_obj.packed
    except ValueError:
        host_bytes = target_host.encode("idna")
        atyp = 0x03
        addr = bytes([len(host_bytes)]) + host_bytes

    sock.sendall(bytes([0x05, 0x01, 0x00, atyp]) + addr + target_port.to_bytes(2, "big"))
    version, reply, _reserved, atyp = recv_exact(sock, 4)
    if version != 0x05:
        raise RuntimeError("SOCKS5 CONNECT 返回版本不正确。")
    if reply != 0x00:
        raise RuntimeError(f"SOCKS5 CONNECT 失败，错误码 {reply}。")
    if atyp == 0x01:
        recv_exact(sock, 4)
    elif atyp == 0x03:
        recv_exact(sock, recv_exact(sock, 1)[0])
    elif atyp == 0x04:
        recv_exact(sock, 16)
    recv_exact(sock, 2)
    return sock


def fetch_url_via_gateway(
    settings: GatewaySettings,
    url: str,
    timeout_ms: int = DEFAULT_DELAY_TIMEOUT_MS,
) -> dict[str, object]:
    normalized = validate_settings(settings)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("仅支持 http:// 或 https:// URL。")
    if not parsed.hostname:
        raise ValueError("请求 URL 缺少主机名。")

    target_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    target_path = parsed.path or "/"
    if parsed.query:
        target_path = f"{target_path}?{parsed.query}"

    connect_host = local_gateway_host(normalized)
    timeout_s = max(timeout_ms / 1000.0, 1.0)
    start = time.perf_counter()
    sock = open_socks5_tunnel(
        connect_host,
        normalized.listen_port,
        normalized.gateway_username,
        normalized.gateway_password,
        parsed.hostname,
        target_port,
        timeout_s,
    )

    with sock:
        stream: socket.socket
        if parsed.scheme == "https":
            context = ssl.create_default_context()
            stream = context.wrap_socket(sock, server_hostname=parsed.hostname)
            stream.settimeout(timeout_s)
        else:
            stream = sock

        request = (
            f"GET {target_path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}\r\n"
            "User-Agent: ClashSocksServerUI\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii", errors="ignore")
        stream.sendall(request)
        response = http.client.HTTPResponse(stream)
        response.begin()
        body = response.read()
        delay_ms = int((time.perf_counter() - start) * 1000)
        return {
            "status_code": response.status,
            "reason": response.reason,
            "headers": dict(response.getheaders()),
            "body": body,
            "delay": delay_ms,
            "endpoint": f"{connect_host}:{normalized.listen_port}",
        }


def parse_ping0_geo_response(body: bytes) -> dict[str, object]:
    text = body.decode("utf-8", errors="ignore").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result: dict[str, object] = {
        "raw_lines": lines,
        "exit_ip": lines[0] if len(lines) > 0 else "",
        "location_line": lines[1] if len(lines) > 1 else "",
        "asn_line": lines[2] if len(lines) > 2 else "",
        "org_line": lines[3] if len(lines) > 3 else "",
    }
    location = str(result["location_line"])
    if location:
        parts = location.split()
        result["country"] = parts[0] if len(parts) > 0 else ""
        result["province"] = parts[1] if len(parts) > 1 else ""
        result["city"] = parts[2] if len(parts) > 2 else ""
    return result


def lookup_ip_metadata(ip: str) -> dict[str, object]:
    query = urllib.parse.quote(ip, safe="")
    url = (
        "http://ip-api.com/json/"
        f"{query}?fields=status,message,continent,continentCode,country,countryCode,region,"
        "regionName,city,district,zip,lat,lon,timezone,isp,org,as,asname,mobile,proxy,hosting,query"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "ClashSocksServerUI"})
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "success":
        raise RuntimeError(f"IP 属性查询失败：{payload.get('message', 'unknown error')}")
    return payload


def infer_network_summary(metadata: dict[str, object]) -> dict[str, str]:
    hosting = bool(metadata.get("hosting"))
    proxy = bool(metadata.get("proxy"))
    mobile = bool(metadata.get("mobile"))
    if mobile:
        return {
            "network_type": "移动网络（推断）",
            "native_hint": "较像原生移动出口（推断）",
            "asn_type": "Mobile（推断）",
            "org_type": "Mobile ISP（推断）",
        }
    if hosting:
        return {
            "network_type": "机房 / IDC（推断）",
            "native_hint": "不太像原生家宽（推断）",
            "asn_type": "IDC / Hosting（推断）",
            "org_type": "Data Center（推断）",
        }
    if proxy:
        return {
            "network_type": "代理出口（推断）",
            "native_hint": "可能为代理或共享出口（推断）",
            "asn_type": "Proxy / Mixed（推断）",
            "org_type": "Network Service（推断）",
        }
    return {
        "network_type": "非机房，疑似原生 / 家宽（推断）",
        "native_hint": "较像原生或家宽（推断）",
        "asn_type": "ISP（推断）",
        "org_type": "ISP / Residential（推断）",
    }


def build_gateway_ip_profile(ping0_geo: dict[str, object], metadata: dict[str, object]) -> dict[str, object]:
    inference = infer_network_summary(metadata)
    return {
        "exit_ip": ping0_geo.get("exit_ip") or metadata.get("query") or "",
        "location": ping0_geo.get("location_line") or " ".join(
            [str(metadata.get("country") or ""), str(metadata.get("regionName") or ""), str(metadata.get("city") or "")]
        ).strip(),
        "country": metadata.get("country") or ping0_geo.get("country") or "",
        "country_code": metadata.get("countryCode") or "",
        "province": metadata.get("regionName") or ping0_geo.get("province") or "",
        "province_code": metadata.get("region") or "",
        "city": metadata.get("city") or ping0_geo.get("city") or "",
        "district": metadata.get("district") or "",
        "zip": metadata.get("zip") or "",
        "continent": metadata.get("continent") or "",
        "continent_code": metadata.get("continentCode") or "",
        "timezone": metadata.get("timezone") or "",
        "latitude": metadata.get("lat"),
        "longitude": metadata.get("lon"),
        "asn": metadata.get("as") or ping0_geo.get("asn_line") or "",
        "asn_name": metadata.get("asname") or "",
        "isp": metadata.get("isp") or "",
        "org": metadata.get("org") or ping0_geo.get("org_line") or "",
        "mobile": bool(metadata.get("mobile")),
        "proxy": bool(metadata.get("proxy")),
        "hosting": bool(metadata.get("hosting")),
        "network_type": inference["network_type"],
        "native_hint": inference["native_hint"],
        "asn_type": inference["asn_type"],
        "org_type": inference["org_type"],
        "ip_risk_hint": "公开免费接口未提供风险分值",
        "source": "Ping0 /geo + ip-api.com",
    }


def test_gateway_link(
    settings: GatewaySettings,
    test_url: str = HEALTH_CHECK_URL,
    timeout_ms: int = DEFAULT_DELAY_TIMEOUT_MS,
) -> dict[str, object]:
    try:
        response = fetch_url_via_gateway(settings, test_url, timeout_ms)
        geo_response = fetch_url_via_gateway(settings, "https://ping0.cc/geo", timeout_ms)
        ping0_geo = parse_ping0_geo_response(bytes(geo_response["body"]))
        exit_ip = str(ping0_geo.get("exit_ip") or "").strip()
        metadata = lookup_ip_metadata(exit_ip) if exit_ip else {}
        ip_profile = build_gateway_ip_profile(ping0_geo, metadata) if metadata else {}
    except Exception as exc:  # noqa: BLE001
        return {
            "alive": False,
            "delay": None,
            "status": "timeout",
            "status_text": f"不可用: {exc}",
            "test_url": test_url,
            "endpoint": "",
            "ip_profile": {},
        }
    return {
        "alive": True,
        "delay": int(response["delay"]),
        "status": "ok",
        "status_text": "可用",
        "test_url": test_url,
        "endpoint": str(response["endpoint"]),
        "ip_profile": ip_profile,
    }


def current_status(settings: GatewaySettings) -> dict[str, object]:
    normalized = settings.normalized()
    pid = read_pid()
    running = pid_matches_mihomo(pid)
    controller_ready = False
    current_proxy = ""
    candidates: list[str] = []
    alive_candidates: list[str] = []
    if running:
        try:
            upstream = list_upstream_proxies(normalized)
            controller_ready = True
            current_proxy = str(upstream.get("now", ""))
            candidates = list(upstream.get("all", []))
            alive_candidates = list(upstream.get("alive", []))
        except Exception:  # noqa: BLE001
            controller_ready = False

    try:
        import_link = build_import_link(normalized)
    except Exception:  # noqa: BLE001
        import_link = ""

    return {
        "running": running,
        "pid": pid or "",
        "controller_ready": controller_ready,
        "current_proxy": current_proxy,
        "candidates": candidates,
        "alive_candidates": alive_candidates,
        "detected_ip": detect_primary_ipv4(),
        "import_link": import_link,
        "config_path": str(CONFIG_PATH),
        "log_path": str(LOG_PATH),
        "mihomo_path": str(MIHOMO_BIN),
    }


def read_recent_log(max_lines: int = 100) -> str:
    if not LOG_PATH.exists():
        return ""
    content = LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    return "\n".join(content[-max_lines:])
