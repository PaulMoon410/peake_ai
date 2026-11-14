# Harold Ollama-compatible adapter

This is a protocol adapter, not an Ollama installation. It runs within Harold's
existing Flask service on port 10000. It calls the existing `NeuralLanguageModel`
directly, using the existing generation lock and rate limiter. It does not call
external AI providers or the consensus pool, and downloads no models.

Configure an app's Ollama base URL as:

- LAN: `http://192.168.1.158:10000/ollama`
- HTTPS: `https://lubuntu.tail239f3d.ts.net/ollama`
- Model: `harold` (also accepts `harold:latest`)
- Header: `Authorization: Bearer <CHAT_API_KEY>`

Use HTTPS outside loopback/trusted networks. Apps must support a custom base
path and bearer headers. Apps hard-coded to port 11434 or lacking custom headers
are not supported by this deployment. The Hub is a separate portal repository.

Supported routes under that base:

- `GET /api/version` identifies the **adapter**, not an actual Ollama runtime.
- `GET /api/tags` lists the existing NPZ checkpoint; this is discovery, not an
  inference health check.
- `POST /api/show` accepts `{"model":"harold"}`.
- `POST /api/chat` accepts text-only system/user/assistant `messages`.
- `POST /api/generate` accepts `prompt` and optional text `system`.

Example (key already stored in your environment, not in source code):

```bash
curl --fail-with-body "$HAROLD_OLLAMA_URL/api/chat" \
  -H "Authorization: Bearer $CHAT_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"harold","messages":[{"role":"user","content":"Hello"}],"stream":false}'
```

Both generation routes support `stream:false` for JSON or default `stream:true`
for NDJSON. Generation is **buffered** and emits one content record plus one
terminal record; it is not live token streaming. `options.temperature` must be
in (0, 2], and `options.num_predict` in [1, 256]. The latter bounds the native
model's generation loop, not all of its pre-existing pattern-matched responses.
The native model consumes labeled text, not an Ollama chat template.

Images, tools, embeddings, pull/create/delete, JSON-format constraints, keep-alive,
and other unsupported fields are rejected, not silently simulated. Input is
limited to 1 MiB, 32 turns and 100,000 characters. Missing/invalid credentials,
busy generation, and unavailable model failures return non-success HTTP statuses.
A listed model does not imply general-purpose LLM quality or full Ollama
compatibility; test the client and actual inference before relying on it.
