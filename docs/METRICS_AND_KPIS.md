# Metrics & KPIs — How Every Metric Is Calculated

This document explains, for every number shown on the admin dashboards, **what it
means**, **exactly how it is computed**, and **what raw data it is based on**.

All formulas below were traced from the code:

| Component | Source |
|---|---|
| Conversation outcome classification (single source of truth) | `src/metrics_outcomes.py` |
| `/metrics/impact` endpoint | `src/api/main.py:1620-1860` |
| `/metrics/ai-performance` endpoint | `src/api/main.py:900-1440` |
| `/metrics/system-performance` endpoint | `src/api/main.py:827-898` |
| RAG metric recording | `src/chatbot/modes/conversational.py` (`_emit_metrics`, `_metric_payload`, `_estimate_response_confidence`) |
| DB queries | `src/database/postgres_real.py` (real Postgres), `src/database/postgres.py` (in-memory stub) |

---

## 1. Data Sources

Every metric is derived from the same set of tables. All queries filter by a
**time window** `[now - days, now)`.

| Table | Holds | Used by |
|---|---|---|
| `conversations` | One row per chat (created when a session starts) | Outcome model, off-hours, repeat users, self-serve |
| `conversation_events` | Timestamped signals per conversation (`completion_confirmed`, `escalation_confirmed`, `service_error`, `unanswered_question`, `agent_joined`, `csat`, `session_end`, `intent`, ...) | Outcome model, escalations, agent pickup, CSAT, intents |
| `rag_metrics` | Numeric telemetry per bot reply (`response_latency`, `confidence_score`, `retrieval_accuracy`, `fallbacks`, `service_heartbeat`) | Latency, AI accuracy, fallback trend, uptime |
| `quotes` | Quote records created by guided flows | Quote count, chatbot leads |
| `payment_transactions` | Payment attempts/results | Quote→payment, payment success |
| `messages` | User/bot messages per conversation | Avg length, avg messages, intent inference fallback |
| `escalation_sessions` | Escalation/handover records | (Source for escalation records) |
| `users` | User identities (phone, Zoho contact id) | Repeat users, Zoho linking |

> **Storage mode matters.** If the app runs with real Postgres
> (`USE_POSTGRES_CONVERSATIONS=true` and a reachable `DATABASE_URL`), all tables
> above live in that database and **persist across redeploys**. Without those
> settings the app silently falls back to an **in-memory stub**
> (`src/utils/runtime_env.py:36-46`, startup log line
> `effective_postgres=true|false`) and all data is ephemeral — it disappears on
> the next deploy, and payment records may be written to a separate stub the
> metrics cannot see.

---

## 2. The Outcome Model — the Single Source of Truth

`compute_conversation_outcomes(db, start, end)` (`src/metrics_outcomes.py:68-124`)
classifies **every conversation created in the window** into **exactly one**
bucket so dashboard cards never double-count the same chat.

### 2.1 The six buckets

| Bucket | Meaning | Signal |
|---|---|---|
| `bot_down` | The bot errored / was down | `service_error` event |
| `escalated` | Handed off to a human agent | `escalation_confirmed` event |
| `resolved` | Customer confirmed "yes" to the completion question | `completion_confirmed` with outcome ≥ 0.5 |
| `unresolved` | Customer said "no", or the bot explicitly couldn't answer | `completion_confirmed` with outcome < 0.5, or `unanswered_question` |
| `no_verdict` | Chat ended but neither an outcome nor an escalation was recorded | `session_end` event with no other signal |
| `in_progress` | Created in the window but no terminal signal yet | None of the above |

### 2.2 Priority when multiple signals exist

A chat can fire several events (e.g. an escalation then a completion). One bucket
wins, in this order:

```
bot_down > escalated > resolved > unresolved > no_verdict > in_progress
```

### 2.3 How each event maps to an outcome (`_event_outcome`, lines 53-65)

- `service_error` → `bot_down`
- `escalation_confirmed` → `escalated`
- `completion_confirmed` → `resolved` if `outcome >= 0.5`, else `unresolved`
- `unanswered_question` → `unresolved`

The completion outcome is normalised by `_coerce_outcome` (lines 38-50), which
accepts **both** numeric values (`1.0`/`0.0`, as the demo seeder writes) and
**worded** values (`"resolved"`/`"unresolved"`/`"yes"`/`"no"`/`"true"`/`"y"`/`"1"`,
as the live chat completion path writes). This is what fixed the resolution
metric for real chats.

### 2.4 Where the signals are produced

