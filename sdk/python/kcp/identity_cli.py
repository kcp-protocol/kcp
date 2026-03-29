"""
KCP Identity CLI

User-friendly command-line interface for identity management.
Supports both English and Portuguese with natural language prompts.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Optional

# Add color support
try:
    from colorama import init, Fore, Style
    init()
    GREEN = Fore.GREEN
    YELLOW = Fore.YELLOW
    RED = Fore.RED
    CYAN = Fore.CYAN
    BLUE = Fore.BLUE
    RESET = Style.RESET_ALL
    BOLD = Style.BRIGHT
except ImportError:
    GREEN = YELLOW = RED = CYAN = BLUE = RESET = BOLD = ""


def detect_language() -> str:
    """Detect user's preferred language from environment."""
    lang = os.environ.get("LANG", "en_US").lower()
    if "pt" in lang:
        return "pt"
    return "en"


def print_header(text: str) -> None:
    """Print a styled header."""
    print(f"\n{BOLD}{CYAN}{'═' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 60}{RESET}\n")


def print_success(text: str) -> None:
    """Print success message."""
    print(f"{GREEN}✅ {text}{RESET}")


def print_warning(text: str) -> None:
    """Print warning message."""
    print(f"{YELLOW}⚠️  {text}{RESET}")


def print_error(text: str) -> None:
    """Print error message."""
    print(f"{RED}❌ {text}{RESET}")


def print_info(text: str) -> None:
    """Print info message."""
    print(f"{BLUE}ℹ️  {text}{RESET}")


def confirm(prompt: str, default: bool = False) -> bool:
    """Ask for yes/no confirmation."""
    suffix = " [S/n]: " if default else " [s/N]: "
    while True:
        response = input(prompt + suffix).strip().lower()
        if not response:
            return default
        if response in ("s", "sim", "y", "yes"):
            return True
        if response in ("n", "não", "nao", "no"):
            return False
        print("Por favor, responda 'sim' ou 'não'.")


def get_keys_dir() -> Path:
    """Get default keys directory."""
    return Path(os.environ.get("KCP_KEYS_DIR", "~/.kcp/keys")).expanduser()


# ═══════════════════════════════════════════════════════════════════════════════
# Interactive Wizards
# ═══════════════════════════════════════════════════════════════════════════════

