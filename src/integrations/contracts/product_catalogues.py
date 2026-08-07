
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from .interfaces import Product

"""
Product catalogue contracts.

Defines the structure of product information used by the chatbot, e.g.:
- product_id, name, category
- description, benefits, eligibility, links
- metadata needed for product discovery and card generation

These contracts must be used by both:
- clients/mocks/local_product_catalogues.py (local data source for development)
- clients/real_http/zoho_product_catalogues.py (Zoho / OM catalogue source when available)

Why:
- Prevents hardcoding product IDs/categories in flow logic
- Makes it easy to reload/update product data without rebuilding the system
- Supports fast re-indexing/re-embedding of product content in the vector database
"""
"""
Product catalogue contract — schemas and helpers for insurance product listings.
"""


# ---------------------------------------------------------------------------
# Extended product models
# ---------------------------------------------------------------------------

@dataclass
class ProductFilter:
    """Optional filters when querying the product catalogue."""
    min_cover_amount: Optional[float] = None
    max_premium_amount: Optional[float] = None
    max_duration_months: Optional[int] = None
    customer_age: Optional[int] = None          # filters by eligibility age range
    currency: Optional[str] = None


@dataclass
class ProductQuote:
    """A premium quote for a specific product and customer."""
    quote_id: str
    product_id: str
    customer_id: str
    premium_amount: float
    cover_amount: float
    currency: str
    duration_months: int
    valid_until: str                             # ISO datetime string
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def filter_products(products: List[Product], f: ProductFilter) -> List[Product]:
    """Apply a ProductFilter to a list of products and return matching ones."""
    result = products

    if f.min_cover_amount is not None:
        result = [p for p in result if p.cover_amount >= f.min_cover_amount]
    if f.max_premium_amount is not None:
        result = [p for p in result if p.premium_amount <= f.max_premium_amount]
    if f.max_duration_months is not None:
        result = [p for p in result if p.duration_months <= f.max_duration_months]
    if f.customer_age is not None:
        result = [p for p in result if p.eligible_age_min <= f.customer_age <= p.eligible_age_max]
    if f.currency is not None:
        result = [p for p in result if p.currency == f.currency]

    return result
