# Organ composition, extension and composite state migration

This is a proposed execution profile for existing `PLS-*`, `SELF-1`, `EMB-*` and `ASM-*` packages. It changes no data owner, production protocol, permission, selected body or release. Existing `StateHandoffReceiptV1` remains same-owner and cardinality-preserving; the composite design here requires separate native admission.

## 1. Four graphs, not one ambiguous body DAG

Maintain distinct initialization/ownership, runtime dataflow, fallback and deployment/failure-domain graphs. Initialization dependencies are acyclic and topologically ordered. Fallback edges are acyclic, terminate in a qualified safe state or human takeover, and never widen authority. Deployment edges describe shared process/host failure domains rather than execution precedence.

Runtime dataflow may contain feedback. Compute strongly connected components and require a bounded feedback profile for each cycle: sample periods, delays/jitter, gains, saturation, queue/buffer bounds, operating region, reference generation, stability analysis, perturbation tests and deterministic exit. A local safety loop cannot depend on synchronous central cognition. An acyclic startup graph does not prove feedback stability, and a stable sampled linearization does not prove all nonlinear operating regions safe.

The current body graph's dependency edges retain their original acyclic meaning. A feedback profile is a separate versioned relation, not a reinterpretation of the same serialized edges. Update native producers/consumers and compatibility fixtures before enabling it.

## 2. Open evolution through closed run generations

Forty is the registered source baseline, not a claim that no future module can exist. Each running generation is closed and fully validated. A new organ uses an admitted factory/template with exact code artifact, typed ports, effect classes, resource envelope, owner, probes, dependencies, state format, failure domain and rollback. Unknown code or ports cannot enter the current generation by naming a new organ.

Adding a genuinely new source module or fact owner requires ordinary reviewed module/data-authority/package registry evolution and compatible verifier updates. It is not performed by the optimized candidate modifying its own admission tests. Creating another instance of an already qualified organ is distinct from adding new code or authority.

One logical CNS coordinates objectives, value, world hypotheses and plans. Local motor/reflex/brainstem services preserve bounded safety and liveness independently. The executive is neither the owner of every database nor the issuer of its own permissions.

## 3. Structural search and objective accounting

Use at most 32 total candidates including no-change, eight sandboxes and one typed structural operation per initial candidate. `add` names an independently observed capability gap; `split` improves a measured bottleneck or isolation need; `merge` preserves role independence and supported lineage; `rewire` verifies ports and feedback/fallback constraints; `retire` proves consumers/drains/history disposition.

Filter hard feasibility first. Then compare independent task utility, retained tasks, reliability, complexity, memory/energy/latency, migration downtime and rollback cost. An improved internal NDU score is not an independent success observation. No operation changes the user's objective to make itself win. Unsupported estimates, duplicate ratio >=50%, exhausted budget, base drift, unavailable evaluation or failed rollback stop the search.

## 4. Composite state partition contract

Before split/merge or owner transfer, bind the source domains and exact record range to a deterministic mapping from every retained source fact to exactly one target domain/partition. Duplicated read projections are allowed only as non-authoritative projections with declared source support; duplicate authoritative writers are not.

The mapping is total on retained records, disjoint across authoritative partitions, preserves correction/tombstone ancestry and records any explicitly authorized deletion separately. Cardinality changes require a reconstruction/provenance relation and domain invariant checks, not just equal record counts. For a merge, define source-ID collision, revision ordering, schema compatibility and conflicting evidence handling; do not select last-write-wins for authoritative facts.

A source fact that cannot be mapped blocks cutover. A new domain/owner is inactive until the canonical registry update and independent authorization exist. Validate resource and downtime feasibility before migration, not only after the target has consumed production capacity.

## 5. Durable multi-party barrier

The coordinator stores evidence references, not migrated domain facts. Each source owner retains its own durable phase and inventory. The forward phases are prepared, admission_stopped, drained, old_writer_fenced, snapshotted, migrated, validated, new_writer_fenced, route_published and retired.

Prepare all participants. Stop old business admission. Drain to explicit watermarks and reconcile/quarantine unknown effects. Fence every old writer in the affected atomic cut. Snapshot exact ranges. Transform only in non-authoritative targets. Validate counts/digests, partition conservation, current revocations, readers and rollback. Establish fresh target fences without opening business admission. Publish one independently selected body/route generation atomically through the owning route service. Open new admission only after route publication. Retire after consumer migration and retention obligations.

Persist every phase before acknowledging it. Receipts bind operation, source/target hosts/manifests, domains, authority epoch, old/new generations and fences, exact range/count, watermarks, unresolved-effect inventory, migration/profile digests, partition manifest, revocation frontier, target digest, route, rollback and independent witnesses. Hash chains are immutable. Identical retries observe prior progress rather than execute another effect; changed semantics under one identity conflict.

Do not claim one distributed transaction when no atomic route service spans the participants. In that case choose and admit explicit per-partition cutovers with mixed-generation reader compatibility, or remain stopped. A coordinator timeout is not evidence that another participant rolled back.

## 6. Recovery and rollback after new writes

At every phase, restart reads durable progress and current authority, never PID start order. Before new admission, resume the compatible predecessor only with a fresh fence and current revocation overlay. After route publication, accepted successor writes must survive rollback: stop/drain/fence the successor, include its delta to a validated reverse or forward-compatible migration, then publish a new route generation.

If no valid reverse path exists, roll forward with a repaired compatible target or quarantine for independent recovery. Do not restore an old snapshot and silently discard acknowledged successor writes. Never restore a revoked predecessor, old lease or stale deletion frontier. Compensation of an external action is a separate authorized action.

## 7. Acceptance matrix

Property fixtures cover initialization/fallback cycles, unqualified feedback cycles, missing ports, source duplication/omission, cross-owner changes without registry admission, stale fence, changed digest retry, route publication before validation, two simultaneous valid writers and post-cutover delta loss. Fault injection interrupts each participant and coordinator before/after every phase.

A successful analytic partition or state-machine fixture is not evidence that the native composite migrator exists. Integration requires compiled schema, real owner producers/consumers, authenticated witnesses, actual store transformation and crash qualification. Operator acceptance and rollout remain separately issued decisions.
