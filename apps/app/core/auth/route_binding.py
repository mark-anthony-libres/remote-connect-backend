from typing import Optional

from fastapi.routing import APIRoute

from infra.groups import ALL_GROUPS, PERMISSION_OVERRIDE_KEY, SyncGroup

_ROUTE_BINDINGS: dict[str, Optional[str]] = {}


def RouteBuilder(
    parent: Optional[SyncGroup] = None,
    child: Optional[SyncGroup] = None,
    *,
    deep: str,
) -> str:
    if child is not None and parent is None:
        raise ValueError("RouteBuilder: 'child' requires 'parent' to be provided")

    if child is not None and parent.find(child.id) is not child:
        raise ValueError(
            f"RouteBuilder: '{child.id}' is not part of the '{parent.id}' group hierarchy"
        )

    segments = [group.id for group in (parent, child) if group is not None]
    segments.append(deep)
    prefix = "/" + "/".join(segments)

    target = child if child is not None else parent
    target_id = target.id if target is not None else None

    if prefix in _ROUTE_BINDINGS and _ROUTE_BINDINGS[prefix] != target_id:
        raise ValueError(
            f"RouteBuilder: route '{prefix}' is already bound to group '{_ROUTE_BINDINGS[prefix]}'"
        )

    _ROUTE_BINDINGS[prefix] = target_id
    return prefix


def resolve_group_id(path: str, api_prefix: str = "") -> Optional[str]:
    relative = path[len(api_prefix):] if api_prefix and path.startswith(api_prefix) else path

    for segment, group_id in _ROUTE_BINDINGS.items():
        if relative == segment or relative.startswith(segment + "/"):
            return group_id

    for group in ALL_GROUPS:
        segment = f"/{group.id}"
        if relative == segment or relative.startswith(segment + "/"):
            return group.id

    return None


def collect_group_permissions(routes, api_prefix: str = "") -> dict[str, set[str]]:
    permissions: dict[str, set[str]] = {group.id: set() for group in ALL_GROUPS}

    def walk(current_routes, current_prefix: str):
        for route in current_routes:
            if isinstance(route, APIRoute):
                full_path = current_prefix + route.path
                group_id = resolve_group_id(full_path, api_prefix)
                if group_id:
                    override = getattr(route.endpoint, PERMISSION_OVERRIDE_KEY, None)
                    if override:
                        permissions[group_id].add(override)
                    else:
                        permissions[group_id].update(
                            m for m in (route.methods or set()) if m != "HEAD"
                        )
            elif hasattr(route, "original_router"):
                include = route.include_context
                walk(route.original_router.routes, current_prefix + (include.prefix or ""))

    walk(routes, "")
    return permissions
