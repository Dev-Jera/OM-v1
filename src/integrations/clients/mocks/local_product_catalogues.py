"""
Local Product Catalogue Client (Mock/Local).

Purpose:
- Acts as a development-time product catalogue source when Zoho access is not available.
- Loads product data from local files (or an internal index) to support product discovery.

Usage:
- Wired in src/api/main.py during development
- Called by ProductDiscoveryFlow / ProductCardGenerator through the CatalogueClient interface

Why this matters:
- Prevents hardcoding product IDs/categories in chatbot logic
- Allows product data to be reloaded easily (data refactor instead of system rebuild)

Swap:
Replace with clients/real_http/zoho_product_catalogues.py once Zoho credentials and
catalogue endpoints are confirmed.
"""
