from __future__ import annotations

import traceback
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import gateway_multi as gateway
from .auth import require_api_login, require_page_login, verify_credentials
from .config import CONFIG


app = FastAPI(
    title=CONFIG.app_name,
    docs_url="/docs" if CONFIG.enable_docs else None,
    openapi_url="/openapi.json" if CONFIG.enable_docs else None,
    redoc_url=None,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=CONFIG.session_secret,
    same_site="lax",
    https_only=CONFIG.base_url.strip().lower().startswith("https://"),
)

templates = Jinja2Templates(directory=str(gateway.ROOT_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(gateway.ROOT_DIR / "static")), name="static")


def json_ok(**payload: Any) -> JSONResponse:
    return JSONResponse({"ok": True, **payload})


def json_error(exc: Exception, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": str(exc), "detail": "".join(traceback.format_exception_only(type(exc), exc)).strip()},
        status_code=status_code,
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "app_name": CONFIG.app_name})


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if not verify_credentials(username, password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "app_name": CONFIG.app_name, "error": "用户名或密码错误。"},
            status_code=401,
        )
    request.session["logged_in"] = True
    request.session["username"] = username
    return RedirectResponse(url="/", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
@require_page_login
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "app_name": CONFIG.app_name,
            "default_test_url": CONFIG.test_url,
            "default_timeout_ms": CONFIG.test_timeout_ms,
            "username": request.session.get("username", CONFIG.admin_username),
        },
    )


@app.on_event("startup")
async def cleanup_stale_runtime() -> None:
    try:
        killed = gateway.cleanup_stale_processes()
        restored = gateway.restore_tracked_processes()
        if killed or restored:
            print(f"[startup] cleaned stale mihomo pids={killed}, restored={restored}")
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] stale mihomo cleanup skipped: {exc}")


@app.get("/api/state")
async def api_state(request: Request):
    require_api_login(request)
    settings = gateway.load_settings()
    return json_ok(state=gateway.dashboard_state(settings))


@app.post("/api/settings/global")
async def api_save_global_settings(request: Request):
    require_api_login(request)
    payload = await request.json()
    try:
        settings = gateway.load_settings()
        updated = gateway.update_global_settings(settings, payload)
        return json_ok(state=gateway.dashboard_state(updated))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.post("/api/routes/create")
async def api_create_route(request: Request):
    require_api_login(request)
    payload = await request.json()
    try:
        settings = gateway.load_settings()
        updated = gateway.add_route(settings, str(payload.get("source_route_id") or "").strip() or None)
        return json_ok(state=gateway.dashboard_state(updated))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.post("/api/routes/save")
async def api_save_route(request: Request):
    require_api_login(request)
    payload = await request.json()
    try:
        settings = gateway.load_settings()
        updated = gateway.update_route(settings, payload)
        return json_ok(state=gateway.dashboard_state(updated))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.post("/api/routes/delete")
async def api_delete_route(request: Request):
    require_api_login(request)
    payload = await request.json()
    try:
        settings = gateway.load_settings()
        updated = gateway.delete_route(settings, str(payload.get("route_id") or "").strip())
        return json_ok(state=gateway.dashboard_state(updated))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.post("/api/routes/activate")
async def api_activate_route(request: Request):
    require_api_login(request)
    payload = await request.json()
    try:
        settings = gateway.load_settings()
        updated = gateway.set_active_route(settings, str(payload.get("route_id") or "").strip())
        return json_ok(state=gateway.dashboard_state(updated))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.post("/api/core/install")
async def api_install_core(request: Request):
    require_api_login(request)
    logs: list[str] = []
    try:
        version = gateway.ensure_mihomo(logs.append)
        return json_ok(version=version, logs=logs)
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.post("/api/subscription/refresh")
async def api_refresh_subscription(request: Request):
    require_api_login(request)
    logs: list[str] = []
    try:
        settings = gateway.load_settings()
        updated = gateway.start_a_inspector(settings, logs.append)
        return json_ok(logs=logs, state=gateway.dashboard_state(updated))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.get("/api/a/proxies")
async def api_a_proxies(request: Request):
    require_api_login(request)
    try:
        settings = gateway.load_settings()
        return json_ok(proxies=gateway.list_subscription_proxies(settings), state=gateway.dashboard_state(settings))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.post("/api/a/proxies/test")
async def api_test_a_proxy(request: Request):
    require_api_login(request)
    payload = await request.json()
    try:
        settings = gateway.load_settings()
        proxy_name = str(payload.get("proxy_name") or "").strip()
        test_url = str(payload.get("test_url") or CONFIG.test_url).strip()
        timeout_ms = int(payload.get("timeout_ms") or CONFIG.test_timeout_ms)
        return json_ok(result=gateway.test_subscription_proxy(settings, proxy_name, test_url, timeout_ms))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.post("/api/a/proxies/test-all")
