from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status

from apps.app.core.auth.access_token import is_impersonation_worker, set_access_token_cookie
from apps.app.core.auth.decorators import AdminOnlyAccess, ImpersonationAuthBypass
from apps.app.core.auth.dependencies import get_current_impersonation, get_current_user
from apps.app.core.auth.tokens import create_impersonation_token
from apps.app.core import db_guard
from apps.app.core.errors import handle_route_errors
from apps.app.modules.impersonation.service import impersonation_lock as lock
from apps.app.modules.impersonation.service import impersonation_provider
from apps.app.modules.impersonation.service import impersonation_service as service
from apps.app.modules.user.repositories.users_repository import UsersRepository
from database.session_factory import get_session

router = APIRouter(prefix="/impersonation")

db_guard.install()

impersonation_provider.install()


def _require_dedicated_worker() -> None:
    if not is_impersonation_worker():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This request must go through the dedicated impersonation "
                "worker (see docker-compose.yml: impersonation-worker), not "
                "a normal application worker. This is what proves normal "
                "load-balanced traffic cannot accidentally continue someone "
                "else's impersonation transaction."
            ),
        )


@router.post("/start")
@ImpersonationAuthBypass()
@AdminOnlyAccess()
@handle_route_errors(context="Impersonation start failed")
def start_impersonation(
    request: Request,
    response: Response,
    body: dict = Body(default={}),
    user=Depends(get_current_user),
):
    _require_dedicated_worker()
    target_user_id = body.get("target_user_id")
    if not target_user_id:
        raise HTTPException(status_code=400, detail="target_user_id is required")

    with get_session()() as session:
        target_user = UsersRepository(session).get_by_id(int(target_user_id))
    if target_user is None:
        raise HTTPException(status_code=404, detail=f"No user found with id {target_user_id}")

    ttl_seconds = int(body.get("ttl_seconds") or lock.IMPERSONATION_MAX_DURATION_SECONDS)
    data = service.start_impersonation(
        admin_user_id=user.id, target_user_id=int(target_user_id), ttl_seconds=ttl_seconds
    )

    token = create_impersonation_token(
        target_user_id=int(target_user_id),
        admin_id=user.id,
        impersonation_id=data["impersonation_id"],
        ttl_seconds=data["ttl_seconds"],
        admin_session_id=request.state.session_id,
    )
    set_access_token_cookie(response, token, max_age_seconds=data["ttl_seconds"])

    return {"data": data}


def _require_active_impersonation(impersonation):
    if impersonation is None:
        raise HTTPException(
            status_code=400,
            detail="This request must be made with an active impersonation token.",
        )
    return impersonation


@router.post("/update")
@handle_route_errors(context="Impersonation update failed")
def update(
    body: dict = Body(default={}),
    impersonation=Depends(get_current_impersonation),
):
    _require_dedicated_worker()
    impersonation = _require_active_impersonation(impersonation)
    name = body.get("name")
    value = body.get("value")
    if not name or value is None:
        raise HTTPException(status_code=400, detail="name and value are required")
    data = service.update_record(
        impersonation_id=impersonation.impersonation_id,
        admin_user_id=impersonation.admin_id,
        name=name,
        value=int(value),
    )
    return {"data": data}


@router.post("/update-again")
@handle_route_errors(context="Impersonation update failed")
def update_again(
    body: dict = Body(default={}),
    impersonation=Depends(get_current_impersonation),
):
    _require_dedicated_worker()
    impersonation = _require_active_impersonation(impersonation)
    name = body.get("name")
    delta = body.get("delta")
    if not name or delta is None:
        raise HTTPException(status_code=400, detail="name and delta are required")
    data = service.adjust_record(
        impersonation_id=impersonation.impersonation_id,
        admin_user_id=impersonation.admin_id,
        name=name,
        delta=int(delta),
    )
    return {"data": data}


@router.get("/state")
@ImpersonationAuthBypass()
@handle_route_errors(context="Impersonation state retrieval failed")
def get_impersonation_info(
    impersonation=Depends(get_current_impersonation),
    user=Depends(get_current_user),
):
    if impersonation is not None:
        _require_dedicated_worker()
        data = service.get_impersonation_info(
            impersonation_id=impersonation.impersonation_id,
            admin_user_id=impersonation.admin_id,
        )
        return {"data": data}

    data = service.get_impersonation_status_for_admin(admin_user_id=user.id)
    return {"data": data}


@router.post("/force-end")
@ImpersonationAuthBypass()
@AdminOnlyAccess()
@handle_route_errors(context="Impersonation force-end failed")
def force_end_impersonation(
    user=Depends(get_current_user),
):
    data = service.force_end_impersonation(admin_user_id=user.id)
    return {"data": data}


@router.post("/logout")
@handle_route_errors(context="Impersonation logout failed")
def logout(
    response: Response,
    impersonation=Depends(get_current_impersonation),
):
    _require_dedicated_worker()
    impersonation = _require_active_impersonation(impersonation)
    data = service.logout(
        impersonation_id=impersonation.impersonation_id,
        admin_user_id=impersonation.admin_id,
    )

    new_admin_token = service.reissue_admin_token(impersonation.admin_id, impersonation.admin_session_id)
    if new_admin_token:
        set_access_token_cookie(response, new_admin_token)

    return {"data": data}
