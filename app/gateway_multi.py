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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from .config import CONFIG


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
RUNTIME_DIR = ROOT_DIR / "runtime"
LOG_DIR = ROOT_DIR / "logs"
PROVIDER_DIR = DATA_DIR / "proxy_providers"
ROUTES_DIR = DATA_DIR / "routes"
SETTINGS_PATH = DATA_DIR / "settings.json"
VERSION_PATH = RUNTIME_DIR / "mihomo.version"
MIHOMO_BIN = RUNTIME_DIR / "mihomo"
SHARED_PROVIDER_PATH = PROVIDER_DIR / "a-sub.yaml"
LEGACY_CONFIG_PATH = DATA_DIR / "config.yaml"
LEGACY_PID_PATH = DATA_DIR / "mihomo.pid"
LEGACY_LOG_PATH = LOG_DIR / "mihomo.log"
INSPECTOR_CONFIG_PATH = DATA_DIR / "a-inspector.yaml"
INSPECTOR_PID_PATH = DATA_DIR / "a-inspector.pid"
INSPECTOR_LOG_PATH = LOG_DIR / "a-inspector.log"
SERVICE_CGROUP = "/system.slice/clash-socks-webui.service"

GITHUB_LATEST_RELEASE = "https://api.github.com/repos/MetaCubeX/mihomo/releases/latest"
HEALTH_CHECK_URL = "https://www.gstatic.com/generate_204"
DEFAULT_DELAY_TIMEOUT_MS = 5000
DEFAULT_C_PORT_POOL = "10808-10999"
NON_PROXY_HINTS = ("流量", "重置", "到期", "公告", "官网", "套餐")


def ensure_directories() -> None:
    for path in (DATA_DIR, RUNTIME_DIR, LOG_DIR, PROVIDER_DIR, ROUTES_DIR):
        path.mkdir(parents=True, exist_ok=True)


def random_secret(length: int = 24) -> str:
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


def default_export_host() -> str:
    configured = CONFIG.default_export_host.strip()
    if configured:
        return configured
    return detect_primary_ipv4()


def default_allowed_c_ports() -> str:
    configured = CONFIG.default_allowed_c_ports.strip()
    if configured:
        return configured
    return DEFAULT_C_PORT_POOL


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def write_text_file(path: Path, content: str, mode: int | None = None) -> None:
    path.write_text(content, encoding="utf-8")
    if mode is not None:
        try:
            os.chmod(path, mode)
        except OSError:
            pass


def is_loopback_host(host: str) -> bool:
    value = (host or "").strip().lower()
    if value in {"127.0.0.1", "::1", "localhost"}:
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def route_dir(route_id: str) -> Path:
    return ROUTES_DIR / route_id


def route_config_path(route_id: str) -> Path:
    if route_id == "default":
        return LEGACY_CONFIG_PATH
    return route_dir(route_id) / "config.yaml"


def route_pid_path(route_id: str) -> Path:
    if route_id == "default":
        return LEGACY_PID_PATH
    return route_dir(route_id) / "mihomo.pid"


def route_log_path(route_id: str) -> Path:
    if route_id == "default":
        return LEGACY_LOG_PATH
    return LOG_DIR / f"{route_id}.log"


def ensure_route_filesystem(route_id: str) -> None:
    ensure_directories()
    if route_id != "default":
        route_dir(route_id).mkdir(parents=True, exist_ok=True)


def next_available_port(used_ports: set[int], start: int) -> int:
    port = start
    while port in used_ports:
        port += 1
    return port


def parse_c_port_pool(spec: str) -> list[int]:
    text = (spec or "").strip() or DEFAULT_C_PORT_POOL
    ports: set[int] = set()
    for raw_part in text.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            try:
                start = int(start_text.strip())
                end = int(end_text.strip())
            except ValueError as exc:
                raise ValueError("C 端口池格式不正确，请使用如 10808-10999 或 10808,10810-10820。") from exc
            if start > end:
                raise ValueError("C 端口范围起始值不能大于结束值。")
            if start <= 0 or end > 65535:
                raise ValueError("C 端口池中的端口必须在 1 到 65535 之间。")
            ports.update(range(start, end + 1))
        else:
            try:
                port = int(part)
            except ValueError as exc:
                raise ValueError("C 端口池格式不正确，请使用如 10808-10999 或 10808,10810-10820。") from exc
            if port <= 0 or port > 65535:
                raise ValueError("C 端口池中的端口必须在 1 到 65535 之间。")
            ports.add(port)
    if not ports:
        raise ValueError("请至少提供一个已开放的 C 端口。")
    return sorted(ports)


def next_available_port_from_pool(used_ports: set[int], port_pool: list[int]) -> int:
    for port in port_pool:
        if port not in used_ports:
            return port
    raise ValueError("已开放的 C 端口池已经分配完，没有可用端口了。")


def build_route_id(existing_ids: set[str], seed: str = "route") -> str:
    while True:
        candidate = f"{seed}-{secrets.token_hex(3)}"
        if candidate not in existing_ids:
            return candidate


def parse_socks5_url(url: str) -> dict[str, str | int]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in {"socks5", "socks"}:
        raise ValueError("B 链接必须以 socks5:// 或 socks:// 开头。")
    if not parsed.hostname or not parsed.port:
        raise ValueError("B 链接缺少主机或端口。")
    return {
        "host": parsed.hostname,
        "port": parsed.port,
        "username": urllib.parse.unquote(parsed.username or ""),
        "password": urllib.parse.unquote(parsed.password or ""),
    }


