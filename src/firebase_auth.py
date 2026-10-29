import firebase_admin
from fastapi import Header, HTTPException
from firebase_admin import auth as firebase_auth_sdk

_app: firebase_admin.App | None = None


def _get_app() -> firebase_admin.App:
    global _app
    if _app is None:
        # No explicit credentials passed -- this resolves via Application
        # Default Credentials, same as the GCS/Firestore clients already in
        # this project: the attached service account on Cloud Run, or
        # `gcloud auth application-default login` locally. Local user-ADC
        # credentials don't carry a project ID the way a service account
        # does, so GOOGLE_CLOUD_PROJECT must be set in .env for this to work
        # outside Cloud Run.
        _app = firebase_admin.initialize_app()
    return _app


def get_current_user_id(authorization: str = Header(...)) -> str:
    """FastAPI dependency: verifies the "Authorization: Bearer <id_token>"
    header against Firebase and returns the caller's uid.

    The id_token itself is self-certifying (a signed JWT Firebase issued at
    login) -- verifying it is a local signature/expiry check against
    Google's public keys, not a network round trip per request.
    """
    _get_app()
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")

    id_token = authorization.removeprefix("Bearer ")
    try:
        decoded = firebase_auth_sdk.verify_id_token(id_token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    return decoded["uid"]
