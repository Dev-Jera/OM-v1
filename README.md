# Old Mutual Zoho RAG System
Hybrid RAG system for Old Mutual Uganda's Zoho ecosystem with conversational AI.

##  Quick Start

### Prerequisites
- Python 3.11+
- API Keys: OpenAI, Pinecone, Zoho
- 4GB+ RAM

### Installation
```bash
# Clone repository
git clone https://github.com/Old-Mutual-Zoho/rag.git
cd rag

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env
# Edit .env with your credentials

# Initialize data directories
mkdir -p data/raw/{website,pdfs,zoho_exports}
mkdir -p data/processed logs
```

### Usage
```bash
# Activate virtual environment
source venv/bin/activate  # Windows: venv\Scripts\activate

# 1. Scrape data
python scripts/run_scraping.py

# Or with options:
python scripts/run_scraping.py --verbose
python scripts/run_scraping.py --dry-run  # Preview what will be scraped
python scripts/run_scraping.py --help     # See all options

# 2. Process data
python scripts/process_data.py

# 3. Generate embeddings
python scripts/generate_embeddings.py \
  --chunks-file data/processed/processed_chunks_*.jsonl

# 4. Run RAG system
python scripts/run_rag.py
```

## 📚 Documentation
- [Contributing](CONTRIBUTING.md)
- [Exploring scraping](SCRAPER_USAGE.md)

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

##  Contact



