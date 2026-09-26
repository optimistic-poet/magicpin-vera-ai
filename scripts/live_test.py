"""scripts/live_test.py — Full live test against running server on port 8000."""
import sys
import urllib.request
import json

BOT = "http://localhost:8000"

def req(method, path, body=None):
    url = BOT + path
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(r, timeout=10)
        return json.loads(resp.read()), resp.status
    except urllib.request.HTTPError as e:
        return json.loads(e.read()), e.code
    except Exception as ex:
        return {"error": str(ex)}, 0

def P(ok, label, detail=""):
    tag = "[PASS]" if ok else "[FAIL]"
    print(f"{tag} {label}" + (f": {detail}" if detail else ""))
    return ok

all_ok = True

print("=" * 55)
print("LIVE SERVER TEST — http://localhost:8000")
print("=" * 55)

# healthz
d, s = req("GET", "/v1/healthz")
all_ok &= P(s == 200, "GET /v1/healthz", f"status={d.get('status')}, uptime={d.get('uptime_seconds')}s")

# metadata
d, s = req("GET", "/v1/metadata")
all_ok &= P(s == 200 and "team_name" in d, "GET /v1/metadata", f"team={d.get('team_name')}")

# context push
d1, s1 = req("POST", "/v1/context", {
    "scope": "category", "context_id": "dentists_livetest",
    "version": 1, "payload": {"slug": "dentists"}, "delivered_at": "2026-04-26T10:00:00Z"
})
all_ok &= P(s1 == 200 and d1.get("accepted"), "POST /v1/context (new)", f"ack={d1.get('ack_id')}")

# Same version -> 409
d2, s2 = req("POST", "/v1/context", {
    "scope": "category", "context_id": "dentists_livetest",
    "version": 1, "payload": {"slug": "dentists"}, "delivered_at": "2026-04-26T10:00:00Z"
})
all_ok &= P(s2 == 409 and d2.get("reason") == "stale_version",
            "POST /v1/context (same version -> 409)", f"reason={d2.get('reason')}")

# Higher version -> 200
d3, s3 = req("POST", "/v1/context", {
    "scope": "category", "context_id": "dentists_livetest",
    "version": 2, "payload": {"slug": "dentists"}, "delivered_at": "2026-04-26T10:00:00Z"
})
all_ok &= P(s3 == 200 and d3.get("accepted"), "POST /v1/context (higher version -> 200)")

# Auto-reply test
print("\n--- AUTO-REPLY DETECTION ---")
auto = "Thank you for contacting us! Our team will respond shortly."
ended = False
for i in range(1, 5):
    d, s = req("POST", "/v1/reply", {
        "conversation_id": f"conv_auto_live_{i}",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "customer_id": None,
        "from_role": "merchant",
        "message": auto,
        "received_at": "2026-04-26T10:01:00Z",
        "turn_number": i + 1
    })
    action = d.get("action", "?")
    print(f"  Turn {i}: {action}")
    if action == "end":
        ended = True
        break
all_ok &= P(ended, "Auto-reply ends correctly within 3 turns")

# Intent transition
print("\n--- INTENT TRANSITION ---")
d, s = req("POST", "/v1/reply", {
    "conversation_id": "conv_intent_live",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "from_role": "merchant",
    "message": "Ok lets do it. Whats next?",
    "received_at": "2026-04-26T10:01:00Z",
    "turn_number": 2
})
body = (d.get("body") or "").lower()
action = d.get("action", "?")
actioning = ["done", "sending", "draft", "confirm", "proceed", "booking", "right away", "on it"]
qualifying = ["would you like to", "do you want", "are you sure"]
is_action = action == "send" and any(w in body for w in actioning)
is_still_qualifying = any(w in body for w in qualifying)
all_ok &= P(is_action and not is_still_qualifying, "Intent transition: action mode", f"action={action}, body={body[:60]!r}")

# Hostile
print("\n--- HOSTILE HANDLING ---")
d, s = req("POST", "/v1/reply", {
    "conversation_id": "conv_hostile_live",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "from_role": "merchant",
    "message": "Stop messaging me. This is useless spam.",
    "received_at": "2026-04-26T10:01:00Z",
    "turn_number": 2
})
all_ok &= P(d.get("action") == "end", "Hostile -> end", f"action={d.get('action')}")

print()
print("=" * 55)
if all_ok:
    print("ALL TESTS PASSED")
else:
    print("SOME TESTS FAILED (see above)")
print("=" * 55)
sys.exit(0 if all_ok else 1)
