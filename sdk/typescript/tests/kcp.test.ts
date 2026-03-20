/**
 * KCP TypeScript SDK — Test Suite
 * Covers: models, crypto, store, node
 */

import { describe, it, expect, beforeEach, afterEach } from '@jest/globals';
import { mkdtempSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

import {
  KnowledgeArtifact, Lineage, ACL, SearchResult, SearchResponse,
  generateKeypair, hashContent, signArtifact, verifyArtifact, toHex, fromHex,
  LocalStore, KCPNode,
} from '../src/index.js';

// ─── Helpers ─────────────────────────────────────────────────

function tmpNode(): { node: KCPNode; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), 'kcp_test_'));
  const node = new KCPNode({
    userId: 'test@example.com',
    tenantId: 'test-corp',
    dbPath: join(dir, 'kcp.db'),
    keysDir: join(dir, 'keys'),
  });
  return { node, dir };
}

// ─── Models ──────────────────────────────────────────────────

describe('Lineage', () => {
  it('creates with minimal args', () => {
    const l = new Lineage({ query: 'test query' });
    expect(l.query).toBe('test query');
    expect(l.dataSources).toEqual([]);
    expect(l.agent).toBe('');
  });

  it('serializes to dict with snake_case keys', () => {
    const l = new Lineage({ query: 'q', dataSources: ['db://x'], agent: 'bot' });
    const d = l.toDict();
    expect(d['data_sources']).toEqual(['db://x']);
    expect(d['agent']).toBe('bot');
  });

  it('deserializes from dict', () => {
    const d = { query: 'q', data_sources: ['src'], agent: 'a', parent_reports: [] };
    const l = Lineage.fromDict(d);
    expect(l.dataSources).toEqual(['src']);
  });
});

describe('ACL', () => {
  it('creates empty ACL', () => {
    const acl = new ACL();
    expect(acl.allowedTenants).toEqual([]);
    expect(acl.allowedUsers).toEqual([]);
  });

  it('serializes correctly', () => {
    const acl = new ACL({ allowedUsers: ['alice@x.com'] });
    const d = acl.toDict();
    expect(d['allowed_users']).toContain('alice@x.com');
  });
});

describe('KnowledgeArtifact', () => {
  it('generates unique IDs', () => {
    const a1 = new KnowledgeArtifact({ title: 'T1', userId: 'u', tenantId: 't', format: 'text' });
    const a2 = new KnowledgeArtifact({ title: 'T2', userId: 'u', tenantId: 't', format: 'text' });
    expect(a1.id).not.toBe(a2.id);
  });

  it('toDict includes required fields', () => {
    const a = new KnowledgeArtifact({ title: 'T', userId: 'u', tenantId: 't', format: 'html' });
    const d = a.toDict();
    for (const key of ['id', 'version', 'user_id', 'tenant_id', 'timestamp', 'format', 'visibility', 'title']) {
      expect(d).toHaveProperty(key);
    }
  });

  it('toDict omits empty optional fields', () => {
    const a = new KnowledgeArtifact({ title: 'T', userId: 'u', tenantId: 't', format: 'text' });
    const d = a.toDict();
    expect(d).not.toHaveProperty('team');
    expect(d).not.toHaveProperty('tags');
    expect(d).not.toHaveProperty('lineage');
  });

  it('toCanonicalJson excludes signature and sorts keys', () => {
    const a = new KnowledgeArtifact({ title: 'T', userId: 'u', tenantId: 't', format: 'text', signature: 'sig' });
    const parsed = JSON.parse(a.toCanonicalJson());
    expect(parsed).not.toHaveProperty('signature');
    const keys = Object.keys(parsed);
    expect(keys).toEqual([...keys].sort());
  });

  it('roundtrip fromDict', () => {
    const a = new KnowledgeArtifact({ title: 'Roundtrip', userId: 'bob', tenantId: 'corp', format: 'json', tags: ['x'] });
    const b = KnowledgeArtifact.fromDict(a.toDict());
    expect(b.id).toBe(a.id);
    expect(b.title).toBe(a.title);
    expect(b.tags).toEqual(a.tags);
  });
});

