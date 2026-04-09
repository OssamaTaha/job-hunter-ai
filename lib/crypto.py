import os
import hashlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

_KEY = None


def _get_key() -> bytes:
    global _KEY
    if _KEY is not None:
        return _KEY
    raw = os.environ.get("ENCRYPTION_KEY", "job-hunter-ai-default-key-change-me")
    _KEY = hashlib.sha256(raw.encode()).digest()
    return _KEY


def encrypt(plaintext: str) -> str:
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(_get_key()), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    pad_len = 16 - (len(plaintext.encode()) % 16)
    padded = plaintext.encode() + bytes([pad_len] * pad_len)
    ct = encryptor.update(padded) + encryptor.finalize()
    return iv.hex() + ":" + ct.hex()


def decrypt(ciphertext: str) -> str:
    parts = ciphertext.split(":")
    if len(parts) != 2:
        return ciphertext
    iv = bytes.fromhex(parts[0])
    ct = bytes.fromhex(parts[1])
    cipher = Cipher(algorithms.AES(_get_key()), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ct) + decryptor.finalize()
    pad_len = padded[-1]
    return padded[:-pad_len].decode()
