/**
 * KCP Local Storage Backend
 * JSON file-based storage for Knowledge Artifacts
 * Zero native dependencies — works in Node.js and browser
 * Mirrors Python SDK store.py interface
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs';
import { dirname, resolve } from 'path';
import { homedir } from 'os';
import { KnowledgeArtifact, SearchResult, SearchResponse } from './models.js';

// ─── Internal Types ──────────────────────────────────────────

interface StoreData {
  artifacts: Record<string, Record<string, unknown>>;
  content: Record<string, string>;
  lineage: Array<{ artifactId: string; derivedFrom: string; createdAt: string }>;
  peers: Record<string, { id: string; url: string; name: string; addedAt: string }>;
  config: Record<string, string>;
}

// ─── LocalStore ──────────────────────────────────────────────

export class LocalStore {
  private readonly _path: string;
  private _data: StoreData;

  constructor(dbPath: string = '~/.kcp/kcp.json') {
    const jsonPath = dbPath.replace(/\.db$/, '.json');
    this._path = jsonPath.startsWith('~')
      ? resolve(homedir(), jsonPath.slice(2))
      : resolve(jsonPath);
    mkdirSync(dirname(this._path), { recursive: true });
    this._data = this._load();
  }

  setConfig(key: string, value: string): void {
    this._data.config[key] = value;
    this._save();
  }

  getConfig(key: string): string | undefined {
    return this._data.config[key];
  }

  publish(artifact: KnowledgeArtifact, content: Buffer, derivedFrom?: string): void {
    this._data.artifacts[artifact.id] = {
      ...artifact.toDict(),
      created_at: artifact.timestamp,
      deleted_at: null,
    };
    this._data.content[artifact.contentHash] = content.toString('base64');
    if (derivedFrom) {
      this._data.lineage.push({ artifactId: artifact.id, derivedFrom, createdAt: artifact.timestamp });
    }
    this._save();
  }

  get(artifactId: string): KnowledgeArtifact | undefined {
    const row = this._data.artifacts[artifactId];
    if (!row || row['deleted_at']) return undefined;
    return this._rowToArtifact(row);
  }

  getContent(contentHash: string): Buffer | undefined {
    const b64 = this._data.content[contentHash];
    if (!b64) return undefined;
    return Buffer.from(b64, 'base64');
  }

  search(query: string, limit = 20, tenantId?: string): SearchResponse {
    const start = Date.now();
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    let rows = Object.values(this._data.artifacts).filter((r) => !r['deleted_at']);
    if (tenantId) rows = rows.filter((r) => r['tenant_id'] === tenantId);
    if (terms.length > 0) {
      rows = rows.filter((r) => {
        const text = `${r['title'] ?? ''} ${r['summary'] ?? ''} ${Array.isArray(r['tags']) ? (r['tags'] as string[]).join(' ') : ''}`.toLowerCase();
        return terms.every((t) => text.includes(t));
      });
    }
    rows.sort((a, b) => String(b['created_at'] ?? '').localeCompare(String(a['created_at'] ?? '')));
    rows = rows.slice(0, limit);
    const results = rows.map((r) => new SearchResult({
      id: r['id'] as string,
      title: r['title'] as string,
      summary: (r['summary'] as string) ?? '',
      createdAt: (r['created_at'] as string) ?? '',
      relevance: terms.length === 0 ? 1.0 : this._score(r, terms),
      format: r['format'] as string,
      preview: ((r['summary'] as string) ?? '').slice(0, 120),
    }));
    return new SearchResponse({ results, total: results.length, queryTimeMs: Date.now() - start });
  }

  list(limit = 50, tags?: string[]): KnowledgeArtifact[] {
    let rows = Object.values(this._data.artifacts).filter((r) => !r['deleted_at']);
    if (tags && tags.length) {
      rows = rows.filter((r) => {
        const t = Array.isArray(r['tags']) ? (r['tags'] as string[]) : [];
        return tags.some((tag) => t.map((x) => x.toLowerCase()).includes(tag.toLowerCase()));
      });
    }
    rows.sort((a, b) => String(b['created_at'] ?? '').localeCompare(String(a['created_at'] ?? '')));
    return rows.slice(0, limit).map((r) => this._rowToArtifact(r));
  }

  delete(artifactId: string, userId: string): boolean {
    const row = this._data.artifacts[artifactId];
    if (!row || row['user_id'] !== userId) return false;
    row['deleted_at'] = new Date().toISOString();
    this._save();
    return true;
  }

  getLineage(artifactId: string): Record<string, unknown>[] {
    const chain: Record<string, unknown>[] = [];
    let currentId: string | undefined = artifactId;
    while (currentId) {
      const row = this._data.artifacts[currentId];
      if (!row || row['deleted_at']) break;
      chain.unshift({ id: row['id'], title: row['title'], created_at: row['created_at'] });
      const parentEntry = this._data.lineage.find((l) => l.artifactId === currentId);
      currentId = parentEntry?.derivedFrom;
    }
    return chain;
  }

  getDerivatives(artifactId: string): Record<string, unknown>[] {
    return this._data.lineage
      .filter((l) => l.derivedFrom === artifactId)
      .map((l) => {
        const row = this._data.artifacts[l.artifactId];
        return row ? { id: row['id'], title: row['title'], created_at: row['created_at'] } : null;
      })
      .filter(Boolean) as Record<string, unknown>[];
  }

  stats(): Record<string, unknown> {
    const total = Object.values(this._data.artifacts).filter((r) => !r['deleted_at']).length;
    const storageBytes = Object.values(this._data.content).reduce((acc, b64) => acc + Math.floor((b64.length * 3) / 4), 0);
    return { total_artifacts: total, storage_bytes: storageBytes };
  }

  addPeer(id: string, url: string, name = ''): void {
    this._data.peers[id] = { id, url, name, addedAt: new Date().toISOString() };
    this._save();
  }

  getPeers(): Record<string, unknown>[] {
    return Object.values(this._data.peers);
  }

  close(): void { this._save(); }

  private _load(): StoreData {
    if (existsSync(this._path)) {
      try { return JSON.parse(readFileSync(this._path, 'utf8')) as StoreData; } catch { /* start fresh */ }
    }
    return { artifacts: {}, content: {}, lineage: [], peers: {}, config: {} };
  }

  private _save(): void {
    writeFileSync(this._path, JSON.stringify(this._data, null, 2), 'utf8');
  }

  private _rowToArtifact(row: Record<string, unknown>): KnowledgeArtifact {
    return KnowledgeArtifact.fromDict({ ...row, timestamp: row['created_at'] ?? row['timestamp'] });
  }

  private _score(row: Record<string, unknown>, terms: string[]): number {
    const text = `${row['title'] ?? ''} ${row['summary'] ?? ''} ${Array.isArray(row['tags']) ? (row['tags'] as string[]).join(' ') : ''}`.toLowerCase();
    const hits = terms.filter((t) => text.includes(t)).length;
    return hits / terms.length;
  }
}
