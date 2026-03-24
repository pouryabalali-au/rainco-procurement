import json
import base64
import requests
import os

REPO = "pouryabalali-au/rainco-procurement"
FILE_PATH = "supplier_data.json"
API_BASE = "https://api.github.com"


def _token():
    try:
        import streamlit as st
        return st.secrets["GITHUB_TOKEN"]
    except Exception:
        return os.getenv("GITHUB_TOKEN")


def _headers():
    return {
        "Authorization": f"token {_token()}",
        "Accept": "application/vnd.github.v3+json",
    }


def load_supplier_data() -> dict:
    """Load supplier_data.json from GitHub. Falls back to local file."""
    try:
        r = requests.get(
            f"{API_BASE}/repos/{REPO}/contents/{FILE_PATH}",
            headers=_headers(), timeout=10
        )
        if r.status_code == 200:
            content = r.json().get("content", "")
            decoded = base64.b64decode(content).decode("utf-8")
            return json.loads(decoded)
    except Exception:
        pass
    # Fallback to local file
    try:
        with open(FILE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_supplier_data(data: dict) -> bool:
    """Save supplier_data.json to GitHub. Returns True on success."""
    try:
        # Get current file SHA (required for update)
        r = requests.get(
            f"{API_BASE}/repos/{REPO}/contents/{FILE_PATH}",
            headers=_headers(), timeout=10
        )
        sha = r.json().get("sha") if r.status_code == 200 else None

        encoded = base64.b64encode(
            json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
        ).decode("utf-8")

        payload = {
            "message": "Update supplier data via Procurement Dashboard",
            "content": encoded,
        }
        if sha:
            payload["sha"] = sha

        r2 = requests.put(
            f"{API_BASE}/repos/{REPO}/contents/{FILE_PATH}",
            headers=_headers(), json=payload, timeout=15
        )
        return r2.status_code in (200, 201)
    except Exception:
        return False
