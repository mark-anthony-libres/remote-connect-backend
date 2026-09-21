import asyncio
import json
import os
from typing import Dict, List

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from apps.app.core.auth.access_token import get_bearer_token
from apps.app.modules.auth.service import auth_service
from apps.app.utils.logger import Logger
from apps.app.core.settings import settings

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
        except:
            pass

    async def close_session(self, session_id: str):
        matches = [ws for ws, sid in self.session_ids.items() if sid == session_id]
        for ws in matches:
            await self.disconnect(ws)

    async def disconnect_all(self):

        connections = list(self.connections)

        for conn in connections:

            try:
                await conn.close()
            except:
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

    channel = settings.ws_invalidation_channel

    redis = aioredis.from_url(
        settings.celery_broker_url,
        encoding="utf8",
        decode_responses=True
    )

    pubsub = redis.pubsub()

    await pubsub.subscribe(channel)

    Logger.info(
        f"[WS] Listening invalidations on channel '{channel}'"
    )

    try:

        while True:

            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1.0
            )

            if message and message.get("data"):

                payload = json.loads(message["data"])

                if payload.get("type") == "revoke_session":
                    await manager.close_session(payload.get("session_id"))
                else:
                    await manager.broadcast(payload)

            await asyncio.sleep(0.05)

    except asyncio.CancelledError:

        Logger.info(
            "[WS] Invalidation listener cancelled"
        )

        raise

    finally:

        try:
            await pubsub.unsubscribe(channel)
        except:
            pass

        try:
            await pubsub.aclose()
        except:
            pass

        try:
            await redis.aclose()
        except:
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
    except:
        pass

    listener_task = None


@router.websocket("/ws")
async def websocket_gateway(websocket: WebSocket):

    token = get_bearer_token(websocket)
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        authenticated = auth_service.authenticate(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    connection_key = (
        str(authenticated.session.id)
        if authenticated.session is not None
        else f"impersonation:{authenticated.impersonation.impersonation_id}"
    )
    await manager.connect(websocket, connection_key)

    try:

        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_RECHECK_SECONDS)
            except asyncio.TimeoutError:
                try:
                    auth_service.authenticate(token)
                except Exception:
                    await manager.disconnect(websocket)
                    return

    except WebSocketDisconnect:

        await manager.disconnect(websocket)

    except asyncio.CancelledError:

        await manager.disconnect(websocket)

        raise

    except Exception:

        await manager.disconnect(websocket)