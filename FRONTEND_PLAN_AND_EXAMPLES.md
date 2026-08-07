# Frontend Plan: Guided Flow & Draft (Personal Accident)

What you need in the frontend and example code for each part.

---

## 1. API layer

**Location:** `chatbot_interface/src/services/api.ts`

**Add:**

- Draft: `getFormDraft(session_id, flow_name)` and `deleteFormDraft(session_id, flow_name)`.
- Types for start-guided and chat response so you can type `response.response` (step payload).
- Optional: `session_id` and `initial_data` in `StartGuidedQuotePayload` (backend already accepts them).

**Example – new types and functions:**

```typescript
// --- Guided flow response types (backend step payloads) ---
export interface GuidedFormField {
  name: string;
  label: string;
  type: string;
  required?: boolean;
  placeholder?: string;
  help?: string;
  minLength?: number;
  maxLength?: number;
  options?: { value: string; label: string }[];
  defaultValue?: string;
}

export type GuidedStepResponse =
  | { type: 'form'; message?: string; fields: GuidedFormField[] }
  | { type: 'premium_summary'; message?: string; monthly_premium: number; annual_premium: number; cover_limit_ugx: number; benefits: string[]; actions: { type: string; label: string }[] }
  | { type: 'yes_no_details'; message: string; question_id: string; options: { id: string; label: string }[]; details_field?: { name: string; label: string; show_when: string } }
  | { type: 'checkbox'; message: string; options: { id: string; label: string }[]; other_field?: { name: string; label: string } }
  | { type: 'file_upload'; message: string; field_name: string; accept?: string }
  | { type: 'final_confirmation'; message?: string }
  | { type: 'message'; message: string };

export interface StartGuidedResponse {
  session_id: string;
  mode: string;
  flow: string;
  step: number;
  response: GuidedStepResponse;
}

export interface ChatMessageResponse {
  response: { response?: GuidedStepResponse; complete?: boolean; [k: string]: unknown };
  session_id: string;
  mode: string;
}

// --- Start guided: allow optional session_id and initial_data ---
export interface StartGuidedQuotePayload {
  user_id: string;
  flow_name: string;
  session_id?: string;
  initial_data?: Record<string, unknown>;
}

// --- Draft API ---
export interface FormDraft {
  session_id: string;
  flow: string;
  step: number;
  collected_data: Record<string, unknown>;
  status?: string;
  updated_at?: string;
}

export async function getFormDraft(session_id: string, flow_name: string) {
  const { data } = await api.get<FormDraft>(`/forms/draft/${session_id}/${flow_name}`);
  return data;
}

export async function deleteFormDraft(session_id: string, flow_name: string) {
  const { data } = await api.delete<{ status: string }>(`/forms/draft/${session_id}/${flow_name}`);
  return data;
}
```

Keep `startGuidedQuote` calling `POST /chat/start-guided` with the payload above; the backend returns `StartGuidedResponse`-shaped data. Use `sendChatMessage` with `form_data` for each step; the backend returns `ChatMessageResponse` where `response.response` is the next step payload.

---

## 2. Pass sessionId into QuoteFormScreen

**Location:** `chatbot_interface/src/screens/ChatScreen.tsx`

**Change:** Pass `sessionId` (and optionally `sessionLoading`) into `QuoteFormScreen` so the PA flow can call start-guided and send steps with the same session.

**Example – where QuoteFormScreen is rendered:**

```tsx
{state.showQuoteForm && (
  <div ref={quoteFormRef} className="flex justify-start animate-fade-in mb-4">
    <div className="w-full">
      <QuoteFormScreen
        key={state.quoteFormKey}
        embedded
        selectedProduct={selectedProduct}
        userId={userId ?? undefined}
        sessionId={sessionId ?? undefined}
        onFormSubmitted={() => dispatch({ type: "QUOTE_FORM_SUBMITTED" })}
      />
    </div>
  </div>
)}
```

**QuoteFormScreen props – add sessionId:**

```tsx
interface QuoteFormScreenProps {
  selectedProduct?: string | null;
  userId?: string | null;
  sessionId?: string | null;
  onFormSubmitted?: () => void;
  embedded?: boolean;
}
```

---

## 3. Personal Accident: backend-driven branch in QuoteFormScreen

**Location:** `chatbot_interface/src/screens/QuoteFormScreen.tsx`

**Idea:** When `selectedProduct === "Personal Accident"` and you have `sessionId`, run the backend-driven flow: start or resume, then on each “Next” call `sendChatMessage` with `form_data` and render whatever `response.response` returns.

**Example – high-level state and flow:**

