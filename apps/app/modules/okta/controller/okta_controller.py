from fastapi import APIRouter, Request, Response, status, Depends
from fastapi.responses import RedirectResponse, PlainTextResponse
import os

from apps.app.core.auth.decorators import Public
from apps.app.utils.concurrency import run_maybe_async
from apps.app.utils.logger import Logger
from apps.app.core import services
from ..service.okta_service import OktaService, login_and_record_session
from apps.app.utils import log_exception_with_traceback
from apps.app.core.settings import settings
from apps.app.core.auth.access_token import set_access_token_cookie

router = APIRouter(prefix="/okta")


def _signed_in_redirect(token: str) -> RedirectResponse:
    response = RedirectResponse(
        url=f"{settings.web_url}{settings.okta_redirect_to}",
        status_code=status.HTTP_302_FOUND,
    )
    set_access_token_cookie(response, token)
    return response


@router.get("")
@Public(rate_limit=False)
def welcome():
    return "welcome to okta auth services"

@router.get("/login")
@Public()
def initiate_login(request: Request):
    if str.lower(settings.environment) == "local" and settings.default_user_email:
        Logger.warning(
            f"Local auth bypass active: logging in as {settings.default_user_email} "
            "instead of redirecting to Okta. Unset DEFAULT_USER_EMAIL to disable."
        )
        forwarded_for = request.headers.get("x-forwarded-for")
        client_ip = (
            forwarded_for.split(",")[0].strip()
            if forwarded_for
            else (request.client.host if request.client else None)
        )
        token_result = services.call(
            login_and_record_session,
            user_data={"email": settings.default_user_email},
            login_context={
                "ip_address": client_ip,
                "user_agent": request.headers.get("user-agent"),
            },
        )
        return _signed_in_redirect(token_result["token"])

    return RedirectResponse(url=settings.sso_login_url, status_code=status.HTTP_302_FOUND)

@router.post("/callback")
@Public()
async def handle_saml_response(request: Request):
    Logger.info("Processing SAML response for Okta integration")
    try:
        form = await request.form()
        post_data = dict(form)
        forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        is_https = forwarded_proto == "https"
        server_port = request.url.port or (443 if is_https else 80)
        request_data = {
            "https": "on" if is_https else "off",
            "http_host": request.headers.get("x-forwarded-host", request.url.hostname),
            "server_port": str(server_port),
            "script_name": request.url.path,
            "get_data": dict(request.query_params),
            "post_data": post_data,
        }
        forwarded_for = request.headers.get("x-forwarded-for")
        client_ip = (
            forwarded_for.split(",")[0].strip()
            if forwarded_for
            else (request.client.host if request.client else None)
        )
        login_context = {
            "ip_address": client_ip,
            "user_agent": request.headers.get("user-agent"),
            "operating_system": request.headers.get("Sec-Ch-Ua-Platform"),
            "browser_version": request.headers.get("Sec-Ch-Ua"),
            "device_type": request.headers.get("Sec-Ch-Ua-Mobile") or request.headers.get("Sec-Ch-Ua-Tablet"),
        }
        okta_service = OktaService()
        result = await run_maybe_async(okta_service.process_saml_response, request_data, login_context)
        return _signed_in_redirect(result["token"])
    except Exception as error:
        log_exception_with_traceback(error, context="SAML callback error")
        redirect_url = f"{settings.web_url}{settings.okta_redirect_to}?error=saml_authentication_failed"
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

@router.get("/metadata")
@Public(rate_limit=False)
def get_metadata(response: Response):
    Logger.info("Serving SAML metadata for Okta integration")
    okta_service = OktaService()
    metadata = okta_service.get_metadata()
    response.headers['Content-Type'] = 'application/xml'
    return PlainTextResponse(content=metadata, media_type='application/xml')
