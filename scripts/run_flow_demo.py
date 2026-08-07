#!/usr/bin/env python3
"""
Run a full underwriting → quotation flow and print each stage to the terminal.
Shows forms, collected data, underwriting assessment, and final quote.

Usage (from repo root):
  python scripts/run_flow_demo.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.database.postgres import PostgresDB
from src.chatbot.flows.underwriting import UnderwritingFlow
from src.chatbot.flows.quotation import QuotationFlow


def setup_logging():
    """Log to terminal at INFO so every stage is visible."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def print_stage(title: str, data: dict | list | str):
    """Print a stage header and data to the terminal."""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)
    if isinstance(data, (dict, list)):
        print(json.dumps(data, indent=2, default=str))
    else:
        print(data)
    print()


async def main():
    setup_logging()
    db = PostgresDB()
    user = db.get_or_create_user(phone_number="demo-user")
    user_id = str(user.id)

    underwriting = UnderwritingFlow(db)
    quotation = QuotationFlow(product_catalog={}, db=db)

    collected = {"user_id": user_id}

    # --- Underwriting: step 0 personal_info ---
    result = await underwriting.process_step("", 0, collected, user_id)
    print_stage("UNDERWRITING STEP 0: Personal info form", result.get("response", {}))
    collected = result.get("collected_data", collected)

    # Simulate user submitting personal info
    personal = {
        "full_name": "Jane Demo",
        "date_of_birth": "1990-05-15",
        "gender": "Female",
        "occupation": "Teacher",
        "email": "jane@example.com",
    }
    collected.update(personal)
    print_stage("USER SUBMITTED: Personal info", personal)

    # --- Underwriting: step 1 coverage_details ---
    result = await underwriting.process_step(json.dumps(personal), 1, collected, user_id)
    print_stage("UNDERWRITING STEP 1: Coverage details form", result.get("response", {}))
    collected = result.get("collected_data", collected)

    coverage = {"sum_assured": 25_000_000, "policy_term": 20, "beneficiaries": "John Demo"}
    collected.update(coverage)
    print_stage("USER SUBMITTED: Coverage details", coverage)

    # --- Underwriting: step 2 health_questions ---
    result = await underwriting.process_step(json.dumps(coverage), 2, collected, user_id)
    print_stage("UNDERWRITING STEP 2: Health questions", result.get("response", {}))
    collected = result.get("collected_data", collected)

    health = {"chronic_conditions": {"answer": "no"}, "medications": {"answer": "no"}, "hospitalizations": {"answer": "no"}, "family_history": {"answer": "no"}}
    collected["health_info"] = health
    print_stage("USER SUBMITTED: Health info", health)

    # --- Underwriting: step 3 lifestyle_questions ---
    result = await underwriting.process_step(json.dumps(health), 3, collected, user_id)
    print_stage("UNDERWRITING STEP 3: Lifestyle form", result.get("response", {}))
    collected = result.get("collected_data", collected)

    lifestyle = {"smoker": "No", "alcohol": "Occasional", "exercise": "3-4 times/week", "hazardous_activities": {"answer": "no"}}
    collected["lifestyle_info"] = lifestyle
    print_stage("USER SUBMITTED: Lifestyle info", lifestyle)

    # --- Underwriting: step 4 review_and_submit ---
    result = await underwriting.process_step(json.dumps(lifestyle), 4, collected, user_id)
    print_stage("UNDERWRITING STEP 4: Review & submit", result.get("response", {}))
    collected = result.get("collected_data", collected)
    print_stage("Underwriting result (requires_review, risk_score)", result.get("data", {}))

    # --- Quotation: start (uses underwriting data) ---
    quote_result = await quotation.start(user_id, collected)
    print_stage("QUOTATION: Quote presentation", quote_result.get("response", {}).get("quote", {}))

    # --- Quotation: process_step 0 presents quote ---
    result = await quotation.process_step("", 0, collected, user_id)
    quote_details = result.get("response", {}).get("quote_details", {})
    print_stage("QUOTATION STEP 0: Quote details (monthly, annual, breakdown)", quote_details)
    collected["monthly_premium"] = quote_details.get("monthly_premium")
    collected["sum_assured"] = quote_details.get("sum_assured")

    # --- Quotation: user accepts ---
    result = await quotation.process_step("accept", 1, collected, user_id)
    print_stage("QUOTATION: User accepted quote", result.get("response", {}))
    print_stage("Final result (complete, next_flow, quote_id)", result.get("data", {}))

    print("\n" + "=" * 60)
    print("  Demo complete. Check logs above for each stage.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