```tsx
const FLOW_NAME_PA = 'personal_accident';

// Backend-driven state (only for Personal Accident)
const [paSessionId, setPaSessionId] = useState<string | null>(sessionId ?? null);
const [paStepIndex, setPaStepIndex] = useState<number>(0);
const [paStepPayload, setPaStepPayload] = useState<GuidedStepResponse | null>(null);
const [paLoading, setPaLoading] = useState(false);
const [paComplete, setPaComplete] = useState(false);

const isBackendDrivenPA = selectedProduct === 'Personal Accident' && (sessionId || paSessionId);

// Initialize: no draft → start flow; draft → restore and show step
useEffect(() => {
  if (!isBackendDrivenPA || !userId) return;
  const sid = paSessionId || sessionId;
  if (!sid) {
    startFlow();
    return;
  }
  getFormDraft(sid, FLOW_NAME_PA)
    .then((draft) => {
      setPaSessionId(draft.session_id);
      setPaStepIndex(draft.step);
      setFormData(flattenCollectedData(draft.collected_data));
      // You need the schema for this step: either from a local step map or by refetching
      setPaStepPayload(getStepSchemaForIndex(draft.step)); // see “Resume” below
    })
    .catch(() => startFlow());
}, [selectedProduct, userId]);

async function startFlow() {
  setPaLoading(true);
  try {
    const res = await startGuidedQuote({
      user_id: userId!,
      flow_name: FLOW_NAME_PA,
      session_id: sessionId ?? undefined,
      initial_data: { product_id: 'Personal Accident' },
    }) as StartGuidedResponse;
    setPaSessionId(res.session_id);
    setPaStepIndex(res.step ?? 0);
    setPaStepPayload(res.response ?? null);
  } finally {
    setPaLoading(false);
  }
}

async function submitStep(payload: Record<string, unknown>) {
  const sid = paSessionId || sessionId;
  if (!sid || !userId) return;
  setPaLoading(true);
  try {
    const res = await sendChatMessage({
      session_id: sid,
      user_id: userId,
      form_data: payload,
    }) as ChatMessageResponse;
    const next = res.response?.response;
    if (res.response?.complete) {
      setPaComplete(true);
      onFormSubmitted?.();
      return;
    }
    if (next) {
      setPaStepPayload(next);
      setPaStepIndex((i) => i + 1);
    }
  } finally {
    setPaLoading(false);
  }
}
```

**Resume without “get schema” endpoint:** Keep a small map step index → step type (and optionally minimal schema) so you can render the current step after restoring from draft, e.g.:

```ts
const PA_STEP_TYPES: Record<number, GuidedStepResponse['type']> = {
  0: 'form', 1: 'premium_summary', 2: 'form', 3: 'form', 4: 'yes_no_details',
  5: 'yes_no_details', 6: 'checkbox', 7: 'file_upload', 8: 'final_confirmation', 9: 'message',
};
function getStepSchemaForIndex(step: number): GuidedStepResponse | null {
  // Return a minimal schema so you can at least show a “Continue” form with pre-filled data
  const type = PA_STEP_TYPES[step];
  if (type === 'form') return { type: 'form', fields: [], message: 'Continue' };
  // ... other types with minimal defaults, or fetch from a static config
  return null;
}
```

---

## 4. Step renderer: switch on response.type

**Location:** New component e.g. `chatbot_interface/src/components/form-components/GuidedStepRenderer.tsx`, or a block inside `QuoteFormScreen.tsx`.

**Purpose:** Given `GuidedStepResponse`, render the right UI and call `onSubmit` with the payload the backend expects.

**Example – component shell and form / premium_summary:**

