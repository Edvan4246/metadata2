"""REST API routes for bot control and monitoring."""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBearer(auto_error=False)


def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if settings.api_secret_key == "changeme":
        return True  # skip auth in dev
    if not credentials or credentials.credentials != settings.api_secret_key:
        raise HTTPException(status_code=401, detail="Invalid token")
    return True


# Bot reference is injected at startup
_bot = None

def set_bot(bot):
    global _bot
    _bot = bot


class RiskConfig(BaseModel):
    max_risk_per_trade: Optional[float] = None
    max_daily_drawdown: Optional[float] = None
    max_open_positions: Optional[int] = None


@router.get("/status", dependencies=[Depends(verify_token)])
async def get_status():
    if _bot is None:
        return {"running": False, "error": "bot_not_initialized"}
    return _bot.get_state()


@router.get("/positions", dependencies=[Depends(verify_token)])
async def get_positions():
    if _bot is None:
        raise HTTPException(503, "Bot not initialized")
    return _bot.get_state()["positions"]


@router.get("/signals", dependencies=[Depends(verify_token)])
async def get_signals():
    if _bot is None:
        raise HTTPException(503, "Bot not initialized")
    return _bot.get_state()["signals"]


@router.get("/account", dependencies=[Depends(verify_token)])
async def get_account():
    if _bot is None:
        raise HTTPException(503, "Bot not initialized")
    return _bot.get_state()["account"]


@router.get("/risk", dependencies=[Depends(verify_token)])
async def get_risk():
    if _bot is None:
        raise HTTPException(503, "Bot not initialized")
    return _bot.get_state()["risk"]


@router.post("/start", dependencies=[Depends(verify_token)])
async def start_bot():
    if _bot is None:
        raise HTTPException(503, "Bot not initialized")
    if _bot._running:
        return {"status": "already_running"}
    import asyncio
    asyncio.create_task(_bot.start())
    return {"status": "started"}


@router.post("/stop", dependencies=[Depends(verify_token)])
async def stop_bot():
    if _bot is None:
        raise HTTPException(503, "Bot not initialized")
    await _bot.stop()
    return {"status": "stopped"}


@router.post("/close-all", dependencies=[Depends(verify_token)])
async def close_all(symbol: Optional[str] = None):
    if _bot is None:
        raise HTTPException(503, "Bot not initialized")
    _bot.order_mgr.close_all(symbol)
    return {"status": "closed", "symbol": symbol or "all"}


@router.post("/risk/resume", dependencies=[Depends(verify_token)])
async def resume_risk():
    if _bot is None:
        raise HTTPException(503, "Bot not initialized")
    _bot.risk_manager.resume()
    return {"status": "resumed"}


@router.post("/retrain", dependencies=[Depends(verify_token)])
async def retrain_models():
    if _bot is None:
        raise HTTPException(503, "Bot not initialized")
    await _bot._retrain_models()
    return {"status": "retrained"}
