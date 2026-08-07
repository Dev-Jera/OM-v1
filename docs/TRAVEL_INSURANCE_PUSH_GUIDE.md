# Step-by-Step Guide: Push Travel Insurance Flow to Main Repo

This guide walks you through testing the Travel Insurance flow and pushing it to the main repository.

---

## Step 1: Run Unit Tests

Verify the flow logic works correctly:

```bash
# From the project root (rag folder)
python scripts/run_travel_insurance_tests.py
```

**Expected output:**
```
Running Travel Insurance flow tests...

[PASS] test_start_returns_product_selection
[PASS] test_product_selection_step
[PASS] test_about_you_stores_data
[PASS] test_premium_calculation
[PASS] test_full_flow_to_payment

5 passed, 0 failed
```

If using pytest:
```bash
pytest tests/test_travel_insurance_flow.py -v
```

---

## Step 2: Run API Tests (Optional but Recommended)

Start the API in one terminal:

```bash
cd "d:\APPRENTICESHIP - REFACTORY\Project phase\Old Mutual Uganda Chatbot\rag"
uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

In another terminal, run the API test script:

```bash
python scripts/test_travel_insurance_api.py
```

**Expected:** Session creation, flow start, product selection, about_you form, session state, and schema fetch all succeed.

---

## Step 3: Check Git Status

See what files were modified or added:

```bash
git status
```

**Expected files:**
- `src/chatbot/flows/travel_insurance.py` (modified/rewritten)
- `src/chatbot/modes/guided.py` (modified - added TravelInsuranceFlow)
- `src/chatbot/flows/router.py` (modified - added travel insurance triggers)
- `src/api/main.py` (modified - added schema endpoint and session handling)
- `tests/test_travel_insurance_flow.py` (new)
- `scripts/test_travel_insurance_api.py` (new)
- `scripts/run_travel_insurance_tests.py` (new)
- `docs/TRAVEL_INSURANCE_PUSH_GUIDE.md` (new)

---

## Step 4: Review Changes

```bash
git diff
```

Or review each file individually:
```bash
git diff src/chatbot/flows/travel_insurance.py
git diff src/chatbot/modes/guided.py
# etc.
```

---

## Step 5: Stage Files

Stage all travel insurance related files:

```bash
git add src/chatbot/flows/travel_insurance.py
git add src/chatbot/modes/guided.py
git add src/chatbot/flows/router.py
git add src/api/main.py
git add tests/test_travel_insurance_flow.py
git add scripts/test_travel_insurance_api.py
git add scripts/run_travel_insurance_tests.py
git add docs/TRAVEL_INSURANCE_PUSH_GUIDE.md
```

Or stage everything:
```bash
git add .
```

---

## Step 6: Commit with a Descriptive Message

```bash
git commit -m "feat: Add Travel Insurance customer buying journey flow

- Implement TravelInsuranceFlow with 10 steps: product selection, about you,
  travel party & trip, data consent, traveller details, emergency contact,
  bank details (optional), passport upload, premium summary, payment
- Add 7 product options: Worldwide Essential/Elite, Schengen Essential/Elite,
  Student Cover, Africa & Asia, Inbound Karibu
- Integrate flow into GuidedMode and ChatRouter
- Add travel insurance triggers: 'travel insurance', 'travel sure', 'travel cover'
- Add GET /api/flows/travel_insurance/schema endpoint
- Add session state support for travel_insurance flow
- Add unit tests and API test script"
```

---

## Step 7: Ensure You're on the Right Branch

If you work with feature branches:

```bash
# Create and switch to a feature branch (optional)
git checkout -b feature/travel-insurance-flow

# Or ensure you're on main
git checkout main
```

---

## Step 8: Pull Latest from Remote (If Working with a Team)

```bash
git pull origin main
```

Resolve any merge conflicts if they appear.

---

## Step 9: Push to Remote

```bash
# If on main:
git push origin main

# If on a feature branch:
git push origin feature/travel-insurance-flow
```

---

## Step 10: Create a Pull Request (If Using Feature Branch)

If you pushed to a feature branch:

1. Go to your repository on GitHub/GitLab/Bitbucket
2. Create a Pull Request from `feature/travel-insurance-flow` to `main`
3. Add a description summarizing the changes
4. Request review if required
5. Merge after approval

---

## Quick Reference: Commands in Order

```bash
# 1. Test
python scripts/run_travel_insurance_tests.py

# 2. Check status
git status

# 3. Stage
git add src/chatbot/flows/travel_insurance.py src/chatbot/modes/guided.py src/chatbot/flows/router.py src/api/main.py tests/test_travel_insurance_flow.py scripts/test_travel_insurance_api.py scripts/run_travel_insurance_tests.py docs/TRAVEL_INSURANCE_PUSH_GUIDE.md

# 4. Commit
git commit -m "feat: Add Travel Insurance customer buying journey flow"

# 5. Pull latest (if needed)
git pull origin main

# 6. Push
git push origin main
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Tests fail | Run `python scripts/run_travel_insurance_tests.py` and fix any errors shown |
| Import errors | Ensure you're in the project root and `src` is on PYTHONPATH |
| Git push rejected | Run `git pull origin main --rebase` then push again |
| Merge conflicts | Resolve manually in the conflicting files, then `git add` and `git commit` |
