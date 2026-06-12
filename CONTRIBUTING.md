# Contributing to Sentigent

Thank you for your interest in contributing to Sentigent!

## Getting Started

1. Fork the repository
2. Clone your fork
3. Install dependencies:
   ```bash
   pip install -e ".[dev]"
   ```
4. Run tests:
   ```bash
   pytest
   ```

## Development

### Running Tests

```bash
pytest                    # Run all tests
pytest tests/test_signals.py  # Run specific test file
pytest -v                 # Verbose output
pytest --cov=sentigent    # With coverage
```

### Code Quality

```bash
ruff check sentigent/     # Linting
ruff format sentigent/    # Formatting
mypy sentigent/           # Type checking
```

### Project Structure

```
sentigent/
├── core/           # Engine, signals, gate, types
├── memory/         # Episodic, procedural, semantic memory
├── learning/       # Outcome attribution, pattern mining
├── profiles/       # Domain profiles (financial_ops, etc.)
├── integrations/   # Framework integrations (LangGraph, etc.)
└── cli.py          # Command-line interface
```

## Guidelines

- Write tests for all new functionality
- Keep the hot path (<50ms) free of LLM calls
- Update domain profiles with real-world baselines when possible
- Document signal computation logic thoroughly

## Areas for Contribution

- New domain profiles (medical, legal, logistics, etc.)
- Framework integrations (CrewAI, OpenAI Agents SDK, etc.)
- Improved similar episode retrieval (embeddings, vector search)
- Dashboard visualizations
- Documentation and examples
