from typing import Optional

from infra.groups import ALL_GROUPS, SyncGroup

_GROUPS_BY_ID: dict[str, SyncGroup] = {group.id: group for group in ALL_GROUPS}
_PARENT_BY_ID: dict[str, str] = {
    child.id: group.id
    for group in ALL_GROUPS
    for child in group.items.values()
}


def get_group(group_id: str) -> Optional[SyncGroup]:
    return _GROUPS_BY_ID.get(group_id)


def get_parent_id(group_id: str) -> Optional[str]:
    return _PARENT_BY_ID.get(group_id)


def get_ancestor_ids(group_id: str) -> list[str]:
    ancestors: list[str] = []
    current = _PARENT_BY_ID.get(group_id)
    while current is not None:
        ancestors.append(current)
        current = _PARENT_BY_ID.get(current)
    return ancestors


def get_descendant_ids(group_id: str) -> list[str]:
    group = _GROUPS_BY_ID.get(group_id)
    if group is None:
        return []

    descendants: list[str] = []

    def collect(node: SyncGroup) -> None:
        for child in node.items.values():
            descendants.append(child.id)
            collect(child)

    collect(group)
    return descendants
