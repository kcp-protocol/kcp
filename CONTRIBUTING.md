# Contributing to KCP

Thank you for your interest in contributing to the Knowledge Context Protocol!

## How to Contribute

### 1. Feedback on Protocol Spec
The most valuable contribution right now is **feedback on the protocol design**:
- Open an issue with your thoughts on [SPEC.md](SPEC.md)
- Describe your use case and whether KCP addresses it
- Point out gaps, ambiguities, or edge cases

### 2. Use Case Validation
- Does KCP solve a real problem for you?
- Share your scenario in an issue (even if it's not fully formed)
- Real-world validation drives protocol evolution

### 3. Code Contributions
- **SDK implementations** in any language (Rust, Java, Ruby, C#, etc.)
- **Storage backends** (new database adapters)
- **Integration plugins** (IDE extensions, CI/CD, monitoring)

### 4. Documentation
- Fix typos, improve clarity
- Translate to other languages
- Add examples and tutorials

## Development Setup

```bash
# Clone the repo
git clone https://github.com/tgosoul2019/kcp.git
cd kcp

# Python SDK — isolated virtual environment (Python 3.13)
cd sdk/python
python3.13 -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows
pip install -e ".[dev]"

# TypeScript SDK — Node.js 25.x
cd sdk/typescript
npm install

# Go SDK — Go 1.22+
cd sdk/go
go mod download
```

Or use the root Makefile to set up everything at once:

```bash
make setup        # all SDKs
make setup-python # Python only
make setup-ts     # TypeScript only
make setup-go     # Go only
```

## Running Tests

Each SDK has an isolated environment and its own test suite. See [docs/testing.md](docs/testing.md) for the full guide. Quick reference:

```bash
make test          # all SDKs
make test-python   # 61 pytest tests
make test-ts       # 37 Jest tests
make test-go       # Go standard tests
```

**Requirements before opening a PR:**
- All existing tests must pass
- New features must include corresponding tests
- Test files mirror the source structure (`kcp/crypto.py` → `tests/test_crypto.py`)

## Code Style

- **Python:** Follow PEP 8, use type hints
- **TypeScript:** Follow Standard style
- **Go:** Follow standard Go conventions (`gofmt`)
- **Docs:** Markdown, max 120 chars per line

## Commit Messages

Follow Conventional Commits:
```
feat: add vector search to Python SDK
fix: correct Ed25519 signature verification
docs: add Federation section to whitepaper
```

## Pull Request Process

1. Fork the repo
2. Create a branch (`feat/my-feature` or `fix/my-fix`)
3. Make your changes
4. Open a PR with clear description of what and why
5. Wait for review (we aim for 48-hour response time)

## Code of Conduct

Be respectful. Be constructive. Focus on the ideas, not the person.

## Questions?

Open an issue or reach out to tgosoul@gmail.com.