def wizard_create_identity(lang: str = "en") -> None:
    """
    Interactive wizard to create a new KCP identity.
    
    Guides the user through:
    1. Explaining what identity is
    2. Generating recovery phrase
    3. Confirming backup
    4. Saving keys
    """
    from .identity import (
        create_identity, save_identity, IdentityStrength, get_message
    )
    
    # Welcome message
    if lang == "pt":
        print_header("🔐 Criar Nova Identidade KCP")
        print("""
Sua identidade KCP é como uma assinatura digital única que:

  📝 Prova que VOCÊ criou seus artefatos de conhecimento
  🔗 Permite rastrear a linhagem do seu trabalho
  🌐 Funciona em qualquer computador com a mesma identidade
  
Vamos criar uma frase de recuperação — são {words} palavras simples
que você precisará guardar em segurança.

{warning}
""".format(
            words="12",
            warning=f"{YELLOW}⚠️  IMPORTANTE: Anote as palavras! É a única forma de recuperar sua identidade.{RESET}"
        ))
    else:
        print_header("🔐 Create New KCP Identity")
        print("""
Your KCP identity is a unique digital signature that:

  📝 Proves YOU created your knowledge artifacts
  🔗 Enables lineage tracking of your work
  🌐 Works on any computer with the same identity
  
We'll create a recovery phrase — {words} simple words that you'll
need to keep safe.

{warning}
""".format(
            words="12",
            warning=f"{YELLOW}⚠️  IMPORTANT: Write down the words! It's the only way to recover your identity.{RESET}"
        ))
    
    # Ask for security level
    if lang == "pt":
        print("Escolha o nível de segurança:")
        print("  1. Padrão (12 palavras) — recomendado para uso pessoal")
        print("  2. Alto (24 palavras) — recomendado para organizações")
    else:
        print("Choose security level:")
        print("  1. Standard (12 words) — recommended for personal use")
        print("  2. High (24 words) — recommended for organizations")
    
    choice = input("\nOpção [1]: ").strip() or "1"
    strength = IdentityStrength.HIGH if choice == "2" else IdentityStrength.STANDARD
    
    # Ask for optional passphrase
    if lang == "pt":
        print(f"\n{CYAN}Senha adicional (opcional):{RESET}")
        print("Adiciona uma camada extra de proteção. Se usar, precisará")
        print("lembrar dela além das palavras de recuperação.")
    else:
        print(f"\n{CYAN}Additional passphrase (optional):{RESET}")
        print("Adds an extra layer of protection. If used, you'll need to")
        print("remember it in addition to the recovery words.")
    
    passphrase = input("\nSenha (Enter para pular): ").strip()
    if passphrase:
        passphrase_confirm = input("Confirme a senha: ").strip()
        if passphrase != passphrase_confirm:
            print_error("As senhas não coincidem. Tente novamente.")
            return
    
    # Generate identity
    print(f"\n{CYAN}Gerando identidade...{RESET}")
    identity = create_identity(
        strength=strength,
        language=lang,
        passphrase=passphrase
    )
    
    # Display recovery phrase
    print_header("🔑 Sua Frase de Recuperação" if lang == "pt" else "🔑 Your Recovery Phrase")
    
    words = identity.mnemonic.split()
    print(f"\n{YELLOW}{'─' * 50}{RESET}")
    for i, word in enumerate(words, 1):
        print(f"  {BOLD}{i:2}.{RESET} {GREEN}{word}{RESET}")
        if i % 4 == 0:
            print()
    print(f"{YELLOW}{'─' * 50}{RESET}")
    
    # Show recovery card
    print(f"\n{CYAN}Cartão de Recuperação (para imprimir):{RESET}")
    print(identity.to_recovery_card())
    
    # Confirm backup
    print()
    if lang == "pt":
        print_warning("ANOTE ESTAS PALAVRAS AGORA!")
        print("Guarde em lugar seguro: papel em cofre, gerenciador de senhas, etc.")
        print("NÃO salve apenas no computador — se ele falhar, você perde o acesso.")
    else:
        print_warning("WRITE DOWN THESE WORDS NOW!")
        print("Store safely: paper in a safe, password manager, etc.")
        print("DON'T save only on computer — if it fails, you lose access.")
    
    print()
    if not confirm("Você anotou as palavras?" if lang == "pt" else "Have you written down the words?"):
        print_warning("Por favor, anote as palavras antes de continuar." if lang == "pt" else 
                     "Please write down the words before continuing.")
        if not confirm("Continuar mesmo assim?" if lang == "pt" else "Continue anyway?"):
            print_info("Operação cancelada." if lang == "pt" else "Operation cancelled.")
            return
    
    # Verify user wrote down correctly
    print(f"\n{CYAN}Verificação:{RESET}")
    if lang == "pt":
        print("Digite a palavra #3, #7 e #11 para confirmar que anotou:")
    else:
        print("Enter word #3, #7 and #11 to confirm you wrote them down:")
    
    word3 = input("  Palavra #3: ").strip().lower()
    word7 = input("  Palavra #7: ").strip().lower()
    word11 = input("  Palavra #11: ").strip().lower()
    
    if word3 != words[2] or word7 != words[6] or word11 != words[10]:
        print_error("Palavras incorretas. Verifique sua anotação." if lang == "pt" else
                   "Incorrect words. Check your notes.")
        if not confirm("Continuar mesmo assim?" if lang == "pt" else "Continue anyway?"):
            return
    else:
        print_success("Verificação OK!" if lang == "pt" else "Verification OK!")
    
    # Save keys
    keys_dir = get_keys_dir()
    if keys_dir.exists() and (keys_dir / "node.key").exists():
        if lang == "pt":
            print_warning(f"Já existe uma identidade em {keys_dir}")
            if not confirm("Substituir identidade existente?"):
                print_info("Operação cancelada.")
                return
        else:
            print_warning(f"Identity already exists at {keys_dir}")
            if not confirm("Replace existing identity?"):
                print_info("Operation cancelled.")
                return
    
    save_identity(identity, keys_dir, save_mnemonic=False)
    
    # Success
    print()
    print_header("✅ Identidade Criada!" if lang == "pt" else "✅ Identity Created!")
    print(f"  {CYAN}Node ID:{RESET}     {identity.node_id}")
    print(f"  {CYAN}Fingerprint:{RESET} {identity.fingerprint}")
    print(f"  {CYAN}Chaves em:{RESET}   {keys_dir}")
    print()
    
    if lang == "pt":
        print("Agora você pode usar o KCP! Seu primeiro artefato será assinado")
        print("com esta identidade. Se precisar recuperar:")
        print(f"\n  {BOLD}kcp identity recover{RESET}")
    else:
        print("You can now use KCP! Your first artifact will be signed with")
        print("this identity. If you need to recover:")
        print(f"\n  {BOLD}kcp identity recover{RESET}")


