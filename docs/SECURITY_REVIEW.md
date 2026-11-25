# Local-workstation security review — 2026-11-26

Scope: file uploads, model loading, configuration writes, SQLite/media access,
WebSocket previews. Threat actor: untrusted browser origin or same-host process.
This is not a network-authenticated/multi-user service.

## Findings from the first implementation pass

1. **Medium / local DoS — image allocation before dimension validation.**
   `backend/app/sources/file.py:18`: a compressed oversized PNG/JPEG can allocate
   before the pixel limit at line 21. Validate image headers before OpenCV decode.
2. **Medium / local DoS — chunked uploads.**
   `backend/app/main.py:43`: Content-Length-only preflight does not bound a chunked
   multipart body before Starlette spools it. Add a byte-counting ASGI receive guard.
3. **Low / resource exhaustion — connection lifecycle.**
   `backend/app/persistence/database.py:25`: sqlite context-manager commits but
   does not close the connection. Close explicitly in a contextmanager.
4. **Deployment restriction — no user authentication.** Loopback and trusted-host /
   origin checks are intentional; same-host processes remain trusted. Binding to
   a network address is not a supported deployment. Add authentication and HTTPS
   at a reviewed gateway before any LAN deployment.
5. **Trusted-artifact boundary — checkpoint execution.** `.pt` model loading can
   execute trusted checkpoint code. Only administrator-installed artifacts under
   `models/` are accepted. There is no web model-upload route or automatic download.

## Non-findings considered

- SQL values use parameterized statements; dynamic history clauses are constants.
- Uploaded filenames are not used as destination paths; storage uses server UUIDs.
- NPY loading disables pickle, rejects object arrays and invalid dimensions.
- Model and media resolution enforce directory confinement.
- No server-side fetch-by-user-URL endpoint; no SSRF surface.
- React text rendering escapes inspection labels; no raw HTML injection.
- Browser mutations and WebSocket connections reject foreign origins.

## Production boundary

Local disk records are auditable but not tamper-evident or access-controlled against
the workstation owner. A safety-critical release needs operational access control,
backup/retention policy, validated model licensing and real-capture acceptance.

The implementation pass following this review addresses findings 1–3. Hardware,
model internals, operating-system permissions and reverse proxies are out of scope.
