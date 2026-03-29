# 🔐 KCP Identity — Guia de Backup e Recuperação

> **Sua identidade KCP é a prova de que você criou seu conhecimento.**
> Este guia explica como funciona e como protegê-la.

## 📖 O Que é Identidade KCP?

Quando você usa o KCP, seus artefatos de conhecimento são **assinados digitalmente** com uma chave única. Essa assinatura:

- ✅ **Prova autoria** — Qualquer pessoa pode verificar que foi você quem criou
- 🔗 **Mantém linhagem** — Conecta versões e derivações do seu trabalho
- 🌐 **Funciona em qualquer lugar** — Mesma identidade em múltiplos computadores
- 🔒 **Privacidade** — Conteúdo privado só você pode ler (criptografado)

## 🎯 Por Que Fazer Backup?

Sua identidade é armazenada no seu computador em `~/.kcp/keys/`. Se você:

- 🖥️ Trocar de computador
- 💾 Formatar o disco
- 🔥 Perder os arquivos

...você **perde o acesso** a:
- Artefatos privados (criptografados com sua chave)
- Capacidade de provar que criou artefatos antigos
- Permissões em grupos/organizações

**Solução: Backup da frase de recuperação!**

---

## 🚀 Como Criar Identidade

### Opção 1: Wizard Interativo (Recomendado)

```bash
kcp identity create
```

O wizard vai:
1. Explicar o processo
2. Gerar 12 palavras de recuperação
3. Pedir que você anote
4. Verificar que anotou corretamente
5. Salvar as chaves

### Opção 2: Programaticamente (Python)

```python
from kcp.identity import create_identity, save_identity
from pathlib import Path

# Criar nova identidade
identity = create_identity()

# Mostrar frase de recuperação (ANOTE ISTO!)
print("Sua frase de recuperação:")
print(identity.mnemonic)

# Salvar chaves no disco
save_identity(identity, Path("~/.kcp/keys"))
```

---

## 📝 Frase de Recuperação

Sua frase de recuperação são **12 palavras simples** como:

```
abandon ability able about above absent absorb abstract absurd abuse access accident
```

### ⚠️ IMPORTANTE:

| ✅ Faça | ❌ Não Faça |
|---------|------------|
| Anote em papel | Salve em arquivo no PC |
| Guarde em cofre | Tire foto com celular |
| Use gerenciador de senhas | Envie por email/chat |
| Divida em 2 locais seguros | Compartilhe com outros |

**Quem tem as 12 palavras = tem sua identidade!**

---

## 🔄 Como Recuperar

### Se Você Tem a Frase de Recuperação

```bash
kcp identity recover
```

Digite as 12 palavras quando solicitado. Sua identidade será restaurada exatamente como era.

### Via Python

```python
from kcp.identity import recover_identity, save_identity
from pathlib import Path

# Recuperar da frase
identity = recover_identity(
    "abandon ability able about above absent absorb abstract absurd abuse access accident"
)

# Verificar - mesmo Node ID de antes!
print(f"Recuperado: {identity.node_id}")

# Salvar
save_identity(identity, Path("~/.kcp/keys"))
```

---

## 📤 Backup em Arquivo (Alternativa)

Se preferir backup em arquivo (menos seguro que mnemonic):

### Exportar

```bash
kcp identity export
# Será pedida uma senha para criptografar
# Salva em ~/kcp-identity-backup.enc
```

### Importar

```bash
kcp identity import --file ~/kcp-identity-backup.enc
# Digite a mesma senha usada na exportação
```

---

## 🔐 Segurança Adicional: Passphrase

Ao criar identidade, você pode adicionar uma **senha extra**:

```bash
kcp identity create
# Quando perguntar "Senha adicional": digite algo secreto
```

Com passphrase:
- As 12 palavras **sozinhas** não funcionam
- Precisa da frase + senha
- Proteção contra roubo da frase

**⚠️ Se esquecer a passphrase, não tem recuperação!**

---

## 🏢 Para Organizações

### Device Keys (Futuro - v0.5)

Em breve suportaremos:

```
Identity Key (master)
  ├── Device Key (laptop)
  ├── Device Key (servidor)
  └── Device Key (CI/CD)
```

- Cada device tem sua própria chave
- Master pode revogar devices comprometidos
- Artifacts assinados por qualquer device são válidos

---

## 🔍 Verificar Identidade Atual

```bash
kcp identity show
```

Saída:
```
🔑 Identidade KCP Atual
═══════════════════════════════════════════════════════════

  Node ID:         a1b2c3d4e5f6...
  Fingerprint:     a1b2c3d4
  Chaves em:       /home/user/.kcp/keys
  Proteção extra:  Não

💡 Para exportar backup: kcp identity export
```

---

## 📋 Cartão de Recuperação

O comando `kcp identity create` gera um cartão imprimível:

```
╔══════════════════════════════════════════════════════════════╗
║           🔐 KCP IDENTITY RECOVERY CARD                      ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  ⚠️  GUARDE ESTE CARTÃO EM LOCAL SEGURO!                     ║
║  Qualquer pessoa com estas palavras pode acessar sua         ║
║  identidade KCP e todos os seus artefatos.                   ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║   1. abandon       2. ability      3. able                   ║
║   4. about         5. above        6. absent                 ║
║   7. absorb        8. abstract     9. absurd                 ║
║  10. abuse        11. access      12. accident               ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║  Node ID: a1b2c3d4e5f6...                                    ║
║  Fingerprint: a1b2c3d4                                       ║
║                                                              ║
║  Para recuperar: kcp identity recover                        ║
╚══════════════════════════════════════════════════════════════╝
```

Imprima e guarde em local seguro!

---

## ❓ FAQ

### Se eu perder a frase, posso resetar?

Não. Suas chaves são únicas. Sem a frase:
- Artefatos privados ficam ilegíveis
- Não pode provar autoria de artefatos antigos
- Precisa criar nova identidade (começa do zero)

### Posso ter múltiplas identidades?

Sim! Cada pasta de chaves é uma identidade:

```bash
KCP_KEYS_DIR=~/.kcp/keys-pessoal kcp identity create
KCP_KEYS_DIR=~/.kcp/keys-trabalho kcp identity create
```

### As 12 palavras são únicas?

Sim. São geradas aleatoriamente com 128 bits de entropia. A chance de colisão é ~1 em 340 undecilhões.

### Posso usar 24 palavras?

Sim, para maior segurança:

```bash
kcp identity create
# Escolha opção 2 (24 palavras / 256 bits)
```

---

## 📚 Referências Técnicas

- **Padrão**: BIP-39 (mesmo usado por Bitcoin/Ethereum wallets)
- **Derivação**: PBKDF2-SHA512 com 2048 iterações
- **Assinatura**: Ed25519 (Curve25519)
- **Criptografia**: AES-256-GCM para conteúdo privado

---

## 🆘 Suporte

Dúvidas sobre identidade?

- 📧 contato@kcp-protocol.org
- 🐙 [GitHub Issues](https://github.com/kcp-protocol/kcp/issues)
- 📖 [Spec completa](https://github.com/kcp-protocol/kcp/blob/main/SPEC.md)
