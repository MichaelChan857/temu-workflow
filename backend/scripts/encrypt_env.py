"""加密 .env 文件,把明文凭据转成可入库的安全格式

用法:
  # 1. 加密(开发机本地)
  python scripts/encrypt_env.py encrypt .env.production --out .env.production.enc

  # 2. 部署机器上解密(运维执行,需 KMS 或本地口令)
  python scripts/encrypt_env.py decrypt .env.production.enc --out .env

加密算法:AES-256-GCM(工业标准,认证加密)
密钥来源:
  - 本地开发:从口令 PBKDF2 派生(100k 轮)
  - 生产:从 AWS Secrets Manager / GCP Secret Manager / HashiCorp Vault 注入
    (本脚本接受 KMS_KEY_BASE64 env var,跳过口令派生)

格式:.env.production.enc = JSON {
  "v": 1, "alg": "aes-256-gcm", "kdf": "pbkdf2-sha256-100k" | "raw-key",
  "salt": "..." (PBKDF2 only),
  "iv": "...",
  "data": "..." (base64 ciphertext)
}
"""
import sys
import os
import json
import base64
import secrets
import argparse
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


def derive_key_from_passphrase(passphrase: str, salt: bytes) -> bytes:
    """本地开发:PBKDF2 派生 32 字节 key"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
    )
    return kdf.derive(passphrase.encode())


def get_key(salt: bytes | None) -> tuple[bytes, bytes | None]:
    """优先用 KMS_KEY_BASE64(生产);fallback 到口令"""
    kms_key_b64 = os.environ.get("KMS_KEY_BASE64")
    if kms_key_b64:
        key = base64.b64decode(kms_key_b64)
        if len(key) != 32:
            raise ValueError(f"KMS_KEY_BASE64 must decode to 32 bytes, got {len(key)}")
        return key, None  # raw key, no salt needed

    # 本地口令派生
    passphrase = os.environ.get("ENV_PASSPHRASE")
    if not passphrase:
        passphrase = input("Enter passphrase for env encryption: ")
    salt = salt or secrets.token_bytes(16)
    return derive_key_from_passphrase(passphrase, salt), salt


def encrypt_file(plaintext_path: Path, out_path: Path) -> None:
    plaintext = plaintext_path.read_bytes()
    key, salt = get_key(None)
    iv = secrets.token_bytes(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(iv, plaintext, None)
    payload = {
        "v": 1,
        "alg": "aes-256-gcm",
        "kdf": "pbkdf2-sha256-100k" if salt else "raw-key",
        "salt": base64.b64encode(salt).decode() if salt else None,
        "iv": base64.b64encode(iv).decode(),
        "data": base64.b64encode(ct).decode(),
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"  [OK] encrypted → {out_path}  ({len(plaintext)} bytes)")


def decrypt_file(enc_path: Path, out_path: Path) -> None:
    payload = json.loads(enc_path.read_text(encoding="utf-8"))
    if payload["v"] != 1:
        raise ValueError(f"unsupported version: {payload['v']}")
    key_bytes = base64.b64decode(os.environ["KMS_KEY_BASE64"]) if payload["kdf"] == "raw-key" \
        else derive_key_from_passphrase(
            os.environ.get("ENV_PASSPHRASE") or input("Enter passphrase: "),
            base64.b64decode(payload["salt"]) if payload["salt"] else b"\x00" * 16,
        )
    iv = base64.b64decode(payload["iv"])
    ct = base64.b64decode(payload["data"])
    pt = AESGCM(key_bytes).decrypt(iv, ct, None)
    out_path.write_bytes(pt)
    print(f"  [OK] decrypted → {out_path}  ({len(pt)} bytes)")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("encrypt")
    e.add_argument("path")
    e.add_argument("--out")
    d = sub.add_parser("decrypt")
    d.add_argument("path")
    d.add_argument("--out")
    args = parser.parse_args()

    src = Path(args.path)
    dst = Path(args.out) if args.out else src.with_suffix(src.suffix + ".enc" if args.cmd == "encrypt" else "")
    if args.cmd == "encrypt":
        encrypt_file(src, dst)
    else:
        decrypt_file(src, dst)


if __name__ == "__main__":
    main()