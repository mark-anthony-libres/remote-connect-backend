from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from apps.app.core.settings import settings


class FileReferenceError(Exception):
    pass


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    return Fernet(settings.file_reference_encryption_key.encode())


def encrypt_file_reference(real_identifier: str) -> str:
    return _get_fernet().encrypt(real_identifier.encode()).decode()


def decrypt_file_reference(reference: str) -> str:
    try:
        return _get_fernet().decrypt(reference.encode()).decode()
    except InvalidToken as e:
        raise FileReferenceError("Invalid or tampered file reference") from e