@dataclass
class RouteSettings:
    route_id: str = ""
    name: str = ""
    landing_socks_url: str = ""
    landing_host: str = ""
    landing_port: int = 0
    landing_username: str = ""
    landing_password: str = ""
    listen_host: str = "0.0.0.0"
    listen_port: int = 10808
    gateway_username: str = "cuser"
    gateway_password: str = "cpass"
    controller_port: int = 19090
    controller_secret: str = ""
    selected_proxy: str = ""

    @classmethod
    def create_default(cls, route_id: str = "default", name: str = "默认路由") -> "RouteSettings":
        return cls(
            route_id=route_id,
            name=name,
            listen_host="0.0.0.0",
            listen_port=10808,
            gateway_username=random_secret(12),
            gateway_password=random_secret(20),
            controller_port=19090,
            controller_secret=random_secret(24),
        )

    def normalized(self) -> "RouteSettings":
        cloned = RouteSettings(**asdict(self))
        cloned.route_id = (cloned.route_id or "").strip()
        cloned.name = (cloned.name or "").strip() or "未命名路由"
        if cloned.landing_socks_url.strip():
            parsed = parse_socks5_url(cloned.landing_socks_url.strip())
            cloned.landing_host = str(parsed["host"])
            cloned.landing_port = int(parsed["port"])
            cloned.landing_username = str(parsed["username"])
            cloned.landing_password = str(parsed["password"])
        cloned.landing_socks_url = cloned.landing_socks_url.strip()
        cloned.landing_host = cloned.landing_host.strip()
        cloned.landing_username = cloned.landing_username.strip()
        cloned.landing_password = cloned.landing_password.strip()
        cloned.listen_host = cloned.listen_host.strip() or "0.0.0.0"
        cloned.gateway_username = cloned.gateway_username.strip()
        cloned.gateway_password = cloned.gateway_password.strip()
        cloned.controller_secret = cloned.controller_secret.strip() or random_secret(24)
        cloned.selected_proxy = cloned.selected_proxy.strip()
        return cloned


@dataclass
class ControllerHandle:
    controller_port: int
    controller_secret: str = ""


@dataclass
class AppSettings:
    version: int = 2
    subscription_url: str = ""
    export_host: str = ""
    allowed_c_ports: str = DEFAULT_C_PORT_POOL
    active_route_id: str = "default"
    inspector_controller_port: int = 19180
    inspector_secret: str = ""
    routes: list[RouteSettings] = field(default_factory=list)

    @classmethod
    def defaults(cls) -> "AppSettings":
        route = RouteSettings.create_default()
        return cls(
            version=2,
            subscription_url="",
            export_host=default_export_host(),
            allowed_c_ports=default_allowed_c_ports(),
            active_route_id=route.route_id,
            inspector_controller_port=19180,
            inspector_secret=random_secret(24),
            routes=[route],
        )

    @classmethod
    def load(cls) -> "AppSettings":
        ensure_directories()
        if not SETTINGS_PATH.exists():
            settings = cls.defaults()
            settings.save()
            return settings

        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("routes"), list):
            routes: list[RouteSettings] = []
            for item in raw.get("routes", []):
                if isinstance(item, dict):
                    routes.append(RouteSettings(**item))
            settings = cls(
                version=int(raw.get("version", 2) or 2),
                subscription_url=str(raw.get("subscription_url") or ""),
                export_host=str(raw.get("export_host") or ""),
                allowed_c_ports=str(raw.get("allowed_c_ports") or default_allowed_c_ports()),
                active_route_id=str(raw.get("active_route_id") or ""),
                inspector_controller_port=int(raw.get("inspector_controller_port") or 19180),
                inspector_secret=str(raw.get("inspector_secret") or random_secret(24)),
                routes=routes,
            )
            return validate_app_settings(settings, save_back=False)

        legacy_route = RouteSettings(
            route_id="default",
            name="默认路由",
            landing_socks_url=str(raw.get("landing_socks_url") or ""),
            landing_host=str(raw.get("landing_host") or ""),
            landing_port=int(raw.get("landing_port") or 0),
            landing_username=str(raw.get("landing_username") or ""),
            landing_password=str(raw.get("landing_password") or ""),
            listen_host=str(raw.get("listen_host") or "0.0.0.0"),
            listen_port=int(raw.get("listen_port") or 10808),
            gateway_username=str(raw.get("gateway_username") or "cuser"),
            gateway_password=str(raw.get("gateway_password") or "cpass"),
            controller_port=int(raw.get("controller_port") or 19090),
            controller_secret=str(raw.get("controller_secret") or random_secret(24)),
            selected_proxy=str(raw.get("selected_proxy") or ""),
        )
        settings = cls(
            version=2,
            subscription_url=str(raw.get("subscription_url") or ""),
            export_host=str(raw.get("export_host") or default_export_host()),
            allowed_c_ports=default_allowed_c_ports(),
            active_route_id="default",
            inspector_controller_port=19180,
            inspector_secret=random_secret(24),
            routes=[legacy_route],
        )
        return validate_app_settings(settings, save_back=False)

    def save(self) -> None:
        ensure_directories()
        payload = {
            "version": self.version,
            "subscription_url": self.subscription_url,
            "export_host": self.export_host,
            "allowed_c_ports": self.allowed_c_ports,
            "active_route_id": self.active_route_id,
            "inspector_controller_port": self.inspector_controller_port,
            "inspector_secret": self.inspector_secret,
            "routes": [asdict(route) for route in self.routes],
        }
        write_text_file(SETTINGS_PATH, json.dumps(payload, ensure_ascii=False, indent=2), mode=0o600)

    def route_map(self) -> dict[str, RouteSettings]:
        return {route.route_id: route for route in self.routes}

    def get_route(self, route_id: str) -> RouteSettings:
        for route in self.routes:
            if route.route_id == route_id:
                return route
        raise ValueError(f"未找到路由：{route_id}")

    def used_ports(self, exclude_route_id: str | None = None) -> set[int]:
        ports: set[int] = {self.inspector_controller_port}
        for route in self.routes:
            if exclude_route_id and route.route_id == exclude_route_id:
                continue
            ports.add(route.listen_port)
            ports.add(route.controller_port)
        return ports


def validate_route(
    route: RouteSettings,
    require_landing: bool = False,
    allowed_listen_ports: set[int] | None = None,
) -> RouteSettings:
    normalized = route.normalized()
    if not normalized.route_id:
        raise ValueError("路由缺少 route_id。")
    if normalized.listen_port <= 0 or normalized.listen_port > 65535:
        raise ValueError(f"路由“{normalized.name}”的 C 监听端口不合法。")
    if allowed_listen_ports is not None and normalized.listen_port not in allowed_listen_ports:
        raise ValueError(f"路由“{normalized.name}”的 C 端口不在服务器已开放端口池中。")
    if normalized.controller_port <= 0 or normalized.controller_port > 65535:
        raise ValueError(f"路由“{normalized.name}”的控制器端口不合法。")
    if normalized.listen_port == normalized.controller_port:
        raise ValueError(f"路由“{normalized.name}”的 C 端口和控制器端口不能相同。")
    if bool(normalized.gateway_username) != bool(normalized.gateway_password):
        raise ValueError("C gateway username and password must both be set or both be blank.")
    if not is_loopback_host(normalized.listen_host) and not normalized.gateway_username:
        raise ValueError("Public C listeners must require a gateway username and password.")
    if require_landing:
        if not normalized.landing_host:
            raise ValueError(f"路由“{normalized.name}”缺少 B 主机，或 B 链接格式不对。")
        if normalized.landing_port <= 0 or normalized.landing_port > 65535:
            raise ValueError(f"路由“{normalized.name}”的 B 端口不合法。")
    elif normalized.landing_host and (normalized.landing_port <= 0 or normalized.landing_port > 65535):
        raise ValueError(f"路由“{normalized.name}”的 B 端口不合法。")
    return normalized


