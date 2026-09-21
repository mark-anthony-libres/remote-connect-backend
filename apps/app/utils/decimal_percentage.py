from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import HTTPException, status

PERCENTAGE_DECIMAL_PLACES = 2


def parse_percentage(value, *, field_label: str = "Weight", max_value: Optional[Decimal] = None) -> Decimal:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_label} is required")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_label} must be a valid number")
    if parsed < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_label} cannot be negative")
    exponent = parsed.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -PERCENTAGE_DECIMAL_PLACES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_label} must have at most {PERCENTAGE_DECIMAL_PLACES} decimal places",
        )
    if max_value is not None and parsed > max_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_label} cannot exceed {max_value}%",
        )
    return parsed
