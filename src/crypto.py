"""Cifratura opzionale dei file di stato (Fernet + PBKDF2-SHA256).

- La password vive solo in RAM (`set_key`), mai su disco.
- Envelope JSON: {"v": 1, "salt": hex, "data": token-fernet}.
- File legacy in chiaro restano leggibili (migrazione trasparente).
"""

import base64
import hashlib
import json
import secrets

MAGIC_V = 1
KDF_ITERATIONS = 600_000

_key: bytes | None = None


def is_unlocked() -> bool:
    return _key is not None


def try_password(password: str, path) -> bool:
    """True se il file non e' cifrato oppure la password lo decifra."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return True
    if not is_envelope(text):
        return True
    try:
        data = json.loads(text)
        salt = bytes.fromhex(data["salt"])
        token = data["data"].encode("ascii")
        _fernet(password, salt).decrypt(token)
    except Exception:
        return False
    return True


def set_key(key: bytes | None) -> None:
    global _key
    _key = key


def password_to_key(password: str) -> bytes:
    """Rappresentazione opaca della password da tenere in RAM."""
    return password.encode("utf-8")


def _derive(password: str, salt: bytes) -> bytes:
    raw = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, KDF_ITERATIONS)
    return base64.urlsafe_b64encode(raw)


def _fernet(password: str, salt: bytes):
    from cryptography.fernet import Fernet

    return Fernet(_derive(password, salt))


def is_envelope(text: str) -> bool:
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return False
    return (
        isinstance(data, dict)
        and data.get("v") == MAGIC_V
        and isinstance(data.get("salt"), str)
        and isinstance(data.get("data"), str)
    )


def protect_text(plain_text: str) -> str:
    """Cifra un JSON plaintext con la chiave in RAM (invariato se lock spento)."""
    if not is_unlocked() or _key is None:
        return plain_text
    try:
        json.loads(plain_text)
    except ValueError:
        return plain_text
    salt = secrets.token_bytes(16)
    token = _fernet(_key.decode("utf-8"), salt).encrypt(plain_text.encode("utf-8"))
    return json.dumps(
        {"v": MAGIC_V, "salt": salt.hex(), "data": token.decode("ascii")},
        ensure_ascii=False,
    )


def unprotect_text(text: str):
    """Ritorna (obj, was_encrypted). ValueError se cifrato senza chiave/errata/corrrotto."""
    if not is_envelope(text):
        return json.loads(text), False
    if not is_unlocked() or _key is None:
        raise ValueError("File cifrato: serve la password.")
    from cryptography.fernet import InvalidToken

    try:
        data = json.loads(text)
        salt = bytes.fromhex(data["salt"])
        token = data["data"].encode("ascii")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError(f"Envelope non valido: {exc}")
    try:
        raw = _fernet(_key.decode("utf-8"), salt).decrypt(token)
    except InvalidToken as exc:
        raise ValueError("Password errata o file corrotto.") from exc
    try:
        return json.loads(raw.decode("utf-8")), True
    except ValueError as exc:
        raise ValueError(f"Contenuto non valido: {exc}") from exc
