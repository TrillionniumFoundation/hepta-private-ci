# N256 dense-compatible action-boundary intent

**Status: HOLD / source-only design / execution disabled / not qualified.**

The frozen sparse candidate in Draft #6823 completed one N256 warm step and two
`scipy.sparse.linalg.expm_multiply` actions, but its preregistered bitwise gate
against the independent dense oracle remained RED: 1,291 of 69,728 FP64 values
differed. Draft #6824 preserves that result and its originals. The mismatch is
not repaired, rounded, tolerated, or reclassified here.

This independent intent freezes the only compatible next experiment currently
supported by the read-only localization: retain CSR construction and its
structural checks, then materialize the already assembled augmented action
matrix and reproduce the dense oracle's exact `scipy.linalg.expm` and matrix
multiplication order at the action boundary. That is a different kernel and a
new lineage. Even if a later separately admitted run passes, it could establish
only a CSR-assembly plus dense-compatible first-step result; it cannot qualify
the sparse `expm_multiply` kernel.

No executable candidate is included. `execution_allowed` is false, the
idempotency key is null, and the verifier uses only the Python standard library.
Before any numerical work, a later source must freeze the implementation,
runtime, archived oracle, input, exact counter budget, independent reviewer,
and a new single-use key. The 69,728-coordinate bitwise gate remains unchanged:
no tolerance, ULP allowance, coordinate omission, or post-processing rescue.

Historical RED, OOM, cancelled, and UNKNOWN records remain unchanged. N512,
later cycles, arbitrary histories, finite-domain all-box accuracy, full prior,
migration, full-network AD/training, same-budget task benefit, asynchronous
complete cost, C2 full replay, HPCA external custody, production, and adoption
remain open. Global `all_closed=false`, HCSN HOLD, HPCA NoUpdate, and C2 full
replay 0/6 remain.
