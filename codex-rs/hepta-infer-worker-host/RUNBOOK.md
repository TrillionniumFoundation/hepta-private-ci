# Inference worker: hosted profile operations

This runbook describes the source interface of `hepta-infer-worker`. It is not a deployment receipt. The [technical guide](../../docs/modules/inference.worker/TECHNICAL.md) separates the executable hosted profile, pure receipt primitives and injected local-model driver. The hosted profile calls the existing owning Agentd/App Server; it does not load local weights, allocate a GPU or install provider credentials.

## Host prerequisites and invocation

The trusted host supplies an enrolled ready Agent with the exact generation, its private Agentd control socket, the model already configured/authenticated in its App Server, a private inference-control journal and an independent final-use authority endpoint. Use the Agent's actual identity and configured model. An unavailable authority or substituted model is an error, not a fallback.

Build from the repository root:

```sh
cargo build --manifest-path codex-rs/Cargo.toml -p codex-hepta-infer-worker-host --bin hepta-infer-worker
```

Invoke the built binary with host-selected absolute paths and a stable request identity:

```sh
codex-rs/target/debug/hepta-infer-worker \
  --profile native-app-server \
  --agentd-socket /absolute/agent/agentd.sock \
  --agent-id 018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12 \
  --generation 1 \
  --model CONFIGURED_MODEL \
  --journal /absolute/agent/private/native-runs.journal \
  --request-id run-001 \
  --maximum-in-flight 1 \
  --final-use-authority-config /absolute/agent/private/final-use-authority.json \
  --timeout-ms 120000 < prompt.txt
```

The Agent ID, generation, model, paths and request ID above are illustrative; use the enrolled owner and runtime-selected values. `CARGO_TARGET_DIR` may change the binary location. The command reads one UTF-8 prompt from stdin. It requires 1–32768 prompt bytes. The profile must be explicitly selected before input/provider access.

| Argument | Requirement |
| --- | --- |
| `--profile` | Exactly `native-app-server`; no default execution profile. |
| `--agentd-socket` | Absolute owning Agentd socket path. |
| `--agent-id` / `--generation` | Exact enrolled Agent UUID and nonzero generation. |
| `--model` | Exact configured model name, 1–256 bytes; no model substitution. |
| `--journal` | Absolute private owner journal. The first admission pins its local policy. |
| `--request-id` | Stable operation identity reused for inspection/recovery of this exact request. |
| `--maximum-in-flight` | Explicit 1–256; unchanged for an existing journal. This is a local-slot policy, not tokens, money or hardware capacity. |
| `--final-use-authority-config` | Required absolute protected JSON file described below. |
| `--context-query` | Optional 1–2048-byte query; requires Agentd `cognitive.context.revalidate@1`. Context is packed into the shared 8 KiB serialized budget and attached as untrusted context. |
| `--timeout-ms` | Optional, defaults to 120000; nonzero and no more than 3600000. The timeout participates in stable request identity. |

For a host-composed intelligence run, supply all four arguments together:

```sh
--intelligence-run-id RUN_ID \
--intelligence-revision REVISION \
--intelligence-context-digest HEX_DIGEST \
--intelligence-envelope-digest HEX_DIGEST
```

They must identify the exact Agentd `ContextAttached` run and immutable compilation/context bindings. The worker requires a newly acknowledged exact `Dispatched` transition before physical turn entry. An idempotent dispatch acknowledgement is reconciliation, not permission for a second send. The arguments are non-authorizing bindings; final-use authority is still required.

## Independent final-use authority

The worker does not run an issuer and never loads its private signing key. The host supplies an independently operated Unix endpoint that decides whether to sign the exact `runtime.codex.turn_start` binding. `UnixFinalUseAuthorizer` verifies and claims its response through the existing `kernel.authority` owner.

[FINAL_USE_AUTHORITY_PORT.md](FINAL_USE_AUTHORITY_PORT.md) is the detailed boundary design for prepare/entry ordering, nonce/revocation semantics, model-only tool denial, bounded issuer exchange and external qualification. This runbook supplies the concrete configuration field names and operating inputs.

The JSON config maps directly to `FinalUseAuthorizerConfig` in `src/final_use_authorizer.rs`; unknown fields are rejected:

| Field | JSON type and meaning |
| --- | --- |
| `issuer_socket` | Absolute Unix socket path for the independent issuer. |
| `issuer_uid` | Expected numeric issuer UID; both socket metadata and connected peer credentials must match. |
| `signer_id` | Trusted signer identity accepted by the final-use verifier. |
| `verifying_key` | Array of exactly 32 integer bytes containing the issuer's public Ed25519 verification key. No private key field exists. |
| `authority_state_dir` | Absolute private verifier state directory; retains consumed nonces and monotonic revocation facts. |
| `authority_epoch` | Initial trusted authority epoch supplied by the host. |
| `revocation_revision` | Initial trusted revision within that epoch. |
| `revoked_grant_ids` | Array of revoked grant ID strings; optional, defaults to empty. This default is not proof that the current issuer has no revocations. |
| `issuer_timeout_ms` | Integer from 1 through 30000. The runtime operation deadline may impose a smaller remaining claim budget. |

