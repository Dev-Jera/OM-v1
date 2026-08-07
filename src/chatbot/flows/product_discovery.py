"""
Product discovery flow - Help users find the right product
"""

from typing import Dict, List


class ProductDiscoveryFlow:
    def __init__(self, product_catalog):
        self.catalog = product_catalog
        self.steps = ["ask_category", "ask_coverage_type", "ask_budget", "show_recommendations"]

    async def start(self, user_id: str, initial_data: Dict) -> Dict:
        """Start the flow"""
        return await self.process_step("", 0, {}, user_id)

    async def process_step(self, user_input: str, current_step: int, collected_data: Dict, user_id: str) -> Dict:
        """Process current step"""

        if current_step == 0:  # ask_category
            return {
                "response": {
                    "type": "options",
                    "message": "👋 Welcome! What would you like to insure?",
                    "options": [
                        {"id": "personal", "label": "👤 Myself / Family", "icon": "👨‍👩‍👧‍👦"},
                        {"id": "business", "label": "💼 My Business", "icon": "🏢"},
                        {"id": "property", "label": "🏠 Property / Assets", "icon": "🏘️"},
                        {"id": "vehicle", "label": "🚗 Vehicle", "icon": "🚙"},
                    ],
                },
                "next_step": 1,
                "collected_data": collected_data,
            }

        elif current_step == 1:  # ask_coverage_type
            collected_data["category"] = user_input

            coverage_options = self._get_coverage_options(user_input)

            return {
                "response": {"type": "options", "message": "What type of coverage do you need?", "options": coverage_options},
                "next_step": 2,
                "collected_data": collected_data,
            }

        elif current_step == 2:  # ask_budget
            collected_data["coverage_type"] = user_input

            return {
                "response": {
                    "type": "options",
                    "message": "What's your monthly budget?",
                    "options": [
                        {"id": "low", "label": "Under UGX 100,000/month"},
                        {"id": "medium", "label": "UGX 100,000 - 500,000/month"},
                        {"id": "high", "label": "UGX 500,000+/month"},
                        {"id": "flexible", "label": "Flexible - show me options"},
                    ],
                },
                "next_step": 3,
                "collected_data": collected_data,
            }

        elif current_step == 3:  # show_recommendations
            collected_data["budget"] = user_input

            # Get recommended products
            products = self._recommend_products(collected_data)

            return {
                "response": {"type": "product_cards", "message": "🎯 Based on your needs, here are my recommendations:", "products": products},
                "complete": True,
                "collected_data": collected_data,
                "data": {"recommended_products": [p["product_id"] for p in products]},
            }

        return {"error": "Invalid step"}

    def _get_coverage_options(self, category: str) -> List[Dict]:
        """Get coverage options based on category"""
        options_map = {
            "personal": [
                {"id": "life", "label": "💙 Life Insurance"},
                {"id": "health", "label": "🏥 Health Insurance"},
                {"id": "accident", "label": "🩹 Accident Cover"},
                {"id": "travel", "label": "✈️ Travel Insurance"},
            ],
            "business": [
                {"id": "group_life", "label": "👥 Group Life Cover"},
                {"id": "group_medical", "label": "🏥 Group Medical"},
                {"id": "liability", "label": "⚖️ Liability Insurance"},
                {"id": "property", "label": "🏢 Business Property"},
            ],
            "property": [
                {"id": "home", "label": "🏠 Home Insurance"},
                {"id": "fire", "label": "🔥 Fire & Perils"},
                {"id": "burglary", "label": "🔒 Burglary Cover"},
            ],
            "vehicle": [
                {"id": "comprehensive", "label": "🚗 Comprehensive"},
                {"id": "third_party", "label": "👥 Third Party"},
                {"id": "comesa", "label": "🌍 COMESA Yellow Card"},
            ],
        }

        return options_map.get(category, [])

    def _recommend_products(self, criteria: Dict) -> List[Dict]:
        """Recommend products based on criteria"""
        # This would use the product catalog and matching logic
        # For now, return mock recommendations

        category = criteria.get("category")
        coverage_type = criteria.get("coverage_type")

        # Simple recommendation logic
        if category == "personal" and coverage_type == "health":
            return [
                {
                    "product_id": "hi_001",
                    "name": "Serenicare",
                    "tagline": "Comprehensive health coverage for you and your family",
                    "min_premium": "UGX 45,000/month",
                    "key_benefits": ["Inpatient & outpatient care", "Maternity coverage", "Dental & optical"],
                }
            ]

        # Default recommendations
        return [{"product_id": "li_002", "name": "Family Life Protection", "tagline": "Protect your family's future", "min_premium": "UGX 50,000/month"}]
