"""
Scraper for Old Mutual Uganda website
"""

from typing import List, Dict, Optional, Set, Any
from pathlib import Path
from urllib.parse import urljoin
from datetime import datetime
import re
import logging
import time
import json
import html
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

from ..utils.config_loader import load_scraping_config, get_website_config
from ..utils.rate_limiter import RateLimiter
from ..utils.content_validator import ContentValidator

logger = logging.getLogger(__name__)


class OldMutualWebsiteScraper:
    """Scraper for Old Mutual Uganda product pages and FAQs"""

    def __init__(self, base_url: Optional[str] = None, output_dir: Optional[str] = None, config_path: Optional[Path] = None, **kwargs):
        """
        Initialize website scraper

        Args:
            base_url: Base URL (overrides config if provided)
            output_dir: Output directory (overrides config if provided)
            config_path: Path to scraping config file
            **kwargs: Additional arguments for scraper configuration
        """
        # Load configuration
        try:
            config = load_scraping_config(config_path)
            website_config = get_website_config(config)
            general_config = config.general

            # Use config values unless overridden
            base_url = base_url or website_config.base_url
            output_dir = output_dir or website_config.output_dir
            delay = kwargs.get("delay", website_config.delay)
            max_retries = kwargs.get("max_retries", website_config.max_retries)
            user_agent = kwargs.get("user_agent", general_config.user_agent)
            priority_urls = website_config.priority_urls
            article_urls = website_config.article_urls
            info_page_urls = website_config.info_page_urls
            timeout = kwargs.get("timeout", 30)

            # Setup rate limiting if enabled
            rate_limiter = None
            if general_config.rate_limit.enabled:
                rate_limiter = RateLimiter(general_config.rate_limit.requests_per_minute)
                logger.info(f"Rate limiting enabled: {general_config.rate_limit.requests_per_minute} " f"requests per minute")

        except Exception as e:
            logger.warning(f"Failed to load config: {e}. Using defaults.")
            base_url = base_url or "https://www.oldmutual.co.ug"
            output_dir = output_dir or "data/raw/website"
            priority_urls = []
            article_urls = []
            info_page_urls = {}
            delay = kwargs.get("delay", 2.0)
            max_retries = kwargs.get("max_retries", 3)
            timeout = kwargs.get("timeout", 30)
            user_agent = kwargs.get(
                "user_agent", ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) " "AppleWebKit/537.36 (KHTML, like Gecko) " "Chrome/120.0.0.0 Safari/537.36")
            )
            rate_limiter = None

        # Initialize base scraper attributes
        self.delay = delay
        self.max_retries = max_retries
        self.timeout = timeout
        self.rate_limiter = rate_limiter
        self.user_agent = user_agent
        self.session = self._create_session()

        # Initialize website scraper attributes
        self.base_url = base_url
        self.output_dir = Path(output_dir)
        self.priority_urls = priority_urls
        self.article_urls = article_urls
        self.info_page_urls = info_page_urls
        self.visited_urls: Set[str] = set()
        self.seen_content_hashes: Set[str] = set()

        # Initialize content validator
        self.validator = ContentValidator(min_content_length=100, max_content_length=1000000, expected_language="en", check_language=True)
        self.enable_js_fallback = kwargs.get("enable_js_fallback", True)
        self.playwright_timeout_ms = int(kwargs.get("playwright_timeout_ms", 45000))

        # Statistics tracking
        self.stats = {"total_scraped": 0, "valid_content": 0, "invalid_content": 0, "duplicates_skipped": 0, "errors": 0}

    def scrape(self) -> Dict:
        """Main scraping orchestration"""
        logger.info("Starting Old Mutual website scraping...")
        logger.info(f"Base URL: {self.base_url}")
        logger.info(f"Priority URLs: {len(self.priority_urls)}")

        result = {"products": {}, "articles": [], "faqs": [], "info_pages": []}

        # Scrape product pages (organized by category from config) - returns nested structure
        product_data = self.scrape_products()
        result["products"] = product_data

        # Scrape article pages (returns nested structure)
        article_data = self.scrape_articles()
        result["articles"] = article_data

        # Scrape FAQ pages
        faq_data = self.scrape_faqs()
        result["faqs"] = faq_data

        # Scrape about/info pages (returns nested structure)
        info_data = self.scrape_info_pages()
        result["info_pages"] = info_data

        # Save all data
        if result["products"] or result["articles"] or result["faqs"] or result["info_pages"]:
            self.save_raw_data(result, f"website_scrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", self.output_dir)

        # Log statistics
        total_products = sum(len(products) for subcats in result["products"].values() for products in subcats.values())
        total_articles = sum(len(articles) for articles in result["articles"].values()) if result["articles"] else 0
        total_info_pages = sum(len(pages) for pages in result["info_pages"].values()) if result["info_pages"] else 0

        logger.info("=" * 60)
        logger.info("Scraping Statistics:")
        logger.info(f"  Total pages scraped: {self.stats['total_scraped']}")
        logger.info(f"  Valid content: {self.stats['valid_content']}")
        logger.info(f"  Invalid content: {self.stats['invalid_content']}")
        logger.info(f"  Duplicates skipped: {self.stats['duplicates_skipped']}")
        logger.info(f"  Errors: {self.stats['errors']}")
        logger.info(f"  Products: {total_products}")
        logger.info(f"  Articles: {total_articles}")
        logger.info(f"  FAQs: {len(result['faqs'])}")
        logger.info(f"  Info pages: {total_info_pages}")
        logger.info("=" * 60)

        return result

    def scrape_products(self) -> Dict[str, Dict[str, List[Dict]]]:
        """
        Scrape all product pages from config, organized by category and subcategory

        Returns nested structure:
        {
            "category": {
                "subcategory": [product1, product2, ...]
            }
        }
        """
        logger.info("Scraping product pages from config...")

        if not self.priority_urls:
            logger.warning("No priority URLs configured. Skipping product scraping.")
            return {}

        # Organize products by category
        products_by_category = self._organize_products_by_category()

        # Structure to hold nested products
        nested_products = {}

        # Scrape products organized by category
        for category, subcategories in products_by_category.items():
            logger.info(f"Scraping {category} products...")

            if category not in nested_products:
                nested_products[category] = {}

            for subcategory, product_urls in subcategories.items():
                # Use a clean key for subcategory (use "general" if empty string)
                subcategory_key = subcategory if subcategory else "general"

                logger.info(f"  Scraping {category}/{subcategory_key} products ({len(product_urls)} products)")

                if subcategory_key not in nested_products[category]:
                    nested_products[category][subcategory_key] = []

                for url_path in product_urls:
                    # Handle both absolute and relative URLs
                    if url_path.startswith("http"):
                        url = url_path
                    else:
                        url = urljoin(self.base_url, url_path)

                    if url in self.visited_urls:
                        logger.debug(f"Skipping already visited product: {url}")
                        continue

                    self.visited_urls.add(url)

                    # Determine category name for product (use subcategory if available, else category)
                    category_name = subcategory if subcategory else category

                    # Scrape individual product page
                    product_data = self._scrape_product_page(url, category_name)

                    if product_data:
                        # Add category and subcategory metadata (override the category set by _scrape_product_page)
                        product_data["category"] = category
                        product_data["subcategory"] = subcategory if subcategory else None
                        nested_products[category][subcategory_key].append(product_data)

        total_products = sum(len(products) for subcats in nested_products.values() for products in subcats.values())
        logger.info(f"Scraped {total_products} product pages")
        return nested_products

    def _organize_products_by_category(self) -> Dict[str, Dict[str, List[str]]]:
        """
        Organize priority URLs by category and subcategory

        Returns:
            Dict structure: {
                'personal': {
                    'save-and-invest': [urls...],
                    'insure': [urls...]
                },
                'business': {
                    '': [urls...]  # no subcategory
                },
                'investment': {
                    '': [urls...]
                }
            }
        """
        organized = {"personal": {"save-and-invest": [], "insure": []}, "business": {"general": []}, "investment": {"general": []}}

        for url_path in self.priority_urls:
            # Parse URL path to extract category and subcategory
            parts = url_path.strip("/").split("/")

            if len(parts) >= 1:
                category = parts[0]  # personal, business, or investment

                if category == "personal" and len(parts) >= 2:
                    subcategory = parts[1]  # save-and-invest or insure
                    if subcategory in organized["personal"]:
                        organized["personal"][subcategory].append(url_path)
                    else:
                        # Unknown subcategory, add to general personal
                        if "general" not in organized["personal"]:
                            organized["personal"]["general"] = []
                        organized["personal"]["general"].append(url_path)
                elif category in organized:
                    # Business or investment (no subcategories in current structure)
                    organized[category]["general"].append(url_path)
                else:
                    # Unknown category, add to a general category
                    if "other" not in organized:
                        organized["other"] = {"general": []}
                    organized["other"]["general"].append(url_path)

        # Remove empty subcategories
        for category in list(organized.keys()):
            organized[category] = {k: v for k, v in organized[category].items() if v}
            if not organized[category]:
                del organized[category]

        return organized

    def _extract_category_info(self, soup, url: str, category: str) -> Optional[Dict]:
        """Extract information from category overview page"""
        try:
            # Extract title
            title = soup.find("h1")
            title_text = title.get_text(strip=True) if title else category.split("/")[-1]

            # Extract main content
            content = self._extract_main_content(soup)

            # Extract features/benefits lists
            features = self._extract_lists(soup, ["feature", "benefit", "coverage"])

            return {
                "type": "category",
                "category": category.split("/")[-1],
                "url": url,
                "title": title_text,
                "content": content,
                "features": features,
                "scraped_at": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error extracting category info from {url}: {str(e)}")
            self.stats["errors"] += 1
            return None

    def _find_product_links(self, soup, base_url: str) -> List[str]:
        """Find all product page links on a category page"""
        links = []

        # Common patterns for product links
        link_patterns = [
            r"/products?/.*",
            r"/insurance/.*",
            r"/plans?/.*",
        ]

        for link in soup.find_all("a", href=True):
            href = link["href"]
            absolute_url = urljoin(base_url, href)

            # Check if link matches product patterns
            for pattern in link_patterns:
                if re.search(pattern, absolute_url):
                    links.append(absolute_url)
                    break

        return list(set(links))  # Remove duplicates

    def _scrape_product_page(self, url: str, category: str) -> Optional[Dict]:
        """Scrape individual product page with validation"""
        logger.debug(f"Scraping product: {url}")

        html = self.fetch_page(url)
        if not html:
            self.stats["errors"] += 1
            return None

        soup = self.parse_html(html)
        if not soup:
            self.stats["errors"] += 1
            return None

        try:
            # Extract product name from URL path (last part of URL)
            # e.g., "sure-deal-savings-plan" -> "Sure Deal Savings Plan"
            url_path = url.rstrip("/").split("/")[-1]
            product_name = url_path.replace("-", " ").title()

            # Extract H1 for display name
            h1_title = soup.find("h1")
            display_name = product_name
            if h1_title:
                h1_text = h1_title.get_text(strip=True)
                if h1_text and not h1_text.endswith("?") and len(h1_text) < 100:
                    display_name = h1_text

            # Extract all text content for validation
            content_text = self._extract_main_content(soup)

            # Validate content before proceeding
            validation = self.validator.validate_content(content_text, url)
            if not validation["valid"]:
                logger.warning(f"Product page {url} failed validation: {validation['errors']}")
                self.stats["invalid_content"] += 1
                return None

            # Check for duplicate content
            is_duplicate, content_hash = self.validator.is_duplicate_content(content_text, self.seen_content_hashes)
            if is_duplicate:
                logger.debug(f"Duplicate content detected for product: {url}")
                self.stats["duplicates_skipped"] += 1
                return None

            # Extract structured content as heading-content pairs (similar to FAQs)
            content = self._extract_structured_content(soup)

            # Extract FAQs from product page HTML structure (only from om-faq-card)
            faqs = self._extract_faqs(soup)

            self.stats["total_scraped"] += 1
            self.stats["valid_content"] += 1

            # Build product data
            product_data = {
                "type": "product",
                "product_id": url_path,  # URL slug as product ID (e.g., "sure-deal-savings-plan")
                "product_name": product_name,  # Formatted from URL (e.g., "Sure Deal Savings Plan")
                "display_name": display_name,  # H1 or product name
                "category": category if "/" not in category else category.split("/")[0],  # Main category
                "subcategory": category.split("/")[-1] if "/" in category else None,  # Will be overridden by caller
                "url": url,
                "content": content,  # List of heading-content pairs
                "content_hash": content_hash,
                "faqs": faqs[:20],  # Limit to 20 FAQs
                "validation": {"quality_score": validation["quality_score"], "warnings": validation["warnings"]},
                "scraped_at": datetime.now().isoformat(),
            }

            return product_data

        except Exception as e:
            logger.error(f"Error scraping product page {url}: {str(e)}")
            self.stats["errors"] += 1
            return None

    def _extract_main_content(self, soup) -> str:
        """Extract main content text from page with sanitization"""
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()

        # Prioritize text-content and nested-grid-wrapper__text elements
        content_parts = []

        # Extract from text-content elements
        text_content_elems = soup.find_all(class_=re.compile(r"text-content", re.IGNORECASE))
        for elem in text_content_elems:
            text = elem.get_text(separator=" ", strip=True)
            if text:
                content_parts.append(text)

        # Extract from nested-grid-wrapper__text
        nested_text_elems = soup.find_all(class_=re.compile(r"nested-grid-wrapper__text", re.IGNORECASE))
        for elem in nested_text_elems:
            text = elem.get_text(separator=" ", strip=True)
            if text:
                content_parts.append(text)

        # If we found content in the prioritized elements, use that
        if content_parts:
            text = " ".join(content_parts)
            text = re.sub(r"\s+", " ", text)
            return text.strip()

        # Fall back to traditional content extraction
        content_selectors = ["main", "article", ".content", ".main-content"]

        content = None
        for selector in content_selectors:
            content = soup.select_one(selector)
            if content:
                break

        if not content:
            content = soup.find("body")

        if content:
            text = content.get_text(separator=" ", strip=True)
            # Clean up whitespace
            text = re.sub(r"\s+", " ", text)
            # Remove any remaining HTML entities or special characters that might cause issues
            text = re.sub(r"[^\w\s\.\,\!\?\;\:\-\(\)\[\]\'\"\/]", " ", text)
            text = re.sub(r"\s+", " ", text)  # Clean up again after character removal
            return text.strip()

        return ""

    def _extract_lists(self, soup, keywords: List[str]) -> List[str]:
        """Extract lists based on keywords in headings or class names"""
        items = []

        # First, prioritize nested-grid-wrapper__text with text-content for lists
        nested_wrappers = soup.find_all(class_=re.compile(r"nested-grid-wrapper__text", re.IGNORECASE))
        for wrapper in nested_wrappers:
            # Check if this wrapper contains content related to our keywords
            wrapper_text = wrapper.get_text(separator=" ", strip=True).lower()
            if any(keyword.lower() in wrapper_text for keyword in keywords):
                # Extract list items from this wrapper
                for li in wrapper.find_all("li"):
                    text = li.get_text(strip=True)
                    if text and len(text) > 10:
                        items.append(text)

                # Also extract from text-content divs within the wrapper
                text_content_divs = wrapper.find_all(class_=re.compile(r"text-content", re.IGNORECASE))
                for div in text_content_divs:
                    text = div.get_text(strip=True)
                    if text and len(text) > 10:
                        items.append(text)

        for keyword in keywords:
            # Find sections with keyword in heading
            headings = soup.find_all(["h2", "h3", "h4", "h5"], string=re.compile(keyword, re.IGNORECASE))

            for heading in headings:
                # Find list following the heading
                next_elem = heading.find_next_sibling(["ul", "ol", "div"])

                if next_elem:
                    if next_elem.name in ["ul", "ol"]:
                        for li in next_elem.find_all("li"):
                            text = li.get_text(strip=True)
                            if text and len(text) > 10 and text not in items:
                                items.append(text)
                    else:
                        # Look for list items in div
                        for li in next_elem.find_all("li"):
                            text = li.get_text(strip=True)
                            if text and len(text) > 10 and text not in items:
                                items.append(text)

            # Also find elements with keyword in class name
            elements = soup.find_all(class_=re.compile(keyword, re.IGNORECASE))
            for elem in elements:
                for li in elem.find_all("li"):
                    text = li.get_text(strip=True)
                    if text and len(text) > 10 and text not in items:
                        items.append(text)

        return items

    def _extract_pricing_info(self, soup) -> Dict[str, str]:
        """Extract pricing/premium information"""
        pricing = {}

        # Look for pricing-related sections
        pricing_keywords = ["premium", "price", "cost", "fee", "payment"]

        for keyword in pricing_keywords:
            sections = soup.find_all(["div", "section", "p"], class_=re.compile(keyword, re.IGNORECASE))

            for section in sections:
                text = section.get_text(strip=True)
                if text and len(text) > 20:
                    pricing[keyword] = text
                    break

        return pricing

    def _extract_structured_content(self, soup, *, enable_strong_headings: bool = False) -> List[Dict[str, str]]:
        """
        Extract structured content as heading-content pairs (similar to FAQs).

        enable_strong_headings:
            When True, treat <strong> elements inside slot="text-content" as section headings.
            This is intended for article pages where headings are embedded as <strong> in the body.
        """
        content_items = []
        processed_elements = set()

        # First, extract H1 and caption as the first heading-content pair
        h1_title = soup.find("h1")
        caption = None

        # Extract caption from heading section
        caption_elem = soup.select_one('[slot="caption"], .caption, page-intro-sub-text[slot="caption"], page-intro-sub-text')
        if caption_elem:
            caption = caption_elem.get_text(strip=True)
            processed_elements.add(id(caption_elem))

        # Add H1 + caption as first content pair
        if h1_title:
            h1_text = h1_title.get_text(strip=True)
            if h1_text:
                content_text = caption if caption else ""
                if content_text:
                    content_items.append({"heading": h1_text, "content": content_text})

        # Extract from nested-grid-wrapper containers (priority)
        # These contain nested-grid-wrapper__text elements with slot="text-heading" and slot="text-content"
        nested_grid_wrappers = soup.find_all(class_=re.compile(r"nested-grid-wrapper(?!__)", re.IGNORECASE))

        for grid_wrapper in nested_grid_wrappers:
            if id(grid_wrapper) in processed_elements:
                continue

            # Find all nested-grid-wrapper__text elements within this wrapper
            text_elements = grid_wrapper.find_all(class_=re.compile(r"nested-grid-wrapper__text", re.IGNORECASE))

            heading_text = None
            content_text = None

            for text_elem in text_elements:
                if id(text_elem) in processed_elements:
                    continue

                # Look for text-heading in slot="text-heading" or slot="om2ColLayoutContentHeader"
                heading_slot = text_elem.find(["span", "div"], slot=re.compile(r"text-heading|om2ColLayoutContentHeader", re.IGNORECASE))
                if heading_slot:
                    heading_text = heading_slot.get_text(strip=True)
                    if not heading_text:
                        # Try to find text-heading inside
                        inner_heading = heading_slot.find(["span", "div"], slot="text-heading")
                        if inner_heading:
                            heading_text = inner_heading.get_text(strip=True)
                    processed_elements.add(id(text_elem))

                # Look for text-content in slot="text-content" or slot="om2ColLayoutContentText"
                content_slot = text_elem.find(["span", "div"], slot=re.compile(r"text-content|om2ColLayoutContentText", re.IGNORECASE))
                if content_slot:
                    content_text = content_slot.get_text(separator=" ", strip=True)
                    if not content_text:
                        # Try to find text-content inside
                        inner_content = content_slot.find(["span", "div", "p"], slot="text-content")
                        if inner_content:
                            content_text = inner_content.get_text(separator=" ", strip=True)
                    processed_elements.add(id(text_elem))

            # If we found both heading and content, add them as a pair
            if heading_text and content_text:
                content_items.append({"heading": heading_text, "content": content_text})
            elif heading_text:
                # Only heading found, add with empty content
                content_items.append({"heading": heading_text, "content": ""})
            elif content_text:
                # Only content found, try to find heading elsewhere or use default
                # Check if there's a heading in the same wrapper
                heading_in_wrapper = grid_wrapper.find(["h2", "h3", "h4", "span", "div"], class_=re.compile(r"heading|text-heading", re.IGNORECASE))
                if heading_in_wrapper:
                    heading_text = heading_in_wrapper.get_text(strip=True)
                    content_items.append({"heading": heading_text, "content": content_text})
                else:
                    content_items.append({"heading": "Content", "content": content_text})

            processed_elements.add(id(grid_wrapper))

        if enable_strong_headings:
            # Extract from slot="text-content" with <strong> tags as headings (for articles)
            # This handles the case where headings are <strong> tags within text-content
            text_content_slots = soup.find_all(["span", "div"], slot=re.compile(r"text-content", re.IGNORECASE))

            for content_slot in text_content_slots:
                if id(content_slot) in processed_elements:
                    continue

                # Find all <strong> tags within this content slot
                strong_tags = content_slot.find_all("strong")

                if strong_tags:
                    # Process each strong tag as a heading
                    for strong_tag in strong_tags:
                        heading_text = strong_tag.get_text(strip=True)
                        if not heading_text:
                            continue

                        # Collect content following this strong tag until next strong tag
                        content_parts = []

                        # Get the parent element (usually <p>)
                        parent_elem = strong_tag.parent

                        if parent_elem:
                            # Get text after the strong tag in the same parent element
                            strong_found = False
                            for child in parent_elem.children:
                                # Check if this child contains or is the strong tag
                                if child == strong_tag:
                                    strong_found = True
                                    continue

                                # Check if this child element contains the strong tag
                                if hasattr(child, "find") and child.find("strong") == strong_tag:
                                    strong_found = True
                                    # Get text after the strong tag in this child
                                    strong_in_child = child.find("strong")
                                    if strong_in_child:
                                        for sibling in strong_in_child.next_siblings:
                                            if hasattr(sibling, "get_text"):
                                                text = sibling.get_text(separator=" ", strip=True)
                                                if text:
                                                    content_parts.append(text)
                                            elif isinstance(sibling, str) and sibling.strip():
                                                content_parts.append(sibling.strip())
                                    continue

                                if strong_found:
                                    if hasattr(child, "get_text"):
                                        text = child.get_text(separator=" ", strip=True)
                                        if text:
                                            content_parts.append(text)
                                    elif isinstance(child, str) and child.strip():
                                        content_parts.append(child.strip())

                            # Get all following sibling elements until next strong tag
                            next_elem = parent_elem.find_next_sibling()
                            while next_elem:
                                # Stop if this element or any child contains a strong tag
                                if next_elem.find("strong"):
                                    break

                                text = next_elem.get_text(separator=" ", strip=True)
                                if text:
                                    content_parts.append(text)

                                next_elem = next_elem.find_next_sibling()

                        content_text = " ".join(content_parts).strip()
                        if content_text:
                            content_items.append({"heading": heading_text, "content": content_text})

                    processed_elements.add(id(content_slot))

        # Extract text-heading and text-content pairs (fallback for non-nested-grid-wrapper structures)
        text_headings = soup.find_all(["span", "div"], slot=re.compile(r"text-heading", re.IGNORECASE))

        for heading_elem in text_headings:
            if id(heading_elem) in processed_elements:
                continue

            heading_text = heading_elem.get_text(strip=True)
            if not heading_text:
                continue

            # Find corresponding text-content (could be sibling or in same container)
            text_content = None

            # First try next sibling with slot="text-content"
            next_elem = heading_elem.find_next_sibling(["span", "div"], slot=re.compile(r"text-content", re.IGNORECASE))
            if next_elem:
                text_content = next_elem.get_text(separator=" ", strip=True)
                processed_elements.add(id(next_elem))
            else:
                # Try to find text-content in parent or nearby
                parent = heading_elem.parent
                if parent:
                    text_content_elem = parent.find(["span", "div"], slot=re.compile(r"text-content", re.IGNORECASE))
                    if text_content_elem and id(text_content_elem) not in processed_elements:
                        text_content = text_content_elem.get_text(separator=" ", strip=True)
                        processed_elements.add(id(text_content_elem))

            if heading_text and text_content:
                content_items.append({"heading": heading_text, "content": text_content})

            processed_elements.add(id(heading_elem))

        # Also look for h2, h3, h4 headings and their content (fallback)
        headings = soup.find_all(["h2", "h3", "h4"])
        for heading in headings:
            if id(heading) in processed_elements:
                continue

            heading_text = heading.get_text(strip=True)
            if not heading_text:
                continue

            # Skip if this heading was already processed
            if any(item["heading"] == heading_text for item in content_items):
                continue

            # Collect content following the heading until next heading
            current = heading.find_next_sibling()
            content_parts = []

            while current:
                # Stop if we hit another heading
                if current.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                    break

                # Collect text from this element
                text = current.get_text(separator=" ", strip=True)
                if text:
                    content_parts.append(text)

                current = current.find_next_sibling()

            if content_parts:
                content_text = " ".join(content_parts).strip()
                if content_text and len(content_text) > 20:
                    content_items.append({"heading": heading_text, "content": content_text})

            processed_elements.add(id(heading))

        return content_items

    def _extract_faqs(self, soup) -> List[Dict[str, str]]:
        """Extract FAQs from product page HTML structure (only from om-faq-card elements)"""
        faqs = []

        # First, look for om-faq-card custom elements (highest priority)
        faq_cards = soup.find_all("om-faq-card")
        for card in faq_cards:
            # Try to get question from closedtext/closed-text attribute or button text
            question = None
            if card.get("closedtext"):
                # Decode HTML entities
                question = html.unescape(card.get("closedtext", ""))
            elif card.get("closed-text"):
                question = html.unescape(card.get("closed-text", ""))
            else:
                # Try to find question in button/h6
                button = card.find("button", class_=re.compile(r"accordion-button"))
                if button:
                    h6 = button.find("h6")
                    if h6:
                        question = h6.get_text(strip=True)

            # Try to get answer from expandedtext/expanded-text attribute or slot
            answer = None
            if card.get("expandedtext"):
                # Decode HTML entities
                answer_html = html.unescape(card.get("expandedtext", ""))
                # Parse HTML to get clean text
                answer_soup = BeautifulSoup(answer_html, "html.parser")
                answer = answer_soup.get_text(separator=" ", strip=True)
            elif card.get("expanded-text"):
                answer_html = html.unescape(card.get("expanded-text", ""))
                answer_soup = BeautifulSoup(answer_html, "html.parser")
                answer = answer_soup.get_text(separator=" ", strip=True)
            else:
                # Try to find answer in slot="expanded-text" div
                expanded_slot = card.find("div", slot="expanded-text")
                if expanded_slot:
                    answer = expanded_slot.get_text(separator=" ", strip=True)
                else:
                    # Try accordion panel
                    panel = card.find("div", class_=re.compile(r"accordion-panel"))
                    if panel:
                        answer = panel.get_text(separator=" ", strip=True)

            if question and answer:
                faqs.append({"question": question.strip(), "answer": answer.strip()})

        return faqs

    def _extract_faqs_from_content(self, content: str) -> List[Dict[str, str]]:
        """Extract FAQs from content text by identifying question-answer patterns"""
        faqs = []

        # Safety check for None or empty content
        if not content or not isinstance(content, str):
            return faqs

        # Split content into sentences/paragraphs (better splitting)
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", content)

        current_question = None
        current_answer = []

        for sentence in sentences:
            if not sentence:  # Skip None or empty
                continue
            sentence = sentence.strip()
            if not sentence:  # Skip empty after strip
                continue

            # Ensure sentence is a string (not None)
            if not isinstance(sentence, str):
                continue

            # Check if this is a question (must end with ? or be a clear question)
            is_question = False

            if sentence.endswith("?"):
                # Must start with question word or be reasonably short
                matches_pattern = re.match(
                    r"^(What|How|Who|Where|When|Why|Can|Do|Does|Is|Are|Will|Would|Should|May|Could|Have|Has|Does|Did|Want|Need)", sentence, re.IGNORECASE
                )
                is_short_question = len(sentence) > 15 and len(sentence) < 200
                if matches_pattern or is_short_question:
                    is_question = True

            if is_question:
                # Save previous Q&A if exists
                if current_question and current_answer:
                    answer_text = " ".join(current_answer).strip()
                    if len(answer_text) > 30:  # Valid answer must be substantial
                        faqs.append({"question": current_question, "answer": answer_text})

                current_question = sentence
                current_answer = []
            elif current_question:
                # This is part of the answer
                # Stop if we hit another question without ?
                if re.match(r"^(What|How|Who|Where|When|Why)", sentence, re.IGNORECASE):
                    # Might be next question - save current and start new
                    answer_text = " ".join(current_answer).strip()
                    if len(answer_text) > 30:
                        faqs.append({"question": current_question, "answer": answer_text})
                    current_question = sentence if len(sentence) < 200 else None
                    current_answer = []
                elif len(sentence) > 20:  # Minimum answer length
                    current_answer.append(sentence)
                    # Stop collecting answer if it gets too long (max 5 sentences)
                    if len(current_answer) >= 5:
                        answer_text = " ".join(current_answer).strip()
                        faqs.append({"question": current_question, "answer": answer_text})
                        current_question = None
                        current_answer = []

        # Add last Q&A if exists
        if current_question and current_answer:
            answer_text = " ".join(current_answer).strip()
            if len(answer_text) > 30:
                faqs.append({"question": current_question, "answer": answer_text})

        return faqs

    def _extract_features_from_content(self, content: str) -> List[str]:
        """Extract features/benefits from content text"""
        features = []

        # Safety check for None or empty content
        if not content or not isinstance(content, str):
            return features

        # Look for "What are the benefits?" section specifically
        benefit_match = re.search(r"What are the benefits[^?]*?\?\s*([^?]+?)(?=\s*(?:What|How|Who|Where|When|Why|$))", content, re.IGNORECASE | re.DOTALL)

        if benefit_match:
            benefits_text = benefit_match.group(1).strip()

            # Split benefits - they might be separated by capital letters (new sentences) or run together
            # First try splitting by capital letters (new sentences)
            parts = re.split(r"(?<=[a-z])\s+(?=[A-Z][a-z])", benefits_text)

            for part in parts:
                part = part.strip()
                # Clean up punctuation
                part = re.sub(r"^[,\s•\-\u2022\s]+|[,\s•\-\u2022\s]+$", "", part)

                # If part is too long, it might contain multiple benefits - try to split further
                if len(part) > 150:
                    # Split by common patterns like "One of", "Offer", "Unit trusts", etc.
                    sub_parts = re.split(r"(?<=\w)\s+(?:One of|Offer|Unit trusts|Low-cost|Full-time)", part, flags=re.IGNORECASE)
                    for sub_part in sub_parts:
                        sub_part = sub_part.strip()
                        if sub_part and len(sub_part) > 20:
                            # Capitalize first letter if needed
                            if sub_part and not sub_part[0].isupper():
                                sub_part = sub_part[0].upper() + sub_part[1:]
                            if len(sub_part) >= 25 and len(sub_part) < 250:
                                features.append(sub_part)
                elif len(part) >= 25 and len(part) < 250:
                    # Capitalize first letter if needed
                    if part and not part[0].isupper():
                        part = part[0].upper() + part[1:]
                    if not part.endswith("?"):
                        features.append(part)

        # Also look for explicit benefit lists (sentences after "benefits are" etc.)
        benefit_list_patterns = [
            r"(?:benefits?|features?|advantages?)(?:\s+are|include|:)?\s+([^.!?]+(?:[.!?][^.!?]+){0,3})",
        ]

        for pattern in benefit_list_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                text = match.group(1).strip()
                # Split into individual benefits
                items = re.split(r"[.!?]\s+(?=[A-Z])", text)
                for item in items:
                    item = item.strip()
                    item = re.sub(r"^[,\s•\-\u2022\s]+|[,\s•\-\u2022\s]+$", "", item)
                    if len(item) > 25 and len(item) < 250 and item[0].isupper():
                        features.append(item)

        # Remove duplicates while preserving order
        seen = set()
        unique_features = []
        for feature in features:
            normalized = feature.lower().strip()
            # More aggressive duplicate detection
            if normalized not in seen and len(normalized) > 20:
                seen.add(normalized)
                unique_features.append(feature)

        return unique_features[:15]  # Limit to 15 features

    def _extract_benefits_from_content(self, content: str) -> List[str]:
        """Extract benefits/advantages from content (customer-focused benefits)"""
        benefits = []

        # Safety check for None or empty content
        if not content or not isinstance(content, str):
            return benefits

        # Look for "What's in it for you?" or similar benefit sections
        benefit_section_patterns = [
            r"What's in it for you[^?]*?\?\s*([^?]+?)(?=\s*(?:What|How|Who|Where|When|Why|$))",
            r"benefits? (?:include|are|:)\s*([^.!?]+(?:[.!?][^.!?]+){0,5})",
        ]

        for pattern in benefit_section_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE | re.DOTALL)
            for match in matches:
                text = match.group(1).strip()
                # Split into individual benefits
                items = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
                for item in items:
                    item = item.strip()
                    # Look for benefits (often start with capital, describe advantages)
                    if len(item) > 25 and len(item) < 250 and item[0].isupper() and not item.endswith("?"):
                        benefits.append(item)

        # Remove duplicates
        seen = set()
        unique_benefits = []
        for benefit in benefits:
            normalized = benefit.lower().strip()
            if normalized not in seen and len(normalized) > 25:
                seen.add(normalized)
                unique_benefits.append(benefit)

        return unique_benefits[:15]  # Limit to 15 benefits

    def _extract_coverage_from_content(self, content: str) -> List[str]:
        """Extract coverage details from content (what's covered)"""
        coverage = []

        # Safety check for None or empty content
        if not content or not isinstance(content, str):
            return coverage

        # Look for coverage sections
        coverage_patterns = [
            r"coverage[^.!?]*?:?\s*([^.!?]+(?:[.!?][^.!?]+){0,5})",
            r"what (?:is |are )?covered[^.!?]*?:?\s*([^.!?]+(?:[.!?][^.!?]+){0,5})",
            r"covers?\s*([^.!?]+(?:[.!?][^.!?]+){0,3})",
        ]

        for pattern in coverage_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE | re.DOTALL)
            for match in matches:
                text = match.group(1).strip()
                items = re.split(r"(?<=[.!?])\s+(?=[A-Z])|,\s*(?=[A-Z])", text)
                for item in items:
                    item = item.strip()
                    if len(item) > 20 and len(item) < 200 and item[0].isupper():
                        coverage.append(item)

        # Remove duplicates
        seen = set()
        unique_coverage = []
        for item in coverage:
            normalized = item.lower().strip()
            if normalized not in seen:
                seen.add(normalized)
                unique_coverage.append(item)

        return unique_coverage[:20]  # Limit to 20 items

    def _extract_exclusions_from_content(self, content: str) -> List[str]:
        """Extract exclusions from content (what's not covered)"""
        exclusions = []

        # Safety check for None or empty content
        if not content or not isinstance(content, str):
            return exclusions

        # Look for exclusion sections
        exclusion_patterns = [
            r"exclusions?[^.!?]*?:?\s*([^.!?]+(?:[.!?][^.!?]+){0,5})",
            r"not covered[^.!?]*?:?\s*([^.!?]+(?:[.!?][^.!?]+){0,5})",
            r"excludes?[^.!?]*?:?\s*([^.!?]+(?:[.!?][^.!?]+){0,5})",
        ]

        for pattern in exclusion_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE | re.DOTALL)
            for match in matches:
                text = match.group(1).strip()
                items = re.split(r"(?<=[.!?])\s+(?=[A-Z])|,\s*(?=[A-Z])", text)
                for item in items:
                    item = item.strip()
                    if len(item) > 20 and len(item) < 200 and item[0].isupper():
                        exclusions.append(item)

        # Remove duplicates
        seen = set()
        unique_exclusions = []
        for item in exclusions:
            normalized = item.lower().strip()
            if normalized not in seen:
                seen.add(normalized)
                unique_exclusions.append(item)

        return unique_exclusions[:20]  # Limit to 20 items

    def _extract_eligibility_from_content(self, content: str) -> List[str]:
        """Extract eligibility criteria from content (who can apply)"""
        eligibility = []

        # Safety check for None or empty content
        if not content or not isinstance(content, str):
            return eligibility

        # Look for eligibility criteria (who can apply, minimum requirements, etc.)
        criteria_patterns = [
            r"(?:eligible|qualify|can apply|criteria)[\s:]+([^.!?]+(?:[.!?][^.!?]+){0,3})",
            r"minimum[\s]+(?:age|amount|requirement)[\s:]+([^.!?]+)",
            r"any person (?:between|aged)[^.!?]+?\.",
            r"(?:age|aged)[\s]+[\d]+[\s]+(?:to|and)[\s]+[\d]+",
        ]

        for pattern in criteria_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                text = match.group(1).strip() if match.lastindex >= 1 else match.group(0).strip()
                if len(text) > 15 and len(text) < 300:
                    eligibility.append(text)

        # Also look for specific eligibility statements
        eligibility_sentences = re.findall(r"([A-Z][^.!?]*(?:eligible|qualify|can apply|aged|between)[^.!?]*)", content, re.IGNORECASE)

        for sentence in eligibility_sentences:
            sentence = sentence.strip()
            if len(sentence) > 15 and len(sentence) < 300:
                eligibility.append(sentence)

        # Remove duplicates
        seen = set()
        unique_eligibility = []
        for item in eligibility:
            normalized = item.lower().strip()
            if normalized not in seen:
                seen.add(normalized)
                unique_eligibility.append(item)

        return unique_eligibility[:20]  # Limit to 20 items

    def _extract_requirements_from_content(self, content: str) -> List[str]:
        """Extract document requirements from content (documents needed)"""
        requirements = []

        # Safety check for None or empty content
        if not content or not isinstance(content, str):
            return requirements

        # Look for document requirements section
        doc_patterns = [
            r"(?:required|need|must have|documents?)[\s:]+([^.!?]+(?:[.!?][^.!?]+){0,5})",
            r"Copy of ([^.!?]+)",
            r"([A-Z][^.!?]*(?:document|ID|certificate|statement|photo|passport)[^.!?]*)",
            r"([A-Z][^.!?]*identification[^.!?]*)",
            r"([A-Z][^.!?]*bank statement[^.!?]*)",
        ]

        for pattern in doc_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                text = match.group(1) if match.lastindex >= 1 else match.group(0)
                text = text.strip()
                if len(text) > 10 and len(text) < 200:
                    requirements.append(text)

        # Look for document lists (often in specific sections)
        # Check for sections with document-related keywords
        lines = content.split("\n")
        in_requirements_section = False
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Detect requirements section
            if re.search(r"(?:required|need|must|documents?|provide|submit)", line, re.IGNORECASE):
                in_requirements_section = True

            if in_requirements_section:
                # Stop at next major section
                if re.match(r"^(What|How|Who|Where|When|Why)", line, re.IGNORECASE):
                    in_requirements_section = False
                    continue

                # Check if line contains document-related terms
                if re.search(r"(?:document|ID|certificate|statement|photo|passport|bank)", line, re.IGNORECASE):
                    if len(line) > 15 and len(line) < 250:
                        requirements.append(line)

        # Remove duplicates
        seen = set()
        unique_requirements = []
        for item in requirements:
            normalized = item.lower().strip()
            if normalized not in seen:
                seen.add(normalized)
                unique_requirements.append(item)

        return unique_requirements[:30]  # Limit to 30 items

    def _extract_pricing_from_content(self, content: str) -> Dict[str, str]:
        """Extract pricing information from content text"""
        pricing = {}

        # Safety check for None or empty content
        if not content or not isinstance(content, str):
            return pricing

        # Look for currency amounts
        currency_pattern = re.compile(r"(?:USD|UGX|KES|\$|minimum|investment|premium|price|cost|fee)[\s:]+([\d,]+(?:\.[\d]+)?)", re.IGNORECASE)

        matches = list(currency_pattern.finditer(content))
        if matches:
            amounts = [m.group(1) for m in matches]
            pricing["minimum_amount"] = amounts[0] if amounts else None
            pricing["amounts"] = list(set(amounts))

        # Look for pricing-related sentences
        pricing_sentences = re.findall(r"([^.!?]*(?:minimum|investment|premium|price|cost|fee|USD|UGX|\$)[^.!?]*)", content, re.IGNORECASE)

        if pricing_sentences:
            pricing["details"] = " ".join(pricing_sentences[:3])  # First 3 sentences

        return pricing if pricing else {}

    def _parse_content_into_sections(self, content: str) -> Dict[str, Any]:
        """Parse content into structured sections"""
        sections = {
            "overview": "",
            "features": [],
            "benefits": [],
            "coverage": [],
            "exclusions": [],
            "eligibility": [],
            "requirements": [],
            "pricing": {},
            "faqs": [],
        }

        # Extract FAQs first (before parsing other sections)
        sections["faqs"] = self._extract_faqs_from_content(content)

        # Extract features (product capabilities)
        sections["features"] = self._extract_features_from_content(content)

        # Extract benefits (customer advantages - distinct from features)
        sections["benefits"] = self._extract_benefits_from_content(content)

        # Extract coverage (what's covered)
        sections["coverage"] = self._extract_coverage_from_content(content)

        # Extract exclusions (what's not covered)
        sections["exclusions"] = self._extract_exclusions_from_content(content)

        # Extract eligibility (who can apply)
        sections["eligibility"] = self._extract_eligibility_from_content(content)

        # Extract requirements (documents needed - distinct from eligibility)
        sections["requirements"] = self._extract_requirements_from_content(content)

        # Extract pricing
        sections["pricing"] = self._extract_pricing_from_content(content)

        # Extract overview (first paragraph or sentences before first major section)
        sentences = re.split(r"(?<=[.!?])\s+", content)
        overview_sentences = []
        for sentence in sentences[:5]:  # First 5 sentences
            sentence = sentence.strip()
            if len(sentence) > 30 and not sentence.endswith("?") and not re.match(r"^(What|How|Who|Where|When|Why)", sentence, re.IGNORECASE):
                overview_sentences.append(sentence)
            if len(overview_sentences) >= 3:
                break

        sections["overview"] = " ".join(overview_sentences)

        return sections

    def _fetch_and_validate_page(self, url: str, skip_duplicate_check: bool = False) -> Optional[tuple[str, BeautifulSoup, Dict, str]]:
        """
        Helper method to fetch, parse, and validate a page

        Args:
            url: URL to fetch
            skip_duplicate_check: If True, skip duplicate content check (useful for articles/info pages)

        Returns:
            Tuple of (content, soup, validation, content_hash) or None if validation fails
        """
        if url in self.visited_urls:
            logger.debug(f"URL already visited: {url}")
            return None

        html = self.fetch_page(url)
        if not html:
            logger.warning(f"Failed to fetch HTML for: {url}")
            self.stats["errors"] += 1
            return None

        soup = self.parse_html(html)
        if not soup:
            logger.warning(f"Failed to parse HTML for: {url}")
            self.stats["errors"] += 1
            return None

        self.visited_urls.add(url)
        content = self._extract_main_content(soup)

        # Validate content
        validation = self.validator.validate_content(content, url)
        if not validation["valid"]:
            logger.warning(f"Content validation failed for {url}: {validation.get('errors', [])}")
            self.stats["invalid_content"] += 1
            return None

        # Check for duplicates (skip for articles/info pages if requested)
        if not skip_duplicate_check:
            is_duplicate, content_hash = self.validator.is_duplicate_content(content, self.seen_content_hashes)
            if is_duplicate:
                logger.debug(f"Duplicate content detected for: {url}")
                self.stats["duplicates_skipped"] += 1
                return None
        else:
            # Still generate hash for tracking, but don't skip
            _, content_hash = self.validator.is_duplicate_content(content, set())  # Empty set to just generate hash

        self.seen_content_hashes.add(content_hash)
        return (content, soup, validation, content_hash)

    def scrape_faqs(self) -> List[Dict]:
        """Scrape dedicated FAQ pages"""
        logger.info("Scraping FAQ pages...")

        faq_urls = [
            "/faqs",
            "/help",
            "/support",
            "/frequently-asked-questions",
        ]

        all_faqs = []

        for faq_path in faq_urls:
            url = urljoin(self.base_url, faq_path)
            result = self._fetch_and_validate_page(url)
            if not result:
                continue

            content, soup, validation, content_hash = result
            faqs = self._extract_faqs(soup)

            if faqs or content:
                all_faqs.append(
                    {
                        "type": "faq_page",
                        "url": url,
                        "content": content,
                        "content_hash": content_hash,
                        "faqs": faqs,
                        "validation": {"quality_score": validation["quality_score"], "warnings": validation["warnings"]},
                        "scraped_at": datetime.now().isoformat(),
                    }
                )
                self.stats["total_scraped"] += 1
                self.stats["valid_content"] += 1

        logger.info(f"Scraped {len(all_faqs)} FAQ pages")
        return all_faqs

    def scrape_articles(self) -> Dict[str, List[Dict]]:
        """
        Scrape article pages, organized by category

        Returns nested structure:
        {
            "category": [article1, article2, ...]
        }
        """
        logger.info("Scraping article pages...")

        if not self.article_urls:
            logger.warning("No article URLs configured. Skipping article scraping.")
            return {}

        # Organize articles by category (extract from URL path)
        nested_articles = {}

        for path in self.article_urls:
            url = urljoin(self.base_url, path)

            if url in self.visited_urls:
                logger.debug(f"Skipping already visited article: {url}")
                continue

            result = self._fetch_and_validate_page(url, skip_duplicate_check=True)
            if not result:
                logger.debug(f"Skipping article {url} - validation or fetch failed")
                continue

            content_text, soup, validation, content_hash = result

            # Extract structured content (same as products)
            content = self._extract_structured_content(soup, enable_strong_headings=True)

            # Extract FAQs if any
            faqs = self._extract_faqs(soup)

            # Extract title
            h1_title = soup.find("h1")
            title = h1_title.get_text(strip=True) if h1_title else path.split("/")[-1]

            # Determine category from URL path
            parts = path.strip("/").split("/")
            category = "safety-and-security"  # Default category
            if len(parts) >= 2:
                category = parts[1]  # e.g., "safety-and-security"

            if category not in nested_articles:
                nested_articles[category] = []

            article_data = {
                "type": "article",
                "article_id": path.strip("/").split("/")[-1],
                "title": title,
                "category": category,
                "url": url,
                "content": content,
                "content_hash": content_hash,
                "faqs": faqs[:20],
                "validation": {"quality_score": validation["quality_score"], "warnings": validation["warnings"]},
                "scraped_at": datetime.now().isoformat(),
            }

            nested_articles[category].append(article_data)
            self.stats["total_scraped"] += 1
            self.stats["valid_content"] += 1

        total_articles = sum(len(articles) for articles in nested_articles.values())
        logger.info(f"Scraped {total_articles} article pages")
        return nested_articles

    def scrape_info_pages(self) -> Dict[str, List[Dict]]:
        """
        Scrape general information pages, organized by page type

        Returns nested structure:
        {
            "about_us": [page1, page2, ...],
            "other": [page1, page2, ...]
        }
        """
        logger.info("Scraping info pages...")

        if not self.info_page_urls:
            logger.warning("No info page URLs configured. Skipping info page scraping.")
            return {}

        nested_info_pages = {}

        for page_type, paths in self.info_page_urls.items():
            if page_type not in nested_info_pages:
                nested_info_pages[page_type] = []

            for path in paths:
                url = urljoin(self.base_url, path)

                if url in self.visited_urls:
                    logger.debug(f"Skipping already visited info page: {url}")
                    continue

                result = self._fetch_and_validate_page(url, skip_duplicate_check=True)
                if not result:
                    logger.debug(f"Skipping info page {url} - validation or fetch failed")
                    continue

                content_text, soup, validation, content_hash = result

                # Extract structured content (same as products)
                content = self._extract_structured_content(soup)

                # Extract FAQs if any
                faqs = self._extract_faqs(soup)

                # Extract title
                h1_title = soup.find("h1")
                title = h1_title.get_text(strip=True) if h1_title else path.split("/")[-1]

                page_data = {
                    "type": "info_page",
                    "page_id": path.strip("/").split("/")[-1],
                    "page_type": page_type,
                    "title": title,
                    "url": url,
                    "content": content,
                    "content_hash": content_hash,
                    "faqs": faqs[:20],
                    "validation": {"quality_score": validation["quality_score"], "warnings": validation["warnings"]},
                    "scraped_at": datetime.now().isoformat(),
                }

                nested_info_pages[page_type].append(page_data)
                self.stats["total_scraped"] += 1
                self.stats["valid_content"] += 1

        total_pages = sum(len(pages) for pages in nested_info_pages.values())
        logger.info(f"Scraped {total_pages} info pages")
        return nested_info_pages

    # Base scraper methods (merged from base_scraper.py)

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic"""
        session = requests.Session()
        retry_strategy = Retry(total=self.max_retries, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["HEAD", "GET", "OPTIONS"])
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def fetch_page(self, url: str, headers: Optional[Dict] = None) -> Optional[str]:
        """
        Fetch a webpage with error handling and rate limiting

        Args:
            url: URL to fetch
            headers: Optional custom headers

        Returns:
            HTML content as string, or None if fetch failed
        """
        # Enforce rate limiting if configured
        if self.rate_limiter:
            self.rate_limiter.wait_if_needed()

        try:
            default_headers = {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Cache-Control": "max-age=0",
            }

            if headers:
                default_headers.update(headers)

            # Apply delay between requests
            if self.delay > 0:
                time.sleep(self.delay)

            response = self.session.get(url, headers=default_headers, timeout=self.timeout)
            response.raise_for_status()

            # Check response size
            content_length = len(response.content)
            max_size = 10 * 1024 * 1024  # 10MB limit
            if content_length > max_size:
                logger.warning(f"Large response from {url}: {content_length} bytes " f"(limit: {max_size})")

            logger.info(f"Successfully fetched: {url} ({content_length} bytes)")
            html_text = response.text

            if self._should_try_js_fallback(url, html_text):
                rendered_html = self._fetch_page_with_playwright(url)
                if rendered_html:
                    logger.info(f"Using JS-rendered HTML for: {url}")
                    return rendered_html

            return html_text

        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout fetching {url}: {str(e)}")
            return None
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error fetching {url}: {e.response.status_code} - {str(e)}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching {url}: {type(e).__name__} - {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {type(e).__name__} - {str(e)}")
            return None

    def _should_try_js_fallback(self, url: str, html_text: str) -> bool:
        """
        Determine whether to attempt JS-rendered fetch fallback.

        We only use this for app/public routes and when static HTML appears to be
        a shell with very little meaningful body text.
        """
        if not self.enable_js_fallback:
            return False

        if "/app/public/" not in url:
            return False

        if not html_text:
            return True

        soup = self.parse_html(html_text)
        if not soup:
            return True

        for script in soup(["script", "style", "noscript"]):
            script.decompose()

        body = soup.find("body")
        visible_text = body.get_text(separator=" ", strip=True) if body else soup.get_text(separator=" ", strip=True)
        visible_text = re.sub(r"\s+", " ", visible_text).strip()

        # If content is very short, it is likely a JS shell page.
        return len(visible_text) < 120

    def _fetch_page_with_playwright(self, url: str) -> Optional[str]:
        """
        Fetch fully rendered HTML using Playwright (Chromium).
        Falls back gracefully if Playwright is unavailable.
        """
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except Exception:
            logger.warning("Playwright is not installed. Skipping JS fallback fetch.")
            return None

        browser = None
        context = None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(user_agent=self.user_agent)
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=self.playwright_timeout_ms)
                page.wait_for_timeout(2000)
                return page.content()
        except PlaywrightTimeoutError:
            logger.warning(f"Playwright timeout while rendering: {url}")
            return None
        except Exception as e:
            logger.warning(f"Playwright render failed for {url}: {type(e).__name__} - {str(e)}")
            return None
        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass

    def parse_html(self, html: str, timeout: int = 30) -> Optional[BeautifulSoup]:
        """
        Parse HTML content with BeautifulSoup with timeout protection

        Args:
            html: HTML content to parse
            timeout: Maximum time to spend parsing (seconds)

        Returns:
            BeautifulSoup object or None if parsing fails/times out
        """
        try:
            # Try lxml parser first (faster), fallback to html.parser
            try:
                soup = BeautifulSoup(html, "lxml")
            except Exception:
                # Fallback to html.parser if lxml not available
                soup = BeautifulSoup(html, "html.parser")

            return soup
        except Exception as e:
            logger.error(f"Error parsing HTML: {type(e).__name__} - {str(e)}")
            return None

    def save_raw_data(self, data: Any, filename: str, output_dir: Path, validate: bool = True):
        """
        Save raw scraped data to JSON with optional validation

        Args:
            data: Data to save
            filename: Output filename
            output_dir: Output directory
            validate: Whether to validate data structure before saving
        """
        try:
            # Basic validation
            if validate:
                if not isinstance(data, (dict, list)):
                    logger.warning(f"Unexpected data type: {type(data)}")
                if isinstance(data, list) and len(data) == 0:
                    logger.warning("Attempting to save empty list")

            output_dir.mkdir(parents=True, exist_ok=True)
            filepath = output_dir / filename

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Log file size
            file_size = filepath.stat().st_size
            logger.info(f"Saved data to {filepath} ({file_size} bytes)")

        except Exception as e:
            logger.error(f"Error saving data to {output_dir / filename}: {type(e).__name__} - {str(e)}")
            raise


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    scraper = OldMutualWebsiteScraper()
    data = scraper.scrape()
    print(f"Scraped {len(data)} pages")
