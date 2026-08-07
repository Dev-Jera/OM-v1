# Website Scraper Usage Guide

## Production Script

The recommended way to run the scraper is using the production script:

```bash
# Activate virtual environment
source venv/bin/activate  # Windows: venv\Scripts\activate

# Run scraper with default config
python scripts/run_scraping.py

# Run with verbose output
python scripts/run_scraping.py --verbose

# Dry run (see what would be scraped without actually scraping)
python scripts/run_scraping.py --dry-run

# Custom configuration
python scripts/run_scraping.py --base-url https://example.com --output-dir data/custom

# Custom delay and retries
python scripts/run_scraping.py --delay 3.0 --max-retries 5

# Custom config file
python scripts/run_scraping.py --config config/custom_config.yml

# Custom log file
python scripts/run_scraping.py --log-file logs/my_scraper.log
```

## Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--config` | Path to config YAML file | `config/scraping_config.yml` |
| `--base-url` | Base URL to scrape | From config |
| `--output-dir` | Output directory | From config |
| `--delay` | Delay between requests (seconds) | From config |
| `--max-retries` | Maximum retries | From config |
| `--verbose`, `-v` | Enable verbose logging | `False` |
| `--log-file` | Path to log file | `logs/scraper.log` |
| `--dry-run` | Dry run mode (no scraping) | `False` |

## Alternative: Direct Python Execution

You can also run the scraper directly from Python:

```python
from src.scrapers.website_scraper import OldMutualWebsiteScraper

# Initialize and run
scraper = OldMutualWebsiteScraper()
data = scraper.scrape()

print(f"Scraped {len(data)} pages")
```

Or use the module's `__main__`:

```bash
python -m src.scrapers.website_scraper
```

## Output

The scraper will:
1. Save data to `data/raw/website/website_scrape_YYYYMMDD_HHMMSS.json`
2. Log to `logs/scraper.log` (or specified log file)
3. Display statistics in the console

## 🔗 Scraping Configuration

The scraper is configured to crawl the following Old Mutual Uganda product pages via `config/scraping_config.yml`:

### Personal Products (9 URLs)
- Savings & Investment: SOMESA Education Plan, Sure Deal Savings Plan, Dollar Unit Trust Fund, Private Wealth Management
- Insurance: Personal Accident, Serenicare, Professional Liability, Family Life Protection, Travel Sure Plus, Domestic Package, Motor Private Insurance, Motor COMESA Insurance

### Business Products (27 URLs)
**Solutions:**
- Investment & Advisory, Office Compact, SME Medical Cover, SME Life Pack

**Group Benefits:**
- Group Life Cover, Group Medical (Standard), Group Personal Accident, Credit Life Cover, Combined Solutions, Umbrella Pension Scheme, Group Last Expense

**General Insurance (17 products):**
- Fidelity Guarantee, Bankers Blanket Bond, Livestock Insurance, Public Liability, Crop Insurance, Carriers Liability, Directors & Officers Liability, Motor Commercial, Marine (Open Cover, Hull, Cargo), Goods in Transit, Industrial All Risks, All Risks Cover, Burglary, Business Interruption, Fire & Special Perils, Money Insurance, Product Liability

### Investment Products (4 Fund URLs)
- Money Market Fund, Umbrella Trust Fund, Balanced Fund, Dollar Unit Trust Fund

**Note:** Parent/category overview pages have been removed to focus the scraper on specific product content rather than category pages.

