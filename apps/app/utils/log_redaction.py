from apps.app.core.settings import settings


def discover_redaction_map() -> dict:
    result = {}
    for name in settings.log_redact_list:
        value = getattr(settings, name, "")
        if isinstance(value, str) and value:
            result[name] = value
    return result


def redact_log_content(content: str) -> str:
    secrets = sorted(discover_redaction_map().items(), key=lambda pair: len(pair[1]), reverse=True)
    for name, value in secrets:
        content = content.replace(value, f"***{name}***")
    return content
