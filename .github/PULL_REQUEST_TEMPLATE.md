<!-- Keep it factual: what changed, why, and how it was verified. -->

## What

<!-- One paragraph. Link the issue: Closes #NN -->

## Why

<!-- The problem this solves. Delete if obvious from the issue. -->

## How it was verified

<!-- Literal commands + results. "Tests pass" alone is not enough. -->

- [ ] `ruff check sdk/python/kcp mcp-server/kcp_mcp_server`
- [ ] `ruff format --check sdk/python/kcp mcp-server/kcp_mcp_server`
- [ ] `bandit -r sdk/python/kcp mcp-server/kcp_mcp_server --severity-level medium --confidence-level medium`
- [ ] `cd sdk/python && python -m pytest tests -q`

```
paste the actual output
```

## Compatibility

- [ ] No wire-format / public API change
- [ ] Public API or wire format changed → migration notes below

## Notes for the reviewer

<!-- Trade-offs, things you deliberately left out, follow-ups you are NOT doing here. -->
