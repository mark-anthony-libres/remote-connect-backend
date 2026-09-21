from fastapi import HTTPException, status


def normalize_display_order(existing_ids: set, items: list) -> dict:
    provided_ids = [item_id for item_id, _ in items]
    if len(set(provided_ids)) != len(provided_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duplicate id in reorder payload")
    if set(provided_ids) != existing_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reorder payload must include every existing item exactly once",
        )

    ordered_ids = [item_id for item_id, _ in sorted(items, key=lambda pair: pair[1])]
    return {item_id: position for position, item_id in enumerate(ordered_ids, start=1)}
