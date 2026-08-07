"""
Product benefits and configuration loader.

Loads product benefits, exclusions, premium factors from JSON configuration files
instead of hardcoding them in flow logic.

Why:
- Allows non-developers to update benefits via JSON
- Centralizes product configuration
- Makes it easy to version and track changes
- Supports dynamic loading and caching
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ProductBenefitsLoader:
    """Loads and caches product configuration from JSON files."""

    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            # Default search roots:
            # - project_root/product_json
            # - project_root/general_information/product_json
            # __file__ = .../rag/src/integrations/product_benefits.py
            # parents[2] = .../rag (project root)
            project_root = Path(__file__).resolve().parents[2]
            self.config_dir = project_root / "product_json"
            self._fallback_config_dir = project_root / "general_information" / "product_json"
        else:
            self.config_dir = Path(config_dir)
            self._fallback_config_dir = self.config_dir

        self._cache: Dict[str, Dict[str, Any]] = {}

    def get_product_config(self, product_id: str) -> Dict[str, Any]:
        """Load product configuration from JSON file."""
        if product_id in self._cache:
            return self._cache[product_id]

        candidate_files = [
            self.config_dir / f"{product_id}_config.json",
            self.config_dir / f"{product_id}.json",
            self._fallback_config_dir / f"{product_id}_config.json",
            self._fallback_config_dir / f"{product_id}.json",
        ]
        config_file = next((p for p in candidate_files if p.exists()), None)

        if not config_file:
            logger.warning("Product config file not found for '%s'. Checked: %s", product_id, ", ".join(str(p) for p in candidate_files))
            return self._get_default_config(product_id)

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            self._cache[product_id] = config
            logger.info(f"Loaded product config for {product_id}")
            return config
        except Exception as e:
            logger.error(f"Failed to load product config for {product_id}: {e}")
            return self._get_default_config(product_id)

    def get_benefits_for_tier(self, product_id: str, sum_assured: float) -> List[Dict[str, Any]]:
        """Get benefits for a specific coverage tier based on sum assured."""
        config = self.get_product_config(product_id)
        tiers = config.get("coverage_tiers", [])

        # Find the tier matching the sum assured
        for tier in tiers:
            if tier.get("sum_assured") == sum_assured:
                return tier.get("benefits", [])

        # If exact match not found, find closest tier
        if tiers:
            # Sort by sum_assured and find closest
            sorted_tiers = sorted(tiers, key=lambda t: abs(t.get("sum_assured", 0) - sum_assured))
            return sorted_tiers[0].get("benefits", [])

        # Backward-compatible schema used by product JSON files that expose
        # top-level "benefits" as an array of strings.
        top_level_benefits = config.get("benefits", [])
        if isinstance(top_level_benefits, list):
            return top_level_benefits

        return []

    def get_exclusions(self, product_id: str) -> List[str]:
        """Get standard exclusions for a product."""
        config = self.get_product_config(product_id)
        return config.get("standard_exclusions", [])

    def get_important_notes(self, product_id: str) -> List[str]:
        """Get important notes/assumptions for quotes."""
        config = self.get_product_config(product_id)
        return config.get("important_notes", [])

    def get_premium_factors(self, product_id: str, sum_assured: float) -> Dict[str, Any]:
        """Get premium calculation factors for a specific tier."""
        config = self.get_product_config(product_id)
        tiers = config.get("coverage_tiers", [])

        for tier in tiers:
            if tier.get("sum_assured") == sum_assured:
                return tier.get("premium_factors", {})

        # Return first tier's factors as default
        if tiers:
            return tiers[0].get("premium_factors", {})

        return {}

    def format_benefit_description(self, benefit: Dict[str, Any]) -> str:
        """Format a benefit into a human-readable string."""
        if isinstance(benefit, str):
            return benefit

        desc = benefit.get("description", "")
        amount = benefit.get("amount")
        unit = benefit.get("unit", "")
        max_days = benefit.get("max_days")

        if amount:
            formatted_amount = f"UGX {amount:,.0f}"
            if unit:
                if max_days:
                    return f"{desc}: {formatted_amount} {unit} (max {max_days} days)"
                else:
                    return f"{desc}: {formatted_amount} {unit}"
            else:
                return f"{desc}: {formatted_amount}"
        else:
            return desc

    def get_formatted_benefits(self, product_id: str, sum_assured: float) -> List[str]:
        """Get formatted benefit descriptions as strings (backward compatible)."""
        benefits = self.get_benefits_for_tier(product_id, sum_assured)
        return [self.format_benefit_description(b) for b in benefits]

    def get_benefits_as_dict(self, product_id: str, sum_assured: float) -> List[Dict[str, str]]:
        """Get benefits formatted as label/value dictionaries."""
        benefits = self.get_benefits_for_tier(product_id, sum_assured)
        result = []
        for benefit in benefits:
            if isinstance(benefit, str):
                result.append({"label": benefit, "value": "Included"})
                continue

            desc = benefit.get("description", "")
            amount = benefit.get("amount")
            unit = benefit.get("unit", "")
            max_days = benefit.get("max_days")

            # Format the value part
            if amount:
                if amount is None or (isinstance(amount, str) and amount.lower() == "null"):
                    value = unit if unit else "N/A"
                else:
                    formatted_amount = f"UGX {amount:,.0f}"
                    if unit:
                        if max_days:
                            value = f"{formatted_amount} {unit} (max {max_days} days)"
                        else:
                            value = f"{formatted_amount} {unit}"
                    else:
                        value = formatted_amount
            else:
                value = unit if unit else "N/A"

            result.append({
                "label": desc,
                "value": value
            })
        return result

    def clear_cache(self):
        """Clear the configuration cache (useful for reloading)."""
        self._cache.clear()
        logger.info("Product configuration cache cleared")

    def _get_default_config(self, product_id: str) -> Dict[str, Any]:
        """Return minimal default config when file is missing."""
        return {
            "product_id": product_id,
            "name": product_id.replace("_", " ").title(),
            "coverage_tiers": [],
            "standard_exclusions": [],
            "important_notes": []
        }


# Global instance
product_benefits_loader = ProductBenefitsLoader()


__all__ = ["ProductBenefitsLoader", "product_benefits_loader"]
