# Magicpin Vera AI Challenge — Solution

Production-ready, deterministic backend solution for the **Magicpin Vera AI Challenge**. Vera is an intelligent merchant and customer engagement engine exposed as an asynchronous FastAPI microservice.

---

## 1. Key Architectural Highlights

- **100% Deterministic & Reliable**: Zero external LLM dependency for response generation. The judge or testing harness can evaluate the bot without needing private API keys or facing rate limits.
- **Strictly Grounded in Context**: Every metric, price, clinical trial, journal, or offer is pulled directly from the versioned in-memory store. Zero hallucination.
- **4-Context Layer Engine**:
  - `CategoryContext`: Vertical voice registers, tone rules, taboo vocabulary, digest items, seasonal peaks, and offer templates.
  - `MerchantContext`: Performance metrics (views, calls, CTR, directions), verification status, active offers, owner details, language preferences, customer aggregates, signals.
  - `CustomerContext`: Recency, lifetime value, preferred time slots, language preferences, consent scopes.
  - `TriggerContext`: Internal performance dips/spikes, recall alerts, license/subscription renewals, external research digests, IPL matches, regulatory updates.
- **Robust Conversation State Machine**:
  - Auto-reply detection and graceful backoff (canned responses detected -> 1st: polite nudge, 2nd: 24h wait, 3rd: clean exit).
  - Instant transition into action mode upon commitment ("Ok let's do it" -> immediate drafting / confirmation without re-qualifying).
  - Graceful exit and 30-day merchant-level suppression upon opt-out or hostile responses.
  - Re-opening closed conversations if a merchant expresses renewed positive intent.
- **Anti-Penalty Compliance**:
  - Absolute suppression of outbound URLs (0 penalty risk).
  - Exact anti-repetition guards per conversation.
  - Versioned atomic context replacement (`POST /v1/context`) with strict 409 stale version enforcement.

---

## 2. API Contract Implementation

| Endpoint | Method | Status | Description |
|---|---|---|---|
| `/v1/healthz` | GET | `200 OK` | Liveness probe with sub-millisecond response and context breakdown counts. |
| `/v1/metadata` | GET | `200 OK` | Bot identification, team details, model designation, and architectural approach. |
| `/v1/context` | POST | `200 / 409` | Versioned context intake for categories, merchants, customers, triggers. |
| `/v1/tick` | POST | `200 OK` | Periodic wake-up evaluation. Filters, prioritizes, deduplicates, and composes actions. |
| `/v1/reply` | POST | `200 OK` | Multi-turn conversation handling returning `send`, `wait`, or `end`. |
| `/v1/teardown`| POST | `200 OK` | Reset endpoint to wipe in-memory context and conversation state between test suites. |

---

## 3. Directory Layout

```text
magicpin-vera-ai/
├── app/
│   ├── config.py              # Metadata, team name, and version constants
│   ├── schemas.py             # Pydantic request/response schemas
│   ├── state.py               # In-memory ContextStore and ConversationStore
│   ├── main.py                # FastAPI HTTP routing and lifecycle
│   ├── engine/
│   │   ├── category_rules.py  # Vertical rules, vocabulary taboos, and tone helpers
│   │   ├── composer.py        # Central composition engine (26 specialized handlers)
│   │   ├── conversation.py    # Conversation state machine and reply routing
│   │   ├── suppression.py     # Suppression key tracking and merchant silencing
│   │   └── trigger_selector.py# Trigger filtering, expiration checks, and prioritization
│   └── utils/
│       ├── detection.py       # Deterministic intent and auto-reply classification
│       └── text.py            # Currency, numbers, and text utilities
├── challenge/                 # Official challenge specifications and seed data
│   ├── dataset/
│   ├── expanded/              # 50 merchants, 200 customers, 100 triggers, 30 canonical pairs
│   └── judge_simulator.py     # Official judge harness
├── scripts/
│   ├── live_test.py           # End-to-end HTTP verification script
│   └── test_warmup.py         # Judge warmup scenario runner
├── tests/
│   ├── conftest.py            # Pytest fixtures and mock contexts
│   ├── test_health.py         # /v1/healthz tests
│   ├── test_metadata.py       # /v1/metadata tests
│   ├── test_context.py        # /v1/context versioning & idempotency tests
│   ├── test_tick.py           # /v1/tick proactive actions and URL validation tests
│   ├── test_reply.py          # /v1/reply multi-turn state machine tests
│   ├── test_suppression.py    # Suppression and deduplication tests
│   └── test_canonical.py      # Canonical pairs validation tests
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 4. Setup & Running Locally

### Prerequisites
- Python 3.10+ (tested on Python 3.11 and 3.13 on Windows)
- pip

### 1. Install dependencies
```powershell
pip install -r requirements.txt
```

### 2. Run the test suite
```powershell
python -m pytest tests/ -v
```
All 40 unit and integration tests will execute.

### 3. Start the server
```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 4. Verify endpoints live
In another terminal:
```powershell
python scripts/live_test.py
```
Or run the complete warmup suite:
```powershell
python scripts/test_warmup.py
```

---

## 5. Docker Deployment

### Build and Run with Docker
```bash
docker build -t magicpin-vera-bot .
docker run -p 8000:8000 magicpin-vera-bot
```

### Or using Docker Compose
```bash
docker compose up -d
```
The container includes a built-in health check polling `http://localhost:8000/v1/healthz`.

---

## 6. Verification & Evaluation Results

- **Unit & Integration Suite**: 40/40 tests passing (`pytest tests/ -v`).
- **Live HTTP Validation**:
  - `GET /v1/healthz` -> `200 OK`
  - `GET /v1/metadata` -> `200 OK`
  - `POST /v1/context` -> `200 Accepted` on first push, `409 Stale Version` on duplicate version, `200 Accepted` on version update.
  - `POST /v1/tick` -> Valid grounded action returned with zero URLs, correct CTA, template naming, and send_as identity.
  - `POST /v1/reply` ->
    - Auto-reply detected: Turn 1 `send`, Turn 2 `wait`, Turn 3 `end`.
    - Hostile opt-out: Immediate `end` and 30-day merchant suppression.
    - Intent transition: Immediate action mode transition with actionable next steps.
- **Judge Simulator Compatibility**: Full compatibility across Warmup, Phase 2, Auto-Reply Detection, Intent Transition, and Hostile Handling test harnesses.
