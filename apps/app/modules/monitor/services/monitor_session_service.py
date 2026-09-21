import json
import secrets
from datetime import datetime, timezone

from apps.app.core.settings import settings
from apps.app.utils.email import EmailUtil
from apps.app.utils.logger import Logger
from apps.app.utils.redis import redis_consume_once, redis_delete, redis_get, redis_set

_BOOTSTRAP_TOKEN_KEY_PREFIX = "monitor:bootstrap:"
_SESSION_TOKEN_KEY_PREFIX = "monitor:session:"


def _bootstrap_token_key(token: str) -> str:
    return f"{_BOOTSTRAP_TOKEN_KEY_PREFIX}{token}"


def _session_token_key(token: str) -> str:
    return f"{_SESSION_TOKEN_KEY_PREFIX}{token}"


def generate_bootstrap_token() -> tuple[str, int]:
    if not settings.monitor_enabled:
        raise RuntimeError(
            "Task monitoring is disabled (MONITOR_ENABLED=false) - "
            "refusing to generate a token that wouldn't work anyway."
        )

    token = secrets.token_urlsafe(32)
    ttl_seconds = settings.monitor_token_ttl_seconds
    redis_set(_bootstrap_token_key(token), "1", ex=ttl_seconds)
    return token, ttl_seconds


def _generate_session_token() -> tuple[str, int]:
    token = secrets.token_urlsafe(32)
    ttl_seconds = settings.monitor_token_ttl_seconds
    idle_timeout_seconds = settings.monitor_token_idle_timeout_seconds

    payload = json.dumps({"created_at": datetime.now(timezone.utc).isoformat()})
    redis_set(_session_token_key(token), payload, ex=min(idle_timeout_seconds, ttl_seconds))
    return token, ttl_seconds


def redeem_session(bootstrap_token: str) -> tuple[str, int] | None:
    if not settings.monitor_enabled:
        return None
    if not redis_consume_once(_bootstrap_token_key(bootstrap_token)):
        return None
    return _generate_session_token()


def is_session_token_valid(token: str) -> bool:
    if not settings.monitor_enabled:
        return False

    key = _session_token_key(token)
    raw = redis_get(key)
    if not raw:
        return False

    try:
        created_at = datetime.fromisoformat(json.loads(raw)["created_at"])
    except (TypeError, ValueError, KeyError):
        redis_delete(key)
        return False

    age_seconds = (datetime.now(timezone.utc) - created_at).total_seconds()
    if age_seconds >= settings.monitor_token_ttl_seconds:
        redis_delete(key)
        return False

    redis_set(key, raw, ex=settings.monitor_token_idle_timeout_seconds)
    return True


def build_monitor_links(token: str) -> tuple[str, str]:
    web_link = f"{settings.web_url.rstrip('/')}{settings.monitor_web_path}?token={token}"
    api_base_url = f"{settings.monitor_base_url.rstrip('/')}{settings.api_prefix}/monitor"
    return web_link, api_base_url


def build_monitor_curl(token: str, api_base_url: str) -> str:
    return (
        f'SESSION=$(curl -s -X POST -H "X-Monitor-Token: {token}" "{api_base_url}/session" | '
        f'python3 -c "import sys,json;print(json.load(sys.stdin)[\'session_token\'])") && '
        f'curl -H "X-Monitor-Token: $SESSION" "{api_base_url}/pool"'
    )


def generate_and_email_monitor_link(requested_by: str | None = None, to: str | list[str] | None = None) -> dict:
    token, ttl_seconds = generate_bootstrap_token()
    web_link, api_base_url = build_monitor_links(token)
    curl_command = build_monitor_curl(token, api_base_url)
    generated_at = datetime.now(timezone.utc)
    recipients = to or settings.mail_default_to

    html = EmailUtil.create_template("task_monitor_link_ready.html", {
        "webLink": web_link,
        "curlCommand": curl_command,
        "expiresInMinutes": ttl_seconds // 60,
        "idleTimeoutMinutes": settings.monitor_token_idle_timeout_seconds // 60,
        "generatedAt": generated_at.strftime("%B %d, %Y at %I:%M:%S %p UTC"),
        "requestedBy": requested_by,
    })

    EmailUtil.send(
        to=recipients,
        subject="CentCom: Task Monitor Access Link",
        html=html,
    )

    Logger.info(f"[monitor] Emailed task monitor access link (requested_by={requested_by}, to={recipients})")

    return {
        "token": token,
        "web_link": web_link,
        "api_base_url": api_base_url,
        "curl_command": curl_command,
        "expires_in_seconds": ttl_seconds,
        "recipients": recipients,
    }
