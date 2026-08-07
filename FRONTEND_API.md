# Frontend API – Application flow and endpoints

How the **frontend** integrates with the backend for the full user journey: **free conversation**, **guided product discovery** (business units → subcategories or products → product cards), and **Get quote** (form-like flow).

---

## Application flow (high level)

1. **Free conversation** – User chats in natural language. Backend uses RAG and returns answers.
2. **Guided – discovery** – User selects a **business unit (category)** → sees **subcategories** (if any) or **products** → if subcategories exist, picks one → sees **products** → picks a **product**.
3. **Product cards** – After selecting a product, show two cards:
   - **General card**: what the product is, benefits, eligibility, what it covers. Use product endpoints (overview, benefits, general; optional FAQ).
   - **Get quote card**: starts the form-based flow. Use `POST /api/v1/chat/start-guided` with `product_id` in `initial_data`, then `POST /api/v1/chat/message` with `form_data` for each step.
4. **Get quote flow** – Form-like steps (e.g. Personal Accident). Same session; submit each step via `form_data`.

---

## Base URL

- **Local:** `http://localhost:8000`
- **Railway:** `https://<your-app>.up.railway.app`

All frontend-facing endpoints are under **`/api/v1`**.

**Flow summary:** Free chat = `POST /api/v1/chat/message` with `message`. Discovery = `GET /api/v1/products/categories` then `GET /api/v1/products/{category}` (subcategories or products), then `GET /api/v1/products/{category}/{subcategory}` if needed, then `GET /api/v1/products/by-id/{product_id}` for the General card. Get quote = `POST /api/v1/chat/start-guided` with `initial_data: { "product_id": "..." }`, then `POST /api/v1/chat/message` with `form_data` for each step.

---

## 1. Session lifecycle

### Create session (when user opens the app)

```http
POST /api/v1/session
Content-Type: application/json

{
  "user_id": "user-123"
}
```

**Response:**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user-123"
}
```

Store `session_id` and send it with every subsequent chat request.

### Get current session state

Use this to know the current step and flow (e.g. to show the right form or progress).

```http
GET /api/v1/session/{session_id}
```

**Response (Personal Accident in progress):**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "mode": "guided",
  "current_flow": "personal_accident",
  "current_step": 0,
  "step_name": "personal_details",
  "steps_total": 9,
  "collected_keys": []
}
```

- **mode:** `"conversational"` | `"guided"`
- **current_flow:** e.g. `"personal_accident"` or `null`
- **current_step:** 0-based step index
- **step_name:** e.g. `"personal_details"`, `"next_of_kin"`
- **steps_total:** only set for Personal Accident (9 steps)
- **collected_keys:** keys already collected (e.g. `["personal_details", "next_of_kin"]`)

---

## 2. Chat: form-like inputs (Personal Accident)

The frontend sends either:

- **Free text** in `message`, or  
- **Structured form payload** in `form_data` when the user submits a step form.

### Send message or form payload

```http
POST /api/v1/chat/message
Content-Type: application/json

{
  "user_id": "user-123",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "",
  "form_data": { ... }
}
```

- **With form submission (guided step):** set `form_data` to the step’s field values; `message` can be `""` or omitted.
- **With text only:** set `message` and omit `form_data` (or send `null`).

**Example – Personal details (step 0):**

```json
{
  "user_id": "user-123",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "",
  "form_data": {
    "surname": "Doe",
    "first_name": "Jane",
    "middle_name": "M.",
    "date_of_birth": "1990-05-15",
    "email": "jane@example.com",
    "mobile_number": "0772123456",
    "national_id_number": "CM123456789AB",
    "nationality": "Ugandan",
    "tax_identification_number": "",
    "occupation": "Teacher",
    "gender": "Female",
    "country_of_residence": "Uganda",
    "physical_address": "Kampala"
  }
}
```

**Example – Next of kin (step 1):**

```json
{
  "user_id": "user-123",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "form_data": {
    "nok_first_name": "John",
    "nok_last_name": "Doe",
    "nok_phone_number": "0772987654",
    "nok_relationship": "Spouse",
    "nok_address": "Kampala"
  }
}
```

**Example – Yes/No step (previous PA policy):**

```json
{
  "user_id": "user-123",
  "session_id": "...",
  "form_data": {
    "had_previous_pa_policy": "no"
  }
}
```

Or with details when “Yes”:

```json
{
  "form_data": {
    "had_previous_pa_policy": "yes",
    "previous_insurer_name": "ABC Insurance"
  }
}
```

**Example – Risky activities (checkbox):**

