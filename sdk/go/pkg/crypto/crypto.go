// Package crypto provides Ed25519 signing and SHA-256 hashing for KCP.
package crypto

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

// GenerateKeypair generates a new Ed25519 keypair.
// Returns (privateKey, publicKey).
func GenerateKeypair() (ed25519.PrivateKey, ed25519.PublicKey, error) {
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return nil, nil, fmt.Errorf("keygen failed: %w", err)
	}
	return priv, pub, nil
}

// Sign signs canonical JSON bytes with an Ed25519 private key.
// Returns hex-encoded signature.
func Sign(data []byte, privateKey ed25519.PrivateKey) string {
	sig := ed25519.Sign(privateKey, data)
	return hex.EncodeToString(sig)
}

// Verify checks an Ed25519 signature against canonical JSON bytes.
func Verify(data []byte, signatureHex string, publicKey ed25519.PublicKey) bool {
	sig, err := hex.DecodeString(signatureHex)
	if err != nil {
		return false
	}
	return ed25519.Verify(publicKey, data, sig)
}

// HashContent computes SHA-256 of content bytes, returns hex string.
func HashContent(content []byte) string {
	h := sha256.Sum256(content)
	return hex.EncodeToString(h[:])
}

// SaveKeys saves a keypair to disk.
func SaveKeys(dir string, priv ed25519.PrivateKey, pub ed25519.PublicKey) error {
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}

	privPath := filepath.Join(dir, "private.key")
	pubPath := filepath.Join(dir, "public.key")

	if err := os.WriteFile(privPath, priv.Seed(), 0600); err != nil {
		return fmt.Errorf("write private key: %w", err)
	}
	if err := os.WriteFile(pubPath, pub, 0644); err != nil {
		return fmt.Errorf("write public key: %w", err)
	}

	return nil
}

// LoadKeys loads a keypair from disk.
func LoadKeys(dir string) (ed25519.PrivateKey, ed25519.PublicKey, error) {
	privPath := filepath.Join(dir, "private.key")
	pubPath := filepath.Join(dir, "public.key")

	seed, err := os.ReadFile(privPath)
	if err != nil {
		return nil, nil, fmt.Errorf("read private key: %w", err)
	}

	pubBytes, err := os.ReadFile(pubPath)
	if err != nil {
		return nil, nil, fmt.Errorf("read public key: %w", err)
	}

	if len(seed) != ed25519.SeedSize {
		return nil, nil, errors.New("invalid private key size")
	}
	if len(pubBytes) != ed25519.PublicKeySize {
		return nil, nil, errors.New("invalid public key size")
	}

	priv := ed25519.NewKeyFromSeed(seed)
	pub := ed25519.PublicKey(pubBytes)

	return priv, pub, nil
}

// LoadOrGenerateKeys loads existing keys or generates new ones.
func LoadOrGenerateKeys(dir string) (ed25519.PrivateKey, ed25519.PublicKey, error) {
	priv, pub, err := LoadKeys(dir)
	if err == nil {
		return priv, pub, nil
	}

	priv, pub, err = GenerateKeypair()
	if err != nil {
		return nil, nil, err
	}

	if err := SaveKeys(dir, priv, pub); err != nil {
		return nil, nil, err
	}

	return priv, pub, nil
}
