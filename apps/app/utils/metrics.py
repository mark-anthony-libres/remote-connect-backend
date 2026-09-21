CHANGE_PERCENTAGE_CAP = 100.0


def period_change(current: float, previous: float, cap_percentage: float = CHANGE_PERCENTAGE_CAP) -> dict:
  change_count = current - previous
  if previous > 0:
    change_percentage = (change_count / previous) * 100
    change_percentage = max(-cap_percentage, min(cap_percentage, change_percentage))
  else:
    change_percentage = 0
  return {"change_count": change_count, "change_percentage": change_percentage}
