"""
Zoho Product Catalogue HTTP Client.

Purpose:
- Fetches product catalogue data from Zoho (or Old Mutual catalogue API)
- Normalizes product entries into our ProductCatalogue contract shape

Usage:
- Wired in src/api/main.py when Zoho credentials and endpoints are confirmed
- Called by ProductDiscoveryFlow / ProductCardGenerator via the CatalogueClient interface

Implementation notes:
- Ensure product IDs/categories are treated as data (not hardcoded in flows)
- Support reloading / refreshing product data
- Consider caching results to reduce API calls if required

Important:
- This client should be the ONLY place that talks to Zoho for product catalogue data.
"""
