# Source-owned proposition admission

Status: native source candidate, not an executed qualification or activated writer. This amendment covers the explicit SQLite proposition path and the ordinary signed provider optimization. Read with `TECHNICAL.md`, `API.md`, `PROCESS_BOOTSTRAP.md` and `IMPLEMENTATION_MAP.json`.

## Existing ownership and additive input

The content, source, revision and KG writer remains `codex-hepta-memory::CognitiveStore`. `remember_with_assertions` and `correct_with_assertions` run the existing source append, exact citation binding, memory revision/CAS, immutable KG fact insertion and projection publication inside one `BEGIN IMMEDIATE` transaction. They introduce no second store, caller-supplied authority or new model invocation.

The affirmative `KgFactSetDraft` declares the common entities and affirmative relations. A separate relation slice supplies explicit negative assertions over those declared endpoints. Both sets share the existing 64-entity/128-relation ceiling. The source content must exactly match the memory input. Only verified active revisions carry facts. Correction replaces the entire assertion set under the existing expected-revision fence; ordinary tombstone/correction invalidation still applies.

This API is an owner-backend candidate. The independently admitted production writer and real extractor still need explicit composition and qualification before source text can produce these declarations in the ordinary product. A typed assertion does not prove that its source statement is true.

## Versioned persistence, not legacy relabelling

The new immutable fact-set contract is `structured_cognitive_propositions_v2`. Within that contract alone, `hepta_asserted_v2:<predicate-sha256>` and `hepta_denied_v2:<predicate-sha256>` distinguish explicit polarity. The predicate digest uses the existing owner canonical-token rules. Canonical subject/object identities, fact-set digest, exact source revision, exact memory revision and applicability interval remain owner-bound.

Historical `structured_cognitive_kg_v1` rows are not reinterpreted, even if an arbitrary historical predicate happens to match a new prefix. `Contradicts` remains conflict-report evidence, not an inferred negation. The new representation does not silently upgrade a generic relation into a causal/procedural channel. No old serialized cognitive wire is redefined.

## Coherent observation and admission

`observe_memory_retrieval` reads all explicit claims for the exact bounded observed revisions in its existing SQLite read transaction. Each revision allows at most 128 claims; the observation allows at most 4096. Overflow fails closed; it is never silently truncated. Claims are digest-sorted and validated before score filtering.

A no-assertion observation retains its predecessor V1 digest. An observation containing explicit assertions uses the distinct V2 observation domain and binds the predecessor observation plus every claim's evidence digest. Consequently existing owner-support/generator/candidate-union receipts transitively bind all observed claims, not only the selected or conflicting claims.

The product adapter derives the same positive-score, score-floor-admitted exact revision set as retrieval. At the declared observation time, opposite polarities conflict only for the same canonical subject/predicate/object/scope. Applicability is half-open: `valid_from <= time < valid_to`; open-ended intervals remain open. Time is an eligibility condition, not an equality shortcut: overlapping but unequal intervals can conflict, while disjoint intervals cannot. Multiple propositions in one revision are retained and evaluated.

When the selected policy requires contradiction abstention, the adapter emits an explicit contradictory-evidence abstention, no selections, recomputed recall receipts and an assignment matching that abstention. Source-currentness revalidation remains downstream. This implementation initially reconstructs the bounded union for auditability; fusing that work requires differential qualification, not an approximate replacement.

## Signed provider and parser changes

`install_and_acquire` uses one fresh challenged frontier observation for a combined installation/acquisition and returns the payload, publication identity and signed deadline under the same provider lock. A concurrent observed rotation/revocation cannot splice another publication into that result. Every acquisition still observes the owner; this is not a freshness TTL cache. Same-payload renewal changes lifecycle identity and identical reinstall does not extend the monotonic lease.

The ordinary file provider caches only successful parsing by the exact original publication bytes. It still reads the protected bounded file, verifies the signature/native context and observes the independent frontier on every acquisition. Changed, invalid, missing or oversized bytes never fall back to a cached payload. Context cloning remains and must be measured.

All six optional bootstrap v2 fields now distinguish absence from explicit JSON null. Omission retains v1 semantics; present null is invalid. This prevents v1 descriptors from smuggling v2 field names as null and preserves strict duplicate/unknown-field handling.

## Required tests and unfinished work

`cognitive_proposition_owner_tests.rs` exercises the real SQLite writer/observation/adapter path, opposite assertions, CAS correction, multi-proposition revisions and legacy-label noninterpretation. Proposition unit tests cover scope, time overlap, wrong revision and malformed/duplicate input. `cognitive_retrieval_acquisition_tests.rs` exercises actual provider calls, single-observation acquisition, renewal, revocation and wrong request identity. Parser/cache tests exercise null, duplicate fields, cache misses and failure paths. These are test source identities until exact-head native execution records their outcomes.

The following are not closed by this amendment: real extractor/production-writer admission of assertions; current-head native and ordered-parent merge qualification; prepared/published/consumed delivery-ledger convergence; protected launcher and independently durable frontier recovery; bounded cancellable shadow scheduling and measured resource isolation; native nine-stage measurement/counters; real encoder/vector-index composition and calibrated OOD; independent rollout and operator acceptance. Production, acceptance, activation and release claims remain false.
