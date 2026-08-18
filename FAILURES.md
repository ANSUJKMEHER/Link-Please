# FAILURES.md — Known Failure Modes & Architectural Edge Cases

This document honestly catalogs the exact edge cases, race conditions, platform quirks, and failure modes under which this system can lose a DM, deliver a duplicate, or report a mismatched stat under extreme load.

---

### 1. In-Flight Process Termination During `POST /v1/dm/send` (Potential Duplicate or Stalled DM)
* **Condition:** A kill signal (`SIGKILL` or hard container preemption) hits the process in the narrow ~20ms–200ms window between when `httpx.post("/v1/dm/send")` is received and processed by the Mock API, and before the SQLite database transaction commits `update_dm_accepted(task_id, dm_id)`.
* **Consequence:** 
  * On restart, SQLite still sees the task in `status = 'pending'`.
  * The outbound worker will re-fetch this task and issue another `POST /v1/dm/send`.
  * **Mitigation:** We send an explicit `Idempotency-Key: dm_{rule_id}_{user_id}` header on every outbound call. If the Mock API respects the `Idempotency-Key`, it returns the existing `dm_id` without sending a duplicate DM. However, if the mock API has an internal idempotency TTL eviction or cache miss, the commenter could receive a duplicate DM.

---

### 2. Mock API Rolling Window Skew & 429 Burst Penalty (Temporary Queue Stagnation)
* **Condition:** The sliding-window rate limiter in memory uses the host machine's monotonic clock (`time.time()`), while Render/Mock API uses its own server clock. If there is a clock drift or if requests land right across rolling minute boundaries, a batch of 10 requests can trigger a sudden `429 Too Many Requests`.
* **Consequence:**
  * When a `429` is returned, `Retry-After` (e.g. 5–60 seconds) halts the worker queue.
  * During this cooldown period, `/stats` reports a high `queued` count. If 500 events arrived simultaneously, draining the entire queue at 10 requests/minute takes up to **50 minutes**. If the test runner times out after 15 minutes, `/stats` will show remaining DMs still in `queued` state rather than `sent`.

---

### 3. Asymmetric Race Condition on `comment.deleted` Arriving Concurrently with DM Dispatch
* **Condition:** A `comment.deleted` webhook event arrives from the mock platform while `POST /v1/dm/send` for that same `comment_id` is already in flight across the network.
* **Consequence:**
  * `cancel_pending_dms_for_comment` executes in SQLite, but the outbound worker has already extracted the task into memory and dispatched the HTTP request.
  * The Mock API receives and accepts the DM (`202 Accepted`) for a comment that was deleted milliseconds earlier.
  * The DM is delivered despite the comment no longer existing.

---

### 4. Terminal `failed` Re-Queue Exhaustion vs Permanent Failure Classification
* **Condition:** The Mock API accepts a DM (`202 Accepted`), but during downstream reconciliation (`GET /v1/dm/{dm_id}`), it returns `status: "failed"` (roughly 15% of accepted DMs fail asynchronously). 
* **Consequence:**
  * The reconciler worker re-queues the DM (`status = 'pending'`) to retry delivery.
  * However, if the mock API fails the delivery repeatedly until `attempts >= max_attempts` (5 attempts), our system marks it `status = 'failed'` to avoid infinite retry loops.
  * In `/stats`, this increments the `failed` counter by 1 and decrements `queued`. If the mock API's failure was transient (e.g. mock server reboot), that DM is permanently conceded as failed.

---

### 5. Multi-Worker / Multi-Instance Horizontal Scaling Without Centralized Redis Lock
* **Condition:** Running multiple web server replicas (e.g. scaling horizontally on Kubernetes or Render to 2+ instances) against separate in-process rate limiters or replicated SQLite databases without a distributed lock.
* **Consequence:**
  * Each worker instance independently allows 10 requests per 60 seconds.
  * With 3 instances, the effective rate becomes 30 req / 60s, instantly breaching the Mock API limit and causing cascading `429` rate limit rejections.
  * **Solution for single-node deployment:** The application is architected as a consolidated singleton worker loop with serialized SQLite WAL transactions, ensuring exactly 10 req/60s platform compliance.

---

### 6. Signature Verification Failure on Trailing Whitespace / Encoding Mutators
* **Condition:** An intermediary reverse proxy or cloud firewall (like Cloudflare or an improperly configured Nginx layer) normalizes, strips trailing newlines, or decodes/re-encodes the raw request payload before passing it to FastAPI.
* **Consequence:**
  * `hmac.new(..., raw_body, ...)` computes a digest on the modified bytes, causing a mismatch with `X-PseudoGram-Signature: sha256=<hex>`.
  * The webhook returns `401 Unauthorized` and legitimately dropped events never enter the queue.
  * **Mitigation:** We consume `await request.body()` directly as raw bytes prior to any JSON decoding.
