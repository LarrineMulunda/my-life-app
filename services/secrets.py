"""
secrets.py — Gemini API key management.
Production: reads from GCP Secret Manager.
Development: falls back to database config table.

Set GEMINI_SECRET_NAME env var to use Secret Manager.
e.g. GEMINI_SECRET_NAME=projects/my-life-app-001/secrets/GEMINI_API_KEY/versions/latest
"""
import os
import logging

log = logging.getLogger(__name__)

GEMINI_SECRET_NAME = os.environ.get("GEMINI_SECRET_NAME")

def get_gemini_key(user_id=None):
    """
    Get Gemini API key.
    Priority: Secret Manager → user's DB config → None
    """
    # 1. GCP Secret Manager (production)
    if GEMINI_SECRET_NAME:
        try:
            from google.cloud import secretmanager
            client  = secretmanager.SecretManagerServiceClient()
            resp    = client.access_secret_version(name=GEMINI_SECRET_NAME)
            key     = resp.payload.data.decode("utf-8").strip()
            if key:
                return key
        except Exception as e:
            log.warning(f"Secret Manager unavailable: {e}")

    # 2. Per-user DB config (dev / fallback)
    if user_id:
        from db import cfg_get
        return cfg_get(user_id, "gemini_api_key")

    return None

def save_gemini_key_to_secret(key: str):
    """
    Save a new key version to GCP Secret Manager.
    Only works if GEMINI_SECRET_NAME is configured.
    Returns True on success, False otherwise.
    """
    if not GEMINI_SECRET_NAME:
        return False
    try:
        from google.cloud import secretmanager
        # Parse secret name to get parent
        parts  = GEMINI_SECRET_NAME.split("/versions/")[0]
        client = secretmanager.SecretManagerServiceClient()
        client.add_secret_version(
            parent=parts,
            payload={"data": key.encode("utf-8")}
        )
        return True
    except Exception as e:
        log.error(f"Failed to save key to Secret Manager: {e}")
        return False
