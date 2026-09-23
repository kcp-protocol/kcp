# Security Policy

## Supported versions

KCP is pre-1.0: security fixes land on the latest released version and on `main`.

| Version | Supported |
| ------- | --------- |
| 0.2.x   | ✅        |
| < 0.2   | ❌        |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately, either by:

- email to **contato@kcp-protocol.org** (subject prefixed with `[SECURITY]`), or
- GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) on this repository (**Security → Report a vulnerability**).

Please include:

- affected version / commit,
- a minimal reproduction (input, expected vs. actual behaviour),
- impact assessment (what an attacker gains),
- whether the finding is already public anywhere.

## What to expect

| Step | Target |
| ---- | ------ |
| Acknowledgement of the report | 3 business days |
| Triage + severity assessment | 10 business days |
| Fix or mitigation plan shared with the reporter | 30 days for high/critical |
| Public advisory + credit (if you want it) | after the fix is released |

We will keep you informed if a fix takes longer than the targets above, and we
will credit reporters in the advisory unless they ask to stay anonymous.

## Scope

In scope: the protocol specification (`SPEC.md`, `RFC-001-CORE.md`, `rfcs/`), the
SDKs (`sdk/`), the MCP server (`mcp-server/`) and the node HTTP surface under
`/kcp/v1/`.

Out of scope: findings that require a compromised host, denial of service by
brute resource exhaustion on a self-hosted node, and issues in third-party
dependencies (please report those upstream — we will still bump the dependency).

## Hardening notes for operators

- Nodes are P2P and listen on all interfaces by default; expose them behind a
  TLS-terminating proxy and treat `/ui` and the write endpoints as privileged.
- Peer discovery data (`docs/peers.json`) is public by design: it must contain
  public endpoints only — never internal addresses or credentials.
