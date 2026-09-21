from typing import Any, Dict, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_JWT_SECRETS = {"", "your-secret-key-change-in-production"}
INSECURE_ENCRYPTION_KEYS = {""}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    environment: str = "local"

    # App
    app_name: str = "remote-desktop-backend"
    app_env: str = "local"
    app_version: str = "0.1.0"
    api_prefix: str = "/api"
    log_level: str = "INFO"
    port: str = "8000"
    host: str = "127.0.0.1"
    web_url : str = "http://localhost:9000"


    # Server
    base_url: str = "http://localhost:8000/"
    trusted_hosts: List[str] = Field(default_factory=lambda: ["*"])

    # CORS
    cors_origins: List[str] = Field(default_factory=lambda: ["*"])
    cors_allow_credentials: bool = True
    cors_allow_methods: List[str] = Field(default_factory=lambda: ["*"])
    cors_allow_headers: List[str] = Field(default_factory=lambda: ["*"])
    cors_expose_headers: List[str] = Field(default_factory=list)

    # Authentication
    sso_login_url: str = ""
    okta_cert: str = ""
    idp: str = Field(default="", validation_alias="OKTA_IDP")
    okta_redirect_to: str = ""

    default_user_email: str = ""

    auth_cookie_name: str = "access_token"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    auth_cookie_domain: str = ""

    # JWT
    jwt_secret: str = "your-secret-key-change-in-production"
    jwt_access_token_minutes: int = 60
    jwt_algorithm: str = "HS256"
    token_rotation_grace_seconds: int = 120

    #API Log Retention Keys
    api_log_retention_seconds: int = 2 * 60 * 60
    api_log_s3_prefix: str = "api-logs"
    api_log_s3_grouped_prefix: str = "api-logs/grouped"
    api_log_s3_group_after_seconds: int = 30 * 24 * 60 * 60
    api_log_s3_retention_seconds: int = 365 * 24 * 60 * 60

    log_redact_list: List[str] = Field(default_factory=lambda: [
        "jwt_secret",
        "okta_cert",
        "pg_db_user",
        "pg_db_password",
        "pg_db_host",
        "mail_user",
        "mail_pass",
        "celery_broker_url",
        "celery_result_backend",
        "aws_access_key_id",
        "aws_secret_access_key",
        "secret_encryption_key",
        "file_reference_encryption_key",
    ])

    # Local Log Archive ("Archive" tab in Task Monitor - per-file selection of
    # today's not-yet-archived local log files, emailed on request)
    local_log_export_s3_prefix: str = "api-logs/on-demand-export/selection"
    local_log_export_token_ttl_seconds: int = 30 * 60
    local_log_export_download_expires_in_seconds: int = 60

    # Task Runs
    task_run_retention_seconds: int = 60 * 24 * 60 * 60

    # Analysis Logs
    analysis_log_retention_seconds: int = 7 * 24 * 60 * 60
    analysis_log_s3_prefix: str = "analysis-logs"

    # Analysis Log Export ("Email logs to devs" - a temporary export, fully
    # independent from the normal analysis log retention above)
    analysis_log_export_s3_prefix: str = "analysis-logs/temp"
    analysis_log_export_token_ttl_seconds: int = 30 * 60
    analysis_log_export_download_expires_in_seconds: int = 60

    # Celery
    celery_broker_url: str = "redis://127.0.0.1:6379/0"
    celery_result_backend: str = "redis://127.0.0.1:6379/0"

    # Redis Cache
    cache_prefix: str = "remote-desktop-backend"
    cache_expire_seconds: int = 600
    cache_disable: bool = False

    #Database
    pg_db_name: str = ""
    pg_db_user: str = ""
    pg_db_password: str = ""
    pg_db_host: str = "127.0.0.1"  # see celery_broker_url's comment above
    pg_db_port: str = "5432"
    pg_dump_path: str = ""

    #MAIL
    mail_host:str = ""
    mail_user:str = ""
    mail_pass:str = ""
    mail_port:str = ""
    mail_default_to: List[str] = Field(default_factory=list)

    #TASK
    max_running_tasks: int = 10
    scheduler_stale_task_timeout_seconds: int = 60 * 60 * 24 * 2  # 2 days
    task_watchdog_grace_period_seconds: int = 300
    task_metadata_key_prefix: str = "remote-desktop-backend:_task_metadata_:"

    #Monitor
    monitor_enabled: bool = True
    monitor_token_ttl_seconds: int = 60 * 60
    monitor_token_idle_timeout_seconds: int = 60 * 30
    monitor_web_path: str = "/monitor-admin/task-monitor"
    monitor_base_url: str = "http://localhost:8001/"
    monitor_trusted_proxy_ips: List[str] = Field(default_factory=list)
    monitor_ws_invalidation_channel: str = "monitor:ws:invalidate"
    monitor_rate_limit_window_seconds: int = 5 * 60
    monitor_rate_limit_max_requests: int = 200

    monitor_access_key_ttl_seconds: int = 60 * 60 * 24
    monitor_access_request_max_unauthenticated: int = 3
    monitor_access_request_window_seconds: int = 30 * 60
    monitor_access_request_block_seconds: int = 30 * 60

    #WEBSOCKET
    ws_invalidation_channel: str = "ws:invalidate"

    #RATE LIMITING
    public_rate_limit_window_seconds: int = 60
    public_rate_limit_max_requests: int = 20
    public_rate_limit_cooldown_seconds: int = 300

    user_rate_limit_window_seconds: int = 60
    user_rate_limit_max_requests: int = 200
    user_block_duration_seconds: int = 300

    #REQUEST LOG
    request_log_session_buffer_ttl_seconds: int = 1800
    user_request_log_summary_retention_days: int = 30

    #AWS
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    s3_bucket_name: str = ""
    s3_attachment_prefix: str = "attachments"
    # Every environment that shares this bucket+credentials (dev, and every
    # developer's local machine) gets its own segment prepended to S3 keys, so
    # uploads never overlap. Leave blank locally - it falls back to
    # f"{environment}-{OS username}" automatically (see s3.upload_namespace()).
    # Set explicitly for dev/staging/prod, since those should get one stable
    # value rather than whatever user the container happens to run as.
    s3_key_namespace: str = ""
    aws_s3_feature_request_uploads: str = "FEATURE-REQUEST-UPLOADS"
    aws_s3_feature_request_uploads_url: str = ""

    # General-purpose secret encryption (e.g. device/session secrets at rest)
    secret_encryption_key: str = ""

    # File reference encryption (opaque references handed to the frontend in
    # place of real backend filenames/paths - separate key from the one above
    # so the two security domains can't be confused or reused)
    file_reference_encryption_key: str = ""

    # Impersonation (temporary POC - apps/app/modules/impersonation)
    impersonation_lease_ttl_seconds: int = 60 * 10
    impersonation_max_lifetime_seconds: int = 3 * 60 * 60

    # Validators
    @field_validator(
        "base_url",
        "api_prefix",
        "sso_login_url",
        "okta_cert",
        "idp",
        "default_user_email",
        "auth_cookie_domain",
        mode="before",
    )
    @classmethod
    def clean_env(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip().strip('"').strip("'")

    @field_validator("jwt_secret")
    @classmethod
    def require_real_jwt_secret(cls, value: str) -> str:
        if value in INSECURE_JWT_SECRETS:
            raise ValueError(
                "JWT_SECRET must be set to a real secret value (see .env.example). "
                "Refusing to start with the insecure placeholder/empty default, since "
                "anyone who knows it could forge a valid session for any user."
            )
        return value

    @field_validator("secret_encryption_key")
    @classmethod
    def require_real_secret_encryption_key(cls, value: str) -> str:
        if value in INSECURE_ENCRYPTION_KEYS:
            raise ValueError(
                "SECRET_ENCRYPTION_KEY must be set to a real Fernet key (see .env.example). "
                "Refusing to start with no key, since encrypted secrets could not be decrypted "
                "or would fall back to being unprotected."
            )
        return value

    @field_validator("file_reference_encryption_key")
    @classmethod
    def require_real_file_reference_encryption_key(cls, value: str) -> str:
        if value in INSECURE_ENCRYPTION_KEYS:
            raise ValueError(
                "FILE_REFERENCE_ENCRYPTION_KEY must be set to a real Fernet key (see .env.example). "
                "Refusing to start with no key, since file references could not be decrypted "
                "or would fall back to leaking the real filename."
            )
        return value


settings = Settings()
