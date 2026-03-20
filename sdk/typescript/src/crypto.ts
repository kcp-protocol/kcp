/**
 * KCP Cryptographic Operations
 * Ed25519 signing/verification + SHA-256 hashing
 * Uses @noble/ed25519 (pure JS, no native deps) + Node.js built-in crypto
 */

import { createHash, randomBytes } from 'crypto';
import * as ed from '@noble/ed25519';
import { sha512 } from '@noble/hashes/sha512';

// noble/ed25519 v2 requires sha512 sync implementation
ed.etc.sha512Sync = (...m) => sha512(ed.etc.concatBytes(...m));

// ─── Types ───────────────────────────────────────────────────

export interface KeyPair {
  privateKey: Uint8Array; // 32 bytes
  publicKey: Uint8Array;  // 32 bytes
}

// ─── Key Generation ──────────────────────────────────────────

/**
 * Generate an Ed25519 keypair.
 * Returns 32-byte private key and 32-byte public key.
 */
export function generateKeypair(): KeyPair {
  const privateKey = ed.utils.randomPrivateKey();
  const publicKey = ed.getPublicKey(privateKey);
  return { privateKey, publicKey };
}

/**
 * Derive public key from private key.
 */
export function getPublicKey(privateKey: Uint8Array): Uint8Array {
  return ed.getPublicKey(privateKey);
}

// ─── Hashing ─────────────────────────────────────────────────

/**
 * Compute SHA-256 hash of content.
 * Returns lowercase hex string (64 chars).
 */
export function hashContent(content: Uint8Array | string): string {
  const data = typeof content === 'string' ? Buffer.from(content, 'utf8') : content;
  return createHash('sha256').update(data).digest('hex');
}

// ─── Signing ─────────────────────────────────────────────────

/**
 * Sign a KCP artifact payload using Ed25519.
 *
 * Produces canonical JSON (sorted keys, compact) of the payload
 * without the signature field, then signs it.
 *
 * Returns hex-encoded 64-byte signature (128 hex chars).
 */
export function signArtifact(
  artifactDict: Record<string, unknown>,
  privateKey: Uint8Array,
): string {
  const payload = { ...artifactDict };
  delete payload['signature'];

  // Canonical JSON: sorted keys, compact
  const canonical = canonicalJson(payload);
  const message = Buffer.from(canonical, 'utf8');

  const signature = ed.sign(message, privateKey);
  return Buffer.from(signature).toString('hex');
}

/**
 * Verify the Ed25519 signature of a KCP artifact.
 * Returns true if the signature is valid.
 */
export function verifyArtifact(
  artifactDict: Record<string, unknown>,
  publicKey: Uint8Array,
): boolean {
  const signatureHex = artifactDict['signature'] as string | undefined;
  if (!signatureHex || signatureHex.length !== 128) return false;

  const payload = { ...artifactDict };
  delete payload['signature'];

  try {
    const canonical = canonicalJson(payload);
    const message = Buffer.from(canonical, 'utf8');
    const signature = Buffer.from(signatureHex, 'hex');
    return ed.verify(signature, message, publicKey);
  } catch {
    return false;
  }
}

// ─── Helpers ─────────────────────────────────────────────────

/**
 * Produce canonical JSON: sorted keys, compact separators.
 * Mirrors Python's json.dumps(sort_keys=True, separators=(',', ':'))
 */
export function canonicalJson(obj: Record<string, unknown>): string {
  return JSON.stringify(sortObjectKeys(obj));
}

function sortObjectKeys(obj: unknown): unknown {
  if (Array.isArray(obj)) return obj.map(sortObjectKeys);
  if (obj !== null && typeof obj === 'object') {
    return Object.keys(obj as Record<string, unknown>)
      .sort()
      .reduce(
        (acc, k) => ({
          ...acc,
          [k]: sortObjectKeys((obj as Record<string, unknown>)[k]),
        }),
        {} as Record<string, unknown>,
      );
  }
  return obj;
}

/**
 * Hex-encode a Uint8Array.
 */
export function toHex(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString('hex');
}

/**
 * Decode a hex string to Uint8Array.
 */
export function fromHex(hex: string): Uint8Array {
  return new Uint8Array(Buffer.from(hex, 'hex'));
}
