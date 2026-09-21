from fastapi import APIRouter, Body, Depends, HTTPException, status

from apps.app.core import services
from apps.app.core.auth.dependencies import get_current_user
from apps.app.core.errors import handle_route_errors
from apps.app.modules.user.entities.user_entity import User
from apps.app.modules.user.service import user_log_service
from datetime import datetime

router = APIRouter(prefix="/user-log")


@router.get("")
@handle_route_errors(context="User page access logs retrieval failed")
def all(user: User = Depends(get_current_user)):
    user_page_access_logs = services.call(user_log_service.get_current_user_page_access_logs, user.id)
    if user_page_access_logs is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User session not found")
    return {"data": user_page_access_logs}


@router.post("/create", status_code=status.HTTP_201_CREATED)
@handle_route_errors(context="User page access log creation failed")
def create_user_page_access_log(
    user_page_access_log_data: dict = Body(default={}),
    user: User = Depends(get_current_user),
):
    resolved_session_id = services.call(user_log_service.resolve_active_session_id, user.id)
    if not resolved_session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User session not found")

    user_page_access_log_data["user_session_id"] = resolved_session_id
    user_page_access_log_data["access_datetime"] = datetime.now()

    services.call(user_log_service.record_user_page_access_log, user_page_access_log_data)
    return {"message": "User page access log created successfully"}