```tsx
import React from 'react';
import type { GuidedStepResponse } from '../../services/api';
import CardForm from './CardForm';
import type { CardFieldConfig } from './CardForm';

interface GuidedStepRendererProps {
  step: GuidedStepResponse | null;
  values: Record<string, string>;
  onChange: (name: string, value: string) => void;
  onSubmit: (payload: Record<string, unknown>) => void;
  onBack?: () => void;
  loading?: boolean;
}

export const GuidedStepRenderer: React.FC<GuidedStepRendererProps> = ({
  step, values, onChange, onSubmit, onBack, loading,
}) => {
  if (!step) return null;

  if (step.type === 'form') {
    const fields: CardFieldConfig[] = (step.fields ?? []).map((f) => ({
      name: f.name,
      label: f.label ?? f.name,
      type: f.type as CardFieldConfig['type'],
      required: f.required,
      placeholder: f.placeholder,
      maxLength: f.maxLength,
      minLength: f.minLength,
      options: f.options,
    }));
    return (
      <CardForm
        title={step.message ?? 'Details'}
        fields={fields}
        values={values}
        onChange={onChange}
        onNext={() => onSubmit(values as Record<string, unknown>)}
        onBack={onBack}
        showBack={!!onBack}
        nextDisabled={loading}
        nextButtonLabel="Next"
      />
    );
  }

  if (step.type === 'premium_summary') {
    return (
      <div className="w-full rounded-2xl p-6 border border-gray-200 bg-white">
        <h3 className="text-lg font-semibold text-primary mb-2">{step.message ?? 'Your premium'}</h3>
        <p className="text-2xl font-bold text-gray-900">UGX {step.monthly_premium?.toLocaleString()} / month</p>
        <p className="text-sm text-gray-600">UGX {step.annual_premium?.toLocaleString()} / year</p>
        <ul className="mt-4 list-disc list-inside text-sm text-gray-700">
          {(step.benefits ?? []).map((b, i) => <li key={i}>{b}</li>)}
        </ul>
        <div className="mt-4 flex gap-2">
          {step.actions?.map((a) => (
            <button
              key={a.type}
              type="button"
              disabled={loading}
              onClick={() => onSubmit({ action: a.type === 'edit' ? 'edit' : 'proceed_to_details' })}
              className="px-4 py-2 rounded-lg border border-primary text-primary hover:bg-green-50"
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>
    );
  }

  if (step.type === 'yes_no_details') {
    const [yesNo, setYesNo] = useState<string>('');
    const [detail, setDetail] = useState('');
    const showDetail = step.details_field?.show_when === 'yes' && yesNo === 'yes'
      || step.details_field?.show_when === 'no' && yesNo === 'no';
    return (
      <div className="w-full rounded-2xl p-6 border border-gray-200 bg-white">
        <p className="font-medium text-gray-900 mb-3">{step.message}</p>
        <div className="flex gap-2 mb-3">
          {(step.options ?? []).map((o) => (
            <button
              key={o.id}
              type="button"
              onClick={() => setYesNo(o.id)}
              className={`px-4 py-2 rounded-lg border ${yesNo === o.id ? 'bg-primary text-white border-primary' : 'border-gray-300'}`}
            >
              {o.label}
            </button>
          ))}
        </div>
        {showDetail && step.details_field && (
          <input
            type="text"
            placeholder={step.details_field.label}
            value={detail}
            onChange={(e) => setDetail(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg"
          />
        )}
        <button
          type="button"
          disabled={loading || !yesNo}
          onClick={() => onSubmit({
            [step.question_id === 'previous_pa_policy' ? 'had_previous_pa_policy' : 'free_from_disability']: yesNo,
            [step.details_field?.name ?? 'details']: detail,
          })}
          className="mt-4 px-4 py-2 bg-primary text-white rounded-lg"
        >
          Next
        </button>
      </div>
    );
  }

  if (step.type === 'checkbox') {
    const [selected, setSelected] = useState<string[]>([]);
    const [other, setOther] = useState('');
    const toggle = (id: string) => setSelected((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]);
    return (
      <div className="w-full rounded-2xl p-6 border border-gray-200 bg-white">
        <p className="font-medium text-gray-900 mb-3">{step.message}</p>
        <div className="flex flex-col gap-2">
          {(step.options ?? []).map((o) => (
            <label key={o.id} className="flex items-center gap-2">
              <input type="checkbox" checked={selected.includes(o.id)} onChange={() => toggle(o.id)} />
              <span>{o.label}</span>
            </label>
          ))}
        </div>
        {step.other_field && (
          <input
            type="text"
            placeholder={step.other_field.label}
            value={other}
            onChange={(e) => setOther(e.target.value)}
            className="mt-3 w-full px-3 py-2 border rounded-lg"
          />
        )}
        <button
          type="button"
          disabled={loading}
          onClick={() => onSubmit({ risky_activities: selected, risky_activity_other: other })}
          className="mt-4 px-4 py-2 bg-primary text-white rounded-lg"
        >
          Next
        </button>
      </div>
    );
  }

  if (step.type === 'file_upload') {
    const [fileRef, setFileRef] = useState('');
    return (
      <div className="w-full rounded-2xl p-6 border border-gray-200 bg-white">
        <p className="font-medium text-gray-900 mb-3">{step.message}</p>
        <input
          type="file"
          accept={step.accept ?? 'application/pdf'}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) setFileRef(f.name); // TODO: upload f and set real file_ref from API
          }}
        />
        <button
          type="button"
          disabled={loading || !fileRef}
          onClick={() => onSubmit({ national_id_file_ref: fileRef })}
          className="mt-4 px-4 py-2 bg-primary text-white rounded-lg"
        >
          Next
        </button>
      </div>
    );
  }

  if (step.type === 'final_confirmation') {
    return (
      <div className="w-full rounded-2xl p-6 border border-gray-200 bg-white">
        <p className="font-medium text-gray-900 mb-3">{step.message ?? 'Review and confirm'}</p>
        <div className="flex gap-2 mt-4">
          {onBack && <button type="button" onClick={onBack} className="px-4 py-2 border rounded-lg">Edit</button>}
          <button type="button" disabled={loading} onClick={() => onSubmit({ action: 'confirm' })} className="px-4 py-2 bg-primary text-white rounded-lg">
            Confirm & Proceed to Payment
          </button>
        </div>
      </div>
    );
  }

  return null;
};
```

