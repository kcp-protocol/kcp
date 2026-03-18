# KCP TypeScript SDK

Reference implementation for Node.js and browser environments.

## Status: Planned (Phase 2)

Track progress in [Phase 2 Roadmap](../../docs/roadmap.md).

## Planned API

```typescript
import { KCPClient } from '@kcp/client';

const client = new KCPClient({
  nodeUrl: 'http://localhost:8080',
  tenantId: 'acme-corp',
  userId: 'alice@example.com',
  privateKey: await loadKey('~/.kcp/keys/private.pem')
});

// Publish
const report = await client.publish({
  title: 'Q1 Customer Churn Analysis',
  content: htmlString,
  format: 'html',
  tags: ['churn', 'analytics'],
  team: 'data-science',
  visibility: 'team',
  lineage: {
    query: 'Predict customer churn',
    dataSources: ['postgres://analytics/customers'],
    agent: 'jupyter-agent-v1.2.3'
  }
});

// Search
const results = await client.search({
  query: 'customer retention',
  tags: ['analytics'],
  limit: 10
});
```

## Installation (Future)

```bash
npm install @kcp/client
```