def validate_app_settings(settings: AppSettings, save_back: bool = False) -> AppSettings:
    ensure_directories()
    normalized = AppSettings(
        version=2,
        subscription_url=(settings.subscription_url or "").strip(),
        export_host=(settings.export_host or default_export_host()).strip() or default_export_host(),
        allowed_c_ports=(settings.allowed_c_ports or default_allowed_c_ports()).strip() or default_allowed_c_ports(),
        active_route_id=(settings.active_route_id or "").strip(),
        inspector_controller_port=int(settings.inspector_controller_port or 19180),
        inspector_secret=(settings.inspector_secret or "").strip() or random_secret(24),
        routes=[],
    )
    allowed_c_port_set = set(parse_c_port_pool(normalized.allowed_c_ports))
    if normalized.inspector_controller_port <= 0 or normalized.inspector_controller_port > 65535:
        raise ValueError("A 检查器控制器端口不合法。")
    if not settings.routes:
        normalized.routes = [RouteSettings.create_default()]
    else:
        seen_ids: set[str] = set()
        used_ports: set[int] = {normalized.inspector_controller_port}
        for route in settings.routes:
            valid_route = validate_route(route, require_landing=False, allowed_listen_ports=allowed_c_port_set)
            if valid_route.route_id in seen_ids:
                raise ValueError(f"发现重复的 route_id：{valid_route.route_id}")
            if valid_route.listen_port in used_ports or valid_route.controller_port in used_ports:
                raise ValueError(f"路由“{valid_route.name}”的端口与其他路由冲突。")
            seen_ids.add(valid_route.route_id)
            used_ports.add(valid_route.listen_port)
            used_ports.add(valid_route.controller_port)
            normalized.routes.append(valid_route)
    if not normalized.active_route_id or normalized.active_route_id not in normalized.route_map():
        normalized.active_route_id = normalized.routes[0].route_id
    if save_back:
        normalized.save()
    return normalized


def load_settings() -> AppSettings:
    return AppSettings.load()


def save_settings(settings: AppSettings) -> AppSettings:
    normalized = validate_app_settings(settings)
    normalized.save()
    return normalized


def build_import_link(app_settings: AppSettings, route: RouteSettings) -> str:
    safe_host = app_settings.export_host.strip() or default_export_host()
    if ":" in safe_host and not safe_host.startswith("["):
        safe_host = f"[{safe_host}]"
    username = urllib.parse.quote(route.gateway_username, safe="")
    password = urllib.parse.quote(route.gateway_password, safe="")
    if route.gateway_username and route.gateway_password:
        return f"socks5://{username}:{password}@{safe_host}:{route.listen_port}"
    return f"socks5://{safe_host}:{route.listen_port}"


def create_route_template(app_settings: AppSettings, source_route_id: str | None = None) -> RouteSettings:
    settings = validate_app_settings(app_settings)
    existing_ids = set(settings.route_map())
    new_route_id = build_route_id(existing_ids)
    used_ports = settings.used_ports()
    listen_port = next_available_port_from_pool(used_ports, parse_c_port_pool(settings.allowed_c_ports))
    used_ports.add(listen_port)
    controller_port = next_available_port(used_ports, 19090)
    base = RouteSettings.create_default(route_id=new_route_id, name=f"新路由 {len(settings.routes) + 1}")
    if source_route_id:
        source = settings.get_route(source_route_id).normalized()
        base.name = f"{source.name} 副本"
        base.landing_socks_url = source.landing_socks_url
        base.landing_host = source.landing_host
        base.landing_port = source.landing_port
        base.landing_username = source.landing_username
        base.landing_password = source.landing_password
        base.listen_host = source.listen_host
        base.selected_proxy = source.selected_proxy
    base.listen_port = listen_port
    base.controller_port = controller_port
    base.gateway_username = random_secret(12)
    base.gateway_password = random_secret(20)
    base.controller_secret = random_secret(24)
    return base


def add_route(app_settings: AppSettings, source_route_id: str | None = None) -> AppSettings:
    settings = validate_app_settings(app_settings)
    route = create_route_template(settings, source_route_id)
    settings.routes.append(route)
    settings.active_route_id = route.route_id
    settings.save()
    return settings


def update_global_settings(app_settings: AppSettings, payload: dict[str, object]) -> AppSettings:
    updated = AppSettings(
        version=2,
        subscription_url=str(payload.get("subscription_url", app_settings.subscription_url) or ""),
        export_host=str(payload.get("export_host", app_settings.export_host) or ""),
        allowed_c_ports=str(payload.get("allowed_c_ports", app_settings.allowed_c_ports) or DEFAULT_C_PORT_POOL),
        active_route_id=str(payload.get("active_route_id", app_settings.active_route_id) or app_settings.active_route_id),
        inspector_controller_port=app_settings.inspector_controller_port,
        inspector_secret=app_settings.inspector_secret,
        routes=app_settings.routes,
    )
    return save_settings(updated)


def update_route(app_settings: AppSettings, payload: dict[str, object]) -> AppSettings:
    settings = validate_app_settings(app_settings)
    route_id = str(payload.get("route_id") or "").strip()
    if not route_id:
        raise ValueError("缺少 route_id。")
    current = settings.get_route(route_id)
    merged = RouteSettings(**{**asdict(current), **payload})
    updated_routes = []
    for route in settings.routes:
        updated_routes.append(merged if route.route_id == route_id else route)
    updated = AppSettings(
        version=2,
        subscription_url=settings.subscription_url,
        export_host=settings.export_host,
        allowed_c_ports=settings.allowed_c_ports,
        active_route_id=route_id,
        inspector_controller_port=settings.inspector_controller_port,
        inspector_secret=settings.inspector_secret,
        routes=updated_routes,
    )
    return save_settings(updated)


