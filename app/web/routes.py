"""FastAPI routes and page rendering."""

from __future__ import annotations

import json
import base64
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.config import get_settings
from app.errors import BadRequestError, NotFoundError
from app.models import (
    AccountPreferencesRequest,
    AccountImportRequest,
    CaptchaVerifyPayloadRequest,
    CreateQrRequest,
    ManualCaptchaRequest,
    NetworkModeRequest,
    PreviewPaymentRequest,
    PreviewSeedRequest,
)
from app.runtime_logging import LOG_STREAM_ACCOUNT, LOG_STREAM_CAPTCHA, LOG_STREAM_GLOBAL, get_runtime_log_service
from app.services.global_settings_service import get_global_settings_service
from app.proxy_pool.service import (
    get_builtin_proxy_pool_service,
    load_proxy_pool_config,
    resolve_config_path,
)
from app.services.payment_service import get_payment_service
from app.services.network_mode_service import get_network_mode_service

router = APIRouter()
payment_service = get_payment_service()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
SPA_INDEX = Path(__file__).resolve().parents[2] / "web" / "dist" / "index.html"


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    if SPA_INDEX.exists():
        return FileResponse(SPA_INDEX)
    return render_legacy_index(request)


@router.get("/legacy", response_class=HTMLResponse)
def legacy_index(request: Request):
    return render_legacy_index(request)


def render_legacy_index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "transport_name": payment_service.health_payload()["transport"],
        },
    )


@router.get("/healthz")
def healthz():
    return success(payment_service.health_payload())


@router.get("/api/network-mode")
def get_network_mode():
    return success(get_network_mode_service().status_payload())


@router.patch("/api/network-mode")
def update_network_mode(payload: NetworkModeRequest):
    return success(get_network_mode_service().set_mode(payload.mode))


@router.get("/api/settings")
def get_settings_payload():
    return success(get_global_settings_service().get().to_dict())


@router.patch("/api/settings")
def update_settings_payload(payload: dict[str, Any]):
    return success(get_global_settings_service().update(payload).to_dict())

class ProxyPoolSourcesRequest(BaseModel):
    content: str = ""


def _resolve_proxy_source_path() -> Path | None:
    """返回 proxy_pool.yaml 中第一个本地代理源文件的绝对路径。"""
    try:
        config = load_proxy_pool_config(resolve_config_path())
    except Exception:
        return None
    for source in config.proxy_list_urls:
        if source.startswith(("http://", "https://")):
            continue
        candidate = Path(source).expanduser()
        if not candidate.is_absolute():
            candidate = config.source_base_dir / candidate
        return candidate
    return None


@router.get("/api/proxy-pool/sources")
def get_proxy_pool_sources():
    """读取本地代理源文件内容（默认 good_proxies.txt）。"""
    path = _resolve_proxy_source_path()
    content = path.read_text(encoding="utf-8") if path and path.exists() else ""
    return success(
        {
            "path": str(path) if path else "",
            "exists": bool(path and path.exists()),
            "content": content,
        }
    )


@router.put("/api/proxy-pool/sources")
def save_proxy_pool_sources(payload: ProxyPoolSourcesRequest):
    """保存代理源；代理池在运行时后台刷新加载新代理。"""
    path = _resolve_proxy_source_path()
    if path is None:
        raise BadRequestError("未找到可编辑的本地代理源：proxy_pool.yaml 未配置本地文件源")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload.content, encoding="utf-8")
    service = get_builtin_proxy_pool_service()
    refreshed = False
    if service.is_started:
        threading.Thread(
            target=service.refresh_once,
            name="proxy-pool-refresh-on-save",
            daemon=True,
        ).start()
        refreshed = True
    return success({"path": str(path), "refreshed": refreshed})


@router.get("/api/logs/today")
def get_today_logs(
    account_id: str | None = Query(default=None),
    stream: str = Query(default=LOG_STREAM_GLOBAL),
    limit: int = Query(default=500, ge=1, le=2000),
):
    settings = get_settings()
    date_part = datetime.now().astimezone().strftime("%Y-%m-%d")
    runtime_logs = get_runtime_log_service()
    payload = runtime_logs.read_logs(
        date=date_part,
        stream=stream,
        account_id=account_id,
        limit=limit,
    )
    parsed = [runtime_logs.format_log_line(line) for line in reversed(payload["lines"])]
    parsed = [item for item in parsed if item is not None]
    return success(
        {
            "date": date_part,
            "path": payload["path"],
            "stream": stream,
            "account_id": account_id,
            "entries": parsed,
            "truncated": payload["truncated"],
            "total": payload["total"],
        }
    )


@router.get("/api/logs/streams")
def list_log_streams():
    return success(
        {
            "streams": [
                {"value": LOG_STREAM_GLOBAL, "label": "全局日志"},
                {"value": LOG_STREAM_ACCOUNT, "label": "账号日志"},
                {"value": LOG_STREAM_CAPTCHA, "label": "验证码日志"},
            ]
        }
    )


