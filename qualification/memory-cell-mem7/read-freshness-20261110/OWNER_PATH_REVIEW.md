# MEM ordinary owner path review

Repository: `TrillionniumFoundation/hepta-private-ci`

Source reviewed: `4c3b1fb6d40de7c85aedd1964357e138fc7aa9d8`

Scope: source/interface review only. No production owner or real-provider memory
experiment was executed for this review. Scientific acceptance remains **HOLD**;
production adoption remains **NoUpdate**.

The native new-session inference path already exists. The Python episodic store
does not have an implemented import path into its original Rust memory owner.
Provider configuration alone cannot complete that integration. This review
narrows the existing [PRODUCT_MEMORY_CONTRACT.md](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4c3b1fb6d40de7c85aedd1964357e138fc7aa9d8/qualification/memory-cell-mem7/PRODUCT_MEMORY_CONTRACT.md);
it is not an integration receipt.

## Existing interfaces

| Repository path | Existing entry and concrete behavior |
| --- | --- |
| `codex-rs/hepta-agentd/src/production_writer_host.rs` | `AgentdProductionWriterHost::open_with_recovery` requires the exact recovery cut, `ProductionAuthorityLease`, retained live verifier, lease identity and generation. `remember_with_kg`, `correct_with_kg` and `forget_with_kg` submit canonical semantic mutations and return `ProductionCognitiveMutationReceiptV1`. Correction and deletion require the canonical memory ID and expected revision. |
| `codex-rs/hepta-memory/src/production_writer.rs` | `ProductionCognitiveMutation` is a sealed capability. A caller cannot implement a replacement owner or create authority by supplying a digest. |
| `codex-rs/hepta-memory/src/cognitive_model.rs` | `SourceDraft`, `MemoryDraft`, `MemoryRevisionDraft` and `KgFactSetDraft` describe canonical source bytes, scope, memory revisions, citations and structured facts. They are not the Python MEM6 record schema. |
| `codex-rs/hepta-agentd/src/client.rs` and `codex-rs/hepta-agent-protocol/src/lib.rs` | The control protocol exposes `CognitiveContext` and `CognitiveContextRevalidate`. It has no episodic-import or general remember/correct/forget control method. |
| `codex-rs/hepta-agentd/src/cognitive_context.rs` | Resolves current owner records and bounded context, and revalidates the owner cut, read binding and selected identities. Query size is 1–2,048 bytes and result limit is 1–4. |
| `codex-rs/hepta-agentd/src/cognitive_retrieval_context.rs` | `CurrentMemoryRetrievalContext::current` supplies host-authenticated current retrieval generations. The compatibility path does not manufacture an HNMF context. |
| `codex-rs/hepta-infer-worker-host/src/native_app_server.rs` | `AppServerModelDriver` creates a fresh retained `ThreadStart`, checks owner home/generation and the returned model, obtains owner context, attaches it as `AdditionalContextKind::Untrusted`, and revalidates it before final-use entry and `turn/start`. |
| `codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs` | `UnixFinalUseAuthorizer` requests an independently issued grant for the exact `runtime.codex.turn_start` binding, checks the issuer peer and current revocation state, and consumes the verified grant. |

The executable entry is
`codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs`:

```text
hepta-infer-worker --profile native-app-server
  --agentd-socket PATH --agent-id ID --generation N --model MODEL
  --journal PATH --request-id ID --maximum-in-flight N
  --final-use-authority-config ABSOLUTE_JSON
  [--context-query TEXT] [--timeout-ms N]
```

It reads the prompt from stdin. The durable request journal reconciles uncertain
dispatches rather than authorizing a replay under a fresh request ID. The values
above are interface placeholders, not an observed deployment configuration.

## What can already write, and what cannot

`codex-rs/ext/hepta-memory/src/cognitive/tools.rs` provides model-facing
`hepta_cognitive.remember`, `recall`, `correct`, `forget` and `explain` tools.
Writes require the retained production capability or the explicit qualification
profile. The turn/workspace witness is checked. A remembered value is marked
`Verified` only when its content is byte-exactly the complete current user text;
otherwise it is provisional and is not automatically attached. Correction
requires the exact directive. This is a witnessed input contract, not proof of
the factual truth of arbitrary imported source text.

