"""
Automatic Netatmo token management.

This module produces a fresh access_token from the long-lived refresh_token and
renews it automatically as soon as it gets close to expiry.

------------------------------------------------------------------------------
One-time setup:

Create a "netatmo_tokens.json" file next to this script, with your app
credentials and the refresh_token from the Token generator (scope read_station)
at https://dev.netatmo.com/apps/ :

    {
      "client_id": "YOUR_CLIENT_ID",
      "client_secret": "YOUR_CLIENT_SECRET",
      "refresh_token": "YOUR_REFRESH_TOKEN"
    }

The access_token is then generated and updated automatically. This file holds
credentials: it is git-ignored and must never be committed.

Then, in your scripts:

    from netatmo_auth import get_valid_token
    token = get_valid_token()      # always valid, refreshed if needed
------------------------------------------------------------------------------
"""

import json
import time
import requests

from pathlib import Path

# Project root = parent of the directory containing this script
PROJECT_ROOT = Path(__file__).resolve().parent.parent

TOKEN_URL = "https://api.netatmo.com/oauth2/token"
TOKENS_FILE = PROJECT_ROOT / "collector/netatmo_tokens.json"


def _load():
    with open(TOKENS_FILE) as f:
        return json.load(f)


def _save(tokens):
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f, indent=2)


def get_valid_token(margin_s=120):
    """
    Return a valid access_token, refreshing it if it expires in less than
    'margin_s' seconds. Persists the new refresh_token (in case Netatmo rotates
    it) so that the next call works too.
    """
    tokens = _load()

    # Still valid? Keep a safety margin.
    if tokens.get("access_token") and tokens.get("expires_at", 0) - margin_s > time.time():
        return tokens["access_token"]

    # Otherwise, exchange the refresh_token for a fresh access_token.
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": tokens["client_id"],
            "client_secret": tokens["client_secret"],
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    tokens["access_token"] = data["access_token"]
    # Persist the new refresh_token if one is returned, otherwise keep the old one
    tokens["refresh_token"] = data.get("refresh_token", tokens["refresh_token"])
    tokens["expires_at"] = time.time() + data.get("expires_in", 10800)  # ~3 h by default
    _save(tokens)
    return tokens["access_token"]


if __name__ == "__main__":
    # Quick test: print a valid token (truncated) and its expiry.
    tok = get_valid_token()
    exp = _load()["expires_at"]
    print("Token OK:", tok[:12], "...")
    print("Expires in", round((exp - time.time()) / 60), "min")