// ─── Crypto ──────────────────────────────────────────────────

describe('generateKeypair', () => {
  it('returns 32-byte keys', () => {
    const { privateKey, publicKey } = generateKeypair();
    expect(privateKey.length).toBe(32);
    expect(publicKey.length).toBe(32);
  });

  it('generates unique keys each call', () => {
    const a = generateKeypair();
    const b = generateKeypair();
    expect(toHex(a.privateKey)).not.toBe(toHex(b.privateKey));
  });
});

describe('hashContent', () => {
  it('returns 64-char hex string', () => {
    const h = hashContent('hello');
    expect(h).toHaveLength(64);
  });

  it('is deterministic', () => {
    expect(hashContent('test')).toBe(hashContent('test'));
  });

  it('known SHA-256 of empty string', () => {
    expect(hashContent('')).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
  });
});

describe('signArtifact / verifyArtifact', () => {
  it('sign produces 128-char hex', () => {
    const { privateKey } = generateKeypair();
    const sig = signArtifact({ title: 'T', user_id: 'u' }, privateKey);
    expect(sig).toHaveLength(128);
  });

  it('valid signature verifies', () => {
    const { privateKey, publicKey } = generateKeypair();
    const payload = { title: 'T', user_id: 'u', tenant_id: 't' };
    const sig = signArtifact(payload, privateKey);
    expect(verifyArtifact({ ...payload, signature: sig }, publicKey)).toBe(true);
  });

  it('wrong public key fails', () => {
    const { privateKey } = generateKeypair();
    const { publicKey: wrongPub } = generateKeypair();
    const payload = { title: 'T', user_id: 'u' };
    const sig = signArtifact(payload, privateKey);
    expect(verifyArtifact({ ...payload, signature: sig }, wrongPub)).toBe(false);
  });

  it('tampered payload fails', () => {
    const { privateKey, publicKey } = generateKeypair();
    const payload = { title: 'Original', user_id: 'u' };
    const sig = signArtifact(payload, privateKey);
    expect(verifyArtifact({ title: 'Tampered', user_id: 'u', signature: sig }, publicKey)).toBe(false);
  });

  it('missing signature returns false', () => {
    const { publicKey } = generateKeypair();
    expect(verifyArtifact({ title: 'T' }, publicKey)).toBe(false);
  });
});

// ─── KCPNode ─────────────────────────────────────────────────

describe('KCPNode — init', () => {
  let node: KCPNode; let dir: string;
  beforeEach(() => { ({ node, dir } = tmpNode()); });
  afterEach(() => { node.close(); rmSync(dir, { recursive: true, force: true }); });

  it('creates with user and tenant', () => {
    expect(node.userId).toBe('test@example.com');
    expect(node.tenantId).toBe('test-corp');
  });

  it('has a node ID', () => {
    expect(node.nodeId.length).toBeGreaterThan(0);
  });

  it('has 32-byte keys', () => {
    expect(node.privateKey.length).toBe(32);
    expect(node.publicKey.length).toBe(32);
  });
});

describe('KCPNode — publish', () => {
  let node: KCPNode; let dir: string;
  beforeEach(() => { ({ node, dir } = tmpNode()); });
  afterEach(() => { node.close(); rmSync(dir, { recursive: true, force: true }); });

  it('publishes and returns signed artifact', () => {
    const a = node.publish({ title: 'Test', content: 'hello', format: 'text' });
    expect(a.title).toBe('Test');
    expect(a.signature.length).toBe(128);
    expect(a.contentHash.length).toBe(64);
  });

  it('get retrieves published artifact', () => {
    const a = node.publish({ title: 'Retrieve', content: 'data', format: 'text' });
    const b = node.get(a.id);
    expect(b?.title).toBe('Retrieve');
  });

  it('get returns undefined for unknown id', () => {
    expect(node.get('nonexistent')).toBeUndefined();
  });

  it('getContent returns original bytes', () => {
    const content = 'hello kcp';
    const a = node.publish({ title: 'Content', content, format: 'text' });
    const retrieved = node.getContent(a.id);
    expect(retrieved?.toString('utf8')).toBe(content);
  });

  it('publishes with tags and summary', () => {
    const a = node.publish({ title: 'Tagged', content: 'c', format: 'text', tags: ['ml'], summary: 'Brief' });
    expect(a.tags).toEqual(['ml']);
    expect(a.summary).toBe('Brief');
  });

  it('supports derived_from lineage', () => {
    const parent = node.publish({ title: 'Parent', content: 'p', format: 'text' });
    const child = node.publish({ title: 'Child', content: 'c', format: 'text', derivedFrom: parent.id });
    expect(child.id).not.toBe(parent.id);
  });
});

