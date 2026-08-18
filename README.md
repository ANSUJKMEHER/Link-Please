# LinkPlease — Instagram DM Automation Engine

> High-throughput, resilient Instagram DM automation engine built for creator marketing automation, handling hostile platform API conditions (rate limits, out-of-order deliveries, network drops, event duplication, and downstream delivery failures).

---

## Architecture & System Design

```
                     ┌──────────────────────────────┐
                     │   Mock Instagram API / Web   │
                     └──────────────┬───────────────┘
                                    │
               POST /webhook (HMAC) │
                                    ▼
                     ┌──────────────────────────────┐
                     │  FastAPI Ingestion Gateway   │
                     │  - Raw-body HMAC-SHA256 Auth │
                     │  - Event ID Deduplication    │
                     │  - Substring Rule Matcher    │
                     │  - Atomic (user, rule) Lock  │
                     └──────────────┬───────────────┘
                                    │ Fast Insert (< 5ms)
                                    ▼
                     ┌──────────────────────────────┐
                     │   SQLite (WAL Mode) Queue    │
                     │   Persistent task storage    │
                     └───────┬──────────────┬───────┘
                             │              │
        Pending DMs to send  │              │ Accepted DMs to verify
                             ▼              ▼
     ┌─────────────────────────────┐  ┌─────────────────────────────┐
     │   Outbound Worker Loop      │  │    Delivery Reconciler      │
     │ - Sliding Rate Limiter      │  │ - Polls GET /v1/dm/{id}     │
     │   (10 req / 60s window)     │  │ - Zero rate limit impact    │
     │ - Exponential Backoff (500) │  │ - Re-queues late failures   │
     │ - Idempotency-Key dispatch  │  │ - Updates terminal states   │
     └─────────────────────────────┘  └─────────────────────────────┘
```

---

## API Contract Compliance

The application strictly implements the required routes with exact JSON schemas:

### 1. `POST /webhook`
* Returns `200 OK` in `< 10ms` asynchronously.
* Verifies `X-PseudoGram-Signature: sha256=<hex>` against raw request bytes using `API_KEY`.
* Deduplicates redelivered `event_id`s (~8% duplicate stream).
* Cancels pending queued DMs if a `comment.deleted` event is received.
* Case-insensitively matches keywords across incoming comments.
* Guarantees `(user_id, rule_id)` uniqueness — no user is ever DMed twice for the same rule.

### 2. `POST /rules`
```json
// Request
{ "keyword": "PRICE", "dm_message": "Here's the price list: https://example.com/pricing" }

// Response 201 Created
{ "rule_id": "rule_a1b2c3d4", "keyword": "PRICE", "dm_message": "Here's the price list: https://example.com/pricing" }
```

### 3. `GET /stats`
```json
{
  "sent": 142,
  "failed": 3,
  "queued": 8,
  "duplicates_blocked": 57
}
```
* `sent` — DMs confirmed delivered by Mock API
* `failed` — Conceded after max retries or 400 errors
* `queued` — Waiting to send, retrying, or awaiting reconciliation
* `duplicates_blocked` — Duplicate DM attempts blocked by deduplication logic

---

## Quickstart & Local Setup

### 1. Clone & Install Dependencies
```bash
git clone <your-repo-url>
cd linkplease

# Create virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### 2. Configure Environment (.env)
```bash
cp .env.example .env
```
Run the setup script to register with the mock API and obtain your API key:
```bash
python scripts/apply_and_keygen.py
```

### 3. Run the Server
```bash
python scripts/start_server.py
# Or directly via uvicorn:
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open [http://localhost:8000](http://localhost:8000) or [http://localhost:8000/docs](http://localhost:8000/docs) in your browser for Swagger API documentation!

---

## Running the Automated Test Suite

We provide a comprehensive test suite testing edge cases, deduplication, rate limiting, and reconciliation:

```bash
pytest -v
```

---

## Deploying to Production (Render / Railway)

The assignment requires a `working_url` (publicly accessible base URL) that the automated grading script can hit.

### Option 1: Deploy on Render (Recommended & Free)
1. Push this codebase to your public GitHub repository:
   ```bash
   git init
   git add .
   git commit -m "feat: complete LinkPlease engine"
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
   git push -u origin main
   ```
2. Go to [dashboard.render.com](https://dashboard.render.com/) and click **New +** → **Web Service**.
3. Select your GitHub repository.
4. Configure the service:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Under **Environment Variables**, add:
   - `MOCK_API_BASE_URL`: `https://pseudogram-api.onrender.com`
   - `API_KEY`: *(your generated API key from step 2)*
   - `VERIFY_SIGNATURE`: `True`
6. Click **Deploy Web Service**.
7. Your deployed base URL will look like: `https://linkplease-engine-xxxx.onrender.com`.

### Option 2: Deploy on Railway
1. Go to [railway.app](https://railway.app/) and create a new project from your GitHub repo.
2. Under Variables, add `API_KEY` and `MOCK_API_BASE_URL`.
3. Under Settings → Networking, click **Generate Domain**.

---

## 3-Minute Loom Video Script

Use this clear, crisp outline for your 3-minute Loom walkthrough:

### Question 1: One tradeoff you made, and what you gave up by making it.
> **Answer:** "I chose a single-process async architecture with SQLite Write-Ahead Logging (WAL) and an in-memory sliding-window token bucket rate limiter instead of an external distributed broker like Redis + Celery. 
>
> **What we gained:** Absolute zero-dependency operational simplicity, microsecond SQLite transactions, zero serialization overhead, and guaranteed single-point strict enforcement of the Mock API's 10 req/60s rate limit without distributed race conditions.
>
> **What we gave up:** Horizontal scalability. If we deploy multiple stateless worker containers behind a load balancer, each container's sliding rate limiter would run independently, potentially bursting up to N × 10 req/60s and causing 429 rejections unless backed by a distributed Redis token bucket."

### Question 2: What you'd do differently with one more week.
> **Answer:** "With one more week, I would implement:
> 1. **Distributed Token Bucket & Redis Streams:** Decouple the ingestion gateway from outbound workers using Redis Streams, allowing the webhook ingestion to scale to tens of thousands of requests/second while outbound workers consume tasks via distributed Lua rate limiters.
> 2. **Multi-Tenant Rule Engine:** Add support for regex patterns, sentiment filtering, and multiple concurrent Instagram creator accounts with per-account token buckets.
> 3. **Dead-Letter Queue (DLQ) & Admin Replay:** A dedicated DLQ with manual inspection and one-click replay for poisoned payloads or permanent 400 Bad Request errors."

---

## Submission Checklist

- [x] Part A: `POST /rules`, `POST /webhook`, `GET /stats`, deduplication by `(user_id, rule_id)`
- [x] Part B: HMAC-SHA256 signature verification & real-time `/stats`
- [x] Part C: Delivery status reconciliation, `comment.deleted` handling, 10 req/60s sliding rate limiter
- [x] `FAILURES.md` present in root with honest edge-case analysis
- [x] All 11 automated test suites passing