def set_active_route(app_settings: AppSettings, route_id: str) -> AppSettings:
    settings = validate_app_settings(app_settings)
    settings.get_route(route_id)
    settings.active_route_id = route_id
    settings.save()
    return settings


def delete_route(app_settings: AppSettings, route_id: str) -> AppSettings:
    settings = validate_app_settings(app_settings)
    if len(settings.routes) <= 1:
        raise ValueError("至少保留一个路由。")
    route = settings.get_route(route_id)
    stop_route(route)
    settings.routes = [item for item in settings.routes if item.route_id != route_id]
    if settings.active_route_id == route_id:
        settings.active_route_id = settings.routes[0].route_id
    settings.save()
    return settings


def render_config(app_settings: AppSettings, route: RouteSettings) -> str:
    bind_address = "*" if route.listen_host in {"0.0.0.0", "*"} else route.listen_host
    lines = [
        "allow-lan: true",
        f"bind-address: {yaml_quote(bind_address)}",
        f"socks-port: {route.listen_port}",
        f'external-controller: {yaml_quote(f"127.0.0.1:{route.controller_port}")}',
        f"secret: {yaml_quote(route.controller_secret)}",
        "mode: rule",
        "log-level: info",
        "ipv6: false",
        "profile:",
        "  store-selected: false",
        "  store-fake-ip: false",
    ]
    if route.gateway_username and route.gateway_password:
        lines.extend(
            [
                "authentication:",
                f"  - {yaml_quote(f'{route.gateway_username}:{route.gateway_password}')}",
            ]
        )
    lines.extend(
        [
            "proxies:",
            "  - name: b-resi",
            "    type: socks5",
            f"    server: {yaml_quote(route.landing_host)}",
            f"    port: {route.landing_port}",
        ]
    )
    if route.landing_username:
        lines.append(f"    username: {yaml_quote(route.landing_username)}")
    if route.landing_password:
        lines.append(f"    password: {yaml_quote(route.landing_password)}")
    lines.extend(
        [
            "    udp: false",
            "    dialer-proxy: a-select",
            "proxy-providers:",
            "  a-sub:",
            "    type: file",
            "    path: ./proxy_providers/a-sub.yaml",
            "    interval: 3600",
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


def write_route_config(app_settings: AppSettings, route: RouteSettings) -> Path:
    ensure_route_filesystem(route.route_id)
    path = route_config_path(route.route_id)
    write_text_file(path, render_config(app_settings, route), mode=0o600)
    return path


def refresh_subscription_cache(
    app_settings: AppSettings,
    progress: Callable[[str], None] | None = None,
) -> Path:
    settings = validate_app_settings(app_settings)
    if not settings.subscription_url:
        raise ValueError("请先填写 Clash 订阅 A。")
    ensure_directories()
    request = urllib.request.Request(
        settings.subscription_url,
        headers={
            "User-Agent": "ClashSocksServerUI",
            "Accept": "*/*",
            "Accept-Encoding": "gzip",
        },
    )
    if progress:
        progress("正在直连刷新共享订阅 A。")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                payload = gzip.decompress(payload)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"刷新订阅 A 失败，HTTP {exc.code}。{detail or '请检查订阅链接是否有效。'}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"刷新订阅 A 失败：{exc.reason}") from exc

    if not payload.strip():
        raise RuntimeError("刷新订阅 A 失败：订阅返回为空。")

    try:
        parsed = yaml.safe_load(payload.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"刷新订阅 A 失败：返回内容不是可解析的 Clash YAML。{exc}") from exc
    proxies = (parsed or {}).get("proxies") or []
    if not isinstance(proxies, list) or not proxies:
        raise RuntimeError("刷新订阅 A 失败：订阅里没有找到 proxies 列表。")

    temp_path = SHARED_PROVIDER_PATH.with_suffix(".tmp")
    temp_path.write_bytes(payload)
    temp_path.replace(SHARED_PROVIDER_PATH)
    if progress:
        progress(f"订阅 A 已写入 {SHARED_PROVIDER_PATH.name}，共 {len(proxies)} 条记录。")
    return SHARED_PROVIDER_PATH


def ensure_subscription_cache(
    app_settings: AppSettings,
    progress: Callable[[str], None] | None = None,
) -> Path:
    settings = validate_app_settings(app_settings)
    if SHARED_PROVIDER_PATH.exists() and SHARED_PROVIDER_PATH.stat().st_size > 0:
        if progress:
            progress(f"Using cached subscription provider: {SHARED_PROVIDER_PATH.name}")
        return SHARED_PROVIDER_PATH
    return refresh_subscription_cache(settings, progress)


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
    current_version = VERSION_PATH.read_text(encoding="utf-8").strip() if VERSION_PATH.exists() else ""
    has_local_binary = MIHOMO_BIN.exists()
    try:
        release = github_request(GITHUB_LATEST_RELEASE)
        tag_name = release["tag_name"]
        asset = choose_linux_asset(release.get("assets", []))
    except Exception:
        if has_local_binary:
            return current_version or "local"
        raise

    if MIHOMO_BIN.exists() and VERSION_PATH.exists():
        if current_version == tag_name:
            if progress:
                progress(f"mihomo 已是最新稳定版 {tag_name}。")
            return tag_name

    archive_path = RUNTIME_DIR / asset["name"]
    request = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "ClashSocksServerUI"})
    if progress:
        progress(f"正在下载 mihomo {tag_name}: {asset['name']}")
    try:
        with urllib.request.urlopen(request, timeout=120) as response, open(archive_path, "wb") as output:
            shutil.copyfileobj(response, output)
    except Exception:
        if has_local_binary:
            return current_version or "local"
        raise

    with tempfile.TemporaryDirectory(prefix="mihomo_extract_") as temp_dir_str:
        temp_bin = Path(temp_dir_str) / "mihomo"
        with gzip.open(archive_path, "rb") as gz_file, open(temp_bin, "wb") as output:
            shutil.copyfileobj(gz_file, output)
        temp_bin.chmod(0o755)
        if MIHOMO_BIN.exists():
            MIHOMO_BIN.unlink()
        shutil.move(str(temp_bin), str(MIHOMO_BIN))

    write_text_file(VERSION_PATH, tag_name, mode=0o644)
    if progress:
        progress(f"mihomo 已更新到 {tag_name}。")
    return tag_name


