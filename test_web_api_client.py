import os

import requests
from dotenv import load_dotenv

load_dotenv()

FIREBASE_API_KEY = os.environ["FIREBASE_WEB_API_KEY"]
TEST_EMAIL = os.environ.get("TEST_EMAIL", "test@example.com")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD", "testpassword123")
BASE_URL = os.environ.get("WEB_API_BASE_URL", "http://localhost:8080")


def get_id_token() -> str:
    """Sign up (or sign in, if the test account already exists) directly
    against Firebase's own REST API -- this is exactly what the browser
    SDK will do under the hood once phase E has a login form; we're just
    doing it by hand here since there's no UI yet.
    """
    payload = {"email": TEST_EMAIL, "password": TEST_PASSWORD, "returnSecureToken": True}
    response = requests.post(
        f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_API_KEY}",
        json=payload,
    )
    if response.status_code == 400 and "EMAIL_EXISTS" in response.text:
        response = requests.post(
            f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}",
            json=payload,
        )
    response.raise_for_status()
    return response.json()["idToken"]


def main() -> None:
    id_token = get_id_token()
    headers = {"Authorization": f"Bearer {id_token}"}
    print("Signed in, got id token.\n")

    api_key_response = requests.post(f"{BASE_URL}/api-keys", headers=headers)
    api_key_response.raise_for_status()
    print(f"Minted MCP API key: {api_key_response.json()}\n")

    note_content = b"Ritvik is building a RAG notes app, learning LangChain, MCP, and GCP deployment from scratch."
    upload_response = requests.post(
        f"{BASE_URL}/notes/upload",
        headers=headers,
        files={"file": ("test-note.txt", note_content, "text/plain")},
    )
    upload_response.raise_for_status()
    print(f"Uploaded note: {upload_response.json()}\n")

    notes_response = requests.get(f"{BASE_URL}/notes", headers=headers)
    notes_response.raise_for_status()
    print(f"Notes on file: {notes_response.json()}\n")

    ask_response = requests.post(
        f"{BASE_URL}/ask",
        headers=headers,
        json={"question": "What is Ritvik building?"},
    )
    ask_response.raise_for_status()
    print(f"Answer: {ask_response.json()}\n")


if __name__ == "__main__":
    main()
