import asyncio
import logging
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.providers.manager import provider_manager
from app.replay.api import router as replay_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("market_intelligence_backend")

app = FastAPI(title=settings.APP_NAME)
app.include_router(replay_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "https://www.tradingview.com",
    ],
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_event():
    await provider_manager.client.aclose()
    logger.info("httpx client closed cleanly.")

@app.get("/")
async def root():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "docs": "/docs",
        "health": "/health",
        "intelligence": "/api/intelligence?symbol=XAUUSD",
        "websocket": "/ws"
    }

@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME}

@app.get("/api/intelligence")
async def get_intelligence(
    symbol: str = Query("XAUUSD", description="Market symbol"),
    timeframe: str = Query("5M", description="Chart timeframe"),
    price: float = Query(None, description="Optional live chart price override")
):
    data = await provider_manager.get_market_intelligence(symbol, timeframe, override_price=price)
    return data.model_dump(by_alias=True)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    initial_symbol = websocket.query_params.get("symbol", "XAUUSD").upper()
    initial_tf = websocket.query_params.get("timeframe", "5M")
    initial_price_str = websocket.query_params.get("price")
    initial_price = float(initial_price_str) if initial_price_str else None
    
    current_symbol = initial_symbol
    current_timeframe = initial_tf
    logger.info(f"WebSocket connected. Symbol={current_symbol}, TF={current_timeframe}, Price={initial_price}")

    try:
        # Push initial data for connected symbol
        try:
            intel = await provider_manager.get_market_intelligence(current_symbol, current_timeframe, override_price=initial_price)
            await websocket.send_json(intel.model_dump(by_alias=True))
        except WebSocketDisconnect:
            raise
        except Exception as e:
            logger.error(f"Error fetching initial market intelligence for {current_symbol}: {e}", exc_info=True)

        while True:
            try:
                try:
                    data_text = await asyncio.wait_for(websocket.receive_text(), timeout=3.0)
                    try:
                        msg = json.loads(data_text)
                        action = msg.get("action")
                        if action in ["SUBSCRIBE", "TICK", "PRICE_UPDATE"]:
                            new_sym = msg.get("symbol")
                            new_tf = msg.get("timeframe", current_timeframe)
                            p_val = msg.get("price")
                            try:
                                p_float = float(p_val) if p_val else None
                                if p_float is not None and p_float <= 0:
                                    p_float = None
                            except (ValueError, TypeError):
                                p_float = None

                            if new_sym:
                                current_symbol = new_sym.upper()
                                current_timeframe = new_tf
                                logger.info(f"WS updated: symbol={current_symbol}, tf={current_timeframe}, price={p_float}")

                            try:
                                intel = await provider_manager.get_market_intelligence(current_symbol, current_timeframe, override_price=p_float)
                                await websocket.send_json(intel.model_dump(by_alias=True))
                            except WebSocketDisconnect:
                                raise
                            except Exception as e:
                                logger.error(f"Error fetching/sending market intelligence on WS update for {current_symbol}: {e}", exc_info=True)
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning(f"Bad WS message from client: {e}")

                except asyncio.TimeoutError:
                    # Periodic push for current_symbol (remembers subscribed symbol!)
                    try:
                        intel = await provider_manager.get_market_intelligence(current_symbol, current_timeframe)
                        await websocket.send_json(intel.model_dump(by_alias=True))
                    except WebSocketDisconnect:
                        raise
                    except Exception as e:
                        logger.error(f"Error in periodic market intelligence push for {current_symbol}: {e}", exc_info=True)

            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected: symbol={current_symbol}")
                break
            except Exception as loop_err:
                logger.error(f"Transient error in WS loop for {current_symbol}: {loop_err}", exc_info=True)
                await asyncio.sleep(0.5)

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: symbol={current_symbol}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        logger.info(f"WebSocket cleanup complete for {current_symbol}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)

