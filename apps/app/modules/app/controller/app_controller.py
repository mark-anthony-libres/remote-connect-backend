from time import sleep

from fastapi import APIRouter, Request

from apps.app.core.errors import handle_route_errors
from apps.app.core.settings import settings
from infra.groups import ALL_GROUPS
from apps.app.core.auth.route_binding import collect_group_permissions
from apps.app.modules.role.service.group_hierarchy import get_parent_id

router = APIRouter(prefix="/app")


@router.get("/groups")
@handle_route_errors(context="Groups retrieval failed")
def list_groups(request: Request):
    permissions = collect_group_permissions(request.app.routes, settings.api_prefix or "")
    data = [
        {
            "id": group.id,
            "name": group.name,
            "details": group.description,
            "icon": group.icon,
            "parent_id": get_parent_id(group.id),
            "permissions": sorted(permissions.get(group.id, set())),
        }
        for group in ALL_GROUPS
    ]
    return {"data": data}