These extension tools are not a Python import RPC. App Server's existing
`mcpServer/tool/call` addresses a configured MCP server through
`thread.call_mcp_tool`; it does not directly address these internal extension
executors. No reference to the Python `episodic_memory`, `episodic_retrieval` or
`hepta.mem6` schema was found in the inspected native owner/inference paths.

`AgentdConfig::with_production_writer_host` can attach an existing writer, but
ordinary process-environment startup does not create its authority. The Linux
production entry in `codex-rs/hepta-agentd/src/production_launcher.rs` retains
original Root handoff, owner process rights and recovered writer inputs.
`codex-rs/hepta-agentd/src/bin/hepta-authority-host.rs` already has
`provider-status --route`, `diagnose-native` and `launch-native` commands; the
latter require existing config, registration, native profile and a pre-held
owner pidfd. A newly fabricated authority is not recovery of that original owner.

## Missing bridge work and its required inputs

The smallest useful implementation must consume the existing writer capability
and preserve these bindings:

- Admit authorized, inspected source bytes as canonical source events; Python
  provenance fields alone cannot determine source authority or verification.
- Persist the mapping from Python authority/namespace/source/key/version/record
  identities to canonical memory IDs, revisions, citations and mutation receipts.
- Apply updates and dependency revocations through canonical compare-and-swap
  mutations, with a visible completion boundary before successor reads.
- Reconcile an owner commit whose response was lost. Reopening a bridge must not
  duplicate an import or resurrect a tombstoned canonical revision.
- Route any Python retrieval baseline through currently admitted owner candidates.
  The existing native CLI accepts a query, not an arbitrary Python selected-ID
  roster; owner revalidation must remain authoritative.

For an actual run, this requires the verified source candidate and inputs above,
the original owner socket/agent/spawn generation, the live writer grant and exact
recovery cut, the existing final-use issuer configuration, a durable request
journal, and an authenticated provider route with its observed model identity.
Matched successor experiments additionally need separate fresh threads and
scoped on/off owner state. These inputs have not been assembled by this review.
Source admission, persistent identity mapping, coordinated mutations and restart
reconciliation remain unimplemented; a JSON-to-draft wrapper does not supply them.

## Provider observation and smoke boundary

The current session reported a healthy `llama-server` on ai395 loopback port
8080, but its model-list request returned HTTP 401 and no bound
`HEPTA_LOCAL_PROVIDER_BASE_URL` / `HEPTA_LOCAL_PROVIDER_MODEL` configuration was
observed. This demonstrates service reachability, not authenticated inference,
an accepted model identity, or Responses/SSE compatibility.

`codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs` contains the opt-in
`real_agentd_loopback_provider_read_only_smoke`. It configures a fresh temporary
fleet with `wire_api = "responses"`, sends a READY-only prompt and waits for turn
completion. It neither writes/reads memory nor asserts semantic READY content.
The smoke currently accepts URL/model inputs but supplies no authentication
environment-key binding. Setting only URL/model does not establish access to a
401-protected service. The existing credential route must provide the authorized
binding; this review did not inspect credentials, change a service or run the smoke.

## Python repair versus ordinary owner integration

The current Python snapshot repair rejects impossible historical chronology and
incomplete dependency structure before filtering through the live frontier.
The retrieval repair rechecks the current authority and selected records after
ranking. Its final successful read is the linearization point for selected
content. A later revocation can still occur before the function returns or an
external effect executes. The v1 receipt remains an internal consistency record,
not a proof of independent ownership or a final-effect authorization lease.

Those changes improve the existing same-authority Python mechanism. They do not
call the Rust production writer, execute native `ThreadStart`/`turn/start`, or
satisfy the ordinary-product integration contract. The native owner revalidation
and independently authorized dispatch described above remain a separate path.
