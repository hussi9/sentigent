#!/bin/bash
# Sentigent project setup script
# Run this to initialize git and install dependencies

set -e

echo "=== Sentigent Project Setup ==="

# Initialize git repo
if [ ! -d ".git" ]; then
    echo "Initializing git repository..."
    git init
    git add -A
    git commit -m "Initial commit: Sentigent - The judgment layer that learns

Complete project scaffold with:
- Core engine (signals, decision gate, types)
- Memory store (SQLite-based episodic/procedural/semantic memory)
- Learning modules (outcome attribution, pattern mining)
- Domain profiles (financial_ops, customer_support)
- LangGraph integration
- CLI interface
- Full test suite
- Product design document
- GTM strategy document
- Strategic analysis

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
    echo "Git initialized and first commit created!"
else
    echo "Git already initialized."
fi

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    echo "Virtual environment created!"
fi

# Activate and install
echo "Installing dependencies..."
source .venv/bin/activate
pip install -e ".[dev]"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To activate: source .venv/bin/activate"
echo "To run tests: pytest"
echo "To run demo:  python examples/refund_agent/demo.py"
echo "To see CLI:   sentigent --help"