Populate the signer/key/frontier from the independently selected authority, and keep the verifier state across process restarts. Epoch/revision values must be valid for that verifier; a rolled-back or conflicting frontier fails closed. Deleting the state directory to reuse a consumed nonce is not recovery.

On Unix the config must be an absolute, non-symlink regular file with one hard link, owned by root or the effective worker UID and not writable by group/others. Its maximum size is 64 KiB. Mode `0600` is an appropriate host choice. The issuer socket must belong to `issuer_uid`, have no permissions for others, and live in a non-symlink immediate parent directory that is not group/world writable. Authentication also checks the connected peer UID. These local checks do not attest issuer process integrity or provide cross-host authentication.

The endpoint exchanges a four-byte big-endian length plus JSON: a schema-v1 `runtime.codex.turn_start` request (at most 16 KiB), followed by one signed grant or explicit denial with the issuer's current revocation head (at most 64 KiB). See the [port contract](FINAL_USE_AUTHORITY_PORT.md#3-authority-endpoint-and-protected-configuration) and `src/final_use_authorizer.rs` for exact response types. A frozen config alone cannot establish timely authenticated revocation distribution.

## Interpreting results

A returned observation is JSON on stdout. The CLI exits successfully only when `NativeRunOutput::succeeded()` is true: matching provider completion, successful boundary status and verified owner authority. Provider `Completed` alone is insufficient. Pre-dispatch or protocol errors may produce only an error, while durable request state remains in the journal.

| Result field | Interpretation |
| --- | --- |
| `status` / `terminal_observed` | Matching observed provider status/terminality. Interrupt acknowledgement and handler acceptance do not establish it. |
| `boundary_status` | Successful, failed, interrupted, cancelled, timed-out, quarantined or indeterminate boundary outcome. Late completion cannot authorize a cancelled/timed-out boundary. |
| `owner_authority` | Independent readiness/fencing observation. `Lost` remains denied; historical missing authority is `Unverified`. |
| `observed_output_tokens` | Actual matching observed u64 usage, or `null` when absent. It is not a payment settlement or estimated zero. |
| `codex_terminal_correlation_digest` | Matching runtime.codex terminal correlation, when observed. It is audit data, not a reusable authority token. |

Output contains private model text and the journal stores that text. Apply the owning Agent's storage/retention policy. Do not copy it into public logs or treat it as trusted instructions. The output projection bounds UTF-8 bytes and item identities; output/transport limit failure does not create a retry permit.

## Recovery, cancellation and rollback

Reuse the exact same command, prompt, context query, timeout and optional intelligence binding to inspect/reconcile a recorded request. Changed content under the same request ID conflicts. A completed duplicate returns durable observations without another provider turn; an unknown dispatch can perform exact-owner `thread/read` recovery without `turn/start`. This is not a retry by a new request identity. For an intelligence-bound run, the worker also retries exact Agentd terminal publication after durable inference settlement. A publication error does not erase the stored provider terminal; repeat the same identity rather than starting a new model run.

Recovery requires the original Agent generation, initialized App Server version/home/provider, stored dispatch correlation, stable client user-message ID and original user input. A missing original thread, unavailable ephemeral history, older incomplete dispatch binding, duplicate matching turns or payload conflict cannot be interpreted as safely unsent. Missing history remains indeterminate and retains its slot; conflicting history rejects recovery. `thread/read` terminal recovery does not reconstruct missing token-usage events.

Ctrl-C requests cancellation. Before provable dispatch, a durable stop can release the local slot. After possible dispatch, the worker records intent and sends `turn/interrupt`; only exact terminal evidence releases the slot. If the process dies after write-ahead dispatch, its in-memory unsent proof is lost and cannot be reconstructed from the journal. Do not change the request ID, delete the journal or substitute a new generation to bypass an unknown operation.

The journal has a 64 MiB total bound, 8 MiB encoded-line bound and 16384-record bound. Admission/dispatch also reserves 16 MiB of spare bytes for bounded observations/metadata. At capacity, writes fail; no authenticated archival/compaction command is supplied here. Preserve the file for owner-controlled retention/recovery. An ambiguous append/sync failure fences further writes, and corrupt/partial history fails replay without truncation.

An old binary may not understand `native-v1` records. Rollback must preserve a compatible binary/state pair and drain or reconcile possible effects before a newly selected generation operates. Independent deployment/authority selection, paid-provider fault runs, long-lived history/usage reconciliation, local weights/device qualification and activation/release remain outside the source CLI contract.
