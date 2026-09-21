from fastapi import APIRouter, Request, Depends
from apps.app.core import services
from apps.app.core.errors import handle_route_errors
from apps.app.core.auth.decorators import Token, CurrentUser
from apps.app.core.auth.tokens import decode_token
from apps.app.modules.user.entities.user_entity import User
from apps.app.modules.user.service import user_log_service
from fastapi import Query
from datetime import datetime
from typing import Optional
from infra.groups import g_user

router = APIRouter(prefix=f"/{g_user.id}")
@router.get("/performance-indicators")
@handle_route_errors(context="Performance indicators failed")
def performance_indicators(request: Request, user: User = Depends(CurrentUser)):
  performance_indicators = services.call(user_log_service.get_performance_indicators, user=user)
  return {"data": performance_indicators}


@router.get("/top-active-users")
@handle_route_errors(context="Top active users failed")
def top_active_users(request: Request, token: str = Depends(Token)):
  top_active_users = services.call(user_log_service.get_top_active_users)
  return {"data": top_active_users}


@router.get("/daily-login-trends")
@handle_route_errors(context="Daily login trends failed")
def daily_login_trends(request: Request, token: str = Depends(Token), from_date: Optional[datetime] = Query(default=None), to_date: Optional[datetime] = Query(default=None)):
  payload = decode_token(token)
  user_id = payload.get("sub") if payload.get("sub") else None
  daily_login_trends = services.call(user_log_service.get_daily_login_trends, from_date=from_date, to_date=to_date, user_id=user_id)
  return {"data": daily_login_trends}


@router.get("/recent-login-history")
@handle_route_errors(context="Recent login history failed")
def recent_login_history(
  request: Request,
  token: str = Depends(Token),
  user: User = Depends(CurrentUser),
  keyword: str = Query(default=""),
  from_date: Optional[datetime] = Query(default=None),
  to_date: Optional[datetime] = Query(default=None),
  page: int = Query(default=1, ge=1),
  page_size: int = Query(default=10, ge=1, le=100),
):
  recent_login_history = services.call(
    user_log_service.get_recent_login_history,
    keyword=keyword, from_date=from_date, to_date=to_date, user=user, page=page, page_size=page_size
  )
  return recent_login_history


@router.get("/most-visited-pages")
@handle_route_errors(context="Most visited pages failed")
def most_visited_pages(request: Request, token: str = Depends(Token)):
  most_visited_pages = services.call(user_log_service.get_most_visited_pages)
  return {"data": most_visited_pages}

@router.get("/sessions-by-role")
@handle_route_errors(context="Sessions by role failed")
def sessions_by_role(request: Request, token: str = Depends(Token)):
  sessions_by_role = services.call(user_log_service.get_sessions_by_role)
  return {"data": sessions_by_role}