def read_pid(route: RouteSettings) -> int | None:
    path = route_pid_path(route.route_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return int(payload["pid"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return None


def write_pid(route: RouteSettings, pid: int) -> None:
    ensure_route_filesystem(route.route_id)
    write_text_file(route_pid_path(route.route_id), json.dumps({"pid": pid}), mode=0o600)


def clear_pid(route: RouteSettings) -> None:
    path = route_pid_path(route.route_id)
    if path.exists():
        path.unlink()


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


def pid_in_service_cgroup(pid: int | None) -> bool:
    if not pid or not is_pid_running(pid):
        return False
    try:
        cgroup_text = (Path("/proc") / str(pid) / "cgroup").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return SERVICE_CGROUP in cgroup_text


def stop_process_group(pid: int) -> None:
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


def process_config_path(pid: int) -> Path | None:
    try:
        raw_parts = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\x00")
    except OSError:
        return None
    parts = [item.decode("utf-8", errors="ignore") for item in raw_parts if item]
    for index, item in enumerate(parts[:-1]):
        if item == "-f":
            return Path(parts[index + 1])
    return None


def iter_managed_mihomo_processes() -> list[tuple[int, Path | None]]:
    proc_dir = Path("/proc")
    if not proc_dir.exists():
        return []
    managed: list[tuple[int, Path | None]] = []
    for entry in proc_dir.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid_matches_mihomo(pid):
            managed.append((pid, process_config_path(pid)))
    return managed


def cleanup_stale_processes(app_settings: AppSettings | None = None) -> list[int]:
    settings = validate_app_settings(app_settings or load_settings())
    tracked_pids = {
        pid for route in settings.routes if pid_matches_mihomo(pid := read_pid(route)) and pid_in_service_cgroup(pid)
    }
    inspector_pid = read_inspector_pid()
    if pid_matches_mihomo(inspector_pid) and pid_in_service_cgroup(inspector_pid):
        tracked_pids.add(int(inspector_pid))

    data_root = DATA_DIR.resolve()
    killed: list[int] = []
    for pid, config_path in iter_managed_mihomo_processes():
        if pid in tracked_pids or config_path is None:
            continue
        try:
            resolved_config = config_path.resolve()
        except OSError:
            continue
        if not resolved_config.is_relative_to(data_root):
            continue
        stop_process_group(pid)
        killed.append(pid)
    return killed


def restore_tracked_processes(app_settings: AppSettings | None = None) -> list[str]:
    settings = validate_app_settings(app_settings or load_settings())
    restored: list[str] = []
    for route in settings.routes:
        if not route_pid_path(route.route_id).exists():
            continue
        pid = read_pid(route)
        if pid_matches_mihomo(pid) and pid_in_service_cgroup(pid):
            continue
        settings = start_route(settings, route.route_id)
        restored.append(route.route_id)
    inspector_pid = read_inspector_pid()
    if INSPECTOR_PID_PATH.exists() and not (pid_matches_mihomo(inspector_pid) and pid_in_service_cgroup(inspector_pid)):
        start_a_inspector(settings)
        restored.append("a-inspector")
    return restored


def controller_request(
    route: RouteSettings | ControllerHandle,
    path: str,
    method: str = "GET",
    payload: dict | None = None,
) -> dict:
    url = f"http://127.0.0.1:{route.controller_port}{path}"
    body = None
    headers: dict[str, str] = {}
    if route.controller_secret:
        headers["Authorization"] = f"Bearer {route.controller_secret}"
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
        raise RuntimeError(f"无法连接本机控制器 127.0.0.1:{route.controller_port}。请先启动该路由。") from exc


def is_selectable_proxy_name(name: str) -> bool:
    clean_name = (name or "").strip()
    return bool(clean_name) and not any(hint in clean_name for hint in NON_PROXY_HINTS)


def wait_for_controller(route: RouteSettings | ControllerHandle, timeout: int = 20) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            controller_request(route, "/proxies")
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"mihomo 控制器未在 {timeout} 秒内就绪：{last_error}")


def list_upstream_proxies(route: RouteSettings | ControllerHandle) -> dict[str, object]:
    proxies = controller_request(route, "/proxies")
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
    route: RouteSettings | ControllerHandle,
    proxy_name: str,
    test_url: str = HEALTH_CHECK_URL,
    timeout_ms: int = DEFAULT_DELAY_TIMEOUT_MS,
) -> dict[str, object]:
    encoded_name = urllib.parse.quote(proxy_name, safe="")
    encoded_url = urllib.parse.quote(test_url, safe="")
    path = f"/proxies/{encoded_name}/delay?url={encoded_url}&timeout={timeout_ms}"
    try:
        response = controller_request(route, path)
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
    route: RouteSettings | ControllerHandle,
    test_url: str = HEALTH_CHECK_URL,
    timeout_ms: int = DEFAULT_DELAY_TIMEOUT_MS,
) -> dict[str, object]:
    upstream = list_upstream_proxies(route)
    encoded_group = urllib.parse.quote("a-select", safe="")
    encoded_url = urllib.parse.quote(test_url, safe="")
    response = controller_request(route, f"/group/{encoded_group}/delay?url={encoded_url}&timeout={timeout_ms}")
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


def wait_for_selected_proxy(
    route: RouteSettings | ControllerHandle,
    proxy_name: str,
    timeout: float = 6.0,
) -> None:
    deadline = time.time() + timeout
    last_now = ""
    while time.time() < deadline:
        upstream = list_upstream_proxies(route)
        last_now = str(upstream.get("now", ""))
        if last_now == proxy_name:
            return
        time.sleep(0.2)
    raise RuntimeError(f"节点切换未在 {timeout:.1f} 秒内生效，当前仍为：{last_now or '未知'}")


def select_upstream_proxy(app_settings: AppSettings, route_id: str, proxy_name: str) -> AppSettings:
    settings = validate_app_settings(app_settings)
    route = settings.get_route(route_id)
    controller_request(
        route,
        f"/proxies/{urllib.parse.quote('a-select', safe='')}",
        method="PUT",
        payload={"name": proxy_name},
    )
    wait_for_selected_proxy(route, proxy_name)
    route.selected_proxy = proxy_name.strip()
    settings.save()
    return settings


