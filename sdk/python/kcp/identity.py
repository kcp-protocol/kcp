"""
KCP Identity Management

Mnemonic-based key derivation for user-friendly backup and recovery.
Uses BIP-39 compatible word list with PBKDF2 derivation for Ed25519 keys.

Security Model:
  - 12 words = 128 bits entropy (sufficient for personal use)
  - 24 words = 256 bits entropy (recommended for high-security)
  - Passphrase optional (adds extra protection)
  - Keys derived via PBKDF2-SHA512 → Ed25519 seed

User Experience:
  - Natural language recovery phrases in Portuguese or English
  - Guided wizard with friendly prompts
  - Clear warnings about backup importance
"""

from __future__ import annotations

import os
import hashlib
import secrets
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass
from enum import Enum


# ═══════════════════════════════════════════════════════════════════════════════
# BIP-39 Word Lists (English + Portuguese)
# ═══════════════════════════════════════════════════════════════════════════════

# English BIP-39 word list (2048 words) - abbreviated for space, full list loaded from file
# In production, this would be the complete 2048-word list
BIP39_WORDLIST_EN = None  # Loaded lazily
BIP39_WORDLIST_PT = None  # Loaded lazily


def _load_wordlist(lang: str = "en") -> List[str]:
    """Load BIP-39 wordlist for given language."""
    global BIP39_WORDLIST_EN, BIP39_WORDLIST_PT
    
    if lang == "en" and BIP39_WORDLIST_EN:
        return BIP39_WORDLIST_EN
    if lang == "pt" and BIP39_WORDLIST_PT:
        return BIP39_WORDLIST_PT
    
    # Try to load from file
    wordlist_path = Path(__file__).parent / "wordlists" / f"bip39_{lang}.txt"
    if wordlist_path.exists():
        words = wordlist_path.read_text().strip().split("\n")
        if lang == "en":
            BIP39_WORDLIST_EN = words
        else:
            BIP39_WORDLIST_PT = words
        return words
    
    # Fallback: use mnemonic library if available
    try:
        from mnemonic import Mnemonic
        m = Mnemonic(lang if lang != "pt" else "portuguese")
        words = m.wordlist
        if lang == "en":
            BIP39_WORDLIST_EN = words
        else:
            BIP39_WORDLIST_PT = words
        return words
    except ImportError:
        pass
    
    # Last resort: generate from common English words (NOT BIP-39 compliant, for dev only)
    raise ImportError(
        "KCP identity requires 'mnemonic' package for secure key recovery. "
        "Install with: pip install mnemonic"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Identity Data Structures
# ═══════════════════════════════════════════════════════════════════════════════

class IdentityStrength(Enum):
    """Security level for identity generation."""
    STANDARD = 12  # 128 bits - good for personal use
    HIGH = 24      # 256 bits - recommended for organizations


@dataclass
class KCPIdentity:
    """
    A KCP cryptographic identity.
    
    Contains the recovery phrase and derived keys.
    The recovery phrase is the ONLY thing the user needs to backup.
    """
    mnemonic: str                    # Space-separated recovery words
    private_key: bytes               # Ed25519 private key (32 bytes)
    public_key: bytes                # Ed25519 public key (32 bytes)
    node_id: str                     # Hex-encoded public key prefix
    language: str = "en"             # Wordlist language
    passphrase_protected: bool = False
    
    @property
    def fingerprint(self) -> str:
        """Short fingerprint for display (first 8 chars of node_id)."""
        return self.node_id[:8]
    
    @property
    def word_count(self) -> int:
        """Number of words in recovery phrase."""
        return len(self.mnemonic.split())
    
    def to_recovery_card(self) -> str:
        """Generate a printable recovery card."""
        words = self.mnemonic.split()
        lines = [
            "╔══════════════════════════════════════════════════════════════╗",
            "║           🔐 KCP IDENTITY RECOVERY CARD                      ║",
            "╠══════════════════════════════════════════════════════════════╣",
            "║                                                              ║",
            "║  ⚠️  GUARDE ESTE CARTÃO EM LOCAL SEGURO!                     ║",
            "║  Qualquer pessoa com estas palavras pode acessar sua         ║",
            "║  identidade KCP e todos os seus artefatos.                   ║",
            "║                                                              ║",
            "╠══════════════════════════════════════════════════════════════╣",
        ]
        
        # Add words in 3 columns
        for i in range(0, len(words), 3):
            row_words = words[i:i+3]
            cols = [f"{i+j+1:2}. {w:<12}" for j, w in enumerate(row_words)]
            line = "║  " + "  ".join(cols).ljust(60) + "║"
            lines.append(line)
        
        lines.extend([
            "║                                                              ║",
            "╠══════════════════════════════════════════════════════════════╣",
            f"║  Node ID: {self.node_id:<50}  ║",
            f"║  Fingerprint: {self.fingerprint:<46}  ║",
            "║                                                              ║",
            "║  Para recuperar: kcp identity recover                        ║",
            "╚══════════════════════════════════════════════════════════════╝",
        ])
        
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Key Generation and Derivation
# ═══════════════════════════════════════════════════════════════════════════════

def generate_mnemonic(
    strength: IdentityStrength = IdentityStrength.STANDARD,
    language: str = "en"
) -> str:
    """
    Generate a new BIP-39 mnemonic phrase.
    
    Args:
        strength: STANDARD (12 words) or HIGH (24 words)
        language: "en" for English, "pt" for Portuguese
    
    Returns:
        Space-separated mnemonic phrase
    """
    try:
        from mnemonic import Mnemonic
        lang_map = {"en": "english", "pt": "portuguese"}
        m = Mnemonic(lang_map.get(language, "english"))
        
        # 128 bits = 12 words, 256 bits = 24 words
        entropy_bits = 128 if strength == IdentityStrength.STANDARD else 256
        return m.generate(entropy_bits)
    except ImportError:
        raise ImportError(
            "KCP identity requires 'mnemonic' package. "
            "Install with: pip install mnemonic"
        )


def mnemonic_to_seed(mnemonic: str, passphrase: str = "") -> bytes:
    """
    Derive a 64-byte seed from mnemonic using PBKDF2-SHA512.
    
    This is BIP-39 compliant derivation.
    
    Args:
        mnemonic: Space-separated recovery words
        passphrase: Optional extra passphrase for additional security
    
    Returns:
        64-byte seed
    """
    try:
        from mnemonic import Mnemonic
        m = Mnemonic("english")  # Language doesn't matter for seed derivation
        return m.to_seed(mnemonic, passphrase)
    except ImportError:
        # Fallback to manual PBKDF2
        import hashlib
        salt = ("mnemonic" + passphrase).encode("utf-8")
        mnemonic_bytes = mnemonic.encode("utf-8")
        return hashlib.pbkdf2_hmac("sha512", mnemonic_bytes, salt, 2048, dklen=64)


def seed_to_ed25519_keypair(seed: bytes) -> Tuple[bytes, bytes]:
    """
    Derive Ed25519 keypair from 64-byte seed.
    
    Uses first 32 bytes of seed as Ed25519 private key seed.
    
    Args:
        seed: 64-byte BIP-39 seed
    
    Returns:
        (private_key, public_key) as 32-byte each
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    
    # Use first 32 bytes of seed for Ed25519 (Ed25519 uses 32-byte seeds)
    private_key = Ed25519PrivateKey.from_private_bytes(seed[:32])
    
    private_bytes = private_key.private_bytes_raw()
    public_bytes = private_key.public_key().public_bytes_raw()
    
    return private_bytes, public_bytes


def validate_mnemonic(mnemonic: str, language: str = "en") -> bool:
    """
    Validate a mnemonic phrase.
    
    Checks:
    - Correct number of words (12 or 24)
    - All words in wordlist
    - Valid checksum
    
    Args:
        mnemonic: Space-separated recovery words
        language: "en" or "pt"
    
    Returns:
        True if valid, False otherwise
    """
    try:
        from mnemonic import Mnemonic
        lang_map = {"en": "english", "pt": "portuguese"}
        m = Mnemonic(lang_map.get(language, "english"))
        return m.check(mnemonic)
    except ImportError:
        # Basic validation without library
        words = mnemonic.strip().split()
        return len(words) in (12, 24)


# ═══════════════════════════════════════════════════════════════════════════════
# Identity Management
# ═══════════════════════════════════════════════════════════════════════════════

def create_identity(
    strength: IdentityStrength = IdentityStrength.STANDARD,
    language: str = "en",
    passphrase: str = ""
) -> KCPIdentity:
    """
    Create a new KCP identity with mnemonic recovery phrase.
    
    Args:
        strength: STANDARD (12 words) or HIGH (24 words)
        language: "en" for English, "pt" for Portuguese
        passphrase: Optional passphrase for extra security
    
    Returns:
        KCPIdentity with mnemonic and derived keys
    """
    mnemonic = generate_mnemonic(strength, language)
    seed = mnemonic_to_seed(mnemonic, passphrase)
    private_key, public_key = seed_to_ed25519_keypair(seed)
    node_id = public_key.hex()
    
    return KCPIdentity(
        mnemonic=mnemonic,
        private_key=private_key,
        public_key=public_key,
        node_id=node_id,
        language=language,
        passphrase_protected=bool(passphrase)
    )


def recover_identity(mnemonic: str, passphrase: str = "", language: str = "en") -> KCPIdentity:
    """
    Recover a KCP identity from mnemonic phrase.
    
    Args:
        mnemonic: Space-separated recovery words
        passphrase: Optional passphrase (must match original)
        language: Language of the mnemonic
    
    Returns:
        Recovered KCPIdentity
    
    Raises:
        ValueError: If mnemonic is invalid
    """
    mnemonic = mnemonic.strip().lower()
    
    if not validate_mnemonic(mnemonic, language):
        raise ValueError(
            "Frase de recuperação inválida. Verifique se digitou todas as "
            "palavras corretamente e na ordem certa."
        )
    
    seed = mnemonic_to_seed(mnemonic, passphrase)
    private_key, public_key = seed_to_ed25519_keypair(seed)
    node_id = public_key.hex()
    
    return KCPIdentity(
        mnemonic=mnemonic,
        private_key=private_key,
        public_key=public_key,
        node_id=node_id,
        language=language,
        passphrase_protected=bool(passphrase)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Key Storage
# ═══════════════════════════════════════════════════════════════════════════════

def save_identity(
    identity: KCPIdentity,
    keys_dir: Path,
    save_mnemonic: bool = False
) -> None:
    """
    Save identity keys to disk.
    
    By default, only saves the derived keys (private + public).
    The mnemonic is NOT saved to disk for security - user must backup manually.
    
    Args:
        identity: KCPIdentity to save
        keys_dir: Directory to save keys
        save_mnemonic: If True, also save mnemonic (NOT RECOMMENDED)
    """
    keys_dir = Path(keys_dir).expanduser()
    keys_dir.mkdir(parents=True, exist_ok=True)
    
    # Save private key
    priv_path = keys_dir / "node.key"
    priv_path.write_bytes(identity.private_key)
    priv_path.chmod(0o600)  # Owner read/write only
    
    # Save public key
    pub_path = keys_dir / "node.pub"
    pub_path.write_bytes(identity.public_key)
    
    # Save metadata
    meta_path = keys_dir / "identity.json"
    import json
    meta = {
        "node_id": identity.node_id,
        "fingerprint": identity.fingerprint,
        "passphrase_protected": identity.passphrase_protected,
        "word_count": identity.word_count,
        "language": identity.language,
        "version": "1.0",
        "warning": "Recovery phrase NOT stored here. User must backup manually."
    }
    meta_path.write_text(json.dumps(meta, indent=2))
    
    # Optionally save mnemonic (encrypted with passphrase would be better)
    if save_mnemonic:
        mnemonic_path = keys_dir / "recovery.txt"
        mnemonic_path.write_text(
            f"# KCP Recovery Phrase - KEEP SECRET!\n"
            f"# Node ID: {identity.node_id}\n"
            f"# Fingerprint: {identity.fingerprint}\n\n"
            f"{identity.mnemonic}\n"
        )
        mnemonic_path.chmod(0o600)


def load_identity_keys(keys_dir: Path) -> Tuple[bytes, bytes, dict]:
    """
    Load identity keys from disk.
    
    Args:
        keys_dir: Directory containing keys
    
    Returns:
        (private_key, public_key, metadata)
    
    Raises:
        FileNotFoundError: If keys not found
    """
    keys_dir = Path(keys_dir).expanduser()
    
    priv_path = keys_dir / "node.key"
    pub_path = keys_dir / "node.pub"
    meta_path = keys_dir / "identity.json"
    
    if not priv_path.exists():
        raise FileNotFoundError(f"Identity not found in {keys_dir}")
    
    private_key = priv_path.read_bytes()
    public_key = pub_path.read_bytes() if pub_path.exists() else None
    
    metadata = {}
    if meta_path.exists():
        import json
        metadata = json.loads(meta_path.read_text())
    
    # Derive public key if not saved
    if not public_key:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        key = Ed25519PrivateKey.from_private_bytes(private_key)
        public_key = key.public_key().public_bytes_raw()
    
    return private_key, public_key, metadata


def export_identity(
    keys_dir: Path,
    output_path: Path,
    password: Optional[str] = None
) -> None:
    """
    Export identity to encrypted backup file.
    
    Args:
        keys_dir: Directory containing keys
        output_path: Path for backup file
        password: Encryption password (prompted if not provided)
    """
    import json
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    
    private_key, public_key, metadata = load_identity_keys(keys_dir)
    
    # Prepare export data
    export_data = {
        "version": "1.0",
        "private_key": private_key.hex(),
        "public_key": public_key.hex(),
        "metadata": metadata
    }
    plaintext = json.dumps(export_data).encode()
    
    if password:
        # Encrypt with password
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        key = kdf.derive(password.encode())
        
        nonce = os.urandom(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        
        # Write encrypted file
        output_path = Path(output_path)
        with open(output_path, "wb") as f:
            f.write(b"KCPKEY1")  # Magic
            f.write(salt)        # 16 bytes
            f.write(nonce)       # 12 bytes
            f.write(ciphertext)  # Rest
        output_path.chmod(0o600)
    else:
        # Write plaintext (NOT RECOMMENDED)
        output_path = Path(output_path)
        output_path.write_text(json.dumps(export_data, indent=2))
        output_path.chmod(0o600)


def import_identity(
    input_path: Path,
    keys_dir: Path,
    password: Optional[str] = None
) -> dict:
    """
    Import identity from backup file.
    
    Args:
        input_path: Path to backup file
        keys_dir: Directory to save keys
        password: Decryption password if encrypted
    
    Returns:
        Imported metadata
    """
    import json
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    
    input_path = Path(input_path)
    content = input_path.read_bytes()
    
    # Check if encrypted
    if content[:7] == b"KCPKEY1":
        if not password:
            raise ValueError("Arquivo protegido por senha. Forneça a senha.")
        
        salt = content[7:23]
        nonce = content[23:35]
        ciphertext = content[35:]
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        key = kdf.derive(password.encode())
        
        aesgcm = AESGCM(key)
        try:
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        except Exception:
            raise ValueError("Senha incorreta ou arquivo corrompido.")
        
        export_data = json.loads(plaintext)
    else:
        # Plaintext JSON
        export_data = json.loads(content)
    
    # Extract keys
    private_key = bytes.fromhex(export_data["private_key"])
    public_key = bytes.fromhex(export_data["public_key"])
    metadata = export_data.get("metadata", {})
    
    # Save to keys_dir
    keys_dir = Path(keys_dir).expanduser()
    keys_dir.mkdir(parents=True, exist_ok=True)
    
    (keys_dir / "node.key").write_bytes(private_key)
    (keys_dir / "node.key").chmod(0o600)
    (keys_dir / "node.pub").write_bytes(public_key)
    
    if metadata:
        (keys_dir / "identity.json").write_text(json.dumps(metadata, indent=2))
    
    return metadata


# ═══════════════════════════════════════════════════════════════════════════════
# User-Friendly Messages (Bilingual)
# ═══════════════════════════════════════════════════════════════════════════════

MESSAGES = {
    "en": {
        "welcome": """
🔐 KCP Identity Setup

Your KCP identity is like a digital signature that proves you created
your knowledge artifacts. It needs to be backed up so you can recover
it if you change computers or lose your data.

We'll create a recovery phrase — 12 simple words that you'll need to
write down and keep safe. Anyone with these words can access your
identity, so treat them like a password!
""",
        "recovery_warning": """
⚠️  IMPORTANT: Write down these words NOW!

This is your ONLY way to recover your identity if something goes wrong.
Store them somewhere safe — not on your computer!

Suggestions:
  • Write on paper and store in a safe place
  • Use a password manager
  • Split between multiple secure locations
""",
        "recovery_prompt": "Enter your 12 recovery words (space-separated): ",
        "recovery_success": "✅ Identity recovered successfully!",
        "recovery_error": "❌ Invalid recovery phrase. Please check and try again.",
        "passphrase_prompt": "Optional passphrase (press Enter to skip): ",
        "confirm_backup": "Have you written down your recovery phrase? (yes/no): ",
    },
    "pt": {
        "welcome": """
🔐 Configuração de Identidade KCP

Sua identidade KCP é como uma assinatura digital que prova que você
criou seus artefatos de conhecimento. Ela precisa de backup para que
você possa recuperá-la se trocar de computador ou perder seus dados.

Vamos criar uma frase de recuperação — 12 palavras simples que você
precisará anotar e guardar em segurança. Qualquer pessoa com essas
palavras pode acessar sua identidade, então trate-as como uma senha!
""",
        "recovery_warning": """
⚠️  IMPORTANTE: Anote estas palavras AGORA!

Esta é sua ÚNICA forma de recuperar sua identidade se algo der errado.
Guarde em um lugar seguro — não no seu computador!

Sugestões:
  • Escreva em papel e guarde em lugar seguro
  • Use um gerenciador de senhas
  • Divida entre vários locais seguros
""",
        "recovery_prompt": "Digite suas 12 palavras de recuperação (separadas por espaço): ",
        "recovery_success": "✅ Identidade recuperada com sucesso!",
        "recovery_error": "❌ Frase de recuperação inválida. Verifique e tente novamente.",
        "passphrase_prompt": "Senha adicional opcional (Enter para pular): ",
        "confirm_backup": "Você anotou sua frase de recuperação? (sim/não): ",
    }
}


def get_message(key: str, lang: str = "en") -> str:
    """Get localized message."""
    return MESSAGES.get(lang, MESSAGES["en"]).get(key, MESSAGES["en"][key])
