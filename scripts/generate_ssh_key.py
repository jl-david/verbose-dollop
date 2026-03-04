"""
Generate an Ed25519 SSH key pair for the marketing pipeline project.

Usage:
    python scripts/generate_ssh_key.py [--name NAME] [--output-dir DIR] [--comment COMMENT]

Options:
    --name          Key filename (default: marketing_pipeline_key)
    --output-dir    Directory to save keys (default: ~/.ssh)
    --comment       Key comment (default: marketing-pipeline)
    --force         Overwrite existing key files
"""

import argparse
import base64
import os
import stat
import struct
import sys
from pathlib import Path

import nacl.signing


# ---------------------------------------------------------------------------
# OpenSSH wire-format helpers
# ---------------------------------------------------------------------------

def _pack_string(s: bytes) -> bytes:
    """Prefix a byte string with a 4-byte big-endian length."""
    return struct.pack(">I", len(s)) + s


def _build_public_key_blob(verify_key_bytes: bytes) -> bytes:
    key_type = b"ssh-ed25519"
    return _pack_string(key_type) + _pack_string(verify_key_bytes)


def _build_openssh_private_key(signing_key: "nacl.signing.SigningKey", comment: str) -> str:
    """Encode an Ed25519 key in OpenSSH private-key format (unencrypted)."""
    verify_key_bytes = bytes(signing_key.verify_key)
    # nacl stores the 32-byte seed; OpenSSH wants seed || public key (64 bytes)
    private_key_bytes = bytes(signing_key) + verify_key_bytes

    pub_blob = _build_public_key_blob(verify_key_bytes)

    # Random 4-byte check integer, repeated for integrity check
    check_int = int.from_bytes(os.urandom(4), "big")
    check_bytes = struct.pack(">II", check_int, check_int)

    comment_bytes = comment.encode()
    key_type = b"ssh-ed25519"

    # Private key section (plaintext)
    priv_section = (
        check_bytes
        + _pack_string(key_type)
        + _pack_string(verify_key_bytes)
        + _pack_string(private_key_bytes)
        + _pack_string(comment_bytes)
    )

    # Pad to 8-byte boundary (AES block size, even for "none" cipher)
    pad_len = (8 - len(priv_section) % 8) % 8
    priv_section += bytes(range(1, pad_len + 1))

    body = (
        b"openssh-key-v1\x00"        # magic
        + _pack_string(b"none")      # cipher
        + _pack_string(b"none")      # kdf
        + _pack_string(b"")          # kdf options
        + struct.pack(">I", 1)       # number of keys
        + _pack_string(pub_blob)     # public key
        + _pack_string(priv_section) # private key section
    )

    b64 = base64.encodebytes(body).decode()
    return f"-----BEGIN OPENSSH PRIVATE KEY-----\n{b64}-----END OPENSSH PRIVATE KEY-----\n"


def _build_public_key_line(verify_key_bytes: bytes, comment: str) -> str:
    pub_blob = _build_public_key_blob(verify_key_bytes)
    b64 = base64.b64encode(pub_blob).decode()
    return f"ssh-ed25519 {b64} {comment}\n"


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------

def generate_keypair(private_key_path: Path, comment: str, force: bool) -> None:
    public_key_path = private_key_path.with_suffix(".pub")

    if private_key_path.exists() and not force:
        print(f"Key already exists: {private_key_path}")
        print("Use --force to overwrite.")
        sys.exit(1)

    signing_key = nacl.signing.SigningKey.generate()
    verify_key_bytes = bytes(signing_key.verify_key)

    private_pem = _build_openssh_private_key(signing_key, comment)
    public_line = _build_public_key_line(verify_key_bytes, comment)

    private_key_path.write_text(private_pem)
    public_key_path.write_text(public_line)

    private_key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)           # 600
    public_key_path.chmod(
        stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH  # 644
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an Ed25519 SSH key pair for the marketing pipeline."
    )
    parser.add_argument(
        "--name",
        default="marketing_pipeline_key",
        help="Key filename (default: marketing_pipeline_key)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path.home() / ".ssh"),
        help="Directory to save keys (default: ~/.ssh)",
    )
    parser.add_argument(
        "--comment",
        default="marketing-pipeline",
        help="Key comment embedded in the public key (default: marketing-pipeline)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing key files if they exist",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir.chmod(stat.S_IRWXU)  # 700

    private_key_path = output_dir / args.name
    public_key_path = private_key_path.with_suffix(".pub")

    print("Generating Ed25519 SSH key pair...")
    generate_keypair(private_key_path, args.comment, args.force)

    public_key = public_key_path.read_text().strip()

    print(f"\nKey pair generated successfully:")
    print(f"  Private key : {private_key_path}")
    print(f"  Public key  : {public_key_path}")
    print(f"\nPublic key contents:")
    print(f"  {public_key}")
    print(f"\nNext steps:")
    print(f"  1. Add the public key to your deployment target:")
    print(f"       cat {public_key_path} >> ~/.ssh/authorized_keys")
    print(f"  2. Or add it to GitHub/GitLab under Settings > SSH Keys.")
    print(f"  3. Reference the key in your Cloud Run / CI environment:")
    print(f"       SSH_PRIVATE_KEY=$(cat {private_key_path})")


if __name__ == "__main__":
    main()
