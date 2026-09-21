import asyncio
import json
from typing import Dict, List

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from apps.app.core.settings import settings
from apps.app.modules.monitor.services.monitor_session_service import is_session_token_valid
from apps.app.utils.logger import Logger

router = APIRouter()

AUTH_RECHECK_SECONDS = 30


class ConnectionManager:

    def __init__(self):
        self.connections: List[WebSocket] = []
        self.session_ids: Dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.connections.append(websocket)
        self.session_ids[websocket] = session_id

    async def disconnect(self, websocket: WebSocket):

        if websocket in self.connections:
            self.connections.remove(websocket)
        self.session_ids.pop(websocket, None)

        try:
            await websocket.close()
        except Exception:
            pass

    async def disconnect_all(self):

        connections = list(self.connections)

        for conn in connections:

            try:
                await conn.close()
            except Exception:
                pass

        self.connections.clear()
        self.session_ids.clear()

    async def broadcast(self, message: dict):

        dead_connections = []

        for conn in self.connections:

            try:
                await conn.send_json(message)

            except Exception:
                dead_connections.append(conn)

        for conn in dead_connections:

            if conn in self.connections:
                self.connections.remove(conn)
            self.session_ids.pop(conn, None)


manager = ConnectionManager()

listener_task: asyncio.Task | None = None


async def _redis_invalidation_listener():

    channel = settings.monitor_ws_invalidation_channel

    redis = aioredis.from_url(
        settings.celery_broker_url,
        encoding="utf8",
        decode_responses=True
    )

    pubsub = redis.pubsub()

    await pubsub.subscribe(channel)

    Logger.info(
        f"[monitor.ws] Listening invalidations on channel '{channel}'"
    )

    try:

        while True:

            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1.0
            )

            if message and message.get("data"):
                payload = json.loads(message["data"])
                await manager.broadcast(payload)

            await asyncio.sleep(0.05)

    except asyncio.CancelledError:

        Logger.info(
            "[monitor.ws] Invalidation listener cancelled"
        )

        raise

    finally:

        try:
            await pubsub.unsubscribe(channel)
        except Exception:
            pass

        try:
            await pubsub.aclose()
        except Exception:
            pass

        try:
            await redis.aclose()
        except Exception:
            pass

        await manager.disconnect_all()


async def start_invalidation_listener():

    global listener_task

    if listener_task and not listener_task.done():
        return

    listener_task = asyncio.create_task(
        _redis_invalidation_listener()
    )


async def stop_invalidation_listener():

    global listener_task

    if not listener_task:
        return

    listener_task.cancel()

    try:
        await asyncio.wait_for(listener_task, timeout=3)
    except Exception:
        pass

    listener_task = None


def _is_monitor_token_valid(token: str) -> bool:
    if str(settings.environment).lower() == "local":
        return True
    return is_session_token_valid(token)


@router.websocket("/ws")
async def monitor_websocket_gateway(websocket: WebSocket):

    token = websocket.query_params.get("token")
    if not token or not _is_monitor_token_valid(token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(websocket, token)

    try:

        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_RECHECK_SECONDS)
            except asyncio.TimeoutError:
                if not _is_monitor_token_valid(token):
                    await manager.disconnect(websocket)
                    return

    except WebSocketDisconnect:

        await manager.disconnect(websocket)

    except asyncio.CancelledError:

        await manager.disconnect(websocket)

        raise

    except Exception:

        await manager.disconnect(websocket)
