# Zoho KPI Dashboard + Escalation Handoff — Plan

**Goal:** the client sees bot performance inside Zoho CRM (one place), escalations land in Zoho
and agents are notified natively, and no manual work is needed after setup.

Agreed 2026-08-18. Daily cadence confirmed. Dashboard built together, click by click.

---

## Phase 1 — Daily KPI push into CRM (all code, no UI)

1. **Custom module `Mia_Bot_Metrics`** — created via CRM API
   (`scripts/zoho_create_modules.py`). Fallback: guided UI creation with the exact field list.
   Fields:
   - `Metric_Date` (date — unique key for idempotent upserts)
   - `Conversations`, `Resolved`, `Escalated`, `Could_Not_Answer`, `Bot_Down` (integers)
   - `Resolution_Rate`, `Self_Serve_Rate`, `Fallback_Rate`, `Bot_Down_Rate`,
     `Off_Hours_Rate`, `Quote_to_Payment_Rate`, `Repeat_User_Rate` (percent)
   - `CSAT` (avg rating), `Avg_Latency_Seconds`, `Effort_Hours_Saved` (decimals)
2. **OAuth scope bump** — widen consent to include the new modules + module-creation scope;
   re-mint the refresh token with `scripts/zoho_oauth_setup.py --env .env --write` (2 min).
3. **Code:**
   - `src/metrics_kpis.py` — the exact KPI math extracted from `/metrics/impact`
     (`src/api/main.py`) into `compute_impact_metrics(db, days, now=None)`. The endpoint
     calls it; the push calls it. They can never drift apart.
   - `src/integrations/zoho/crm_writer.py` — thin CRM write client (create / upsert).
   - `src/integrations/zoho/push_metrics.py` — computes the day's KPIs and **upserts** one
     record keyed by `Metric_Date` (`PUT /crm/v2/{module}/upsert` with
     `duplicate_check_fields`). Re-running updates, never duplicates.
   - `scripts/run_zoho_metrics_push.py` — CLI (`--env`, `--date` for backfill, `--days`).
4. **Scheduler:** GitHub Actions cron, daily 18:00 Kampala (15:00 UTC). ZOHO creds as repo secrets.
5. **Tests:** fixture-based — KPI computation, upsert/idempotency, missing-creds errors.

## Phase 2 — The dashboard (guided, one-time, ~10 min)

- Built together in the CRM UI: dashboard -> widgets fed by `Mia_Bot_Metrics`
  (KPI numbers, resolution trend line, outcomes pie).
- Trends improve automatically — every daily push adds a row of history.
- This is the only manual step in the whole plan.

## Phase 3 — Escalation handoff to Zoho

Destination: **CRM module** (confirmed default; Zoho Desk is the swap-in alternative —
`.env` already carries a `ZOHO_DESK_ORG_ID` placeholder if Desk is preferred later).

1. **Custom module `Mia_Escalations`** (API-created): `Escalated_At` (datetime),
   `Conversation_ID`, `Session_ID`, `Reason`, `Customer_Name`, `Phone`,
   `Zoho_Contact_Id`, `Transcript` (long text), `Status` (picklist: New / In Progress / Closed).
2. **Hook:** all escalation paths converge in `EscalationService.escalate_to_human`
   (`src/integrations/policy/escalation_service.py`). The `/escalate` endpoint is routed
   through the service too so no path is missed.
3. **Payload:** reason + customer info (name / phone / `zoho_contact_id` — already stored
   on users) + chat transcript + conversation id.
4. **Fire-and-forget:** the push runs in a background thread with a short timeout and full
   try/except — a Zoho failure logs and moves on; it can never break the chat or the
   escalation itself. Gated by `ZOHO_ESCALATION_PUSH_ENABLED` (default off).
5. **Agent notification:** one CRM workflow rule (guided clicks, one time):
   "when an escalation record is created -> notify the assigned agent".
6. **Tests:** push failure doesn't break escalation; transcript assembly; contact linking;
   gate off by default.

## Phase 4 — Wire-up, deploy, verify

1. Render env vars: enable flags after testing.
2. Full suite green -> commit -> push.
3. **Live test:**
   - Run push script -> record appears in `Mia_Bot_Metrics`
   - Run twice -> still one record (idempotent)
   - Trigger a real escalation ("I want an agent") -> record with transcript in `Mia_Escalations`
   - Kill the flag -> chat behaves exactly as today

## Out of scope (later, if ever wanted)

- Agent replies flowing back into the chat UI (two-way sync via Desk webhooks)
- Zoho Analytics upgrade for fancier charts
- Zoho SalesIQ live-chat replacement

## Open items

1. Escalation destination final confirmation: CRM module (default) vs Desk.
2. Cron time — 18:00 Kampala default.
3. ZOHO creds added as GitHub repo secrets for the daily cron.

## Env vars introduced

| Var | Default | Purpose |
| --- | --- | --- |
| `ZOHO_METRICS_MODULE` | `Mia_Bot_Metrics` | CRM module receiving daily KPIs |
| `ZOHO_ESCALATION_MODULE` | `Mia_Escalations` | CRM module receiving escalations |
| `ZOHO_ESCALATION_PUSH_ENABLED` | `false` | Master switch for escalation push |
