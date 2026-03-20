/**
 * KCP Data Models
 * Mirrors the Python SDK models.py
 */

import { v4 as uuidv4 } from 'uuid';

// ─── Lineage ─────────────────────────────────────────────────

export interface LineageData {
  query: string;
  dataSources?: string[];
  agent?: string;
  parentReports?: string[];
}

export class Lineage implements LineageData {
  query: string;
  dataSources: string[];
  agent: string;
  parentReports: string[];

  constructor(data: LineageData) {
    this.query = data.query;
    this.dataSources = data.dataSources ?? [];
    this.agent = data.agent ?? '';
    this.parentReports = data.parentReports ?? [];
  }

  toDict(): Record<string, unknown> {
    return {
      query: this.query,
      data_sources: this.dataSources,
      agent: this.agent,
      parent_reports: this.parentReports,
    };
  }

  static fromDict(data: Record<string, unknown>): Lineage {
    return new Lineage({
      query: (data['query'] as string) ?? '',
      dataSources: (data['data_sources'] as string[]) ?? [],
      agent: (data['agent'] as string) ?? '',
      parentReports: (data['parent_reports'] as string[]) ?? [],
    });
  }
}

// ─── ACL ─────────────────────────────────────────────────────

export interface ACLData {
  allowedTenants?: string[];
  allowedUsers?: string[];
  allowedTeams?: string[];
}

export class ACL implements ACLData {
  allowedTenants: string[];
  allowedUsers: string[];
  allowedTeams: string[];

  constructor(data: ACLData = {}) {
    this.allowedTenants = data.allowedTenants ?? [];
    this.allowedUsers = data.allowedUsers ?? [];
    this.allowedTeams = data.allowedTeams ?? [];
  }

  toDict(): Record<string, unknown> {
    return {
      allowed_tenants: this.allowedTenants,
      allowed_users: this.allowedUsers,
      allowed_teams: this.allowedTeams,
    };
  }

  static fromDict(data: Record<string, unknown>): ACL {
    return new ACL({
      allowedTenants: (data['allowed_tenants'] as string[]) ?? [],
      allowedUsers: (data['allowed_users'] as string[]) ?? [],
      allowedTeams: (data['allowed_teams'] as string[]) ?? [],
    });
  }
}

// ─── KnowledgeArtifact ───────────────────────────────────────

export interface KnowledgeArtifactOptions {
  title: string;
  userId: string;
  tenantId: string;
  format: string;
  visibility?: string;
  id?: string;
  version?: string;
  timestamp?: string;
  team?: string;
  tags?: string[];
  source?: string;
  summary?: string;
  lineage?: Lineage;
  contentUrl?: string;
  contentHash?: string;
  embeddings?: number[];
  signature?: string;
  acl?: ACL;
}

export class KnowledgeArtifact {
  id: string;
  version: string;
  title: string;
  userId: string;
  tenantId: string;
  format: string;
  visibility: string;
  timestamp: string;
  team?: string;
  tags: string[];
  source: string;
  summary: string;
  lineage?: Lineage;
  contentUrl: string;
  contentHash: string;
  embeddings: number[];
  signature: string;
  acl?: ACL;

  constructor(opts: KnowledgeArtifactOptions) {
    this.id = opts.id ?? uuidv4();
    this.version = opts.version ?? '1';
    this.title = opts.title;
    this.userId = opts.userId;
    this.tenantId = opts.tenantId;
    this.format = opts.format;
    this.visibility = opts.visibility ?? 'private';
    this.timestamp = opts.timestamp ?? new Date().toISOString();
    this.team = opts.team;
    this.tags = opts.tags ?? [];
    this.source = opts.source ?? '';
    this.summary = opts.summary ?? '';
    this.lineage = opts.lineage;
    this.contentUrl = opts.contentUrl ?? '';
    this.contentHash = opts.contentHash ?? '';
    this.embeddings = opts.embeddings ?? [];
    this.signature = opts.signature ?? '';
    this.acl = opts.acl;
  }

