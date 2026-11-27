# Frozen-prefix Q24 proposal surface — research only

**Status: HOLD_NO_GO / DENY_ALL.** This increment closes a narrow
reference-interface leak risk; it does **not** establish owner attestation,
actual training, model effectiveness, independent future evaluator, production
admission, or an Adopt/NoUpdate/NextUse lifecycle.

The historical `time_aligned_credit` reference intentionally returns a
`transcript_digest` and `future_withheld` for complete-input auditing.
Those fields may depend on post-cutoff feedback; a selector must never use
them as features, model identity or candidate-selection keys. A separate
`causal_training_digest` fixes frozen prefix identity but does not prevent an
unsafe caller from choosing a full-audit field.

`frozen_prefix.frozen_prefix_proposal` exposes only declared visible feedback,
causal digest, group deltas, matched/expired counts and explicit `DENY_ALL`.
It rejects any receipt whose declared availability is after cutoff and admits
the zero-feedback case. Its result type has **no** complete-input audit digest
or future-feedback count. The historical full-audit function remains unchanged
for forensic use.

The eight new unit tests check zero feedback, future-input rejection,
duplicate/forged/pre-action rejection, expiration, causal identity agreement
with the complete audit and absence of forbidden output fields. All are
**synthetic contract tests**, not experiments demonstrating neural benefit.

**Unclosed trust boundary:** `available_sequence`, source digests and
feedback values remain caller assertions. A malicious caller can backdate a
receipt; this adapter cannot detect it. A real native Owner must independently
authenticate source, action time, feedback receipt, model/generation, cutoff,
evaluation partition and observation clock, then keep future B labels
unavailable to selection. Only a real Owner can issue verified source/effect
provenance, frozen evaluator and actual outcome receipts.

Additional unclosed gates: ordinary A→real training→independent B→actual
NoUpdate/Adopt→different C→cold recovery, full-cost seven-lineage and
sparse/dense ACT/CTRL comparisons, MEM deletion and retention and Core×NDU
2×2 attribution. Do not merge into production, auto-promote or deploy.

Run in this directory: `python3 -m unittest -v test_frozen_prefix.py`.

This small change does not touch HPCA V2 training, MEM, native Rust Q24,
Agentd or other concurrent PR branches.
