# channel.matrix qualification matrix

Status labels: `source` means the fixture/source exists; `executed` requires an exact-candidate receipt; `external` requires the named real target host. This document does not convert source into execution evidence.

## 1. Required scenarios

| ID | Scenario | Required oracle | Current gate |
|---|---|---|---|
| MATRIX-Q01 | normal send | SDK event ID recorded as transport accepted; matching `/sync` atomically confirms ledger/outbox | source fixture; exact-head execution required |
| MATRIX-Q02 | ACK/response loss | remains accepted/indeterminate, same transaction after restart, later `/sync` confirms | source fixture |
| MATRIX-Q03 | HTTP 429 | validated `retry_after_ms` plus bounded jitter; no hot loop | implementation/fixture pending |
| MATRIX-Q04 | server accepts then connection drops | never marked failed; terminal only after sync | source fault seam |
| MATRIX-Q05 | revoke after claim, before adapter entry | zero transport calls; fresh attempt/grant required | source fixture |
| MATRIX-Q06 | crash after server acceptance, before local commit | restart preserves transaction and reconciles | hermetic Synapse fixture |
| MATRIX-Q07 | matrixd restart | stable transaction, dispatch history and authority claims survive | source + Synapse fixture |
| MATRIX-Q08 | supervisor restart/orphan | exact lease/adoption or fenced rejection | supervisor tests + Synapse fixture |
| MATRIX-Q09 | redaction | confirmed event becomes redacted in same sync-owner transaction | source fixture |
| MATRIX-Q10 | sync gap/reconnect | no duplicate projection/send; cursor cannot skip terminal event | source fixture |
| MATRIX-Q11 | room/device/session generation change | old scope/grant/daemon fenced before I/O | source/negative tests |
| MATRIX-Q12 | encrypted room rotation | session/device restoration and terminal reconciliation | real encrypted homeserver required |
| MATRIX-Q13 | authenticated backup restore | revoked/redacted content and old claims do not resurrect | target-host restore fixture required |
| MATRIX-Q14 | later permanent rejection after acceptance | prior accepted effect remains unresolved, never failed | source fixture |
| MATRIX-Q15 | capacity and shutdown | bounded unresolved/claim batch; pre-entry claims released; post-entry unknown retained | partial source; release fixture pending |

## 2. Existing real-environment fixture

`codex-rs/hepta-matrixd/tests/real_synapse_e2e.rs` and `tests/fixtures/run-hermetic-synapse.sh` define a pinned, hermetic dual-Agent/dual-matrixd Synapse qualification. The fixture pins image digest, image ID, Synapse version/Git SHA, runner tools, source mode and completion nonce. It exercises paired release composition, isolation, restart and outbound response loss.

The runner is target-host-specific. Merely compiling the feature or storing its source is not a successful run.

## 3. Receipt schema

Every executed scenario emits one JSON receipt containing:

```json
{
  "schema": "hepta.channel-matrix-qualification.v1",
  "scenario": "MATRIX-Q02",
  "candidate": {"commit": "...", "tree": "..."},
  "source_blobs": [{"path": "...", "sha1": "...", "sha256": "..."}],
  "binary_digests": {},
  "homeserver": {"image": "...", "version": "...", "git_sha": "..."},
  "configuration_sha256": "...",
  "failure_injection": {},
  "observed": {},
  "result": "pass|fail|skip",
  "artifact_manifest_sha256": "...",
  "authority_granted": false
}
```

Receipts are immutable artifacts. `skip` is not pass. Logs are bounded and secret-redacted. The manifest binds every retained log/database snapshot/result by digest.

## 4. Exact-candidate lanes

1. Source-head: run implementation-map/callsite verifier and focused Rust tests at PR head.
2. Synthetic merge: repeat on the exact deterministic merge candidate.
3. Hermetic Synapse: execute supported unencrypted transport/restart/fault scenarios on the pinned host profile.
4. Encrypted target: execute device/session rotation on the selected encrypted homeserver profile.
5. Restore/capacity: execute backup restore, long-running queue pressure, 429 and graceful shutdown scenarios.
6. Independent acceptance: security/operator review of receipts; no generator self-acceptance.

## 5. Promotion rule

Source composition may be marked complete when exact-head and merge tests pass and the map/callsites are current. Deployment qualification remains false until all applicable real-homeserver, encryption, restore, rate-limit and target-host scenarios have passing current receipts. Activation, canary, promotion and release remain separate external decisions.
