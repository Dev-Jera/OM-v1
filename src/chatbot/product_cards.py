"""
Generate product cards with Learn More functionality
"""

from typing import Dict, List


class ProductCardGenerator:
    def __init__(self, product_catalog, rag_system):
        self.catalog = product_catalog
        self.rag = rag_system

    def generate_card(self, product_id: str, include_details: bool = False) -> Dict:
        """Generate product card"""

        # Get product from catalog
        from src.utils.product_matcher import ProductMatcher

        matcher = ProductMatcher()
        product = matcher.get_product_by_id(product_id)

        if not product:
            return None

        card = {
            "product_id": product_id,
            "name": product["name"],
            "category": product["category_name"],
            "subcategory": product["sub_category_name"],
            "tagline": self._generate_tagline(product),
            "icon": self._get_product_icon(product_id),
            "buy_online": product.get("buy_online", False),
            "actions": [
                {"type": "learn_more", "label": "Learn More", "icon": "📖"},
                {"type": "get_quote", "label": "Get a Quote", "icon": "💰", "primary": True},
            ],
        }

        # Add detailed information if requested
        if include_details:
            card["details"] = self.get_product_details(product_id)

        return card

    async def get_product_details(self, product_id: str) -> Dict:
        """Get detailed product information using RAG"""

        # Get product info
        from src.utils.product_matcher import ProductMatcher

        matcher = ProductMatcher()
        product = matcher.get_product_by_id(product_id)

        # Use RAG to get comprehensive information
        details_query = f"Explain {product['name']} insurance product, its benefits, coverage, and eligibility"

        rag_results = await self.rag.retrieve(query=details_query, filters={"products": [product_id]}, top_k=3)

        # Extract information
        what_it_is = await self._extract_description(rag_results, product)
        benefits = await self._extract_benefits(rag_results, product)
        eligibility = await self._extract_eligibility(rag_results, product)
        coverage = await self._extract_coverage(rag_results, product)
        exclusions = await self._extract_exclusions(rag_results, product)

        return {
            "what_it_is": what_it_is,
            "key_benefits": benefits,
            "eligibility": eligibility,
            "coverage": coverage,
            "exclusions": exclusions,
            "pricing": self._get_pricing_info(product),
            "related_products": self._get_related_products(product_id),
        }

    async def _extract_description(self, rag_results, product) -> str:
        """Extract product description"""
        # Use LLM to generate clear description
        # prompt = f"In 2-3 sentences, explain what {product['name']} insurance is and who it's for."

        # This would use the LLM
        # For now, return default
        return f"{product['name']} provides comprehensive coverage for your insurance needs."

    async def _extract_benefits(self, rag_results, product) -> List[str]:
        """Extract key benefits"""
        # Extract from RAG results or use defaults
        default_benefits = {
            "hi_001": [  # Serenicare
                "Inpatient and outpatient care",
                "Maternity coverage included",
                "Dental and optical benefits",
                "Annual health checkup",
                "Emergency evacuation",
            ],
            "li_002": [  # Family Life Protection
                "Lump sum death benefit to beneficiaries",
                "Terminal illness cover",
                "Funeral expense benefit",
                "Flexible premium payment terms",
                "Optional riders available",
            ],
            "mi_001": [  # Motor Private
                "Comprehensive accident damage cover",
                "Third party liability",
                "Theft and fire protection",
                "24/7 roadside assistance",
                "Windscreen replacement",
            ],
        }

        return default_benefits.get(
            product.get("product_id"), ["Comprehensive coverage", "Competitive premiums", "Fast claims processing", "24/7 customer support"]
        )

    async def _extract_eligibility(self, rag_results, product) -> Dict:
        """Extract eligibility criteria"""
        return {
            "age_range": "18-65 years",
            "requirements": ["Ugandan resident or valid work permit", "Medical screening may be required", "Valid identification document"],
            "exclusions": ["Pre-existing conditions (subject to review)", "High-risk occupations (subject to loading)"],
        }

    async def _extract_coverage(self, rag_results, product) -> List[str]:
        """Extract what's covered"""
        return ["Coverage detail 1", "Coverage detail 2", "Coverage detail 3"]

    async def _extract_exclusions(self, rag_results, product) -> List[str]:
        """Extract what's NOT covered"""
        return ["War and civil unrest", "Self-inflicted injuries", "Criminal activities"]

    def _get_pricing_info(self, product) -> Dict:
        """Get pricing information"""
        return {
            "starting_from": "UGX 45,000/month",
            "payment_frequency": ["Monthly", "Quarterly", "Annually"],
            "discounts": ["Family discount available", "Annual payment discount: 10%"],
        }

    def _get_related_products(self, product_id: str) -> List[Dict]:
        """Get related products"""
        from src.utils.product_matcher import ProductMatcher

        matcher = ProductMatcher()

        related = matcher.get_related_products(product_id)

        return [{"product_id": p["product_id"], "name": p["name"], "tagline": self._generate_tagline(p)} for p in related]

    def _generate_tagline(self, product: Dict) -> str:
        """Generate tagline for product"""
        taglines = {
            "hi_001": "Comprehensive health coverage for you and your family",
            "li_002": "Protect your family's future",
            "mi_001": "Drive with confidence, we've got you covered",
            "ti_001": "Travel worry-free with comprehensive protection",
            "pa_001": "Protection against unexpected accidents",
        }

        return taglines.get(product.get("product_id"), f"Quality {product['name']} coverage")

    def _get_product_icon(self, product_id: str) -> str:
        """Get icon for product"""
        icons = {"hi_001": "🏥", "li_002": "👨‍👩‍👧‍👦", "mi_001": "🚗", "ti_001": "✈️", "pa_001": "🩹", "hp_001": "🏠"}

        return icons.get(product_id, "📋")

    # End of product cards
