# Testing OpenAPI Spec

## ✅ Syntax validation (local)

```bash
cd /Users/thiago.tsilva/dados/repos/kcp
.venv/bin/python -c "
import yaml
with open('docs/openapi.yaml') as f:
    spec = yaml.safe_load(f)
print(f'✅ Valid OpenAPI {spec[\"openapi\"]} spec')
print(f'   Endpoints: {len(spec[\"paths\"])}')
"
```

## 🌐 Online validators

### 1. Swagger Editor (recommended)
- Visit: https://editor.swagger.io/
- Click "File" → "Import URL"
- Paste: `https://raw.githubusercontent.com/kcp-protocol/kcp/main/docs/openapi.yaml`
- ✅ Should load with no errors and show interactive docs

### 2. Swagger UI (browser)
```bash
# Serve locally
npx @redocly/openapi-cli preview-docs docs/openapi.yaml
# Opens http://localhost:8080 with interactive docs
```

### 3. Postman
- Open Postman
- Click "Import" → "Link"
- Paste: `https://raw.githubusercontent.com/kcp-protocol/kcp/main/docs/openapi.yaml`
- ✅ Auto-generates collection with all 11 endpoints

## 🧪 Test real endpoints

```bash
# Health check
curl https://peer01.kcp-protocol.org/kcp/v1/health

# Search artifacts
curl "https://peer01.kcp-protocol.org/kcp/v1/artifacts?q=kcp&limit=5"

# Network status (CORS enabled)
curl https://peer01.kcp-protocol.org/kcp/v1/network-status

# Publish artifact (requires X-KCP-Client header)
curl -X POST https://peer01.kcp-protocol.org/kcp/v1/artifacts \
  -H "Content-Type: application/json" \
  -H "X-KCP-Client: test" \
  -d '{
    "title": "Test artifact",
    "content": "Hello from OpenAPI test",
    "format": "text",
    "tags": ["test"],
    "visibility": "public"
  }'
```

## 📊 Validation with openapi-spec-validator

```bash
pip install openapi-spec-validator
openapi-spec-validator docs/openapi.yaml
```

## 🔗 Generate clients

### Python
```bash
npm install -g @openapitools/openapi-generator-cli
openapi-generator-cli generate \
  -i docs/openapi.yaml \
  -g python \
  -o sdk/python-generated
```

### TypeScript/JavaScript
```bash
openapi-generator-cli generate \
  -i docs/openapi.yaml \
  -g typescript-fetch \
  -o sdk/typescript-generated
```

### Go
```bash
openapi-generator-cli generate \
  -i docs/openapi.yaml \
  -g go \
  -o sdk/go-generated
```

## ✅ Current status

- **Version**: OpenAPI 3.1.0
- **Endpoints**: 11
- **Schemas**: 3 (Artifact, Peer, PeerHealth)
- **Servers**: 3 (peer01, peer02, localhost)
- **Security**: KCPClient (X-KCP-Client header)

All endpoints documented match the implementation in `sdk/python/kcp/node.py`.