def wizard_recover_identity(lang: str = "en") -> None:
    """
    Interactive wizard to recover a KCP identity from mnemonic.
    """
    from .identity import recover_identity, save_identity
    
    print_header("🔄 Recuperar Identidade KCP" if lang == "pt" else "🔄 Recover KCP Identity")
    
    if lang == "pt":
        print("""
Digite sua frase de recuperação (12 ou 24 palavras).
Você pode digitar todas as palavras separadas por espaço,
ou uma por linha.
""")
    else:
        print("""
Enter your recovery phrase (12 or 24 words).
You can type all words separated by spaces,
or one per line.
""")
    
    print(f"{CYAN}Frase de recuperação:{RESET}")
    
    # Collect words
    words = []
    while len(words) < 12:
        line = input(f"  {len(words)+1}. ").strip().lower()
        if not line:
            continue
        # Check if multiple words
        if " " in line:
            words.extend(line.split())
        else:
            words.append(line)
    
    # If 12 words, ask if there are more
    if len(words) == 12:
        has_more = input("\nMais palavras? (Enter se não, ou continue digitando): ").strip()
        if has_more:
            words.extend(has_more.lower().split())
            while len(words) < 24:
                line = input(f"  {len(words)+1}. ").strip().lower()
                if not line:
                    break
                if " " in line:
                    words.extend(line.split())
                else:
                    words.append(line)
    
    mnemonic = " ".join(words[:24])  # Max 24 words
    
    # Ask for passphrase
    if lang == "pt":
        print(f"\n{CYAN}Senha adicional (se você usou uma ao criar):{RESET}")
    else:
        print(f"\n{CYAN}Additional passphrase (if you used one when creating):{RESET}")
    
    passphrase = input("Senha (Enter se não usou): ").strip()
    
    # Recover
    print(f"\n{CYAN}Recuperando identidade...{RESET}")
    
    try:
        identity = recover_identity(mnemonic, passphrase, lang)
    except ValueError as e:
        print_error(str(e))
        return
    
    # Save
    keys_dir = get_keys_dir()
    if keys_dir.exists() and (keys_dir / "node.key").exists():
        if lang == "pt":
            print_warning(f"Já existe uma identidade em {keys_dir}")
            if not confirm("Substituir pela identidade recuperada?"):
                print_info("Operação cancelada.")
                return
        else:
            print_warning(f"Identity already exists at {keys_dir}")
            if not confirm("Replace with recovered identity?"):
                print_info("Operation cancelled.")
                return
    
    save_identity(identity, keys_dir, save_mnemonic=False)
    
    # Success
    print()
    print_success("Identidade recuperada!" if lang == "pt" else "Identity recovered!")
    print(f"  {CYAN}Node ID:{RESET}     {identity.node_id}")
    print(f"  {CYAN}Fingerprint:{RESET} {identity.fingerprint}")
    print(f"  {CYAN}Chaves em:{RESET}   {keys_dir}")
    print()
    
    if lang == "pt":
        print("Sua identidade foi restaurada. Todos os artefatos assinados com")
        print("esta identidade agora serão reconhecidos como seus.")
    else:
        print("Your identity has been restored. All artifacts signed with")
        print("this identity will now be recognized as yours.")


def show_identity(lang: str = "en") -> None:
    """Show current identity information."""
    from .identity import load_identity_keys
    
    print_header("🔑 Identidade KCP Atual" if lang == "pt" else "🔑 Current KCP Identity")
    
    keys_dir = get_keys_dir()
    
    try:
        private_key, public_key, metadata = load_identity_keys(keys_dir)
    except FileNotFoundError:
        if lang == "pt":
            print_warning("Nenhuma identidade configurada.")
            print(f"\nPara criar uma nova: {BOLD}kcp identity create{RESET}")
            print(f"Para recuperar:       {BOLD}kcp identity recover{RESET}")
        else:
            print_warning("No identity configured.")
            print(f"\nTo create new:  {BOLD}kcp identity create{RESET}")
            print(f"To recover:     {BOLD}kcp identity recover{RESET}")
        return
    
    node_id = public_key.hex()
    fingerprint = node_id[:8]
    
    print(f"  {CYAN}Node ID:{RESET}         {node_id}")
    print(f"  {CYAN}Fingerprint:{RESET}     {fingerprint}")
    print(f"  {CYAN}Chaves em:{RESET}       {keys_dir}")
    
    if metadata:
        if metadata.get("passphrase_protected"):
            print(f"  {CYAN}Proteção extra:{RESET}  {GREEN}Sim (passphrase){RESET}")
        print(f"  {CYAN}Palavras:{RESET}        {metadata.get('word_count', '?')}")
    
    print()
    if lang == "pt":
        print(f"💡 Para exportar backup: {BOLD}kcp identity export{RESET}")
        print(f"💡 Para ver cartão:      {BOLD}kcp identity card{RESET}")
    else:
        print(f"💡 To export backup: {BOLD}kcp identity export{RESET}")
        print(f"💡 To view card:     {BOLD}kcp identity card{RESET}")