  /** Serialize to KCP wire format (snake_case for protocol interop) */
  toDict(): Record<string, unknown> {
    const d: Record<string, unknown> = {
      id: this.id,
      version: this.version,
      user_id: this.userId,
      tenant_id: this.tenantId,
      timestamp: this.timestamp,
      format: this.format,
      visibility: this.visibility,
      title: this.title,
      content_hash: this.contentHash,
      signature: this.signature,
    };
    if (this.team) d['team'] = this.team;
    if (this.tags.length) d['tags'] = this.tags;
    if (this.source) d['source'] = this.source;
    if (this.summary) d['summary'] = this.summary;
    if (this.lineage) d['lineage'] = this.lineage.toDict();
    if (this.contentUrl) d['content_url'] = this.contentUrl;
    if (this.embeddings.length) d['embeddings'] = this.embeddings;
    if (this.acl) d['acl'] = this.acl.toDict();
    return d;
  }

  /** Canonical JSON for signing — sorted keys, no signature field */
  toCanonicalJson(): string {
    const d = this.toDict();
    delete d['signature'];
    const sorted = Object.keys(d)
      .sort()
      .reduce((acc, k) => ({ ...acc, [k]: d[k] }), {} as Record<string, unknown>);
    return JSON.stringify(sorted);
  }

  static fromDict(data: Record<string, unknown>): KnowledgeArtifact {
    const lineageRaw = data['lineage'] as Record<string, unknown> | undefined;
    const aclRaw = data['acl'] as Record<string, unknown> | undefined;
    return new KnowledgeArtifact({
      id: (data['id'] as string) ?? uuidv4(),
      version: (data['version'] as string) ?? '1',
      title: data['title'] as string,
      userId: data['user_id'] as string,
      tenantId: data['tenant_id'] as string,
      format: data['format'] as string,
      visibility: (data['visibility'] as string) ?? 'private',
      timestamp: (data['timestamp'] as string) ?? new Date().toISOString(),
      team: data['team'] as string | undefined,
      tags: (data['tags'] as string[]) ?? [],
      source: (data['source'] as string) ?? '',
      summary: (data['summary'] as string) ?? '',
      lineage: lineageRaw ? Lineage.fromDict(lineageRaw) : undefined,
      contentUrl: (data['content_url'] as string) ?? '',
      contentHash: (data['content_hash'] as string) ?? '',
      embeddings: (data['embeddings'] as number[]) ?? [],
      signature: (data['signature'] as string) ?? '',
      acl: aclRaw ? ACL.fromDict(aclRaw) : undefined,
    });
  }
}

// ─── Search ──────────────────────────────────────────────────

export interface SearchResultData {
  id: string;
  title: string;
  summary: string;
  createdAt: string;
  relevance: number;
  format: string;
  preview?: string;
}

export class SearchResult {
  id: string;
  title: string;
  summary: string;
  createdAt: string;
  relevance: number;
  format: string;
  preview: string;

  constructor(data: SearchResultData) {
    this.id = data.id;
    this.title = data.title;
    this.summary = data.summary;
    this.createdAt = data.createdAt;
    this.relevance = data.relevance;
    this.format = data.format;
    this.preview = data.preview ?? '';
  }

  static fromDict(data: Record<string, unknown>): SearchResult {
    return new SearchResult({
      id: data['id'] as string,
      title: data['title'] as string,
      summary: (data['summary'] as string) ?? '',
      createdAt: data['created_at'] as string,
      relevance: (data['relevance'] as number) ?? 0,
      format: (data['format'] as string) ?? '',
      preview: (data['preview'] as string) ?? '',
    });
  }
}

export interface SearchResponseData {
  results: SearchResult[];
  total: number;
  queryTimeMs: number;
}

export class SearchResponse {
  results: SearchResult[];
  total: number;
  queryTimeMs: number;

  constructor(data: SearchResponseData) {
    this.results = data.results;
    this.total = data.total;
    this.queryTimeMs = data.queryTimeMs;
  }
}
