/**
 * KCP TypeScript SDK
 * Knowledge Context Protocol — Layer 8
 *
 * @version 0.1.0
 */

export const KCP_VERSION = '0.1.0';
export const KCP_PROTOCOL_VERSION = '1';

// Core
export { KCPNode } from './node.js';
export type { KCPNodeOptions, PublishOptions } from './node.js';

// Storage
export { LocalStore } from './store.js';

// Models
export {
  KnowledgeArtifact,
  Lineage,
  ACL,
  SearchResult,
  SearchResponse,
} from './models.js';
export type {
  KnowledgeArtifactOptions,
  LineageData,
  ACLData,
  SearchResultData,
  SearchResponseData,
} from './models.js';

// Crypto
export {
  generateKeypair,
  getPublicKey,
  hashContent,
  signArtifact,
  verifyArtifact,
  canonicalJson,
  toHex,
  fromHex,
} from './crypto.js';
export type { KeyPair } from './crypto.js';
