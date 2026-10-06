import secrets

from google.cloud import firestore

_client: firestore.Client | None = None


def _get_client() -> firestore.Client:
    global _client
    if _client is None:
        _client = firestore.Client()
    return _client


def resolve_api_key(api_key: str) -> str | None:
    """Look up which user an MCP API key belongs to.

    Keys are stored as documents in the "api_keys" collection, keyed by the
    key string itself, each holding the user_id it belongs to -- a lookup
    by document ID is a single point read, not a collection scan.
    """
    doc = _get_client().collection("api_keys").document(api_key).get()
    return doc.to_dict()["user_id"] if doc.exists else None


def create_api_key(user_id: str) -> str:
    """Mint a new personal MCP API key for this user and store the mapping.

    32 random url-safe bytes makes a collision astronomically unlikely, so
    no uniqueness check before writing -- not worth the extra read.
    """
    api_key = secrets.token_urlsafe(32)
    _get_client().collection("api_keys").document(api_key).set({"user_id": user_id})
    return api_key
