# Native Q24 frozen-prefix proposal contract (research-only)

**HOLD_NO_GO / DENY_ALL.** This is a narrow Rust reference API isolation increment on top of [#5855](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5855) (base 17bd0d3cadafd8a6345c84028da6622c253d3f09), not a production Owner attestation, an effectiveness result, or an adopt permission.

accumulate_frozen_temporal_credit_q24 rejects **all** feedback with declared available_sequence > cutoff_sequence; it allows no feedback as a real missing-outcome/zero-delta case. The public FrozenTemporalCreditProposalV1 cannot carry the complete-input transcript_digest or withheld_future_feedback_count. A forensic caller may still explicitly use the original accumulate_temporal_credit_q24 with its complete audit fields, which are **not eligible for frozen selection**.

The native unit tests check no feedback, cutoff rejection, canonical action/group/feedback permutations, owner/model/split drift refusal, and exact agreement between the restricted prefix and the forensic prefix. They are **synthetic contract tests** only. Neither source/feedback digests nor the caller-declared observation clock are authenticated. A malicious caller can backdate a feedback receipt; the native Owner must enforce data custody, effect provenance, immutable model/generation identity, observation timestamps and independent future-evaluator isolation before candidate review. The returned AuthorityPosture remains DENY_ALL.

**Unclosed:** original StageOwner source/action/feedback chain; genuinely independent evaluator B; A→actual training→NoUpdate/Adopt→different task C→cold recovery; seven-lineage/matched-cost sparse+dense ACT/CTRL tests; MEM exact RAG, typed replay, deletion and retention; and Core×NDU 2×2 attribution. No production authority, model installation, or auto-deploy is changed.

Run from codex-rs: cargo test -p codex-hepta-neuron frozen_native_prefix --lib --locked, followed by cargo test -p codex-hepta-neuron --lib --locked.
