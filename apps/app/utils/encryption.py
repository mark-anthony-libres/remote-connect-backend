from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from apps.app.core.settings import settings


class DecryptionError(Exception):
    pass


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    return Fernet(settings.secret_encryption_key.encode())


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise DecryptionError("Failed to decrypt value: invalid token or wrong key") from e
