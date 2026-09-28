# runtime.codex deployment guide

Production deployment is a target-host qualification activity, not a repository-source assertion.

## Trust layout

Run the final-use issuer under a dedicated service UID that is not shared with Agentd, the inference worker, interactive users, or the App Server. Keep the Ed25519 signing key in an HSM/KMS-backed service or equivalently controlled process; the worker receives only a verifying key. Place the issuer socket in a root-owned, non-group-writable directory and pin the connected peer UID plus process-instance evidence required by the selected host profile.

Agentd and the App Server must have independently authenticated generation, socket, executable, boot identity, workspace, home root, and service-unit identity. Provider credentials belong to the App Server/provider owner and must not be copied into runtime.codex receipts, prompts, journals, or general logs.

## Required persistent surfaces

- runtime.codex native journal and its capacity accounting;
- final-use verifier state, nonce history, authority epoch, and monotonic revocation head;
- Agentd run-state owner and generation/fence state;
- external anti-rollback evidence for restored or relocated authority state;
- quarantine release sequence and signed release envelopes.

Backups must preserve schema compatibility, file ownership, permissions, monotonic sequence, and the relationship between the binary, journal, authority state, and Agent generation. Restoring a file alone is not an anti-rollback proof.

## Startup order

1. Establish trusted time and anti-rollback services.
2. Start the independent final-use issuer and validate key custody plus socket/process identity.
3. Start Agentd and App Server; bind the exact generation and ingress socket.
4. Reconcile all unresolved native and Agentd runs before opening admission.
5. Run a no-effect health check, then a canary under the protected qualification profile.
6. Open bounded admission only after all identity, state, capacity, and revocation checks pass.

## Configuration rules

Configuration is immutable for one process generation. Changes to issuer key, authority epoch, revocation distribution, provider, model, App Server binary, socket, workspace, capacity, timeout, or schema create a new generation/profile. Never silently fall back to an ambient Codex home, provider, model, socket, or authority endpoint.

## Target qualification

Use `.github/workflows/runtime-codex-target-qualification.yml` on a protected self-hosted runner with the `runtime-codex-qualified` label and the `runtime-codex-production-qualification` environment. The target driver is itself digest-pinned. Passing that workflow validates the supplied target evidence; independent acceptance, activation, promotion, and release remain separate decisions.
