import os
import secrets
import string
import tempfile

import pyzipper

_PASSWORD_ALPHABET = string.ascii_uppercase + string.digits
_PASSWORD_SEGMENT_LENGTHS = (4, 3, 4)


def generate_zip_password() -> str:
    segments = [
        "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))
        for length in _PASSWORD_SEGMENT_LENGTHS
    ]
    return "-".join(segments)


def zip_and_encrypt(files: list[tuple[bytes, str]], password: str) -> str:
    fd, zip_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)

    with pyzipper.AESZipFile(
        zip_path, "w", compression=pyzipper.ZIP_LZMA, encryption=pyzipper.WZ_AES
    ) as zip_file:
        zip_file.setpassword(password.encode("utf-8"))
        for content, arcname in files:
            zip_file.writestr(arcname, content)

    return zip_path
