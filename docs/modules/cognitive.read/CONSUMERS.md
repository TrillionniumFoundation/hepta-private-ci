# cognitive.read consumer migration and evidence matrix

This supplement separates contract registration, source composition, normal-product execution,
independent acceptance and activation. A registered port is not a completed migration, and no
row below grants authority. Durable facts remain with their existing owners.

The reviewed machine policy is
[`CONSUMER_POLICY.json`](CONSUMER_POLICY.json). The exact-candidate audit
`scripts/cognitive_read_consumers.py` verifies the closed seven-consumer registry, each
consumer implementation-map blob, declared source roots, direct read-interface references,
mapped operation and test blobs, mapped normal-product callers and their symbols. The audit
is intentionally source-only: it never changes `productExecutionProved`, acceptance or
activation.

## Reviewed consumer states

| Consumer | Declared product caller state | Current read boundary | Normal product caller(s) recorded by the consumer map | Migration assessment |
|---|---|---|---|---|
| `compact.engine` | `not_composed` | Exact-owner candidate API and fixtures exist; no normal caller or checkpoint publication is claimed | None | Candidate source implemented; product composition pending |
| `context.compiler` | `legacy_v1_composed_revision_bound_v2_ingress_source_implemented_product_use_pending` | Legacy V1 product adapter plus local revision-bound V2 ingress | `hepta-agentd/src/intelligence_product.rs::compile_context` | Legacy source composition exists; V2 provider-bound product use remains pending |
| `memory.federation` | `composed_candidate_pending_execution` | Registered local-owner composition | `hepta-agentd/src/runtime.rs::attach_federation_after_generation_fence`; `ext/hepta-memory/src/cognitive/federation.rs::CombinedCognitiveEphemeralContributor` | Source composed; exact product execution remains pending |
| `memory.retrieval` | `source_composed_explicit_profile_not_product_qualified` | Exact owner cut through Agentd cognitive context | `hepta-agentd/src/cognitive_context.rs::read_prepared_with_retrieval_context_and_learning` | Normal source path exists; product qualification remains pending |
| `neuron.runtime` | `agentd_owner_source_compiled_not_daemon_lifecycle_composed` | Registered context input; no direct cognitive.read migration is claimed | `hepta-agentd/src/neuron_runtime.rs::AgentdNeuronOwner`; `hepta-intelligence/src/neuron_runtime.rs::run_neuron_tick_v1` | Owner source compiles; daemon lifecycle composition remains pending |
| `objective.compiler` | `source_composed_authenticated_agentd_not_activated` | Registered context input through the authenticated objective host | `hepta-agentd/src/objective_runtime.rs::submit` | Authenticated source composition exists; activation and target-host evidence remain pending |
| `utility.ndu` | `request_local_read_only_established_authenticated_owner_source_candidate_not_product_composed` | Request-local deny-all planning chain | `hepta-agentd/src/intelligence_product.rs::evaluate_utility` | Request-local read-only path is separately recorded; authenticated production owner composition remains pending |

These strings are not manually normalized status labels. The policy binds the exact
`productCallerState` currently published by each consumer implementation map. A state change
therefore requires a reviewed policy update and a fresh exact-candidate audit rather than
silently changing the interpretation of an old artifact.

## Final-use and error ownership

The per-consumer policy records four separate facts:

1. the adopted read boundary, including whether no direct migration is claimed;
2. the owner responsible for final-use currentness;
3. the required error distinctions at that consumer boundary; and
4. the execution evidence still required before migration can be called complete.

For example, `memory.retrieval` keeps the owner cut in the memory owner, while Agentd and the
native worker revalidate the selected ID, revision, content and retrieval-context bindings.
`context.compiler` keeps compiler admission separate from the provider/model-use owner.
`utility.ndu` keeps request-local evaluation deny-all and leaves effects or durable mutation
to independent authority owners. These responsibilities are not replaced by a successful
lexical source scan.

## Machine-readable source audit

Run:

```bash
python3 scripts/cognitive_read_consumers.py \
  --expected-sha "$(git rev-parse HEAD)" \
  --output .hepta-evidence/<new-run>/consumers.json
```

The V2 source-audit artifact includes:

- candidate commit and tree;
- registry and policy blobs;
- consumer implementation-map blob;
- declared source roots;
- direct read-interface references and exact blobs;
- mapped operations and test blobs;
- normal product caller paths, symbols, states and exact blobs;
- the reviewed migration class, final-use responsibility, error mapping and required
  execution evidence;
- the consumer map's narrow claim flags; and
- the shared owner-acquisition, request-local prepared view, Agentd final-use and physical
  worker composition symbols.

Missing files, missing caller symbols, policy/map state drift, an unreviewed consumer or an
active consumer map fail the audit. A passing audit still states
`product_execution_proved_by_audit=false`.

## Exact execution matrix

[`CONSUMER_EXECUTION.json`](CONSUMER_EXECUTION.json) maps every registered consumer to the exact
package and normal-product gate names used by the read-only qualification runner. The source-head
and deterministic merge receipts record the exit state for every required gate. They do not
collapse distinct migration states:

- package gates prove that the exact consumer package compiled and executed nonzero tests;
- the authenticated intelligence product fixture exercises the existing context, objective,
  neuron and NDU owner calls but does not claim verified V2 read ingress;
- federation owner and extension tests exercise the existing local product source path but do
  not claim cross-host authentication;
- the retrieval row additionally requires owner expiry/rollback, stale host-generation, read
  replay and the physical worker final-use case; and
- `compact.engine` remains uncomposed even when its package and candidate API
  fixture gates pass. `build_cognitive_read_compaction_candidate` constructs
  deny-all evidence; it does not publish or persist a checkpoint.

The qualification receipt explicitly writes `v2_migration_proved=false` for all seven rows.
Advancing a row requires a new normal-product caller state, reviewed policy change and a fresh
exact source/merge receipts rather than reinterpretation of these package results.

## Promotion requirements

A consumer advances only when its normal product entry, exact caller blob, build
configuration, relevant error mapping, final-use owner and exercised tests are captured in
an immutable exact-head and deterministic merge receipt. Direct source references do not
prove that a cfg/module path compiled; mapped tests do not prove that they ran; a historical
receipt cannot be rebound to a changed caller or policy.

The current durable SQLite adapter remains `Fact`-only. Supporting `Episode`, `Preference`
or `Procedure` requires an owner schema migration and rollback interpretation, not a read
port enum cast.

V1 legacy citation ID/digest sets still lack authoritative source revisions. The additive
revision-bound V2 shadow accepts only explicit owner-issued ID/revision/digest bridges and
validates them against canonical provenance. It does not silently upgrade V1, compose a
consumer, or grant final-use authority.

`ReadIdsResultV1`, `ReadResultV2` and both canonical shadow digests remain local integrity
formats. They are not admitted cross-process protocols. New transport requires explicit
versioned protocol admission and consumer migration.