@router.get("/api/accounts")
def list_accounts():
    return success(payment_service.list_accounts())


@router.post("/api/accounts/import")
def import_account(payload: AccountImportRequest):
    return success(payment_service.import_account(payload))


@router.get("/api/accounts/{account_id}")
def get_account(account_id: str):
    return success(payment_service.get_account_detail(account_id))


@router.delete("/api/accounts/{account_id}")
def delete_account(account_id: str):
    return success(payment_service.delete_account(account_id))


@router.patch("/api/accounts/{account_id}")
def update_account_preferences(account_id: str, payload: AccountPreferencesRequest):
    return success(payment_service.update_preferences(account_id, payload))


@router.post("/api/accounts/{account_id}/bootstrap")
def bootstrap_account(account_id: str, refresh_fingerprint: bool = Query(default=False)):
    return success(payment_service.bootstrap_account(account_id, refresh_fingerprint=refresh_fingerprint))


@router.get("/api/accounts/{account_id}/products")
def get_products(account_id: str):
    return success(payment_service.load_products(account_id))


@router.post("/api/accounts/{account_id}/captcha")
def save_captcha(account_id: str, payload: ManualCaptchaRequest):
    return success(payment_service.save_manual_captcha(account_id, payload))


@router.get("/api/accounts/{account_id}/captcha/challenge")
def get_captcha_challenge(account_id: str, analyze: bool = Query(default=True)):
    return success(payment_service.fetch_captcha_challenge(account_id, analyze=analyze))


@router.get("/api/accounts/{account_id}/captcha/tdc")
def collect_captcha_tdc(account_id: str):
    return success(payment_service.collect_captcha_tdc(account_id))


@router.post("/api/accounts/{account_id}/captcha/verify-payload")
def build_captcha_verify_payload(account_id: str, payload: CaptchaVerifyPayloadRequest):
    return success(payment_service.build_captcha_verify_payload(account_id, payload))


@router.post("/api/accounts/{account_id}/captcha/verify")
def submit_captcha_verify(account_id: str, payload: CaptchaVerifyPayloadRequest):
    return success(payment_service.submit_captcha_verify(account_id, payload))


@router.post("/api/accounts/{account_id}/captcha/solve")
def solve_captcha(account_id: str):
    return success(payment_service.solve_captcha(account_id))


@router.post("/api/accounts/{account_id}/payments/preview")
def preview_payment(account_id: str, payload: PreviewPaymentRequest):
    return success(payment_service.preview_payment(account_id, payload))


@router.post("/api/accounts/{account_id}/payments/preview/seed")
def seed_preview_payment(account_id: str, payload: PreviewSeedRequest):
    return success(payment_service.seed_preview(account_id, payload))


@router.post("/api/accounts/{account_id}/payments/qr")
def create_qr(account_id: str, payload: CreateQrRequest):
    return success(payment_service.create_qr(account_id, payload))



@router.post("/api/accounts/{account_id}/stock-monitor/start")
def start_stock_monitor(account_id: str):
    from app.services.scheduler_service import get_scheduler_service

    return success(get_scheduler_service().start_stock_monitor(account_id))


@router.post("/api/accounts/{account_id}/stock-monitor/stop")
def stop_stock_monitor(account_id: str):
    from app.services.scheduler_service import get_scheduler_service

    return success(get_scheduler_service().stop_stock_monitor(account_id))


@router.get("/api/accounts/{account_id}/tickets")
def get_ticket_pool(account_id: str):
    return success(payment_service.get_ticket_pool(account_id))


@router.delete("/api/accounts/{account_id}/tickets")
def clear_ticket_pool(account_id: str):
    return success(payment_service.clear_ticket_pool(account_id))


@router.post("/api/accounts/{account_id}/pause")
def pause_account_flow(account_id: str):
    from app.services.scheduler_service import get_scheduler_service

    return success(get_scheduler_service().request_pause(account_id))


@router.get("/api/accounts/{account_id}/payments/check/{biz_id}")
def check_payment(account_id: str, biz_id: str):
    return success(payment_service.check_payment(account_id, biz_id))


@router.get("/api/accounts/{account_id}/tasks")
def list_tasks(account_id: str):
    return success(payment_service.list_tasks(account_id))


@router.get("/api/accounts/{account_id}/tasks/{task_id}/qr.png")
def get_task_qr_image(account_id: str, task_id: str):
    task = next((item for item in payment_service.list_tasks(account_id) if item.id == task_id), None)
    if task is None or not task.qr_base64:
        raise NotFoundError("二维码不存在", details={"account_id": account_id, "task_id": task_id})
    return Response(
        content=_decode_qr_base64(task.qr_base64),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


def success(data: Any) -> dict[str, Any]:
    """Wrap success payloads consistently."""
    return {"ok": True, "data": data}


def _decode_qr_base64(value: str) -> bytes:
    payload = (value or "").strip()
    if "," in payload:
        payload = payload.split(",", 1)[1]
    return base64.b64decode(payload)
