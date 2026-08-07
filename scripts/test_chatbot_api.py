#!/usr/bin/env python3
"""
Test script for the frontend chatbot API: session, start-guided, and form_data steps.

Start the API first (in another terminal):
  cd /path/to/rag
  uvicorn src.api.main:app --host 127.0.0.1 --port 8000

Then run this script:
  python scripts/test_chatbot_api.py
  python scripts/test_chatbot_api.py --base-url http://127.0.0.1:8000 --user-id test-user-1

If you see "Connection refused", the API is not running — start uvicorn as above.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict


import requests


def post_json(url: str, data: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    r = requests.post(url, json=data, timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_json(url: str, timeout: int = 30) -> Dict[str, Any]:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="Test chatbot API (session, start-guided, form_data)")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--user-id", default="test-user-pa-001", help="User identifier")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    user_id = args.user_id

    print("=== Chatbot API test (Personal Accident flow) ===\n")
    print(f"Base URL: {base}")
    print(f"User ID:  {user_id}\n")

    # 1) Create session
    print("1) POST /api/v1/session")
    try:
        out = post_json(f"{base}/api/v1/session", {"user_id": user_id})
        session_id = out["session_id"]
        print(f"   session_id: {session_id}\n")
    except requests.RequestException as e:
        print(f"   FAIL: {e}")
        if "Connection refused" in str(e) or "Failed to establish" in str(e):
            print("   → Start the API first: uvicorn src.api.main:app --host 127.0.0.1 --port 8000")
        if hasattr(e, "response") and e.response is not None:
            try:
                print(f"   body: {e.response.text[:500]}")
            except Exception:
                pass
        return 1

    # 2) Get session state (optional)
    print("2) GET /api/v1/session/{session_id}")
    try:
        state = get_json(f"{base}/api/v1/session/{session_id}")
        print(f"   mode={state.get('mode')} flow={state.get('current_flow')} step={state.get('current_step')}\n")
    except requests.RequestException as e:
        print(f"   FAIL: {e}\n")
        return 1

    # 3) Start Personal Accident flow
    print("3) POST /api/v1/chat/start-guided (personal_accident)")
    try:
        out = post_json(
            f"{base}/api/v1/chat/start-guided",
            {"flow_name": "personal_accident", "user_id": user_id, "session_id": session_id},
        )
        resp = out.get("response", {})
        if isinstance(resp, dict):
            msg = resp.get("message", resp.get("type", ""))
            fields = resp.get("fields", [])
            print(f"   step 0 prompt: {msg[:80]}...")
            print(f"   fields: {len(fields)} form fields\n")
        else:
            print(f"   response: {str(resp)[:200]}\n")
    except requests.RequestException as e:
        print(f"   FAIL: {e}\n")
        return 1

    # 4) Submit personal details (step 0 -> 1)
    print("4) POST /api/v1/chat/message (form_data: personal_details)")
    personal = {
        "surname": "Test",
        "first_name": "Jane",
        "middle_name": "M.",
        "date_of_birth": "1990-05-15",
        "email": "jane.test@example.com",
        "mobile_number": "0772123456",
        "national_id_number": "CM123456789AB",
        "nationality": "Ugandan",
        "tax_identification_number": "",
        "occupation": "Teacher",
        "gender": "Female",
        "country_of_residence": "Uganda",
        "physical_address": "Kampala",
    }
    try:
        out = post_json(
            f"{base}/api/v1/chat/message",
            {"user_id": user_id, "session_id": session_id, "message": "", "form_data": personal},
        )
        payload = out.get("response", {})
        if isinstance(payload, dict):
            inner = payload.get("response", payload)
            if isinstance(inner, dict):
                msg = inner.get("message", str(inner)[:80])
                print(f"   next step: {msg}\n")
            else:
                print(f"   next: {str(inner)[:120]}\n")
        else:
            print(f"   response: {str(payload)[:120]}\n")
    except requests.RequestException as e:
        print(f"   FAIL: {e}\n")
        return 1

    # 5) Submit next of kin (step 1 -> 2)
    print("5) POST /api/v1/chat/message (form_data: next_of_kin)")
    nok = {
        "nok_first_name": "John",
        "nok_last_name": "Test",
        "nok_middle_name": "",
        "nok_phone_number": "0772987654",
        "nok_relationship": "Spouse",
        "nok_address": "Kampala",
        "nok_id_number": "",
    }
    try:
        out = post_json(
            f"{base}/api/v1/chat/message",
            {"user_id": user_id, "session_id": session_id, "message": "", "form_data": nok},
        )
        payload = out.get("response", {})
        if isinstance(payload, dict):
            inner = payload.get("response", payload)
            if isinstance(inner, dict):
                msg = inner.get("message", str(inner)[:80])
                print(f"   next step: {msg}\n")
            else:
                print(f"   next: {str(inner)[:120]}\n")
        else:
            print(f"   response: {str(payload)[:120]}\n")
    except requests.RequestException as e:
        print(f"   FAIL: {e}\n")
        return 1

    # 6) Get session state again
    print("6) GET /api/v1/session/{session_id} (after 2 steps)")
    try:
        state = get_json(f"{base}/api/v1/session/{session_id}")
        print(f"   mode={state.get('mode')} flow={state.get('current_flow')} step={state.get('current_step')} step_name={state.get('step_name')}")
        print(f"   collected_keys={state.get('collected_keys')}\n")
    except requests.RequestException as e:
        print(f"   FAIL: {e}\n")
        return 1

    print("=== All steps completed successfully ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
