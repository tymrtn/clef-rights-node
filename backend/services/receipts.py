from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


SCHEMA_VERSION = "clef.permission-receipt.v1"
LIFECYCLE_SCHEMA_VERSION = "clef.permission-status-receipt.v1"
SETTLEMENT_SCHEMA_VERSION = "clef.settlement-reconciliation-receipt.v1"
CANONICALIZATION = "CLEF-CANONICAL-JSON-1"


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class ReceiptVerification:
    valid: bool
    payload_hash_valid: bool
    signature_valid: bool
    transparency_hash_valid: bool
    error: str | None = None


class ReceiptSigner:
    def __init__(self, *, node_id: str, private_key_b64: str | None, app_env: str) -> None:
        self.node_id = node_id
        self.ephemeral = not bool(private_key_b64)
        if private_key_b64:
            raw = _b64url_decode(private_key_b64)
            if len(raw) != 32:
                raise RuntimeError("NODE_SIGNING_PRIVATE_KEY_B64 must contain a 32-byte Ed25519 private key")
            self._private_key = Ed25519PrivateKey.from_private_bytes(raw)
        else:
            if app_env.lower() in {"staging", "production"}:
                raise RuntimeError("Persistent NODE_SIGNING_PRIVATE_KEY_B64 is required outside development/test")
            self._private_key = Ed25519PrivateKey.generate()

        self._public_key = self._private_key.public_key()
        public_raw = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.public_key_b64 = _b64url_encode(public_raw)
        self.key_id = f"ed25519:{sha256_hex(public_raw)[:24]}"

    def sign_statement(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Sign a typed statement; only sign_receipt adds a ledger commitment."""
        payload_bytes = canonical_json(payload)
        return {"payload": payload, "proof": {
            "algorithm": "Ed25519", "canonicalization": CANONICALIZATION,
            "payloadHash": sha256_hex(payload_bytes), "keyId": self.key_id,
            "publicKey": self.public_key_b64,
            "signature": _b64url_encode(self._private_key.sign(payload_bytes)),
        }}

    def sign_receipt(
        self,
        *,
        payload: dict[str, Any],
        transparency_sequence: int,
        previous_entry_hash: str | None,
    ) -> dict[str, Any]:
        statement = self.sign_statement(payload)
        payload_hash = statement["proof"]["payloadHash"]
        transparency = {
            "sequence": transparency_sequence,
            "previousEntryHash": previous_entry_hash,
            "payloadHash": payload_hash,
        }
        entry_hash = sha256_hex(canonical_json(transparency))
        return {
            **statement,
            "transparency": {
                **transparency,
                "entryHash": entry_hash,
            },
        }

    @staticmethod
    def verify_receipt(receipt: dict[str, Any]) -> ReceiptVerification:
        try:
            payload = receipt["payload"]
            proof = receipt["proof"]
            transparency = receipt["transparency"]
            if proof["algorithm"] != "Ed25519" or proof["canonicalization"] != CANONICALIZATION:
                raise ValueError("Unsupported receipt proof format")
            payload_bytes = canonical_json(payload)
            payload_hash_valid = sha256_hex(payload_bytes) == proof["payloadHash"]

            transparency_core = {
                "sequence": transparency["sequence"],
                "previousEntryHash": transparency.get("previousEntryHash"),
                "payloadHash": proof["payloadHash"],
            }
            transparency_hash_valid = (
                transparency["payloadHash"] == proof["payloadHash"]
                and sha256_hex(canonical_json(transparency_core)) == transparency["entryHash"]
            )

            signature_valid = False
            if payload_hash_valid:
                public_key = Ed25519PublicKey.from_public_bytes(_b64url_decode(proof["publicKey"]))
                public_key.verify(_b64url_decode(proof["signature"]), payload_bytes)
                signature_valid = True

            valid = payload_hash_valid and signature_valid and transparency_hash_valid
            return ReceiptVerification(
                valid=valid,
                payload_hash_valid=payload_hash_valid,
                signature_valid=signature_valid,
                transparency_hash_valid=transparency_hash_valid,
            )
        except (KeyError, TypeError, ValueError, InvalidSignature, json.JSONDecodeError) as error:
            return ReceiptVerification(
                valid=False,
                payload_hash_valid=False,
                signature_valid=False,
                transparency_hash_valid=False,
                error=str(error),
            )

    def export_private_key_b64(self) -> str:
        raw = self._private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return _b64url_encode(raw)