def export_backup(output_path: Optional[str] = None, lang: str = "en") -> None:
    """Export identity to backup file."""
    from .identity import export_identity, load_identity_keys
    
    print_header("📤 Exportar Backup" if lang == "pt" else "📤 Export Backup")
    
    keys_dir = get_keys_dir()
    
    try:
        load_identity_keys(keys_dir)
    except FileNotFoundError:
        print_error("Nenhuma identidade para exportar." if lang == "pt" else 
                   "No identity to export.")
        return
    
    if not output_path:
        default_path = Path.home() / "kcp-identity-backup.enc"
        if lang == "pt":
            output_path = input(f"Arquivo de saída [{default_path}]: ").strip() or str(default_path)
        else:
            output_path = input(f"Output file [{default_path}]: ").strip() or str(default_path)
    
    # Password protection
    if lang == "pt":
        print(f"\n{CYAN}Proteger com senha (recomendado):{RESET}")
    else:
        print(f"\n{CYAN}Password protect (recommended):{RESET}")
    
    password = input("Senha: ").strip()
    if password:
        password_confirm = input("Confirme: ").strip()
        if password != password_confirm:
            print_error("Senhas não coincidem." if lang == "pt" else "Passwords don't match.")
            return
    
    export_identity(keys_dir, Path(output_path), password or None)
    
    print()
    print_success(f"Backup exportado para: {output_path}")
    if lang == "pt":
        print("Guarde este arquivo em local seguro (pen drive, cloud, etc).")
    else:
        print("Store this file safely (USB drive, cloud, etc).")


def import_backup(input_path: Optional[str] = None, lang: str = "en") -> None:
    """Import identity from backup file."""
    from .identity import import_identity
    
    print_header("📥 Importar Backup" if lang == "pt" else "📥 Import Backup")
    
    if not input_path:
        if lang == "pt":
            input_path = input("Arquivo de backup: ").strip()
        else:
            input_path = input("Backup file: ").strip()
    
    if not input_path or not Path(input_path).exists():
        print_error("Arquivo não encontrado." if lang == "pt" else "File not found.")
        return
    
    # Check if encrypted
    content = Path(input_path).read_bytes()[:7]
    password = None
    if content == b"KCPKEY1":
        password = input("Senha: ").strip()
    
    keys_dir = get_keys_dir()
    
    try:
        metadata = import_identity(Path(input_path), keys_dir, password)
    except ValueError as e:
        print_error(str(e))
        return
    
    print()
    print_success("Identidade importada!" if lang == "pt" else "Identity imported!")
    print(f"  {CYAN}Node ID:{RESET}     {metadata.get('node_id', 'unknown')}")
    print(f"  {CYAN}Chaves em:{RESET}   {keys_dir}")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """CLI entry point for kcp identity commands."""
    import argparse
    
    lang = detect_language()
    
    parser = argparse.ArgumentParser(
        prog="kcp identity",
        description="Gerenciar identidade KCP" if lang == "pt" else "Manage KCP identity"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Comando")
    
    # create
    create_parser = subparsers.add_parser(
        "create", 
        help="Criar nova identidade" if lang == "pt" else "Create new identity"
    )
    
    # recover
    recover_parser = subparsers.add_parser(
        "recover",
        help="Recuperar identidade da frase" if lang == "pt" else "Recover identity from phrase"
    )
    
    # show
    show_parser = subparsers.add_parser(
        "show",
        help="Mostrar identidade atual" if lang == "pt" else "Show current identity"
    )
    
    # export
    export_parser = subparsers.add_parser(
        "export",
        help="Exportar backup" if lang == "pt" else "Export backup"
    )
    export_parser.add_argument("-o", "--output", help="Arquivo de saída")
    
    # import
    import_parser = subparsers.add_parser(
        "import",
        help="Importar backup" if lang == "pt" else "Import backup"
    )
    import_parser.add_argument("-f", "--file", help="Arquivo de backup")
    
    # Language flag
    parser.add_argument(
        "--lang", "-l",
        choices=["en", "pt"],
        default=lang,
        help="Idioma / Language"
    )
    
    args = parser.parse_args()
    lang = args.lang
    
    if args.command == "create":
        wizard_create_identity(lang)
    elif args.command == "recover":
        wizard_recover_identity(lang)
    elif args.command == "show":
        show_identity(lang)
    elif args.command == "export":
        export_backup(args.output, lang)
    elif args.command == "import":
        import_backup(args.file, lang)
    else:
        # Default: show help or current status
        show_identity(lang)


if __name__ == "__main__":
    main()
