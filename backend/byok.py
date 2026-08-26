"""
BYOK-01: Bring Your Own Key.

The single place that ever sees a tenant's plaintext OpenAI API key. Every
agent module should route its OpenAI client through get_openai_client_for_tenant()
below instead of building its own module-level `OpenAI(api_key=...)` client
-- a module-level client is fixed to whichever key was in the environment
at import time and has no way to become tenant-specific.

Encryption: Fernet (symmetric, from the `cryptography` package -- added to
requirements.txt by this change; run `pip install -r requirements.txt`
again to pick it up). The encryption key itself comes from the
BYOK_ENCRYPTION_KEY environment variable, generated once and kept secret
(NOT the same thing as a tenant's OpenAI key) -- this module refuses to
start with a missing or malformed key rather than silently falling back to
an insecure default, since a wrong/missing key would otherwise mean
"encrypt with something, decrypt with something else" and every stored
BYOK key becomes silently unrecoverable.

Generate one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
and put it in backend/.env as BYOK_ENCRYPTION_KEY=<the output>.
"""
import os
import logging
from typing import Optional

from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

logger = logging.getLogger("eivanta.byok")

try:
    from backend.db_manager import get_tenant_byok_key_encrypted
except ImportError:
    from db_manager import get_tenant_byok_key_encrypted


def _get_fernet():
    """
    Lazy import + lazy construction on purpose: a tenant that never uses
    BYOK should never be blocked by a missing `cryptography` install or a
    missing BYOK_ENCRYPTION_KEY -- only the BYOK code paths themselves
    (encrypt_secret/decrypt_secret) need this to succeed.
    """
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        raise RuntimeError(
            "BYOK requires the 'cryptography' package. Run: pip install -r requirements.txt"
        ) from e

    raw_key = os.getenv("BYOK_ENCRYPTION_KEY")
    if not raw_key:
        raise RuntimeError(
            "BYOK_ENCRYPTION_KEY is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
            "and add it to backend/.env."
        )
    try:
        return Fernet(raw_key.encode() if isinstance(raw_key, str) else raw_key)
    except Exception as e:
        raise RuntimeError(f"BYOK_ENCRYPTION_KEY is not a valid Fernet key: {e}") from e


def encrypt_secret(plaintext: str) -> str:
    if not plaintext:
        raise ValueError("Cannot encrypt an empty key.")
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    f = _get_fernet()
    return f.decrypt(ciphertext.encode()).decode()


async def get_openai_api_key_for_tenant(client_id: str) -> Optional[str]:
    """
    Returns the tenant's own OpenAI key if they've configured one (BYOK),
    otherwise None -- callers should fall back to the platform's own
    OPENAI_API_KEY env var in that case, exactly as every agent already
    does today. Fails closed to the platform key: if decryption itself
    breaks (corrupt data, rotated encryption key), this logs the error and
    returns None rather than raising into the middle of an agent call.
    """
    encrypted = await get_tenant_byok_key_encrypted(client_id)
    if not encrypted:
        return None
    try:
        return decrypt_secret(encrypted)
    except Exception as e:
        logger.error(f"BYOK decrypt failed for tenant '{client_id}' -- falling back to platform key: {e}")
        return None


def get_openai_client_for_tenant_sync(client_id: str, platform_api_key: Optional[str], timeout: float, max_retries: int):
    """
    Sync convenience wrapper for agent modules (most agent functions in
    this codebase are plain sync functions run via asyncio.to_thread, not
    async themselves -- see e.g. agents/ops_shield.py). Builds a fresh
    OpenAI client scoped to THIS call using the tenant's BYOK key when one
    is configured, otherwise the platform key -- never a shared
    module-level client, so this is safe to call per-request.
    """
    from openai import OpenAI
    import asyncio

    tenant_key: Optional[str] = None
    try:
        # Agent functions are called from asyncio.to_thread(...), i.e. off
        # the event loop thread -- asyncio.run() is correct here, not
        # asyncio.get_event_loop().run_until_complete(), since there is no
        # running loop on this thread to conflict with.
        tenant_key = asyncio.run(get_openai_api_key_for_tenant(client_id))
    except Exception as e:
        logger.error(f"BYOK lookup failed for tenant '{client_id}' -- falling back to platform key: {e}")

    effective_key = tenant_key or platform_api_key
    if not effective_key:
        return None
    return OpenAI(api_key=effective_key, timeout=timeout, max_retries=max_retries)
