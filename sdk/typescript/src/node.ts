/**
 * KCP Embedded Node
 * Runs in-process — no separate server needed.
 * Mirrors Python SDK node.py
 *
 * Usage (embedded — no server):
 *   const node = new KCPNode({ userId: 'alice@acme.com' });
 *   const artifact = await node.publish({ title: 'My Analysis', content: '...', format: 'markdown' });
 *   const results = await node.search('analysis');
 */

import { mkdirSync, existsSync, readFileSync, writeFileSync } from 'fs';
import { resolve } from 'path';
import { homedir } from 'os';
import { v4 as uuidv4 } from 'uuid';
import { KnowledgeArtifact, Lineage, ACL, SearchResponse } from './models.js';
import { generateKeypair, signArtifact, verifyArtifact, hashContent, toHex, fromHex } from './crypto.js';
import { LocalStore } from './store.js';

// ─── Types ───────────────────────────────────────────────────

export interface KCPNodeOptions {
  userId?: string;
  tenantId?: string;
  dbPath?: string;
  keysDir?: string;
}

export interface PublishOptions {
  title: string;
  content: Buffer | string;
  format?: string;
  tags?: string[];
  summary?: string;
  visibility?: string;
  derivedFrom?: string;
  source?: string;
  lineage?: Lineage;
}

// ─── KCPNode ─────────────────────────────────────────────────

export class KCPNode {
  readonly userId: string;
  readonly tenantId: string;
  readonly store: LocalStore;
  readonly privateKey: Uint8Array;
  readonly publicKey: Uint8Array;

  private readonly _keysDir: string;

  constructor(opts: KCPNodeOptions = {}) {
    this.userId = opts.userId ?? 'anonymous';
    this.tenantId = opts.tenantId ?? 'local';

    const dbPath = opts.dbPath ?? '~/.kcp/kcp.db';
    this._keysDir = opts.keysDir
      ? resolve(opts.keysDir)
      : resolve(homedir(), '.kcp', 'keys');

    mkdirSync(this._keysDir, { recursive: true });

    this.store = new LocalStore(dbPath);

    const keys = this._loadOrGenerateKeys();
    this.privateKey = keys.privateKey;
    this.publicKey = keys.publicKey;

    // Persist identity
    this.store.setConfig('user_id', this.userId);
    this.store.setConfig('tenant_id', this.tenantId);
    this.store.setConfig('public_key', toHex(this.publicKey));
    this.store.setConfig('node_id', this._getOrCreateNodeId());
  }

  get nodeId(): string {
    return this.store.getConfig('node_id') ?? '';
  }

  // ─── Core Operations ───────────────────────────────────────

  publish(opts: PublishOptions): KnowledgeArtifact {
    const rawContent =
      typeof opts.content === 'string'
        ? Buffer.from(opts.content, 'utf8')
        : opts.content;

    const artifact = new KnowledgeArtifact({
      title: opts.title,
      userId: this.userId,
      tenantId: this.tenantId,
      format: opts.format ?? 'markdown',
      visibility: opts.visibility ?? 'public',
      tags: opts.tags ?? [],
      summary: opts.summary ?? '',
      source: opts.source ?? '',
      lineage: opts.lineage,
      contentHash: hashContent(rawContent),
    });

    // Sign
    artifact.signature = signArtifact(artifact.toDict(), this.privateKey);

    // Persist
    this.store.publish(artifact, rawContent, opts.derivedFrom);

    return artifact;
  }

  get(artifactId: string): KnowledgeArtifact | undefined {
    return this.store.get(artifactId);
  }

  getContent(artifactId: string): Buffer | undefined {
    const artifact = this.store.get(artifactId);
    if (!artifact) return undefined;
    return this.store.getContent(artifact.contentHash);
  }

  search(query: string, limit = 20): SearchResponse {
    return this.store.search(query, limit);
  }

  list(limit = 50, tags?: string[]): KnowledgeArtifact[] {
    return this.store.list(limit, tags);
  }

  delete(artifactId: string): boolean {
    return this.store.delete(artifactId, this.userId);
  }

  verify(artifact: KnowledgeArtifact, publicKey?: Uint8Array): boolean {
    return verifyArtifact(artifact.toDict(), publicKey ?? this.publicKey);
  }

  lineage(artifactId: string): Record<string, unknown>[] {
    return this.store.getLineage(artifactId);
  }

  derivatives(artifactId: string): Record<string, unknown>[] {
    return this.store.getDerivatives(artifactId);
  }

  stats(): Record<string, unknown> {
    const s = this.store.stats();
    return {
      ...s,
      node_id: this.nodeId,
      user_id: this.userId,
      tenant_id: this.tenantId,
    };
  }

  addPeer(url: string, name = ''): string {
    const peerId = uuidv4();
    this.store.addPeer(peerId, url, name);
    return peerId;
  }

  getPeers(): Record<string, unknown>[] {
    return this.store.getPeers();
  }

  close(): void {
    this.store.close();
  }

  // ─── Private helpers ───────────────────────────────────────

  private _loadOrGenerateKeys(): { privateKey: Uint8Array; publicKey: Uint8Array } {
    const privPath = resolve(this._keysDir, 'private.hex');
    const pubPath = resolve(this._keysDir, 'public.hex');

    if (existsSync(privPath) && existsSync(pubPath)) {
      const privateKey = fromHex(readFileSync(privPath, 'utf8').trim());
      const publicKey = fromHex(readFileSync(pubPath, 'utf8').trim());
      return { privateKey, publicKey };
    }

    const { privateKey, publicKey } = generateKeypair();
    writeFileSync(privPath, toHex(privateKey), { mode: 0o600 });
    writeFileSync(pubPath, toHex(publicKey));
    return { privateKey, publicKey };
  }

  private _getOrCreateNodeId(): string {
    const existing = this.store.getConfig('node_id');
    if (existing) return existing;
    const nodeId = uuidv4();
    this.store.setConfig('node_id', nodeId);
    return nodeId;
  }
}
