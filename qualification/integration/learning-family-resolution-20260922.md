# Learning family convergence

## learning.eval

Normal merges retain #960 (`79e217dbd6cc44adb8b7142f5f845d9c7ea963ac`) and #903 (`279d21c726b57e1819c64b399aee436716c58a10`) history. The canonical production source is #960's `ProductEvaluationRunnerV1`, fenced CAS owner and locked-file CAS store. Direct signed V2/V3 decision ingress remains crate-private. #903's signed qualification scenario is preserved as a crate-internal test, so it cannot reopen the default direct-admission API.

The merge retains #903's exact-source and synthetic-merge evidence recorder, OIDC attestations, signed qualification stress and compatibility feature test registration. #960's coverage, product-runner, fenced holdout and runtime tests remain required. Source checks now recognize generic Rust implementation owners, the three additional EVAL cases and the actual canonical production API. #903's external-anchor adapter stays in the older file-journal compatibility surface; production composition remains the CAS-backed runner. Its stale-replica, capacity-before-CAS and indeterminate reservation tests are preserved.

Conflict resolution keeps #960's production contract, module truth and cross-crate product-runner callers while carrying #903's default-build cfg fixes. A preexisting #960 compile error in confidence receipt validation was repaired by retaining its error through `TemporalEvaluationError::Confidence`.

No release, activation or external acceptance claims are added. Test results are recorded after the integrated candidate is built.
