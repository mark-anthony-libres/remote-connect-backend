import secrets

from sqlalchemy.exc import IntegrityError

from apps.app.modules.device.entities.device_entity import DeviceEntity
from apps.app.modules.device.repositories.device_repository import DeviceRepository
from database.session_factory import SessionFactory

_DEVICE_CODE_SPACE = 10_000_000_000
_MAX_CODE_ATTEMPTS = 5


def _generate_device_code() -> str:
    return f"{secrets.randbelow(_DEVICE_CODE_SPACE):010d}"


def _generate_install_key() -> str:
    return secrets.token_hex(32)


class DeviceIdentityService:

    def get_or_create_device(self, install_key: str | None, device_name: str | None = None) -> DeviceEntity:
        """
        Resolves (or mints) a device identity. Raises on failure — this is not
        fire-and-forget bookkeeping like task_tracking_service; the caller (the
        WS handler) must know when it fails so it can close the socket.
        """
        with SessionFactory() as db_session:
            repository = DeviceRepository(db_session)

            if install_key:
                existing = repository.get_by_install_key(install_key)
                if existing is not None:
                    return repository.touch_last_seen(existing)

            last_error: Exception | None = None
            for _ in range(_MAX_CODE_ATTEMPTS):
                candidate = _generate_device_code()
                if repository.get_by_device_code(candidate) is not None:
                    continue
                try:
                    return repository.create_device(
                        device_code=candidate,
                        install_key=_generate_install_key(),
                        device_name=device_name,
                    )
                except IntegrityError as exc:
                    db_session.rollback()
                    last_error = exc
                    continue

            raise RuntimeError(
                f"device_identity: failed to allocate a unique device_code after {_MAX_CODE_ATTEMPTS} attempts"
            ) from last_error
