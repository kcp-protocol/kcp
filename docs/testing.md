# Testing the KCP SDK

This document explains how to run tests for each KCP SDK, how the test suites are structured, and conventions for writing new tests.

---

## Quick Start

```bash
# Run all SDK test suites at once (requires all environments set up)
make test

# Or run individually:
make test-python
make test-ts
make test-go
```

See the root [`Makefile`](../Makefile) for all available targets.

---

## Python SDK

**Location:** `sdk/python/tests/`  
**Framework:** [pytest](https://docs.pytest.org/) + [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)  
**Python version:** 3.13 (see `sdk/python/.python-version`)

### Setup

```bash
cd sdk/python

# Create isolated virtual environment (Python 3.13)
python3.13 -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows

# Install package + dev dependencies
pip install -e ".[dev]"
```

Or via Makefile from the root:

```bash
make setup-python
```

### Running Tests

```bash
# All tests
cd sdk/python && .venv/bin/pytest tests/ -v

# Specific module
.venv/bin/pytest tests/test_crypto.py -v

# Single test
.venv/bin/pytest tests/test_node.py::TestKCPNodePublish::test_publish_with_lineage -v

# With coverage report
.venv/bin/pytest tests/ --tb=short -q
```

### Test Structure

```
sdk/python/tests/
├── __init__.py
├── test_models.py   # 19 tests — Lineage, ACL, KnowledgeArtifact, SearchResult
├── test_crypto.py   # 16 tests — generate_keypair, hash_content, sign, verify
└── test_node.py     # 26 tests — KCPNode init, publish, get, search, verify, lineage
```

### Writing New Tests

Each test module mirrors one source module (`kcp/models.py` → `tests/test_models.py`).

```python
import pytest
import tempfile
import os
from kcp.node import KCPNode
from kcp.crypto import generate_keypair


@pytest.fixture
def node(tmp_path):
    """Create a temporary KCPNode that is isolated from the OS."""
    private_key, public_key = generate_keypair()
    n = KCPNode(
        user_id="test@example.com",
        tenant_id="test-corp",
        private_key=private_key,
        public_key=public_key,
        db_path=str(tmp_path / "kcp.db"),
    )
    yield n
    n.close()


def test_publish_returns_artifact(node):
    artifact = node.publish(
        title="My Knowledge",
        content="The answer is 42",
        format="text",
    )
    assert artifact.artifact_id is not None
    assert artifact.signature is not None
```

**Conventions:**
- Use `tmp_path` (pytest built-in) for file storage — never write to `~/.kcp` in tests
- Use class grouping for related tests (`class TestKCPNodePublish:`)
- Each test should be self-contained and clean up after itself
- Test both the happy path and failure modes (tampered content, missing fields, etc.)

---

## TypeScript SDK

**Location:** `sdk/typescript/tests/`  
**Framework:** [Jest](https://jestjs.io/) + [ts-jest](https://kulshekhar.github.io/ts-jest/)  
**Node.js version:** 25.x (see `sdk/typescript/.nvmrc`)

### Setup

```bash
cd sdk/typescript
npm install
```

Or via Makefile:

```bash
make setup-ts
```

### Running Tests

```bash
# All tests
cd sdk/typescript && npm test

# Watch mode (re-runs on file change)
cd sdk/typescript && npm test -- --watch

# Specific file
cd sdk/typescript && npm test -- tests/kcp.test.ts

# Specific test by name
cd sdk/typescript && npm test -- -t "verifies own artifact"
```

### Test Structure

```
sdk/typescript/tests/
└── kcp.test.ts   # 37 tests — models, crypto, KCPNode (publish, search, verify, lineage)
```

### Writing New Tests

```typescript
import { describe, it, expect, beforeEach, afterEach } from '@jest/globals';
import { mkdtempSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { KCPNode } from '../src/node.js';
import { generateKeypair } from '../src/crypto.js';

function tmpNode(): { node: KCPNode; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), 'kcp-test-'));
  const { privateKey, publicKey } = generateKeypair();
  const node = new KCPNode({
    userId: 'test@example.com',
    tenantId: 'test-corp',
    privateKey,
    publicKey,
    dbPath: join(dir, 'kcp.json'),
  });
  return { node, dir };
}

describe('MyFeature', () => {
  let node: KCPNode;
  let dir: string;

  beforeEach(() => { ({ node, dir } = tmpNode()); });
  afterEach(() => { node.close(); rmSync(dir, { recursive: true, force: true }); });

  it('does something', () => {
    const a = node.publish({ title: 'Test', content: 'hello', format: 'text' });
    expect(a.title).toBe('Test');
  });
});
```

**Conventions:**
- Always use `beforeEach` with block body `{ ... }` — arrow shorthand causes TypeScript type errors
- Clean up `tmpdir` in `afterEach` to avoid filesystem pollution
- One `describe` block per feature/method group
- Test names should read as sentences: `"detects tampered title"`

---

## Go SDK

**Location:** `sdk/go/` (tests co-located with source as `*_test.go`)  
**Framework:** Go standard `testing` package  
**Go version:** 1.22 (see `sdk/go/.go-version`)

### Setup

```bash
cd sdk/go
go mod download
```

Or via Makefile:

```bash
make setup-go
```

### Running Tests

```bash
# All packages
cd sdk/go && go test ./... -v

# Specific package
cd sdk/go && go test ./pkg/crypto/... -v

# With race detection
cd sdk/go && go test -race ./...
```

### Writing New Tests

```go
package crypto_test

import (
    "testing"
    "github.com/tgosoul2019/kcp/pkg/crypto"
)

func TestHashContent(t *testing.T) {
    hash := crypto.HashContent([]byte("hello"))
    if len(hash) != 64 {
        t.Errorf("expected 64-char hex, got %d", len(hash))
    }
}
```

**Conventions:**
- Test files follow the `*_test.go` convention and live alongside their source
- Use `t.TempDir()` for temporary storage (auto-cleaned)
- Use `t.Run()` for subtests grouping

---

## CI / Continuous Integration

All three test suites run in CI. The equivalent of running CI locally is:

```bash
make test
```

Which runs `make test-python`, `make test-ts`, and `make test-go` in sequence.

**Expected output:**
```
→ Running Python tests...
61 passed in X.XXs ✓

→ Running TypeScript tests...
Tests: 37 passed ✓

→ Running Go tests...
ok  github.com/tgosoul2019/kcp/pkg/... ✓
```

---

## Test Coverage Summary

| SDK        | Tests | Coverage Area                                              |
|------------|-------|------------------------------------------------------------|
| Python     | 61    | models, crypto, KCPNode (publish, get, search, lineage, verify, stats) |
| TypeScript | 37    | models, crypto, KCPNode (full feature parity with Python)  |
| Go         | —     | In progress                                                |

---

## Related

- [CONTRIBUTING.md](../CONTRIBUTING.md) — how to contribute and open PRs
- [SPEC.md](../SPEC.md) — protocol specification
- [poc/kcp_core.py](../poc/kcp_core.py) — end-to-end demo using all SDK features