```json
{
  "form_data": {
    "risky_activities": ["manufacture_wire_works", "mining"],
    "risky_activity_other": ""
  }
}
```

**Example – Coverage plan:**

```json
{
  "form_data": {
    "coverage_plan": "standard"
  }
}
```

**Example – National ID upload (step 6):**

```json
{
  "form_data": {
    "national_id_file_ref": "uploaded-file-id-or-url"
  }
}
```

**Example – “View all plans” vs “Proceed to pay” (step 8):**

```json
{
  "form_data": {
    "action": "view all plans"
  }
}
```

or

```json
{
  "form_data": {
    "action": "proceed to pay"
  }
}
```

### Chat response shape

The API returns the same structure for `POST /api/v1/chat/message`:

```json
{
  "response": {
    "mode": "guided",
    "flow": "personal_accident",
    "step": 1,
    "response": {
      "type": "form",
      "message": "👥 Next of kin details",
      "fields": [
        { "name": "nok_first_name", "label": "First Name", "type": "text", "required": true },
        ...
      ]
    },
    "complete": false
  },
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "mode": "guided",
  "timestamp": "2026-01-25T12:00:00"
}
```

For guided steps, `response.response` describes the next form:

- **type:** `"form"` | `"yes_no_details"` | `"checkbox"` | `"options"` | `"file_upload"` | `"premium_summary"` | `"proceed_to_payment"`
- **message:** Short instruction.
- **fields:** For `type: "form"` – name, label, type, required, options (for select).
- **options:** For checkbox/options steps.

When the flow moves to payment, you get `"complete": true` and `"next_flow": "payment"` in the payload; the backend switches to the payment flow and the next message continues in that flow.

---

## 3. Start Personal Accident flow

If the user chooses “Apply for Personal Accident” from the UI, start the flow explicitly:

```http
POST /api/v1/chat/start-guided
Content-Type: application/json

{
  "flow_name": "personal_accident",
  "user_id": "user-123",
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

If `session_id` is omitted, the backend creates a new session and returns it:

```json
{
  "session_id": "new-uuid",
  "mode": "guided",
  "flow": "personal_accident",
  "step": 0,
  "response": { "type": "form", "message": "...", "fields": [...] }
}
```

Use the returned `session_id` for all later requests.

---

## 4. Form schema (build UI ahead of time)

To build a stepper or validate forms on the client, you can load the Personal Accident schema:

```http
GET /api/v1/flows/personal_accident/schema
```

**Response:**

```json
{
  "flow_id": "personal_accident",
  "steps": [
    {
      "index": 0,
      "name": "personal_details",
      "form": {
        "type": "form",
        "fields": [
          { "name": "surname", "label": "Surname", "type": "text", "required": true },
          ...
        ]
      }
    },
    ...
  ]
}
```

Step names: `personal_details`, `next_of_kin`, `previous_pa_policy`, `physical_disability`, `risky_activities`, `coverage_selection`, `upload_national_id`, `premium_and_download`, `choose_plan_and_pay`.

You can either drive the UI entirely from each step’s `response.response` in the chat, or use this schema for initial layout and validation.

---

## 5. Database and sessions (Railway)

- **Conversations and users** are stored in **PostgreSQL** when `USE_POSTGRES_CONVERSATIONS=true` and `DATABASE_URL` are set.
- **Session state** (current flow, step, `collected_data`) is stored in **Redis** when `REDIS_URL` is set; otherwise it uses an in-memory store (lost on restart).

For production on Railway:

1. Use a **Neon** (or other) Postgres and set `DATABASE_URL`.
2. Set **`USE_POSTGRES_CONVERSATIONS=true`** so chats and users persist.
3. Add a **Redis** service on Railway and set **`REDIS_URL`** so session state persists across restarts and instances.

Run once per environment:

- `python scripts/init_pgvector.py` – enable pgvector (for RAG).
- `python scripts/init_database.py` – create users, conversations, messages, quotes.

See **RAILWAY_DEPLOYMENT.md** and **SESSIONS_AND_STORAGE.md** for details.

---

## 6. Endpoints overview

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Service info / health |
| GET | `/health` | Health + DB/Redis status |
| POST | `/api/v1/session` | Create session |
| GET | `/api/v1/session/{session_id}` | Get session state |
| POST | `/api/v1/chat/message` | Send message or `form_data` |
| POST | `/api/v1/chat/start-guided` | Start flow (e.g. `personal_accident`) |
| GET | `/api/v1/flows/personal_accident/schema` | Form schema for PA |
| GET | `/api/v1/sessions/{session_id}/history` | Conversation history |
| GET | `/api/v1/products/list` | List products (optional) |

Use **`/api/v1/chat/message`** and **`/api/v1/chat/start-guided`** for the frontend; support **`form_data`** for each Personal Accident step as above.
: "..."
}
```

