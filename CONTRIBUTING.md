# New Developer Onboarding

## Prerequisites
- Python 3.11+
- Git
- Docker (optional)
- VS Code (recommended)

## Setup Steps

1. **Clone Repository**
```bash
   git clone https://github.com/old-mutual-uganda/rag.git
   cd rag
```

2. **Run Setup Script**
```bash
   ./setup.sh
```

3. **Get API Keys**
   - Request from team lead:
     - OpenAI API key
     - Pinecone credentials
     - Zoho API credentials
   
4. **Configure Environment**
```bash
   cp .env.example .env
   # Add your API keys to .env
```

5. **Test Installation**
```bash
   source venv/bin/activate
   pytest tests/
```

6. **Run Sample Pipeline**
```bash
   # Test with sample data
   python scripts/run_scraping.py --scrapers website
```

## Development Workflow

1. Create feature branch: `git checkout -b feature/my-feature`
2. Make changes
3. Run tests: `pytest tests/`
4. Format code: `black src tests`
5. Commit: `git commit -m "Add: feature description"`
6. Push: `git push origin feature/my-feature`
7. Create Pull Request on GitHub

## Useful Commands
```bash
# Run full pipeline
make pipeline  # (if Makefile exists)

# Or manually:
python scripts/run_scraping.py --scrapers all
python scripts/process_data.py
python scripts/generate_embeddings.py --chunks-file data/processed/*.jsonl

# Run tests
pytest tests/ -v

# Check code quality
flake8 src tests
black --check src tests
mypy src

# Start local services
docker-compose up -d
```

## Resources
- [Readme](README.md)
- [Exploring scraping](SCRAPER_USAGE.md)