def apply_saved_proxy_choice(
    app_settings: AppSettings,
    route: RouteSettings,
    progress: Callable[[str], None] | None = None,
) -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            upstream = list_upstream_proxies(route)
            candidates = upstream.get("all", [])
            alive_candidates = upstream.get("alive", [])
            current_proxy = str(upstream.get("now", ""))
            if route.selected_proxy and route.selected_proxy in candidates:
                controller_request(
                    route,
                    f"/proxies/{urllib.parse.quote('a-select', safe='')}",
                    method="PUT",
                    payload={"name": route.selected_proxy},
                )
                if progress:
                    progress(f"已恢复上游节点选择：{route.selected_proxy}")
                return
            if current_proxy in candidates:
                return
            fallback = alive_candidates[0] if alive_candidates else (candidates[0] if candidates else "")
            if fallback:
                controller_request(
                    route,
                    f"/proxies/{urllib.parse.quote('a-select', safe='')}",
                    method="PUT",
                    payload={"name": fallback},
                )
                route.selected_proxy = fallback
                app_settings.save()
                if progress:
                    progress(f"已自动切换到可用节点：{fallback}")
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)


def start_route(
    app_settings: AppSettings,
    route_id: str,
    progress: Callable[[str], None] | None = None,
) -> AppSettings:
    settings = validate_app_settings(app_settings)
    route = validate_route(
        settings.get_route(route_id),
        require_landing=True,
        allowed_listen_ports=set(parse_c_port_pool(settings.allowed_c_ports)),
    )
    refresh_subscription_cache(settings, progress)
    write_route_config(settings, route)
    ensure_mihomo(progress)
    pid = read_pid(route)
    if pid_matches_mihomo(pid):
        stop_route(route)
        if progress:
            progress("已停止旧的 mihomo 进程。")
    elif pid and not pid_matches_mihomo(pid):
        clear_pid(route)

    log_path = route_log_path(route.route_id)
    log_handle = open(log_path, "a", encoding="utf-8")
    process = subprocess.Popen(
        [str(MIHOMO_BIN), "-d", str(DATA_DIR), "-f", str(route_config_path(route.route_id))],
        cwd=str(ROOT_DIR),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    write_pid(route, process.pid)
    log_handle.close()
    if progress:
        progress(f"路由“{route.name}”已启动，PID={process.pid}。")
    wait_for_controller(route)
    apply_saved_proxy_choice(settings, route, progress)
    settings.save()
    return settings


def stop_route(route: RouteSettings) -> None:
    pid = read_pid(route)
    if not pid:
        return
    if not pid_matches_mihomo(pid):
        clear_pid(route)
        return
    stop_process_group(pid)
    clear_pid(route)


def inspector_handle(app_settings: AppSettings) -> ControllerHandle:
    settings = validate_app_settings(app_settings)
    return ControllerHandle(
        controller_port=settings.inspector_controller_port,
        controller_secret=settings.inspector_secret,
    )


def read_inspector_pid() -> int | None:
    if not INSPECTOR_PID_PATH.exists():
        return None
    try:
        payload = json.loads(INSPECTOR_PID_PATH.read_text(encoding="utf-8"))
        return int(payload["pid"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return None


def write_inspector_pid(pid: int) -> None:
    write_text_file(INSPECTOR_PID_PATH, json.dumps({"pid": pid}), mode=0o600)


def clear_inspector_pid() -> None:
    if INSPECTOR_PID_PATH.exists():
        INSPECTOR_PID_PATH.unlink()


def render_inspector_config(app_settings: AppSettings) -> str:
    handle = inspector_handle(app_settings)
    lines = [
        "allow-lan: false",
        f'external-controller: {yaml_quote(f"127.0.0.1:{handle.controller_port}")}',
        f"secret: {yaml_quote(handle.controller_secret)}",
        "mode: rule",
        "log-level: info",
        "ipv6: false",
        "proxy-providers:",
        "  a-sub:",
        "    type: file",
        "    path: ./proxy_providers/a-sub.yaml",
        "    interval: 3600",
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
        "  - MATCH,DIRECT",
        "",
    ]
    return "\n".join(lines)


def write_inspector_config(app_settings: AppSettings) -> Path:
    ensure_directories()
    write_text_file(INSPECTOR_CONFIG_PATH, render_inspector_config(app_settings), mode=0o600)
    return INSPECTOR_CONFIG_PATH


def stop_a_inspector() -> None:
    pid = read_inspector_pid()
    if not pid:
        return
    if not pid_matches_mihomo(pid):
        clear_inspector_pid()
        return
    stop_process_group(pid)
    clear_inspector_pid()


def start_a_inspector(
    app_settings: AppSettings,
    progress: Callable[[str], None] | None = None,
    refresh_subscription: bool = True,
) -> AppSettings:
    settings = validate_app_settings(app_settings)
    if refresh_subscription:
        refresh_subscription_cache(settings, progress)
    else:
        ensure_subscription_cache(settings, progress)
    write_inspector_config(settings)
    ensure_mihomo(progress)
    pid = read_inspector_pid()
    if pid_matches_mihomo(pid):
        stop_a_inspector()
    elif pid and not pid_matches_mihomo(pid):
        clear_inspector_pid()

    log_handle = open(INSPECTOR_LOG_PATH, "a", encoding="utf-8")
    process = subprocess.Popen(
        [str(MIHOMO_BIN), "-d", str(DATA_DIR), "-f", str(INSPECTOR_CONFIG_PATH)],
        cwd=str(ROOT_DIR),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    write_inspector_pid(process.pid)
    log_handle.close()
    if progress:
        progress(f"A 检查器已启动，PID={process.pid}。")
    wait_for_controller(inspector_handle(settings))
    return settings


def ensure_a_inspector(
    app_settings: AppSettings,
    progress: Callable[[str], None] | None = None,
    refresh_subscription: bool = False,
) -> AppSettings:
    settings = validate_app_settings(app_settings)
    handle = inspector_handle(settings)
    pid = read_inspector_pid()
    if pid_matches_mihomo(pid) and not refresh_subscription:
        try:
            controller_request(handle, "/proxies")
            return settings
        except Exception:  # noqa: BLE001
            pass
    return start_a_inspector(settings, progress, refresh_subscription=refresh_subscription)


def local_gateway_host(route: RouteSettings) -> str:
    host = route.listen_host.strip()
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
        raise RuntimeError("SOCKS5 服务拒绝认证方法。")

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


def fetch_url_via_socks_endpoint(
    proxy_host: str,
    proxy_port: int,
    username: str,
    password: str,
    url: str,
    timeout_ms: int = DEFAULT_DELAY_TIMEOUT_MS,
) -> dict[str, object]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("仅支持 http:// 或 https:// URL。")
    if not parsed.hostname:
        raise ValueError("请求 URL 缺少主机名。")

    target_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    target_path = parsed.path or "/"
    if parsed.query:
        target_path = f"{target_path}?{parsed.query}"

    timeout_s = max(timeout_ms / 1000.0, 1.0)
    start = time.perf_counter()
    sock = open_socks5_tunnel(
        proxy_host,
        proxy_port,
        username,
        password,
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
            "endpoint": f"{proxy_host}:{proxy_port}",
        }


def fetch_url_via_gateway(
    route: RouteSettings,
    url: str,
    timeout_ms: int = DEFAULT_DELAY_TIMEOUT_MS,
    connect_host: str | None = None,
) -> dict[str, object]:
    gateway_host = (connect_host or "").strip() or local_gateway_host(route)
    if gateway_host.startswith("[") and gateway_host.endswith("]"):
        gateway_host = gateway_host[1:-1]
    return fetch_url_via_socks_endpoint(
        gateway_host,
        route.listen_port,
        route.gateway_username,
        route.gateway_password,
        url,
        timeout_ms,
    )


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
        "ip_risk_hint": "公开免费接口未提供风险分值。",
        "source": "Ping0 /geo + ip-api.com",
    }


def resolve_ip_profile_via_socks_endpoint(
    proxy_host: str,
    proxy_port: int,
    username: str,
    password: str,
    timeout_ms: int,
    default_endpoint: str,
) -> tuple[dict[str, object], dict[str, object]]:
    ip_profile: dict[str, object] = {}
    exit_ip = ""
    try:
        geo_response = fetch_url_via_socks_endpoint(
            proxy_host,
            proxy_port,
            username,
            password,
            "https://ping0.cc/geo",
            timeout_ms,
        )
        ping0_geo = parse_ping0_geo_response(bytes(geo_response["body"]))
        exit_ip = str(ping0_geo.get("exit_ip") or "").strip()
        if not exit_ip:
            raise RuntimeError("Ping0 未返回出口 IP。")
        metadata = lookup_ip_metadata(exit_ip)
        ip_profile = build_gateway_ip_profile(ping0_geo, metadata)
        ip_lookup = {
            "alive": True,
            "delay": int(geo_response["delay"]),
            "status": "ok",
            "status_text": "已获取出口 IP 与属性。",
            "endpoint": str(geo_response["endpoint"]),
            "lookup_url": "https://ping0.cc/geo",
            "exit_ip": exit_ip,
            "ip_profile": ip_profile,
        }
    except Exception as ping0_exc:  # noqa: BLE001
        try:
            ip_response = fetch_url_via_socks_endpoint(
                proxy_host,
                proxy_port,
                username,
                password,
                "http://api.ipify.org",
                timeout_ms,
            )
            exit_ip = bytes(ip_response["body"]).decode("utf-8", errors="ignore").strip()
            if not exit_ip:
                raise RuntimeError("api.ipify 未返回出口 IP。")
            metadata = lookup_ip_metadata(exit_ip)
            ip_profile = build_gateway_ip_profile({"exit_ip": exit_ip}, metadata)
            ip_lookup = {
                "alive": True,
                "delay": int(ip_response["delay"]),
                "status": "ok",
                "status_text": "已获取出口 IP 与简化属性。",
                "endpoint": str(ip_response["endpoint"]),
                "lookup_url": "http://api.ipify.org + ip-api.com",
                "exit_ip": exit_ip,
                "ip_profile": ip_profile,
            }
        except Exception as exc:  # noqa: BLE001
            ip_lookup = {
                "alive": False,
                "delay": None,
                "status": "failed",
                "status_text": f"IP 查询失败：{ping0_exc if str(ping0_exc).strip() else exc}",
                "endpoint": default_endpoint,
                "lookup_url": "https://ping0.cc/geo",
                "exit_ip": exit_ip,
                "ip_profile": {},
            }
    return ip_lookup, ip_profile


def test_gateway_link(
    app_settings: AppSettings,
    route_id: str,
    test_url: str = HEALTH_CHECK_URL,
    timeout_ms: int = DEFAULT_DELAY_TIMEOUT_MS,
) -> dict[str, object]:
    settings = validate_app_settings(app_settings)
    route = settings.get_route(route_id)
    gateway_host = (settings.export_host or "").strip() or local_gateway_host(route)
    default_endpoint = f"{gateway_host}:{route.listen_port}"

    connectivity: dict[str, object]
    try:
        response = fetch_url_via_gateway(route, test_url, timeout_ms, connect_host=gateway_host)
        connectivity = {
            "alive": True,
            "delay": int(response["delay"]),
            "status": "ok",
            "status_text": "可用",
            "test_url": test_url,
            "endpoint": str(response["endpoint"]),
        }
    except Exception as exc:  # noqa: BLE001
        connectivity = {
            "alive": False,
            "delay": None,
            "status": "timeout",
            "status_text": f"不可用：{exc}",
            "test_url": test_url,
            "endpoint": default_endpoint,
        }
        return {
            "alive": False,
            "delay": None,
            "status": str(connectivity["status"]),
            "status_text": str(connectivity["status_text"]),
            "test_url": test_url,
            "endpoint": default_endpoint,
            "ip_profile": {},
            "connectivity": connectivity,
            "ip_lookup": {
                "alive": False,
                "delay": None,
                "status": "skipped",
                "status_text": "连通性未通过，未查询出口 IP。",
                "endpoint": default_endpoint,
                "lookup_url": "https://ping0.cc/geo",
                "exit_ip": "",
                "ip_profile": {},
            },
        }

    ip_lookup, ip_profile = resolve_ip_profile_via_socks_endpoint(
        gateway_host,
        route.listen_port,
        route.gateway_username,
        route.gateway_password,
        timeout_ms,
        default_endpoint,
    )

    return {
        "alive": bool(connectivity["alive"]),
        "delay": connectivity["delay"],
        "status": str(connectivity["status"]),
        "status_text": str(connectivity["status_text"]),
        "test_url": test_url,
        "endpoint": str(connectivity["endpoint"]),
        "ip_profile": ip_profile,
        "connectivity": connectivity,
        "ip_lookup": ip_lookup,
    }


def test_landing_link(
    app_settings: AppSettings,
    route_id: str,
    test_url: str = HEALTH_CHECK_URL,
    timeout_ms: int = DEFAULT_DELAY_TIMEOUT_MS,
) -> dict[str, object]:
    settings = validate_app_settings(app_settings)
    route = validate_route(settings.get_route(route_id), require_landing=True)
    default_endpoint = f"{route.landing_host}:{route.landing_port}"

    try:
        response = fetch_url_via_socks_endpoint(
            route.landing_host,
            route.landing_port,
            route.landing_username,
            route.landing_password,
            test_url,
            timeout_ms,
        )
        connectivity = {
            "alive": True,
            "delay": int(response["delay"]),
            "status": "ok",
            "status_text": "可用",
            "test_url": test_url,
            "endpoint": str(response["endpoint"]),
        }
        ip_lookup, ip_profile = resolve_ip_profile_via_socks_endpoint(
            route.landing_host,
            route.landing_port,
            route.landing_username,
            route.landing_password,
            timeout_ms,
            default_endpoint,
        )
        return {
            "alive": True,
            "delay": int(response["delay"]),
            "status": "ok",
            "status_text": "可用",
            "test_url": test_url,
            "endpoint": str(response["endpoint"]),
            "status_code": int(response["status_code"]),
            "reason": str(response["reason"]),
            "ip_profile": ip_profile,
            "connectivity": connectivity,
            "ip_lookup": ip_lookup,
        }
    except Exception as exc:  # noqa: BLE001
        connectivity = {
            "alive": False,
            "delay": None,
            "status": "failed",
            "status_text": f"不可用：{exc}",
            "test_url": test_url,
            "endpoint": default_endpoint,
        }
        return {
            "alive": False,
            "delay": None,
            "status": "failed",
            "status_text": f"不可用：{exc}",
            "test_url": test_url,
            "endpoint": default_endpoint,
            "status_code": None,
            "reason": "",
            "ip_profile": {},
            "connectivity": connectivity,
            "ip_lookup": {
                "alive": False,
                "delay": None,
                "status": "skipped",
                "status_text": "连通性未通过，未查询出口 IP。",
                "endpoint": default_endpoint,
                "lookup_url": "https://ping0.cc/geo",
                "exit_ip": "",
                "ip_profile": {},
            },
        }


def route_status_summary(app_settings: AppSettings, route: RouteSettings) -> dict[str, object]:
    pid = read_pid(route)
    running = pid_matches_mihomo(pid)
    controller_ready = False
    current_proxy = ""
    candidate_count = 0
    alive_count = 0
    if running:
        try:
            upstream = list_upstream_proxies(route)
            controller_ready = True
            current_proxy = str(upstream.get("now", ""))
            candidate_count = len(upstream.get("all", []))
            alive_count = len(upstream.get("alive", []))
        except Exception:  # noqa: BLE001
            controller_ready = False

    return {
        "route_id": route.route_id,
        "name": route.name,
        "running": running,
        "pid": pid or "",
        "controller_ready": controller_ready,
        "current_proxy": current_proxy,
        "candidate_count": candidate_count,
        "alive_count": alive_count,
        "detected_ip": detect_primary_ipv4(),
        "import_link": build_import_link(app_settings, route),
        "config_path": str(route_config_path(route.route_id)),
        "log_path": str(route_log_path(route.route_id)),
        "mihomo_path": str(MIHOMO_BIN),
        "landing_endpoint": f"{route.landing_host}:{route.landing_port}" if route.landing_host and route.landing_port else "",
        "listen_port": route.listen_port,
        "controller_port": route.controller_port,
        "selected_proxy": route.selected_proxy,
    }


def a_inspector_status(app_settings: AppSettings) -> dict[str, object]:
    settings = validate_app_settings(app_settings)
    handle = inspector_handle(settings)
    pid = read_inspector_pid()
    running = pid_matches_mihomo(pid)
    controller_ready = False
    candidate_count = 0
    alive_count = 0
    current_proxy = ""
    if running:
        try:
            upstream = list_upstream_proxies(handle)
            controller_ready = True
            candidate_count = len(upstream.get("all", []))
            alive_count = len(upstream.get("alive", []))
            current_proxy = str(upstream.get("now", ""))
        except Exception:  # noqa: BLE001
            controller_ready = False
    return {
        "running": running,
        "pid": pid or "",
        "controller_ready": controller_ready,
        "candidate_count": candidate_count,
        "alive_count": alive_count,
        "current_proxy": current_proxy,
        "controller_port": settings.inspector_controller_port,
        "provider_path": str(SHARED_PROVIDER_PATH),
        "log_path": str(INSPECTOR_LOG_PATH),
    }


def list_subscription_proxies(app_settings: AppSettings) -> dict[str, object]:
    settings = ensure_a_inspector(app_settings, refresh_subscription=False)
    return list_upstream_proxies(inspector_handle(settings))


def test_subscription_proxy(
    app_settings: AppSettings,
    proxy_name: str,
    test_url: str = HEALTH_CHECK_URL,
    timeout_ms: int = DEFAULT_DELAY_TIMEOUT_MS,
) -> dict[str, object]:
    settings = ensure_a_inspector(app_settings)
    return test_proxy_delay(inspector_handle(settings), proxy_name, test_url, timeout_ms)


def test_all_subscription_proxies(
    app_settings: AppSettings,
    test_url: str = HEALTH_CHECK_URL,
    timeout_ms: int = DEFAULT_DELAY_TIMEOUT_MS,
) -> dict[str, object]:
    settings = ensure_a_inspector(app_settings)
    return test_group_delays(inspector_handle(settings), test_url, timeout_ms)


def dashboard_state(app_settings: AppSettings) -> dict[str, object]:
    settings = validate_app_settings(app_settings)
    route_statuses = {route.route_id: route_status_summary(settings, route) for route in settings.routes}
    return {
        "app_settings": {
            "subscription_url": settings.subscription_url,
            "export_host": settings.export_host,
            "allowed_c_ports": settings.allowed_c_ports,
            "active_route_id": settings.active_route_id,
        },
        "a_inspector": a_inspector_status(settings),
        "routes": [asdict(route) for route in settings.routes],
        "route_statuses": route_statuses,
    }


def read_recent_log(route_id: str, max_lines: int = 120) -> str:
    path = route_log_path(route_id)
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return "\n".join(content[-max_lines:])