describe('KCPNode — search', () => {
  let node: KCPNode; let dir: string;
  beforeEach(() => {
    ({ node, dir } = tmpNode());
    node.publish({ title: 'Rate Limiting Guide', content: 'token bucket', format: 'markdown', summary: 'Rate limiting patterns' });
    node.publish({ title: 'Auth Best Practices', content: 'JWT OAuth2', format: 'markdown', summary: 'Authentication guide' });
  });
  afterEach(() => { node.close(); rmSync(dir, { recursive: true, force: true }); });

  it('finds relevant results', () => {
    const r = node.search('rate limiting');
    expect(r.total).toBeGreaterThan(0);
    expect(r.results[0].title).toContain('Rate Limiting');
  });

  it('returns empty for no match', () => {
    const r = node.search('xyznonexistent99999');
    expect(r.total).toBe(0);
  });
});

describe('KCPNode — verify', () => {
  let node: KCPNode; let dir: string;
  beforeEach(() => { ({ node, dir } = tmpNode()); });
  afterEach(() => { node.close(); rmSync(dir, { recursive: true, force: true }); });

  it('verifies own artifact', () => {
    const a = node.publish({ title: 'Verify', content: 'data', format: 'text' });
    expect(node.verify(a)).toBe(true);
  });

  it('detects tampered title', () => {
    const a = node.publish({ title: 'Original', content: 'data', format: 'text' });
    a.title = 'Tampered';
    expect(node.verify(a)).toBe(false);
  });
});

describe('KCPNode — lineage', () => {
  let node: KCPNode; let dir: string;
  beforeEach(() => { ({ node, dir } = tmpNode()); });
  afterEach(() => { node.close(); rmSync(dir, { recursive: true, force: true }); });

  it('builds lineage chain', () => {
    const root = node.publish({ title: 'Root', content: 'r', format: 'text' });
    const child = node.publish({ title: 'Child', content: 'c', format: 'text', derivedFrom: root.id });
    const chain = node.lineage(child.id);
    expect(chain.length).toBe(2);
    expect(chain[0]['title']).toBe('Root');
    expect(chain[1]['title']).toBe('Child');
  });

  it('returns derivatives', () => {
    const parent = node.publish({ title: 'Parent', content: 'p', format: 'text' });
    node.publish({ title: 'C1', content: 'c1', format: 'text', derivedFrom: parent.id });
    node.publish({ title: 'C2', content: 'c2', format: 'text', derivedFrom: parent.id });
    expect(node.derivatives(parent.id).length).toBe(2);
  });
});

describe('KCPNode — stats', () => {
  let node: KCPNode; let dir: string;
  beforeEach(() => { ({ node, dir } = tmpNode()); });
  afterEach(() => { node.close(); rmSync(dir, { recursive: true, force: true }); });

  it('returns expected keys', () => {
    const s = node.stats();
    expect(s).toHaveProperty('node_id');
    expect(s).toHaveProperty('user_id');
    expect(s).toHaveProperty('tenant_id');
    expect(s).toHaveProperty('total_artifacts');
  });

  it('counts published artifacts', () => {
    node.publish({ title: 'A', content: 'a', format: 'text' });
    node.publish({ title: 'B', content: 'b', format: 'text' });
    expect(node.stats()['total_artifacts']).toBe(2);
  });
});
