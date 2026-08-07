#!/usr/bin/env python3
"""
Discover exact URLs for business products on Old Mutual Uganda website.
"""
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import time
import re

BASE_URL = "https://www.oldmutual.co.ug"

# Product names to search for
PRODUCTS_TO_FIND = [
    "Group Life Cover",
    "Umbrella Scheme Pension",
    "Combined Solutions",
    "Group Personal Accident cover",
    "Standard Group Medical Cover",
    "Enhanced Group Life",
    "Fidelity Guarantee",
    "Livestock Insurance",
    "Bankers Blanket Bond",
    "Public Liability",
    "Crop Insurance",
    "Professional Liability",
    "Directors & Officers Liability",
    "Carriers Liability",
    "Marine Cargo Insurance",
    "Marine Open Cover",
    "All Risks Cover",
    "Goods in Transit",
    "Money Insurance",
]

# Start with known entry points
SEED_URLS = [
    "/business/",
    "/business/insurance/",
]

discovered_urls = {}
visited_urls = set()

def normalize_path(url):
    """Extract and normalize the path from a URL."""
    parsed = urlparse(url)
    path = parsed.path
    if parsed.query:
        path += "?" + parsed.query
    return path

def fetch_page(url, timeout=15):
    """Fetch a page and return BeautifulSoup object."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            return BeautifulSoup(response.content, 'html.parser')
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return None

def extract_links(soup, current_url):
    """Extract all links from a page."""
    links = []
    if not soup:
        return links
    
    for link in soup.find_all('a', href=True):
        href = link.get('href')
        if href:
            # Skip anchors and empty links
            if href.startswith('#') or href == '' or href == '/':
                continue
            # Convert relative URLs to absolute
            if href.startswith('/'):
                full_url = urljoin(BASE_URL, href)
            elif href.startswith('http'):
                full_url = href
            else:
                full_url = urljoin(current_url, href)
            
            # Only follow links on the same domain
            if urlparse(full_url).netloc == urlparse(BASE_URL).netloc:
                links.append(full_url)
    
    return links

def search_products_on_page(soup, url):
    """Search for product names on a page and store if found."""
    if not soup:
        return
    
    page_text = soup.get_text().lower()
    path = normalize_path(url)
    
    for product in PRODUCTS_TO_FIND:
        product_lower = product.lower()
        if product_lower in page_text:
            if product not in discovered_urls:
                discovered_urls[product] = []
            if path not in discovered_urls[product]:
                discovered_urls[product].append(path)
                print(f"✓ Found '{product}' at {path}")

def crawl(max_pages=50):
    """Crawl the website to discover product URLs."""
    to_visit = [urljoin(BASE_URL, seed) for seed in SEED_URLS]
    pages_crawled = 0
    
    while to_visit and pages_crawled < max_pages:
        url = to_visit.pop(0)
        
        if url in visited_urls:
            continue
        
        visited_urls.add(url)
        pages_crawled += 1
        
        print(f"\n[{pages_crawled}/{max_pages}] Crawling: {url}")
        
        soup = fetch_page(url)
        if soup:
            search_products_on_page(soup, url)
            links = extract_links(soup, url)
            
            # Add new links to visit (prioritize /business/ paths)
            for link in links:
                if link not in visited_urls and "/business/" in link:
                    to_visit.insert(0, link)
                elif link not in visited_urls:
                    to_visit.append(link)
        
        time.sleep(1)  # Rate limiting
    
    print(f"\n\nCrawl complete. Visited {pages_crawled} pages.")

def main():
    print("Starting URL discovery for Old Mutual business products...\n")
    crawl(max_pages=100)
    
    print("\n" + "="*80)
    print("DISCOVERED PRODUCT URLs")
    print("="*80)
    
    if discovered_urls:
        for product in PRODUCTS_TO_FIND:
            if product in discovered_urls:
                urls = discovered_urls[product]
                print(f"\n{product}:")
                for url in urls:
                    print(f"  → {url}")
            else:
                print(f"\n{product}: NOT FOUND")
    else:
        print("\nNo products found. Trying alternative approach...\n")
        # Try fetching business main page and looking for links
        print("Fetching /business/ main page and extracting all links...")
        soup = fetch_page(urljoin(BASE_URL, "/business/"))
        if soup:
            links = extract_links(soup, urljoin(BASE_URL, "/business/"))
            print("\nAll business-related links found:")
            for link in sorted(set(links)):
                path = normalize_path(link)
                if "/business/" in path:
                    print(f"  {path}")

if __name__ == "__main__":
    main()
