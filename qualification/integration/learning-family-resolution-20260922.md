# Learning family convergence

## learning.eval

Normal merges retain #960 (`79e217dbd6cc44adb8b7142f5f845d9c7ea963ac`) and #903 (`279d21c726b57e1819c64b399aee436716c58a10`) history. The canonical production source is #960's `ProductEvaluationRunnerV1`, fenced CAS owner and locked-file CAS store. Direct signed V2/V3 decision ingress remains crate-private. #903's signed qualification scenario is preserved as a crate-internal test, so it cannot reopen the default direct-admission API.

The merge retains #903's exact-source and synthetic-merge evidence recorder, OIDC attestations, signed qualification stress and compatibility feature test registration. #960's coverage, product-runner, fenced holdout and runtime tests remain required. Source checks now recognize generic Rust implementation owners, the three additional EVAL cases and the actual canonical production API. #903's external-anchor adapter stays in the older file-journal compatibility surface; production composition remains the CAS-backed runner. Its stale-replica, capacity-before-CAS and indeterminate reservation tests are preserved.

Conflict resolution keeps #960's production contract, module truth and cross-crate product-runner callers while carrying #903's default-build cfg fixes. A preexisting #960 compile error in confidence receipt validation was repaired by retaining its error through `TemporalEvaluationError::Confidence`.

No release, activation or external acceptance claims are added. Test results are recorded after the integrated candidate is built.

## learning.ledger

Normal merge history retains #738 (`91283d7b133f16ad0ac73cc01ea691bc0f6b156c`) and #869 (`3b361d7ff147d095bebd1749fef476b60884f79d`). The canonical writer, independent witness, typed V2 records, dataset membership, unlearning handoff and protocol adapters come from #738. #869's optional post-append witness facade and competing `trust_root`, `index_checkpoint`, `unlearning` and `convergence_tests` modules are superseded. These cannot be combined by registering both codecs: #869 assigns event tag 4 to authenticated Outcome V1 while #738 assigns it to authenticated Outcome V2 with a different layout. V1 tags 0–3 retain the canonical reader; experimental divergent branch formats are not silently accepted as the same protocol.

Preserved unique #869 semantics:

- Raw durable/segmented appends are crate-private. `qualification-legacy-write` is an explicit non-production escape hatch for historical fixture writes. The sealed journal port exposes default read access; product mutations use `LedgerWriter`.
- `LedgerWriter::rotate_trust` applies live root-signed successor distributions through the canonical activation validator. Revocation and rollback tests verify denied writes and unchanged witness/state after rejected rotations. This preserves live rotation without admitting a caller-asserted trust provider.
- `measure_ledger_recovery_work` validates canonical replay and binds record counts, actual encoded event bytes, largest record and the current chain. The 8,192-record recovery test is retained. #738 already supplies an equivalent 4,096-record content-addressed checkpoint test, so the duplicate #869 checkpoint type is retired.
- The durable workflow also tests actual evaluated-shadow composition; it does not gate the product caller behind the old qualification-only feature.

The integrated evaluated-shadow caller seals the qualified generator into `ProductQualificationReceiptV1` (evidence digest domain v3), requires that same generator to sign `ProductionDecisionV2`, and writes through the witness-owning ledger. The receipt test rejects generator substitution. Initialization of an empty segmented ledger now leaves its empty witness unchanged until the first record, matching existing witness validation and eliminating an invalid zero-digest metadata advance.

## Validation

The composed source passed 286 focused nextest tests across learning.ledger, learning.eval, intelligence and cross-crate shadow qualification (one preexisting skipped test). The explicit trusted evaluator compatibility test also passed. Earlier test failures exposed and corrected a missing confidence-error conversion, a reused holdout ID in a divergent-history fixture, an ineffective tamper mutation, and initial segmented witness metadata admission. Lane E verification and self-tests are run against the final registries. Source qualification does not constitute external acceptance or release evidence.
