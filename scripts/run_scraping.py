#!/usr/bin/env python3
"""
Production script to run the website scraper
"""
import sys
import argparse
import logging
from pathlib import Path
from typing import Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.scrapers.website_scraper import OldMutualWebsiteScraper


def setup_logging(verbose: bool = False, log_file: Optional[Path] = None):
    """Setup logging configuration"""
    level = logging.DEBUG if verbose else logging.INFO
    
    handlers = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )


def main():
    """Main entry point for scraper"""
    parser = argparse.ArgumentParser(
        description='Scrape Old Mutual Uganda website for RAG data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run scraper with default config
  python scripts/run_scraping.py

  # Run scraper with verbose output
  python scripts/run_scraping.py --verbose

  # Run scraper with custom config
  python scripts/run_scraping.py --config config/custom_config.yml

  # Run scraper and save to custom output directory
  python scripts/run_scraping.py --output-dir data/custom_output

  # Run scraper with custom base URL
  python scripts/run_scraping.py --base-url https://example.com
        """
    )
    
    parser.add_argument(
        '--config',
        type=Path,
        default=None,
        help='Path to scraping config YAML file (default: config/scraping_config.yml)'
    )
    
    parser.add_argument(
        '--base-url',
        type=str,
        default=None,
        help='Base URL to scrape (overrides config)'
    )
    
    parser.add_argument(
        '--output-dir',
        type=str,
        default=None,
        help='Output directory for scraped data (overrides config)'
    )
    
    parser.add_argument(
        '--delay',
        type=float,
        default=None,
        help='Delay between requests in seconds (overrides config)'
    )
    
    parser.add_argument(
        '--max-retries',
        type=int,
        default=None,
        help='Maximum number of retries for failed requests (overrides config)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    parser.add_argument(
        '--log-file',
        type=Path,
        default=Path('logs/scraper.log'),
        help='Path to log file (default: logs/scraper.log)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run mode - show what would be scraped without actually scraping'
    )
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(verbose=args.verbose, log_file=args.log_file)
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("=" * 80)
        logger.info("Old Mutual Website Scraper")
        logger.info("=" * 80)
        
        # Prepare scraper arguments
        scraper_kwargs = {}
        if args.base_url:
            scraper_kwargs['base_url'] = args.base_url
        if args.output_dir:
            scraper_kwargs['output_dir'] = args.output_dir
        if args.config:
            scraper_kwargs['config_path'] = args.config
        if args.delay:
            scraper_kwargs['delay'] = args.delay
        if args.max_retries:
            scraper_kwargs['max_retries'] = args.max_retries
        
        # Initialize scraper
        logger.info("Initializing scraper...")
        scraper = OldMutualWebsiteScraper(**scraper_kwargs)
        
        # Display configuration
        logger.info("\nScraper Configuration:")
        logger.info(f"  Base URL: {scraper.base_url}")
        logger.info(f"  Output Directory: {scraper.output_dir}")
        logger.info(f"  Priority URLs: {len(scraper.priority_urls)}")
        logger.info(f"  Rate Limiting: {'Enabled' if scraper.rate_limiter else 'Disabled'}")
        if scraper.rate_limiter:
            logger.info(f"    Rate Limit: {scraper.rate_limiter.requests_per_minute} requests/min")
        logger.info(f"  Delay: {scraper.delay}s")
        logger.info(f"  Max Retries: {scraper.max_retries}")
        
        if args.dry_run:
            logger.info("\n" + "=" * 80)
            logger.info("DRY RUN MODE - No scraping will be performed")
            logger.info("=" * 80)
            logger.info(f"\nWould scrape {len(scraper.priority_urls)} product URLs:")
            for url in scraper.priority_urls[:5]:
                logger.info(f"  - {scraper.base_url}{url}")
            if len(scraper.priority_urls) > 5:
                logger.info(f"  ... and {len(scraper.priority_urls) - 5} more")
            logger.info("\n" + "=" * 80)
            return 0
        
        # Run scraping
        logger.info("\n" + "=" * 80)
        logger.info("Starting scraping process...")
        logger.info("=" * 80 + "\n")
        
        data = scraper.scrape()
        flat_items = []

        if isinstance(data, list):
            flat_items = data
        elif isinstance(data, dict):
            products = data.get('products') or {}
            if isinstance(products, dict):
                for subcats in products.values():
                    if isinstance(subcats, dict):
                        for items in subcats.values():
                            if isinstance(items, list):
                                flat_items.extend([item for item in items if isinstance(item, dict)])

            articles = data.get('articles') or {}
            if isinstance(articles, dict):
                for items in articles.values():
                    if isinstance(items, list):
                        flat_items.extend([item for item in items if isinstance(item, dict)])
            elif isinstance(articles, list):
                flat_items.extend([item for item in articles if isinstance(item, dict)])

            faqs = data.get('faqs') or []
            if isinstance(faqs, list):
                flat_items.extend([item for item in faqs if isinstance(item, dict)])

            info_pages = data.get('info_pages') or {}
            if isinstance(info_pages, dict):
                for items in info_pages.values():
                    if isinstance(items, list):
                        flat_items.extend([item for item in items if isinstance(item, dict)])
            elif isinstance(info_pages, list):
                flat_items.extend([item for item in info_pages if isinstance(item, dict)])
        else:
            logger.warning('Unexpected scrape output type: %s', type(data).__name__)
        
        # Display results
        logger.info("\n" + "=" * 80)
        logger.info("SCRAPING COMPLETE")
        logger.info("=" * 80)
        logger.info(f"Total pages scraped: {len(flat_items)}")

        if len(flat_items) == 0:
            logger.error("No pages were scraped successfully. This usually means upstream blocking (e.g., HTTP 403).")
            return 2
        
        # Breakdown by type
        type_counts = {}
        category_counts = {}
        
        for item in flat_items:
            item_type = item.get('type', 'unknown')
            type_counts[item_type] = type_counts.get(item_type, 0) + 1
            
            if 'category' in item:
                category = item.get('category', 'unknown')
                category_counts[category] = category_counts.get(category, 0) + 1
        
        if type_counts:
            logger.info("\nBreakdown by type:")
            for item_type, count in sorted(type_counts.items()):
                logger.info(f"  {item_type}: {count}")
        
        if category_counts:
            logger.info("\nBreakdown by category:")
            for category, count in sorted(category_counts.items()):
                logger.info(f"  {category}: {count}")
        
        # Show statistics
        logger.info("\nScraper Statistics:")
        logger.info(f"  Total scraped: {scraper.stats['total_scraped']}")
        logger.info(f"  Valid content: {scraper.stats['valid_content']}")
        logger.info(f"  Invalid content: {scraper.stats['invalid_content']}")
        logger.info(f"  Duplicates skipped: {scraper.stats['duplicates_skipped']}")
        logger.info(f"  Errors: {scraper.stats['errors']}")
        
        # Show sample data
        if flat_items:
            logger.info("\nSample scraped data (first item):")
            sample = flat_items[0]
            logger.info(f"  Type: {sample.get('type')}")
            logger.info(f"  URL: {sample.get('url')}")
            logger.info(f"  Title: {sample.get('title', sample.get('product_name', 'N/A'))}")
            if 'category' in sample:
                logger.info(f"  Category: {sample.get('category')}")
            if 'subcategory' in sample:
                logger.info(f"  Subcategory: {sample.get('subcategory')}")
            if 'validation' in sample:
                logger.info(f"  Quality Score: {sample['validation'].get('quality_score', 'N/A')}")
            if 'faqs' in sample and sample['faqs']:
                logger.info(f"  FAQs: {len(sample['faqs'])} items")
            if 'features' in sample and sample['features']:
                logger.info(f"  Features: {len(sample['features'])} items")
            logger.info(f"  Content length: {len(sample.get('content', ''))} chars")
        
        logger.info("\n" + "=" * 80)
        logger.info("Scraping completed successfully!")
        logger.info("=" * 80)

        return 0
        
    except KeyboardInterrupt:
        logger.warning("\n\nScraping interrupted by user")
        return 130
    except Exception as e:
        verbose = getattr(args, 'verbose', False)
        logger.error(f"\nError during scraping: {type(e).__name__}: {str(e)}", exc_info=verbose)
        return 1


if __name__ == "__main__":
    # Create logs directory if it doesn't exist
    Path("logs").mkdir(exist_ok=True)
    
    exit_code = main()
    sys.exit(exit_code)

