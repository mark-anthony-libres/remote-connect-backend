from __future__ import annotations

from datetime import timezone
import traceback

import json
import ipaddress
from fastapi.routing import APIRoute
import requests

import configparser
import os
from apps.app.core.settings import settings
from apps.app.utils import datetime
from apps.app.utils.decorators.task_decorator import task
from apps.app.utils.logger import Logger


def is_local() -> bool:
    return str(settings.environment).lower() == "local"


def print_query(query, label: str = "SQL") -> None:
    """Print a SQLAlchemy ORM query with all bind parameters inlined."""
    statement = query.statement
    compiled = statement.compile(
        dialect=query.session.bind.dialect,
        compile_kwargs={"render_postcompile": True, "literal_binds": True},
    )
    print(f"{label}:")
    print(str(compiled))
    raise



def log_exception_with_traceback(error, context=None):
    error_type = type(error).__name__
    tb = traceback.format_exc()
    prefix = f"[{context}] " if context else ""
    Logger.error(f"{prefix}Exception Type: {error_type}\nMessage: {error}\nTraceback:\n{tb}")


def get_model_globs():
    ini_path = os.path.join(os.path.dirname(__file__), '../../../infra/alembic.ini')
    config = configparser.ConfigParser()
    config.read(ini_path)
    model_globs_str = config.get('alembic', 'model_globs', fallback=None)
    if model_globs_str:
        return [g.strip() for g in model_globs_str.split(",") if g.strip()]
    return ['database/entities']


def convert_string_none_to_null(value):
    return None if value == "None" else value


def serialize_dict_fields(record):
    result = {}
    for key, value in record.items():
        if isinstance(value, (dict, list)):
            result[key] = json.dumps(value)
        else:
            result[key] = value
    return result


def ip_to_location(ip_address):

    if not ip_address:
        return None

    ip_value = str(ip_address).strip()

    if ip_value.count(":") == 1 and "." in ip_value:
        ip_value = ip_value.split(":", 1)[0]

    try:
        parsed_ip = ipaddress.ip_address(ip_value)
    except ValueError:
        return None

    if (
        parsed_ip.is_private
        or parsed_ip.is_loopback
        or parsed_ip.is_link_local
        or parsed_ip.is_multicast
        or parsed_ip.is_reserved
        or parsed_ip.is_unspecified
    ):
        return None

    try:
        response = requests.get(
            f"http://ip-api.com/json/{ip_value}",
            params={"fields": "status,country,countryCode,regionName,city,lat,lon,query"},
            timeout=3
        )
        
        if response.status_code != 200:
            return None

        data = response.json()
        
        if data.get("status") != "success":
            return None

        return {
            "ip": data.get("query", ip_value),
            "country": data.get("country"),
            "country_code": data.get("countryCode"),
            "region": data.get("regionName"),
            "city": data.get("city"),
            "latitude": data.get("lat"),
            "longitude": data.get("lon"),
        }
    except Exception:
        return None



def get_func(request):
    for route in request.app.routes:
        if isinstance(route, APIRoute):
            if request.method in route.methods and route.path == request.url.path:
                return route.endpoint
    raise Exception(f"Endpoint function not found for path={request.url.path} method={request.method}")


    