| Signal | Emitted from |
|---|---|
| `completion_confirmed` | Completion question reply (affirmative → `resolved`, negative → `unresolved`) — `conversational.py:2036-2051` |
| `escalation_confirmed` | Chat-flow handover (`conversational.py:749`), the "Connect to agent" button (`flows/router.py:103`), and the direct `POST /escalate` endpoint (`api/escalation.py:52`) |
| `agent_joined` | Agent joins an escalated session (`state_manager.py:110`) |
| `unanswered_question` | No relevant chunks / low confidence (`conversational.py:2004-2018`) |
| `service_error` | Generator/LLM failure (`conversational.py:2020-2034`) |
| `csat` | `POST /metrics/csat` (`main.py:1862-1899`) |
| `session_end` | Session ended by user or bot (`state_manager.py:178`) |

### 2.5 Derived counts returned

`resolved`, `unresolved`, `escalated`, `bot_down`, `no_verdict`, `in_progress`,
plus `verdict_total` = resolved + unresolved + escalated + bot_down
(the chats that have a clear terminal verdict).

---

## 3. `/metrics/impact` — "Bot Impact" KPIs

Each KPI below is the exact formula in code, with its dashboard target and the
current demo-walkthrough value for reference.

### 3.1 AI Resolution (strict) — target **≥ 80%**

```
resolution_rate = resolved / verdict_total × 100
verdict_total = resolved + unresolved + escalated + bot_down
```

Only chats with a **clear verdict** count in the denominator. `no_verdict` and
`in_progress` chats are shown separately and never dilute the rate.
*(Walkthrough: 12 resolved / 20 verdicts = 60%.)*

### 3.2 Handled Without Agent (self-serve) — target **≥ 80%**

```
self_serve_rate = (conversations − escalated − bot_down) / conversations × 100
```

Every chat the bot handled to completion without a human agent, regardless of
resolved/unresolved outcome.

### 3.3 Could Not Answer (fallback) — target **≤ 15%**

```
fallback_rate = unresolved / conversations × 100
```

One "could not answer" per unresolved conversation (the `unanswered_question` or
negative completion event). *(Walkthrough: 4/25 = 16%.)*

### 3.4 Bot Down / Errors — target **≤ 5%**

```
bot_down_rate = bot_down / conversations × 100
```

### 3.5 CSAT (avg rating) — target **≥ 4.2**

```
csat = mean(rating) over csat events tied to a conversation in this window
```

- Only ratings stored via `POST /metrics/csat` (event `csat`, `rating` 1-5).
- **Orphan ratings are excluded** — a rating whose `conversation_id` is not in
  the window's outcome model is dropped.
- CSAT is also split by outcome: average of ratings on `resolved` chats vs
  `escalated` chats.

### 3.6 Avg Bot Latency — target **< 8 s**

```
latency_seconds = mean(value) of rag_metrics where metric_type = 'response_latency'
```

Recorded once per bot reply. **Successful replies only** — service errors record
no latency.

### 3.7 Off-Hours Handled — target **≥ 60%**

```
off_hours_rate = off_hours_handled / off_hours_total × 100
off_hours_total  = chats whose created_at is outside Mon-Fri 08:00-17:00 Kampala
off_hours_handled= those chats whose outcome is NOT escalated and NOT bot_down
```

Business hours are defined in code as **Mon–Fri 08:00–17:00 Kampala (UTC+3)**
(`main.py:1705-1709`): weekend, or hour < 08:00 or >= 17:00 UTC+3 ⇒ off-hours.

### 3.8 Quote → Payment — target **≥ 20%**

```
quote_to_payment_rate = paid / quotes × 100
quotes = count of quotes created in the window (all statuses)
paid   = count of payment_transactions created in the window with status in
         {SUCCESS, COMPLETED, PAID, payment_initiated}
```

The acid test that payments and quotes live in the **same** database.
*(Walkthrough: 2 quotes / 2 paid = 100%. Before the real-Postgres fix this read
0 because payments went to a separate stub.)*

### 3.9 Effort Hours Saved — labelled **estimate**

```
effort_hours_saved = self_serve × minutes_per_conversation / 60
minutes_per_conversation = env EFFORT_MINUTES_PER_CONVERSATION (default 4)
```

An estimate (`chats handled without an agent × 4 min`), clearly flagged as such
in the API response. Switch to "measured" once real agent timing data exists.

### 3.10 Repeat Users — repeat rate

```
active_users = distinct users with ≥1 conversation in the window
repeat_users = users with ≥2 conversations
repeat_rate  = repeat_users / active_users × 100
```

Identity key: **Zoho contact id when the user is linked, otherwise the internal
user id / phone** (`main.py:1741-1758`). The response reports whether it was
`zoho-contact` or `phone-based`.

### 3.11 Targets (defaults)

