# channel.matrix qualification matrix

Status labels: `source` means implementation/fixture exists; `executed` requires a passing exact-candidate receipt; `external` requires the named real target host. Source presence, compilation or a workflow definition is never execution evidence.

## 1. Required scenarios

| ID | Scenario | Required oracle | Current gate |
|---|---|---|---|
| MATRIX-Q01 | normal send | SDK event ID recorded only as transport accepted; matching `/sync` atomically confirms ledger/outbox | source; exact-head execution required |
| MATRIX-Q02 | ACK/response loss | accepted/indeterminate, same transaction after restart, later `/sync` confirms | source |
| MATRIX-Q03 | HTTP 429 | typed Matrix `Retry-After` honored, bounded and jittered; no hot loop | source; real homeserver receipt required |
| MATRIX-Q04 | server accepts then connection drops | never marked failed; terminal only after sync | source fault seam |
| MATRIX-Q05 | revoke after claim, before adapter entry | zero transport polls/calls; fresh attempt/grant required | source |
| MATRIX-Q06 | crash after server acceptance, before local commit | restart preserves transaction and reconciles | hermetic Synapse source fixture |
| MATRIX-Q07 | matrixd restart | transaction, random claim history, witness and authority claims survive | source + Synapse fixture |
| MATRIX-Q08 | supervisor restart/orphan | exact lease/adoption or fenced rejection | supervisor source tests + Synapse fixture |
| MATRIX-Q09 | redaction | confirmed event becomes redacted in the same sync-owner transaction | source |
| MATRIX-Q10 | sync gap/reconnect | no duplicate projection/send; cursor cannot skip terminal event | source |
| MATRIX-Q11 | room/device/session generation change | old scope/grant/daemon fenced before I/O | source/negative tests |
| MATRIX-Q12 | encrypted room rotation | session/device restoration and terminal reconciliation | external encrypted homeserver |
| MATRIX-Q13 | authenticated backup restore | revoked/redacted content, active claims and old sessions do not resurrect | external restore profile |
| MATRIX-Q14 | later permanent rejection after acceptance | prior accepted/unknown effect remains unresolved, never failed | source |
| MATRIX-Q15 | capacity and shutdown | bounded unresolved/claim batches; pre-entry claims released; post-entry unknown retained | source; sustained host receipt required |
| MATRIX-Q16 | stale claim capability | wrong token/attempt/lease cannot mutate active attempt or outcome | source |
| MATRIX-Q17 | typed network failures | DNS, TLS, connect/read timeout, response loss and 5xx persist distinct classes | source; platform fault receipt required |

## 2. Existing qualification sources

- `codex-rs/hepta-matrix-sdk/tests/durable_transport.rs` covers durable transaction identity, authority, claim fencing, retry and reconciliation behavior.
- `codex-rs/hepta-matrixd/tests/real_synapse_e2e.rs` plus `tests/fixtures/run-hermetic-synapse.sh` define the pinned unencrypted Synapse target profile.
- supervisor tests cover exact Matrix companion lease, generation and orphan-adoption rules.
- migration 7 fixtures cover random claim identity, authority witnesses and append-only attempt events.

The Synapse runner pins image digest/ID, Synapse version/Git SHA, source mode, runner tools and completion nonce. Merely storing or compiling it is not a successful run.

## 3. Receipt schema

Every executed scenario emits one immutable JSON receipt:

```json
{
  "schema": "hepta.channel-matrix-qualification.v1",
  "scenario": "MATRIX-Q02",
  "candidate": {"commit": "...", "tree": "..."},
  "source_blobs": [{"path": "...", "git_blob": "...", "sha256": "..."}],
  "workflow": {"path": "...", "git_blob": "...", "run_id": "...", "job_id": "..."},
  "toolchain": {},
  "binary_digests": {},
  "homeserver": {"image": "...", "image_digest": "...", "version": "...", "git_sha": "..."},
  "configuration_sha256": "...",
  "failure_injection": {},
  "observed": {},
  "result": "pass|fail|skip",
  "artifact_manifest_sha256": "...",
  "authority_granted": false
}
```

`skip` is not pass. Logs are bounded and secret-redacted. The artifact manifest binds every retained log, database snapshot, structured result and binary by digest.

## 4. Exact-candidate lanes

1. **Source head:** candidate verifier, migration/startup checks, focused Rust tests, strict clippy and clean tree at the PR head.
2. **Synthetic merge:** repeat the same applicable checks on the deterministic merge candidate.
3. **Hermetic Synapse:** execute supported unencrypted transport/restart/ACK-loss/redaction scenarios on the pinned host profile.
4. **Encrypted target:** execute device/session rotation against the selected encrypted homeserver profile.
5. **Restore/capacity:** execute authenticated backup restore, long-running queue pressure, 429 and graceful shutdown.
6. **Independent acceptance:** security and operator review the exact receipts; generator self-acceptance is prohibited.

The implementation map uses an immutable ancestor as `sourceBase` because a commit cannot embed its own future SHA. `scripts/verify_channel_matrix_candidate.py --expected-sha "$GITHUB_SHA"` emits the exact current commit/tree, map digest and every inspected source/document blob. That receipt is the enforceable current-candidate binding.

## 5. Promotion rule

Source composition may be marked complete only when current source-head and merge checks pass without relevant skips and the retained receipts bind the exact final candidate. Deployment qualification remains false until all applicable real-homeserver, encryption, restore, rate-limit and sustained-capacity scenarios have passing current receipts. Independent acceptance, activation, canary, promotion and release are separate externally governed decisions.
