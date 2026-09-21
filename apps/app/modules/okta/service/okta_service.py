
import os
from urllib.parse import urljoin
from zoneinfo import available_timezones
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.settings import OneLogin_Saml2_Settings
import jwt
from typing import Any, Dict

from apps.app.utils.dict import get_attribute
from apps.app.core import services
from apps.app.modules.user.repositories.users_repository import UsersRepository
from apps.app.modules.user.repositories.user_sessions_resposity import UserSessionsRepository

from apps.app.utils.datetime import DateTime
from datetime import timedelta

from apps.app.utils.logger import Logger
from apps.app.core.settings import settings


class OktaService:
	def __init__(self):
		self.saml_settings = self._build_saml_settings()

	@staticmethod
	def create_new_token(user):
		now = DateTime(user).now()
		exp = now + timedelta(minutes=settings.jwt_access_token_minutes)

		payload = {
			'sub': str(user.id),
			'exp': int(exp.timestamp()),
			'iat': int(now.timestamp())
		}

		token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

		return {'user': user, 'token': token}


	def _clean_env(self, value: str, default: str = "") -> str:
		cleaned = (value or default).strip().strip('"').strip("'")
		return cleaned

	def _build_absolute_url(self, base_url: str, path: str) -> str:
		normalized_base = base_url if base_url.endswith('/') else f"{base_url}/"
		normalized_path = path.lstrip('/')
		return urljoin(normalized_base, normalized_path)

	def _build_saml_settings(self):
		Logger.info("Building SAML settings for Okta integration")
		
		api_prefix_segment = settings.api_prefix.strip('/')
		callback_path = f"{api_prefix_segment}/okta/callback" 
		metadata_path = f"{api_prefix_segment}/okta/metadata"

		acs_url = self._build_absolute_url(settings.base_url, callback_path)
		metadata_url = self._build_absolute_url(settings.base_url, metadata_path)

		with open(settings.okta_cert, 'r') as f:
			okta_cert = f.read()
		okta_settings = {
			'strict': True,
			'debug': settings.environment.lower() == "local",
			'sp': {
				'entityId': metadata_url,
				'assertionConsumerService': {
					'url': acs_url,
					'binding': 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST',
				},
				'allowUnencryptedAssertion': True,
			},
			'idp': {
				   'entityId': settings.idp,
				'singleSignOnService': {
					'url': settings.sso_login_url,
					'binding': 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect',
				},
				'x509cert': okta_cert,
			},
		}
		return OneLogin_Saml2_Settings(okta_settings)

	def process_saml_response(
		self,
		request_data: Dict[str, Any],
		login_context: Dict[str, Any] | None = None, # ip_address, user_agent, operating_system, browser_version, device_type
	) -> Dict[str, Any]:
		Logger.info("Processing SAML response from Okta")
		auth = OneLogin_Saml2_Auth(request_data, self.saml_settings)
		auth.process_response()
		errors = auth.get_errors()
		if errors:
			raise Exception(f'SAML errors: {errors}')
		attributes = auth.get_attributes()
		email = get_attribute(attributes, 'email')
		name = get_attribute(attributes, 'name')
		first_name = get_attribute(attributes, 'firstName')
		last_name = get_attribute(attributes, 'lastName')
		mobile_phone = get_attribute(attributes, 'mobilePhone')
		primary_phone = get_attribute(attributes, 'primaryPhone')
		title = get_attribute(attributes, 'title')
		timezone = get_attribute(attributes, 'timezone')

		user_data = {
			'email': email,
			'name': name,
			'first_name': first_name,
			'last_name': last_name,
			'title': title
		}

		if timezone in available_timezones():
			user_data['okta_timezone'] = timezone

		return services.call(login_and_record_session, user_data=user_data, login_context=login_context)

	def get_metadata(self) -> str:
		return self.saml_settings.get_sp_metadata()


def login_and_record_session(context, user_data: dict, login_context: Dict[str, Any] | None = None) -> Dict[str, Any]:
	session = context.session
	user = UsersRepository(session).find_or_create(user_data)
	token_result = OktaService.create_new_token(user)
	UserSessionsRepository(session).record_login(user, token_result['token'], **(login_context or {}))
	return token_result
