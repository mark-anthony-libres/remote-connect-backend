
from dataclasses import dataclass, field
from typing import Optional

PERMISSION_OVERRIDE_KEY = "permission_override"


@dataclass(frozen=True)
class SyncGroup:
    id: str
    name: str
    description: str
    icon: str
    items: dict[str, "SyncGroup"] = field(default_factory=dict)

    def find(self, group_id: str) -> Optional["SyncGroup"]:
        if self.id == group_id:
            return self
        for child in self.items.values():
            found = child.find(group_id)
            if found is not None:
                return found
        return None


g_role = SyncGroup(
    id="roles",
    name="Roles",
    description=(
        "Manages role definitions used to control what features and pages "
        "users can access across the platform."
    ),
    icon="user-cog",
)

g_feature_request = SyncGroup(
    id="feature-requests",
    name="Feature Requests",
    description=(
        "Collects and tracks feature requests and feedback submitted by users."
    ),
    icon="lightbulb",
)

g_user = SyncGroup(
    id="users",
    name="Users",
    description=(
        "Manages platform user accounts, including roles, timezone "
        "preferences, and access status."
    ),
    icon="users",
)

_ROOT_GROUPS: tuple[SyncGroup, ...] = (
    g_role,
    g_feature_request,
    g_user,
)


def _flatten(groups) -> list[SyncGroup]:
    flat: list[SyncGroup] = []
    for group in groups:
        flat.append(group)
        flat.extend(_flatten(group.items.values()))
    return flat


ALL_GROUPS: list[SyncGroup] = _flatten(_ROOT_GROUPS)
