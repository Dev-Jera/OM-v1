# Personal Accident Guided Flow - Updated Implementation

## Overview

The Personal Accident flow has been restructured to prioritize a **quick quote-first experience** where users get an instant premium calculation, review benefits, and then proceed to detailed underwriting steps with pre-filled data.

---

## New Flow Architecture

### Step 0: Quick Quote
**Purpose:** Instant premium calculation with minimal required fields

**Frontend-style field names (from your schema):**
- `firstName` (text, 2-50 chars)
- `lastName` (text, 2-50 chars)
- `middleName` (text, optional)
- `mobile` (tel, normalized format)
- `email` (email, valid format)
- `dob` (date, age 18-65)
- `policyStartDate` (date, must be after today)
- `coverLimitAmountUgx` (enum: 5M, 10M, 20M)

**Backend actions:**
1. Validate all fields with age checks (18-65) and date constraints
2. Calculate premium using age-based modifiers:
   - Base rate: 0.15% of sum assured per year
   - <25 years: +25% loading
   - >60 years: +20% loading
3. Create Quote in Postgres (status="draft")
4. Store quick quote data in `collected_data["quick_quote"]` for autofill

**Response:** Form with 8 fields and validation rules

---

### Step 1: Premium Summary & Review
**Purpose:** Display calculated premium, benefits for selected cover level, download option

**Display:**
- Monthly & Annual Premium (calculated from quick quote)
- Coverage Level Benefits (from `PA_BENEFITS_BY_LEVEL` config):
  - UGX 5M: Basic benefits
  - UGX 10M: Extended benefits + funeral expenses
  - UGX 20M: Premium benefits + trauma counseling
- PDF Download Option
- Actions: Edit Quote (→ back to Step 0) or Proceed

**Backend actions:**
- If user clicks "Edit", return to Step 0
- If user clicks "Proceed", advance to Step 2 (next_of_kin)

---

### Step 2: Next of Kin
**Purpose:** Collect beneficiary details

**Auto-filled fields (from quick quote):**
- `nok_first_name` → pre-filled with user's first name (editable)
- `nok_last_name` → pre-filled with user's last name (editable)

**Other fields:**
- `nok_middle_name` (optional)
- `nok_phone_number` (validated Uganda format)
- `nok_relationship` (text)
- `nok_address` (text)
- `nok_id_number` (optional, validated NIN)

---

### Step 3: Previous PA Policy
**Purpose:** Underwriting question

**Type:** Yes/No with conditional details field
- If "Yes": show field for previous insurer name
- If "No": skip to next step

---

### Step 4: Physical Disability
**Purpose:** Underwriting question

**Type:** Yes/No with conditional details field
- If "No": show field for disability details
- If "Yes": proceed to next step

---

### Step 5: Risky Activities
**Purpose:** Underwriting question about occupation/activities

**Type:** Checkbox (multi-select)
- Manufacture of wire works
- Mining / Quarrying
- Handling explosives
- Construction work at heights
- Underwater diving
- Motor/speed racing
- Other (with text field for description)

---

### Step 6: Upload National ID
**Purpose:** Document verification

**Type:** File upload (PDF)
- Max size: 5 MB
- Accepted format: PDF only
- Field name: `national_id_file_ref`

---

### Step 7: Final Confirmation
**Purpose:** Review all collected data before payment

**Display:** Summary of:
- Applicant details (from quick quote)
- Next of kin (from step 2)
- Coverage details (cover limit, policy start, premiums)

**Actions:**
- Edit Details (back to previous steps)
- Confirm & Proceed to Payment (→ Step 8)

---

### Step 8: Choose Plan & Pay
**Purpose:** Final submission and payment handoff

**Backend actions:**
1. If quote not yet created (fallback), create it now
2. Return quote ID and payment flow reference
3. Clear Redis draft automatically (on flow completion)

**Response:** Proceed to payment with quote confirmation

---

## Benefits Configuration

Benefits are stored in `PA_BENEFITS_BY_LEVEL` dict (config_file style):

```python
PA_BENEFITS_BY_LEVEL = {
    "5000000": [
        "Accidental death benefit: UGX 5,000,000",
        "Permanent disability: Up to UGX 5,000,000",
        "Temporary disability: UGX 2,500 per day (max 365 days)",
        "Medical expenses: UGX 1,000,000",
        "Hospitalization: UGX 10,000 per day (max 30 days)",
    ],
    "10000000": [...],
    "20000000": [...],
}
```

**Add/update** by modifying `src/chatbot/flows/personal_accident.py`

---

## Data Flow & Redis Caching

### Session State (Redis)
- **TTL:** 30 minutes (conversational mode)
- **Stored:** `mode`, `current_flow`, `current_step`, `collected_data`

### Form Draft (Redis)
- **TTL:** 7 days
- **Stored:** Snapshot after each step success
- **Contains:** `session_id`, `flow`, `step`, `collected_data`, `status`, `updated_at`
- **Use case:** Resume incomplete forms

### Quote Record (Postgres)
- **Created:** During Step 0 (quick quote)
- **Status:** "draft" initially
- **Updated:** On final submission (Step 8)
- **Contains:** Premium, coverage level, underwriting data, pricing breakdown

