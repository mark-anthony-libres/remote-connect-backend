import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from apps.app.modules.device.services.device_identity_service import DeviceIdentityService
from apps.app.utils.logger import Logger

router = APIRouter()

FIRST_MESSAGE_TIMEOUT_SECONDS = 10

# Minimal registry keyed by device_code. Not consumed by anything yet — this is
# the hook point for a future feature (e.g. pushing an incoming-connection
# notification to a specific device). Deliberately not a full ConnectionManager
# class until something needs broadcast()/close_session()-style behavior.
_connections: dict[str, WebSocket] = {}


@router.websocket("/ws/device")
async def device_identity_gateway(websocket: WebSocket):
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_json(), timeout=FIRST_MESSAGE_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, WebSocketDisconnect, json.JSONDecodeError, ValueError):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    install_key = raw.get("install_key") if isinstance(raw, dict) else None
    device_name = raw.get("device_name") if isinstance(raw, dict) else None
    if install_key is not None and not isinstance(install_key, str):
        install_key = None

    try:
        device = DeviceIdentityService().get_or_create_device(
            install_key=install_key, device_name=device_name
        )
    except Exception as exc:
        Logger.error(f"[device.ws] handshake failed: {exc}")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    response = {"type": "device_identity", "device_id": device.device_code}
    if install_key != device.install_key:
        response["install_key"] = device.install_key
    await websocket.send_json(response)

    _connections[device.device_code] = websocket

    try:
        while True:
            await websocket.receive_text()  # connection kept open; no messages handled yet
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    finally:
        if _connections.get(device.device_code) is websocket:
            _connections.pop(device.device_code, None)