Use this inside `QuoteFormScreen` when `isBackendDrivenPA` and `paStepPayload` is set; pass `formData` as `values`, `handleChange`, and `submitStep` as `onSubmit`.

---

## 5. Wire QuoteFormScreen: two modes

**Location:** `chatbot_interface/src/screens/QuoteFormScreen.tsx`

**Logic:**

- If `selectedProduct === 'Personal Accident'` and `sessionId` (or `paSessionId`) exists → backend-driven: render `GuidedStepRenderer` with `paStepPayload`, `formData`, and submit via `sendChatMessage` + update `paStepPayload` / `paComplete`.
- Else → keep current behaviour: `steps = getProductFormSteps(selectedProduct)`, render `CardForm` for `steps[step]`, and on last step call `startGuidedQuote` once with full form (for Travel, Motor, Serenicare).

**Example – render branch:**

```tsx
if (selectedProduct === 'Personal Accident' && (paSessionId || sessionId) && (paStepPayload || paLoading)) {
  return (
    <div className={embedded ? 'w-full' : 'flex flex-col h-full bg-white'}>
      <div className={embedded ? 'px-3 sm:px-4 py-3' : 'p-4 mt-12'}>
        {paLoading && !paStepPayload ? (
          <p>Loading...</p>
        ) : paComplete ? (
          <p>Thank you! Your quote has been submitted.</p>
        ) : (
          <GuidedStepRenderer
            step={paStepPayload}
            values={formData}
            onChange={handleChange}
            onSubmit={submitStep}
            onBack={paStepIndex > 0 ? () => setPaStepIndex((i) => i - 1) : undefined}
            loading={paLoading}
          />
        )}
      </div>
    </div>
  );
}

// Existing static-step flow for other products
const steps = getProductFormSteps(selectedProduct) ?? [];
return (
  // ... existing CardForm with steps[step]
);
```

---

## 6. Draft: clear on cancel

**Where:** Same `QuoteFormScreen` or a “Start over” / “Cancel” button in the PA flow.

**Example:** When user cancels or starts over, call:

```ts
await deleteFormDraft(paSessionId || sessionId!, FLOW_NAME_PA);
setPaSessionId(null);
setPaStepPayload(null);
setPaStepIndex(0);
setFormData({});
```

---

## 7. File upload (optional until backend has upload)

Backend expects `national_id_file_ref`. If there is no upload endpoint yet:

- Either show a file input and send a **placeholder** (e.g. `client-file-${Date.now()}`) so the rest of the flow runs.
- Or add a small backend endpoint e.g. `POST /api/v1/forms/upload` that accepts a file and returns `{ file_ref: "..." }`, then use that in the `file_upload` step.

---

## Checklist

| # | What you need | Where | Example |
|---|----------------|--------|--------|
| 1 | Draft API + guided response types | `api.ts` | Section 1 |
| 2 | Pass `sessionId` to QuoteFormScreen | `ChatScreen.tsx`, `QuoteFormScreen` props | Section 2 |
| 3 | PA backend-driven state & start/submit/resume | `QuoteFormScreen.tsx` | Section 3 |
| 4 | Render step by `response.type` | New `GuidedStepRenderer.tsx` (or inline) | Section 4 |
| 5 | Two modes in QuoteFormScreen (PA vs rest) | `QuoteFormScreen.tsx` | Section 5 |
| 6 | Clear draft on cancel | QuoteFormScreen or button handler | Section 6 |
| 7 | File ref (placeholder or upload API) | GuidedStepRenderer file_upload block | Section 7 |

After this, Personal Accident will be backend-driven with step-by-step submission and draft resume; other products stay on the current static form and single `startGuidedQuote` call.
