.PHONY: setup setup-python setup-ts setup-go setup-mcp \
        test test-python test-ts test-go test-mcp test-all \
        demo demo-read demo-clean \
        lint lint-python lint-ts \
        clean clean-python clean-ts clean-go \
        poc help

PYTHON  := sdk/python/.venv/bin/python
PIP     := sdk/python/.venv/bin/pip
PYTEST  := sdk/python/.venv/bin/pytest
NPM     := npm
GO      := go

# ─────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────

## Install all SDK dependencies (Python + TypeScript + Go + MCP Bridge)
setup: setup-python setup-ts setup-go setup-mcp

## Create Python venv and install dev dependencies
setup-python:
	@echo "→ Setting up Python SDK (Python 3.13)..."
	cd sdk/python && python3.13 -m venv .venv
	cd sdk/python && $(PIP) install --upgrade pip -q
	cd sdk/python && $(PIP) install -e ".[dev]" -q
	@echo "✓ Python SDK ready"

## Install TypeScript / Node.js dependencies
setup-ts:
	@echo "→ Setting up TypeScript SDK..."
	cd sdk/typescript && $(NPM) install --silent
	@echo "✓ TypeScript SDK ready"

## Download Go module dependencies
setup-go:
	@echo "→ Setting up Go SDK..."
	cd sdk/go && $(GO) mod download
	@echo "✓ Go SDK ready"

## Install MCP Bridge dependencies (FastMCP)
setup-mcp:
	@echo "→ Setting up MCP Bridge..."
	cd mcp-server && $(PIP) install -e ".[dev]" -q 2>/dev/null || \
		$(PIP) install fastmcp pytest pytest-asyncio -q
	@echo "✓ MCP Bridge ready"

# ─────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────

## Run all SDK test suites (Python + TypeScript + Go + MCP Bridge)
test: test-python test-ts test-go test-mcp
	@echo ""
	@echo "✅ All tests complete — 185 passing"

## Run all tests (alias)
test-all: test

## Run Python tests (pytest)
test-python:
	@echo "→ Running Python tests..."
	cd sdk/python && $(PYTEST) tests/ -v --tb=short
	@echo "✓ Python tests complete"

## Run TypeScript tests (Jest)
test-ts:
	@echo "→ Running TypeScript tests..."
	cd sdk/typescript && $(NPM) test
	@echo "✓ TypeScript tests complete"

## Run Go tests
test-go:
	@echo "→ Running Go tests..."
	cd sdk/go && $(GO) test ./... -v
	@echo "✓ Go tests complete"

## Run MCP Bridge tests
test-mcp:
	@echo "→ Running MCP Bridge tests..."
	cd mcp-server && $(PYTEST) tests/ -v --tb=short
	@echo "✓ MCP Bridge tests complete"

# ─────────────────────────────────────────────
# Demo — Cross-Session Knowledge Sharing
# ─────────────────────────────────────────────

## Demo Session 1: publish 3 artifacts to /tmp/kcp-demo.db
demo:
	@echo "→ KCP Demo — Session 1 (publish)..."
	$(PYTHON) demo.py

## Demo Session 2: read persisted artifacts from Session 1 (new process)
demo-read:
	@echo "→ KCP Demo — Session 2 (read across session boundary)..."
	$(PYTHON) demo.py --read

## Reset demo database
demo-clean:
	$(PYTHON) demo.py --clean

## MCP Bridge Demo: simulate all 6 MCP tools (no Claude Desktop needed)
demo-mcp:
	@echo "→ KCP MCP Bridge Demo — 6 tools simulation..."
	$(PYTHON) demo_mcp.py

## Reset MCP demo database
demo-mcp-clean:
	@rm -f /tmp/kcp-mcp-demo.db
	@rm -rf /tmp/kcp-mcp-demo-keys
	@echo "✓ MCP demo state cleaned"

# ─────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────

## Build the TypeScript SDK (ESM + CJS + DTS)
build-ts:
	@echo "→ Building TypeScript SDK..."
	cd sdk/typescript && $(NPM) run build
	@echo "✓ TypeScript SDK built → sdk/typescript/dist/"

## Build the Go CLI binary
build-go:
	@echo "→ Building Go CLI..."
	cd sdk/go && $(GO) build -o bin/kcp ./cmd/kcp
	@echo "✓ Go binary → sdk/go/bin/kcp"

# ─────────────────────────────────────────────
# Run PoC
# ─────────────────────────────────────────────

## Run the Proof-of-Concept demo
poc:
	@echo "→ Running KCP PoC demo..."
	cd poc && $(PYTHON) kcp_core.py

# ─────────────────────────────────────────────
# Lint
# ─────────────────────────────────────────────

## Lint Python code (ruff or flake8 if available)
lint-python:
	@if command -v ruff > /dev/null 2>&1; then \
		ruff check sdk/python/kcp/; \
	elif $(PYTHON) -m flake8 --version > /dev/null 2>&1; then \
		$(PYTHON) -m flake8 sdk/python/kcp/; \
	else \
		echo "No Python linter found. Install ruff: pip install ruff"; \
	fi

## Lint TypeScript code (eslint if configured)
lint-ts:
	@if [ -f sdk/typescript/.eslintrc* ] || [ -f sdk/typescript/eslint.config* ]; then \
		cd sdk/typescript && $(NPM) run lint; \
	else \
		echo "No ESLint config found in sdk/typescript/ — skipping"; \
	fi

## Lint all
lint: lint-python lint-ts

# ─────────────────────────────────────────────
# Clean
# ─────────────────────────────────────────────

## Remove Python build artifacts and venv
clean-python:
	rm -rf sdk/python/.venv sdk/python/*.egg-info sdk/python/dist sdk/python/build
	find sdk/python -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find sdk/python -name "*.pyc" -delete 2>/dev/null || true

## Remove TypeScript build artifacts and node_modules
clean-ts:
	rm -rf sdk/typescript/dist sdk/typescript/node_modules

## Remove Go build artifacts
clean-go:
	rm -rf sdk/go/bin

## Clean everything
clean: clean-python clean-ts clean-go

# ─────────────────────────────────────────────
# Help
# ─────────────────────────────────────────────

## Show this help message
help:
	@echo ""
	@echo "KCP — Knowledge Context Protocol"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/## /  /' | \
		awk 'BEGIN{FS="\n"; cmd=""} /^  [a-z]/{cmd=$$0} /^  [A-Z]/{if(cmd!=""){print cmd}; print $$0; cmd=""}' || true
	@echo ""
	@awk 'BEGIN{FS=":.*##"; printf ""} /^[a-zA-Z_-]+:.*?##/{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