### Conversation History (Postgres)
- **Stored:** User and assistant messages after each step
- **Contains:** Form inputs, step responses, timestamps

---

## Frontend Integration

### 1. Start a Personal Accident Flow
```typescript
const response = await fetch(`${API_BASE_URL}/api/chat/start-guided`, {
  method: 'POST',
  headers: { 'X-API-Key': process.env.VITE_API_KEY },
  body: JSON.stringify({
    flow_name: 'personal_accident',
    user_id: phoneNumber,
    session_id: existingSessionId || undefined,
  }),
});
const { session_id, response: startResponse } = await response.json();
// startResponse contains step 0 form schema
```

### 2. Submit Each Step
```typescript
const stepResponse = await fetch(`${API_BASE_URL}/api/chat`, {
  method: 'POST',
  headers: { 'X-API-Key': process.env.VITE_API_KEY },
  body: JSON.stringify({
    session_id: sessionId,
    user_id: phoneNumber,
    message: '',
    form_data: {
      // Step-specific fields
      firstName: 'John',
      lastName: 'Doe',
      // ... other fields
    },
  }),
});
// Backend automatically:
// 1. Saves draft to Redis
// 2. Advances current_step in session
// 3. Returns next step form schema
```

### 3. Resume a Form (from Draft)
```typescript
const draft = await fetch(
  `${API_BASE_URL}/api/forms/draft/${sessionId}/personal_accident`,
  { headers: { 'X-API-Key': process.env.VITE_API_KEY } }
);
if (draft.ok) {
  const draftData = await draft.json();
  // draftData.step, draftData.collected_data, draftData.updated_at
  // Pre-populate form with collected_data
}
```

### 4. Clear Draft (if user cancels)
```typescript
await fetch(
  `${API_BASE_URL}/api/forms/draft/${sessionId}/personal_accident`,
  {
    method: 'DELETE',
    headers: { 'X-API-Key': process.env.VITE_API_KEY },
  }
);
```

---

## Data Auto-fill Patterns

1. **Quick Quote → Next of Kin:**
   - `firstName` (from step 0) → `nok_first_name` (default value)
   - `lastName` (from step 0) → `nok_last_name` (default value)
   - Fields are **editable**, not read-only

2. **Persistent Draft:**
   - Each step saves `collected_data` to Redis with TTL=7 days
   - On resume, load draft and pre-populate all fields

3. **Comparison Step (Step 7):**
   - Display all collected data from all previous steps
   - Allow user to navigate back and edit any section

---

## Premium Calculation Formula

```
Base Annual = sum_assured * 0.0015

Age Modifier:
- If age < 25: +25% loading → annual = base * 1.25
- If age > 60: +20% loading → annual = base * 1.20
- Else: no modifier

Monthly = Annual / 12
```

Example (Age 35, UGX 10M cover):
```
Base Annual = 10,000,000 * 0.0015 = 15,000
Age Modifier = None (35 is between 25-60)
Monthly = 15,000 / 12 = 1,250 UGX
Annual = 15,000 UGX
```

---

## API Endpoints Summary

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/session` | Create new session |
| POST | `/api/chat/start-guided` | Start Personal Accident flow |
| POST | `/api/chat` | Submit form step (auto-saves draft) |
| GET | `/api/session/{id}` | Get session state |
| GET | `/api/forms/draft/{session}/{flow}` | Fetch cached draft |
| DELETE | `/api/forms/draft/{session}/{flow}` | Clear draft |
| GET | `/api/sessions/{id}/history` | Get conversation history |

---

## Migration Notes

### Old Flow Structure (Deprecated)
- Step 0: personal_details (all fields)
- Step 1: next_of_kin
- Step 5: coverage_selection
- Step 7: premium_and_download
- Step 8: choose_plan_and_pay

### New Flow Structure
- Step 0: quick_quote (minimal fields)
- Step 1: premium_summary
- Step 2: next_of_kin (with autofill)
- Step 3-6: underwriting & upload
- Step 7: final_confirmation
- Step 8: choose_plan_and_pay

**Breaking Change:** Field names in Step 0 changed from snake_case backend format to camelCase frontend format.

---

## Files Modified

- `src/chatbot/flows/personal_accident.py` - Complete flow restructure
- `src/api/main.py` - Updated `_build_flow_schema()` for new steps
- `src/database/redis.py` & `redis_real.py` - Form draft cache (already implemented)
- `src/chatbot/state_manager.py` - Draft helpers (already implemented)
- `src/chatbot/modes/guided.py` - Draft persistence on step advance (already implemented)

---

## Testing Checklist

- [ ] Quick quote validation (age, dates, phone format)
- [ ] Premium calculation with age modifiers
- [ ] Quote creation in Postgres
- [ ] Draft saving to Redis after each step
- [ ] Autofill from quick quote to next_of_kin
- [ ] Resume draft functionality
- [ ] Clear draft on completion/cancellation
- [ ] Final confirmation summary display
- [ ] Payment flow handoff with quote ID
- [ ] Conversation history logging

