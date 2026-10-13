# Source-lexicon readout (research diagnostic only)

The `source_candidate_kway.py` addition to the source-before-task workflow freezes
one source scope with 2–16 distinct ORIGINAL source-derived values, and tests up
to two preselected source questions with paraphrased wording. The COMPLETE
same-scope candidate lexicon is identical for the disabled/enabled LoRA reader;
missing, duplicate or overflowing scope candidates are excluded as a WHOLE,
never ranked down using the correct label. Actual reader prompts have ZERO
source evidence. The only model difference within a matched K-way row is the
existing source-written LoRA adapter. Raw conditional-likelihood attempts are
persisted before any label comparison. Incomplete model calls widen explicit
missing-outcome bounds; those bounds are not 95% confidence intervals.

**This is NOT a pure parameter-only result.** The scoring procedure receives
the candidate values extracted from the original source corpus, which is a
non-parametric lexicon and must be counted as such, including scanning and
storage costs. Conditional NLL ranking over an external closed set is distinct
from unconstrained answer generation. These are exposed source-training facts,
not independent transfer tasks, reviewer-certified semantics or production
acceptance. A positive signal would motivate genuine previously unseen source
families with the same reader and strong RAG/tool controls; a negative signal
would isolate weak entity/relation binding before spending on larger LoRA.

Exact observed outcomes are reported only after their generating workflow
reaches terminal success and a complete immutable original answer journal exists.
Source-only diagnosis never changes default serving, selected-LoRA production,
source authority, independent reviewer requirements or existing CI gates.