async def api_test_all_a_proxies(request: Request):
    require_api_login(request)
    payload = await request.json()
    try:
        settings = gateway.load_settings()
        test_url = str(payload.get("test_url") or CONFIG.test_url).strip()
        timeout_ms = int(payload.get("timeout_ms") or CONFIG.test_timeout_ms)
        return json_ok(result=gateway.test_all_subscription_proxies(settings, test_url, timeout_ms))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.post("/api/a/inspector/start")
async def api_start_a_inspector(request: Request):
    require_api_login(request)
    logs: list[str] = []
    try:
        settings = gateway.load_settings()
        updated = gateway.start_a_inspector(settings, logs.append)
        return json_ok(logs=logs, state=gateway.dashboard_state(updated))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.post("/api/core/start")
async def api_start_core(request: Request):
    require_api_login(request)
    payload = await request.json()
    logs: list[str] = []
    try:
        settings = gateway.load_settings()
        updated = gateway.start_route(settings, str(payload.get("route_id") or "").strip(), logs.append)
        return json_ok(logs=logs, state=gateway.dashboard_state(updated))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.post("/api/core/stop")
async def api_stop_core(request: Request):
    require_api_login(request)
    payload = await request.json()
    try:
        settings = gateway.load_settings()
        route = settings.get_route(str(payload.get("route_id") or "").strip())
        gateway.stop_route(route)
        return json_ok(state=gateway.dashboard_state(settings))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.get("/api/proxies")
async def api_proxies(request: Request, route_id: str):
    require_api_login(request)
    try:
        settings = gateway.load_settings()
        route = settings.get_route(route_id)
        return json_ok(proxies=gateway.list_upstream_proxies(route))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.post("/api/proxies/select")
async def api_select_proxy(request: Request):
    require_api_login(request)
    payload = await request.json()
    try:
        settings = gateway.load_settings()
        updated = gateway.select_upstream_proxy(
            settings,
            str(payload.get("route_id") or "").strip(),
            str(payload.get("proxy_name") or "").strip(),
        )
        route = updated.get_route(str(payload.get("route_id") or "").strip())
        return json_ok(proxies=gateway.list_upstream_proxies(route), state=gateway.dashboard_state(updated))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.post("/api/proxies/test")
async def api_test_proxy(request: Request):
    require_api_login(request)
    payload = await request.json()
    try:
        settings = gateway.load_settings()
        route = settings.get_route(str(payload.get("route_id") or "").strip())
        proxy_name = str(payload.get("proxy_name") or "").strip()
        test_url = str(payload.get("test_url") or CONFIG.test_url).strip()
        timeout_ms = int(payload.get("timeout_ms") or CONFIG.test_timeout_ms)
        return json_ok(result=gateway.test_proxy_delay(route, proxy_name, test_url, timeout_ms))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.post("/api/proxies/test-all")
async def api_test_all_proxies(request: Request):
    require_api_login(request)
    payload = await request.json()
    try:
        settings = gateway.load_settings()
        route = settings.get_route(str(payload.get("route_id") or "").strip())
        test_url = str(payload.get("test_url") or CONFIG.test_url).strip()
        timeout_ms = int(payload.get("timeout_ms") or CONFIG.test_timeout_ms)
        return json_ok(result=gateway.test_group_delays(route, test_url, timeout_ms))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.post("/api/gateway/test")
async def api_test_gateway(request: Request):
    require_api_login(request)
    payload = await request.json()
    try:
        settings = gateway.load_settings()
        test_url = str(payload.get("test_url") or CONFIG.test_url).strip()
        timeout_ms = int(payload.get("timeout_ms") or CONFIG.test_timeout_ms)
        route_id = str(payload.get("route_id") or "").strip()
        return json_ok(result=gateway.test_gateway_link(settings, route_id, test_url, timeout_ms))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.post("/api/landing/test")
async def api_test_landing(request: Request):
    require_api_login(request)
    payload = await request.json()
    try:
        settings = gateway.load_settings()
        test_url = str(payload.get("test_url") or CONFIG.test_url).strip()
        timeout_ms = int(payload.get("timeout_ms") or CONFIG.test_timeout_ms)
        route_id = str(payload.get("route_id") or "").strip()
        return json_ok(result=gateway.test_landing_link(settings, route_id, test_url, timeout_ms))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)


@app.get("/api/logs")
async def api_logs(request: Request, route_id: str):
    require_api_login(request)
    try:
        return json_ok(log=gateway.read_recent_log(route_id))
    except Exception as exc:  # noqa: BLE001
        return json_error(exc)