| KPI | Target |
|---|---|
| resolution_rate | 80% |
| self_serve_rate | 80% |
| fallback_rate | ≤ 15% |
| bot_down_rate | ≤ 5% |
| csat | 4.2 |
| latency_seconds | < 8 s |
| off_hours_rate | 60% |
| quote_to_payment_rate | 20% |

---

## 4. `/metrics/ai-performance` — AI Performance

### 4.1 Top metrics

| Metric | Formula |
|---|---|
| **AI Accuracy (Rated)** | percentage of CSAT ratings ≥ 4 out of all ratings in window (rated samples) |
| **AI Resolution Rate** | same strict `resolution_rate` as impact |
| **Fallback Rate** | same `fallback_rate` as impact |
| **Agent Pickup Rate** | `distinct conversations with an agent_joined event / conversations × 100` |
| **Avg Response Time** | same mean `response_latency` as impact |

Each carries a `delta` vs the **previous equal-length window**.

### 4.2 Trend data (last 7 days)

```
accuracy per day = mean(retrieval_accuracy) × 100
fallback per day = count(fallbacks metrics) / count(confidence_score metrics) × 100
```

### 4.3 Quality metrics

| Metric | Formula |
|---|---|
| Total Handled | conversations in window (+% change vs previous) |
| AI Resolution Rate / Fallback Rate | as above |
| Avg Length | mean of (max message timestamp − min message timestamp) per conversation |
| Avg Messages | mean message count per conversation |
| User CSAT | `mean csat rating` (or "N/A" if none) |
| Agent Pickup Rate | as above |
| Accuracy Coverage | rated samples / conversations × 100 |
| Rated Samples | count of CSAT ratings in window |

### 4.4 RAG internals (what the raw telemetry means)

- **`retrieval_accuracy`** = `min(len(sources) / 5.0, 1.0)` — sources returned by
  the RAG pipeline, capped at 5.
- **`confidence_score`** = `_estimate_response_confidence`
  (`conversational.py:494-528`): weighted blend of
  `0.7 × (normalised avg retrieval score)` + `0.3 × (retrieval coverage)`, then
  penalised to ≤ 0.25 if the reply looks like a fallback, ≤ 0.35 if no chunks
  were retrieved, and clamped to [0.05, 0.95].
- **`response_latency`** = wall-clock seconds for one bot reply.
- **`fallbacks`** = a 1.0 sentinel when the bot answered with a fallback / no
  sources.

### 4.5 Intent recognition

- Prefers real `intent` conversation events.
- **Fallback:** if no intent events exist, intents are **inferred from user
  messages** by keyword rules (`main.py:1195-1212`) with a fixed confidence of
  0.6 — clearly logged as `INFERRED_FROM_MESSAGE`. Structured form payloads are
  skipped.
- Rows aggregate the top 5 intent categories by volume, with peak window,
  average confidence, regions, and a product breakdown from the intent payload.

---

## 5. `/metrics/system-performance` — System Performance

All three KPIs are computed for the current window and compared (delta) against
the **previous window of the same length**.

| KPI | Formula |
|---|---|
| Escalation Rate | `escalated / conversations × 100` (higher = worse, `invertTrend: true`) |
| AI Resolution Rate | `resolved / verdict_total × 100` |
| Payment Success | `SUCCESS+COMPLETED payments / (SUCCESS+COMPLETED+FAILED+ERROR payments) × 100` |

**Service uptime** (the "Online/Degraded" card) is driven by a heartbeat: the
app writes a `service_heartbeat` `rag_metrics` row every 300 s
(`main.py:133-161`). Online = heartbeat seen in the last hour; Degraded = user
traffic but stale heartbeat; Unknown = no traffic or heartbeat in the last hour.

---

## 6. Caveats & Edge Cases

1. **Strict resolution excludes open chats.** `no_verdict` and `in_progress`
   chats are never in the denominator, so "today's" rate can swing as chats
   finish.
2. **Orphan CSAT ratings are ignored** (not tied to an in-window conversation).
3. **Off-hours uses UTC+3 hardcoded** (Kampala business hours) — safe as long as
   the deployment stays in the Uganda timezone.
4. **Repeat-user identity** depends on Zoho linking; unlinked users are counted
   by user id/phone.
5. **Effort hours are an estimate** (`EFFORT_MINUTES_PER_CONVERSATION`, default
   4 min/chat).
6. **Data provenance:** demo/walkthrough numbers come from the seeded
   conversations and the `demo-*` walkthrough script (`scripts/demo_walkthrough.py`);
   they are real API traffic, not fabricated dashboard figures.
7. **Real vs stub storage** (Section 1) is the single most common cause of
   "why is this number 0?" — confirm the startup log says
   `effective_postgres=True` before trusting persistence-sensitive metrics
   (quote→payment, CSAT, trends).