**Step types** (in `response.response.type`): `form`, `yes_no_details`, `checkbox`, `options`, `file_upload`, `premium_summary`, `proceed_to_payment`, etc. Use `GET /api/v1/session/{session_id}` to reflect progress (e.g. step index, `step_name`).

When the flow finishes, `response.complete` is `true` and you may see `next_flow` (e.g. payment). Use the same session and continue with the next flow or show a confirmation screen.

---

## 5. Form schema (build UI ahead of time)

To build steppers or validate forms on the client, you can load the Personal Accident schema:

```http
GET /api/v1/flows/personal_accident/schema
```

**Response:**

```json
{
  "flow_id": "personal_accident",
  "steps": [
    {
      "index": 0,
      "name": "personal_details",
      "form": {
        "type": "form",
        "fields": [
          { "name": "surname", "label": "Surname", "type": "text", "required": true },
          ...
        ]
      }
    },
    ...
  ]
}
```

Step names: `personal_details`, `next_of_kin`, `previous_pa_policy`, `physical_disability`, `risky_activities`, `coverage_selection`, `upload_national_id`, `premium_and_download`, `choose_plan_and_pay`.

You can drive the UI from the step responses in the chat payload or use this schema for layout and validation.

---

## 6. Database and sessions (Railway)

- **Conversations and users** are stored in **PostgreSQL** when `USE_POSTGRES_CONVERSATIONS=true` and `DATABASE_URL` are set.
- **Session state** (mode, current flow, step, `collected_data`) is stored in **Redis** when `REDIS_URL` is set; otherwise an in-memory store is used (state lost on restart).

For production:

1. Use **Neon** (or other) Postgres and set `DATABASE_URL`.
2. Set **`USE_POSTGRES_CONVERSATIONS=true`** so chats and users persist.
3. Add **Redis** and set **`REDIS_URL`** so session state survives restarts and multiple instances.

See **RAILWAY_DEPLOYMENT.md** and **SESSIONS_AND_STORAGE.md** for details.

---

## 7. Endpoints overview

| Method | Path | Purpose |
|--------|------|--------|
| GET | `/` | Service info / health |
| GET | `/health` | Health + DB/Redis status |
| POST | `/api/v1/session` | Create session |
| GET | `/api/v1/session/{session_id}` | Get session state (mode, flow, step) |
| POST | `/api/v1/chat/message` | Send message (free chat) or `form_data` (guided step) |
| POST | `/api/v1/chat/start-guided` | Start guided flow (e.g. get-quote); pass `product_id` in `initial_data` |
| GET | `/api/v1/flows/personal_accident/schema` | Form schema for Personal Accident |
| GET | `/api/v1/products/categories` | List business units (categories) |
| GET | `/api/v1/products/{category}` | Subcategories or products for that category |
| GET | `/api/v1/products/{category}/{subcategory}` | Products in category + subcategory |
| GET | `/api/v1/products/by-id/{product_id}` | Product info for **General** card (overview, benefits, general; optional `?include_details=true` for FAQ) |
| GET | `/api/v1/products/by-id/{product_id}?include_details=true` | Same as by-id with FAQ included |
| GET | `/api/v1/sessions/{session_id}/history` | Conversation history |
| DELETE | `/api/v1/sessions/{session_id}` | End session |
| POST | `/api/v1/quotes/generate` | Generate quote from underwriting data |
| GET | `/api/v1/quotes/{quote_id}` | Get quote by ID |

---

## 8. Flow summary for the frontend

- **Free chat:** `POST /api/v1/chat/message` with `message` and no `form_data`.
- **Discovery:**  
  `GET /api/v1/products/categories` → user picks category →  
  `GET /api/v1/products/{category}` → show subcategories or products →  
  if subcategories: `GET /api/v1/products/{category}/{subcategory}` → show products →  
  user picks product.
- **General card:** `GET /api/v1/products/by-id/{product_id}` (and optionally `?include_details=true`).
- **Get quote card:**  
  `POST /api/v1/chat/start-guided` with `flow_name` and `initial_data: { "product_id": "..." }` →  
  then `POST /api/v1/chat/message` with `form_data` for each step until the flow is complete.

Use **`/api/v1/chat/message`** and **`/api/v1/chat/start-guided`** for chat and guided flows; use the product endpoints above for discovery and the General card.
