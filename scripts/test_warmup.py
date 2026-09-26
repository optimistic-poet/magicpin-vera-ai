"""
scripts/test_warmup.py — Manual warmup test that runs without an LLM API key.
Tests all 5 endpoints against a running server.
"""
import sys
import json
from pathlib import Path

# Fix Windows console encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Add challenge dir to path to import judge_simulator
challenge_dir = Path(__file__).parent.parent / "challenge"
sys.path.insert(0, str(challenge_dir))

import judge_simulator as j

BOT_URL = "http://localhost:8000"
client = j.BotClient(BOT_URL)
ds = j.DatasetLoader(challenge_dir / "dataset")
ds.load()

print("=" * 60)
print("WARMUP TEST (no LLM required)")
print("=" * 60)

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"

# --- healthz ---
data, err, lat = client.healthz()
if err:
    print(f"{FAIL} healthz: {err}")
    sys.exit(1)
print(f"{PASS} healthz ({lat:.0f}ms)")

# --- metadata ---
data, err, lat = client.metadata()
if err:
    print(f"{WARN} metadata: {err}")
else:
    print(f"{PASS} metadata - Team: {data.get('team_name')}, Model: {data.get('model')}")

# --- context push ---
print("\n--- CONTEXT PUSH ---")
all_ok = True
for slug, cat in ds.categories.items():
    data, err, _ = client.push_context("category", slug, 1, cat)
    ok = data and data.get("accepted")
    print(f"  [{'PASS' if ok else 'FAIL'}] category/{slug}")
    if not ok:
        all_ok = False

for mid, m in list(ds.merchants.items())[:10]:
    data, err, _ = client.push_context("merchant", mid, 1, m)
    ok = data and data.get("accepted")
    short = mid[:35]
    print(f"  [{'PASS' if ok else 'FAIL'}] merchant/{short}")
    if not ok:
        all_ok = False

for tid, t in list(ds.triggers.items())[:5]:
    data, err, _ = client.push_context("trigger", tid, 1, t)
    ok = data and data.get("accepted")
    print(f"  [{'PASS' if ok else 'FAIL'}] trigger/{tid[:35]}")

# --- same-version re-push → 409 ---
print("\n--- IDEMPOTENCY TEST ---")
first_slug = list(ds.categories.keys())[0]
data, err, _ = client.push_context("category", first_slug, 1, ds.categories[first_slug])
if data and not data.get("accepted") and data.get("reason") == "stale_version":
    print(f"{PASS} Same-version re-push -> 409 stale_version (correct)")
else:
    print(f"{FAIL} Same-version re-push did not return stale_version: {data}")

# --- tick ---
print("\n--- TICK TEST ---")
for tid, t in list(ds.triggers.items())[:3]:
    client.push_context("trigger", tid, 1, t)

tids = list(ds.triggers.keys())[:3]
data, err, lat = client.tick(tids)
if err:
    print(f"{FAIL} tick: {err}")
else:
    actions = data.get("actions", [])
    print(f"{PASS} tick ({lat:.0f}ms) -> {len(actions)} action(s)")
    for a in actions:
        body = a.get("body", "")[:80]
        cta = a.get("cta")
        sa = a.get("send_as")
        has_url = "http://" in body or "https://" in body
        print(f"  [{a.get('trigger_id', '?')[:30]}]")
        print(f"    send_as={sa}, cta={cta}")
        print(f"    body: {body!r}")
        if has_url:
            print(f"  {FAIL} URL found in body!")

# --- reply: auto-reply ---
print("\n--- AUTO-REPLY TEST ---")
mid = list(ds.merchants.keys())[0]
auto_msg = "Thank you for contacting us! Our team will respond shortly."
for i in range(1, 4):
    data, err, _ = client.reply(f"conv_auto_{i}", mid, auto_msg, i + 1)
    action = data.get("action", "?") if data else "ERROR"
    print(f"  Turn {i}: {action}")
    if action == "end":
        print(f"  {PASS} Bot correctly ended after detecting auto-reply pattern")
        break
else:
    print(f"  {WARN} Bot never ended after 3 auto-replies")

# --- reply: intent transition ---
print("\n--- INTENT TRANSITION TEST ---")
mid = list(ds.merchants.keys())[0]
data, err, _ = client.reply("conv_intent_1", mid, "Ok lets do it. Whats next?", 2)
if data:
    action = data.get("action", "?")
    body = (data.get("body") or "").lower()
    qualifying = ["would you like", "are you sure", "do you want"]
    actioning = ["done", "sending", "draft", "here", "confirm", "proceed", "next", "booking", "going"]
    if action == "send" and any(w in body for w in actioning):
        print(f"{PASS} Bot switched to ACTION mode correctly")
    elif any(w in body for w in qualifying):
        print(f"{FAIL} Bot still qualifying after commitment!")
    else:
        print(f"{WARN} Response: action={action}, body={body[:80]!r}")
else:
    print(f"{FAIL} Error: {err}")

# --- reply: hostile ---
print("\n--- HOSTILE TEST ---")
mid = list(ds.merchants.keys())[0]
data, err, _ = client.reply("conv_hostile", mid, "Stop messaging me. This is useless spam.", 2)
if data:
    if data.get("action") == "end":
        print(f"{PASS} Bot ended conversation on hostile message")
    else:
        print(f"{WARN} action={data.get('action')}, body={data.get('body', '')[:50]!r}")

print("\n" + "=" * 60)
print("WARMUP COMPLETE")
print("=" * 60)
