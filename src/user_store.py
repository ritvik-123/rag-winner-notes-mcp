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
