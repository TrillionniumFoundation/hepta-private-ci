# ui.control deployment and independent acceptance

This directory contains qualification tooling for the selected, real ui.control deployment.
Source-owned browser mocks and generated policy files are not deployment evidence.

## Deployment security

Build the exact selected artifact first, then run:

```bash
npm --prefix apps/hepta-control-ui run build
HEPTA_UI_CONTROL_BASE_URL=https://control.example.invalid \
HEPTA_UI_CONTROL_COOKIE='<externally authenticated cookie>' \
node qualification/ui-control/deployment-security.mjs
```

The runner deliberately requires an externally authenticated session. It does not mint a principal,
does not accept HTTP outside TLS, and does not execute a real operator mutation. It verifies the
actual HTTPS host for generated security-header application, HSTS, no wildcard CORS, authenticated
bootstrap, cross-origin rejection with a valid session, CSRF-before-connect, authenticated connect,
bounded JSON snapshot, mutation CSRF precheck, and authenticated close.

A PASS is deployment-security evidence for that exact endpoint/artifact only. It is not independent
accessibility acceptance and does not set activation or release authority.

## Independent browser/accessibility acceptance

The selected candidate remains blocked until evidence is retained from a verifier independent of the
implementation author for the exact built artifact and real backend. At minimum record all of:

| Surface | Required evidence |
|---|---|
| Chrome | real-backend request, pending/indeterminate, reconcile, stale view, offline/reconnect, focus recovery |
| Firefox | same behavioral set against the same backend/candidate |
| Safari | same behavioral set against the same backend/candidate |
| Keyboard only | every control and final confirmation; focus restoration after cancel/error/terminal update |
| Screen reader | status vs alert announcements, exact confirmation target, uncertainty, stop request, recovery |
| Security | TLS/session/cookie, Origin/CSRF/CSP/CORS, no secret/provider payload leakage |
| Failure | response loss after accepted mutation, browser reload, backend restart, terminal reconciliation |
| Rollback | compatible client/backend protocol pair restored without forgetting unresolved operations |

Each retained record must bind: candidate commit/tree, built-asset-manifest digest, backend deployment
identity/digest, browser + version + OS, assistive technology + version where applicable, verifier
identity/organization, timestamp, test-case identity, observed result, and attached raw evidence.

Do not translate source-owned Chrome smoke tests, a generated `security-headers.json`, or an
implementation-author attestation into `independentAcceptance`.
