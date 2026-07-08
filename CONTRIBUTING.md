# Contributing to Sentigent

Thank you for your interest in contributing to Sentigent! This guide will help you get set up and ready to contribute.

## Development Setup

### Prerequisites

- Python 3.10+
- Node.js 18+ (for dashboard frontend)
- git

### Installation

1. **Fork and clone the repository**
   ```bash
   git clone https://github.com/your-username/sentigent.git
   cd sentigent
   ```

2. **Create a Python virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install Sentigent with development dependencies**
   ```bash
   pip install -e ".[dev,mcp]"
   ```

   This installs the core package plus development and MCP server dependencies. 
   
   **Optional heavy dependencies** (install only when needed):
   - For embeddings work: `pip install -e ".[embeddings]"`
   - For dashboard frontend dev: `pip install -e ".[dashboard]"`
   - For all extras: `pip install -e ".[all]"`

   Note: Tests requiring embeddings auto-skip if `[embeddings]` is not installed.

## Running Tests

Tests are the backbone of quality. We follow a **test-first development** philosophy:

```bash
pytest -q                  # Quick test run (minimal output)
pytest -v                  # Verbose output with test names
pytest tests/test_file.py  # Run specific test file
pytest -k "pattern"        # Run tests matching a pattern
pytest --cov=sentigent     # With coverage report
```

**Before submitting a PR:**
- Write tests for all new functionality
- Ensure the full test suite passes: `pytest -q`
- Include a note in your PR description if any tests require optional extras (e.g., `[embeddings]`)

## Code Quality

All code must pass linting, formatting, and type checking:

```bash
ruff check sentigent/      # Lint check
ruff format sentigent/     # Auto-format
mypy sentigent/            # Type checking (strict mode enabled)
```

We enforce strict type checking. Every function should have type hints.

## Dashboard Frontend Development

The dashboard is a React + TypeScript app in `sentigent/dashboard/frontend/`:

```bash
cd sentigent/dashboard/frontend

# Install dependencies
npm ci

# Development server
npm run dev

# Build for production
npm run build
```

Built static files in `static/` must be committed to the repo for distribution with the Python package.

## Architecture & Design Decisions

Before making large changes, read:

- **`docs/DECISIONS.md`** — Architectural decision records (ADRs)
- **`docs/LOOP.md`** — How the judgment loop works
- **`docs/PROOF.md`** — Core safety claims
- **`docs/EVALUATION.md`** — Testing & evaluation methodology
- **`docs/SIGNALS.md`** — Signal computation reference

The `docs/` directory contains the authoritative documentation. When in doubt, check there first.

## Project Structure

```
sentigent/
├── core/               # Engine, signals, gate, types
├── memory/             # Episodic, procedural, semantic memory
├── learning/           # Outcome attribution, pattern mining
├── profiles/           # Domain profiles (financial_ops, etc.)
├── integrations/       # Framework integrations (LangGraph, etc.)
├── dashboard/          # Web interface (Python FastAPI + React frontend)
├── eval/               # Evaluation & ablation studies
├── cli.py              # Command-line interface
└── [...]
docs/                   # Architecture, decisions, examples
tests/                  # Test suite
```

## Guidelines

1. **Write tests first.** We practice TDD. Tests should exist before or alongside new code.
2. **Keep the hot path fast.** The judgment loop must stay sub-50ms. No blocking LLM calls in the critical path.
3. **Type everything.** Strict mypy mode is enforced. Every function needs type hints.
4. **Document signals thoroughly.** If you add or modify a signal, document its computation and interpretation in code.
5. **Update domain profiles with real data.** Don't ship demo profiles; test with actual operational baselines when possible.
6. **No hardcoded secrets or paths.** All configuration must come from environment variables or config files (in `~/.sentigent/` or equivalent).

## Pull Request Checklist

When you submit a PR:

- [ ] **Tests added** — All new functionality has corresponding tests
- [ ] **Suite is green** — `pytest -q` passes locally before pushing
- [ ] **README is accurate** — Claims in README.md still reflect the code
- [ ] **No secrets committed** — No API keys, tokens, or private paths in the diff
- [ ] **Code is formatted** — `ruff format` and `ruff check` pass
- [ ] **Types are correct** — `mypy sentigent/` produces no errors
- [ ] **Dashboard built** (if changed) — `npm run build` completed and `static/` committed

## Areas for Contribution

We welcome PRs for:

- New domain profiles (medical, legal, logistics, financial services beyond our current scopes)
- Framework integrations (CrewAI, AutoGen, OpenAI Agents SDK, etc.)
- Improved episode retrieval (better embeddings, hybrid search strategies)
- Dashboard features and visualizations
- Documentation and examples
- Bug fixes and performance improvements

Check `docs/good-first-issues.md` for starter issues if you're new to the codebase.

## Questions?

- Open an issue with the `question` label
- Check existing issues first—your question may already be answered
- Read the docs in `docs/` for in-depth explanations
