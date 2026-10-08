"""Field level encryption with AES-256-GCM and key identifiers for rotation.

Stored format: ``<key_id>:<base64url(nonce || ciphertext || tag)>``. The key id is stored with
every value so that a new key can be introduced while old values stay readable. The field name
is bound into the authenticated data, so a ciphertext cannot be moved to another column.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

NONCE_BYTES = 12
KEY_BYTES = 32


class CryptoError(Exception):
    """Raised when a value cannot be decrypted."""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text.encode("ascii"))


def generate_key(key_id: str) -> str:
    """Return a new key in the ``<key_id>:<base64url key>`` format used by the settings."""
    if ":" in key_id or not key_id:
        raise ValueError("key id must be non empty and must not contain ':'")
    return f"{key_id}:{_b64e(secrets.token_bytes(KEY_BYTES))}"


def parse_key(entry: str) -> tuple[str, bytes]:
    key_id, _, encoded = entry.strip().partition(":")
    if not key_id or not encoded:
        raise ValueError("encryption key must use the format '<key_id>:<base64url key>'")
    key = _b64d(encoded)
    if len(key) != KEY_BYTES:
        raise ValueError("encryption key must decode to exactly 32 bytes")
    return key_id, key


@dataclass(frozen=True)
class FieldCipher:
    active_key_id: str
    keys: dict[str, bytes]

    @classmethod
    def from_settings(
        cls, active: str, old_keys: str = "", fallback_secret: str = ""
    ) -> "FieldCipher":
        """Build a cipher. Outside production an empty key falls back to one derived from the
        JWT secret so development works without extra setup; settings validation forbids
        that fallback in production."""
        if not active:
            derived = HKDF(
                algorithm=SHA256(), length=KEY_BYTES, salt=None, info=b"field-encryption-dev"
            ).derive(fallback_secret.encode("utf-8"))
            return cls("dev", {"dev": derived})
        key_id, key = parse_key(active)
        keys = {key_id: key}
        for entry in filter(None, (e.strip() for e in old_keys.split(","))):
            old_id, old_key = parse_key(entry)
            keys.setdefault(old_id, old_key)
        return cls(key_id, keys)

    def encrypt(self, plaintext: str, field: str) -> str:
        nonce = secrets.token_bytes(NONCE_BYTES)
        sealed = AESGCM(self.keys[self.active_key_id]).encrypt(
            nonce, plaintext.encode("utf-8"), field.encode("utf-8")
        )
        return f"{self.active_key_id}:{_b64e(nonce + sealed)}"

    def decrypt(self, token: str, field: str) -> str:
        key_id, _, payload = token.partition(":")
        key = self.keys.get(key_id)
        if key is None or not payload:
            raise CryptoError("unknown key id or malformed value")
        try:
            raw = _b64d(payload)
            plaintext = AESGCM(key).decrypt(
                raw[:NONCE_BYTES], raw[NONCE_BYTES:], field.encode("utf-8")
            )
        except (InvalidTag, ValueError) as exc:
            raise CryptoError("value could not be decrypted") from exc
        return plaintext.decode("utf-8")

    def needs_rotation(self, token: str) -> bool:
        return token.partition(":")[0] != self.active_key_id

    def encrypt_optional(self, value: str | None, field: str) -> str | None:
        return None if value in (None, "") else self.encrypt(value, field)

    def decrypt_optional(self, token: str | None, field: str) -> str | None:
        return None if not token else self.decrypt(token, field)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
