#!/bin/bash
# setup.sh - Automated environment setup

set -e

echo " Setting up Old Mutual Zoho RAG Environment..."

# Check Python version
python_version=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
if (( $(echo "$python_version < 3.11" | bc -l) )); then
    echo " Python 3.11+ required. Current: $python_version"
    exit 1
fi

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Create data directories
echo "Creating data directories..."
mkdir -p data/raw/{website,pdfs,zoho_exports}
mkdir -p data/processed
mkdir -p data/embeddings
mkdir -p logs
mkdir -p data/reports

# Add .gitkeep files
find data -type d -exec touch {}/.gitkeep \;

# Setup environment file
if [ ! -f .env ]; then
    echo "Creating .env file..."
    cp .env.example .env
    echo "⚠️  Please edit .env with your credentials"
fi

# Download spaCy model (if needed)
# python -m spacy download en_core_web_sm

# Run initial tests
echo "Running tests..."
pytest tests/ --maxfail=1

echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env with your API keys"
echo "2. Run: python scripts/run_scraping.py --scrapers all"
echo "3. Check logs/ for any issues"