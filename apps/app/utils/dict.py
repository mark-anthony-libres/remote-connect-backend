from typing import Any, Dict

def get_attribute(attributes: Dict[str, Any], key: str) -> Any:
    value = attributes.get(key)
    if isinstance(value, list):
        return value[0] if value else None
    return value
