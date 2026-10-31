"""Ed25519 keys for this device and for each vet.

Signatures are what make sign-off real: a model can write any text it likes, but it cannot produce a
signature, because no tool ever exposes these keys. In this demo the vet's key sits on the kit and is
unlocked by the vet's PIN; a real rollout would keep it on the vet's phone or in AWS KMS.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from . import config


def _keydir() -> Path:
    path = config.data_dir() / "keys"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_or_create(name: str) -> Ed25519PrivateKey:
    file = _keydir() / f"{name}.key"
    if file.exists():
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(file.read_text()))
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    file.write_text(base64.b64encode(raw).decode())
    (_keydir() / f"{name}.pub").write_text(public_key_b64(key))
    return key


def public_key_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def public_key_for(name: str) -> str:
    _load_or_create(name)
    return (_keydir() / f"{name}.pub").read_text()


def sign(name: str, message: str) -> str:
    return base64.b64encode(_load_or_create(name).sign(message.encode())).decode()


def verify(public_key: str, message: str, signature: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key)).verify(
            base64.b64decode(signature), message.encode()
        )
        return True
    except (InvalidSignature, ValueError):
        return False


def set_pin(vet_id: str, pin: str) -> None:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 100_000)
    (_keydir() / f"{vet_id}.pin").write_text(json.dumps({"salt": salt.hex(), "digest": digest.hex()}))


def check_pin(vet_id: str, pin: str) -> bool:
    file = _keydir() / f"{vet_id}.pin"
    if not file.exists():
        return False
    stored = json.loads(file.read_text())
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(stored["salt"]), 100_000)
    return hmac.compare_digest(digest.hex(), stored["digest"])
