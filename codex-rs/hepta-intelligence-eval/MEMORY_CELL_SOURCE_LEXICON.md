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

## Question-value binding specificity (new research diagnostic)

The source K-way report now contains question_value_binding: a two-question,
two-value interaction computed from the SAME already-journaled base and
adapter likelihoods. It never calls the reader again. If adapter training
merely boosts a value globally, its question-independent preference cancels
and earns no binding specificity gain. A positive specificity shift is
not yet a correct free-generated answer. A two-question pair whose two targets
are identical, whose completion lengths differ, or with an actual failed
likelihood call is recorded explicitly, not scored as an improvement.

The full candidate vocabulary is source-derived and nonparametric. Paired
questions and their target values were visible during earlier source training:
they are NOT independent future generalization or statistical support.
The baseline prompt and reader are unchanged, original K-way results remain
in place, and the report maintains zero additional model calls. No semantic
entailment or citation certification, policy acceptance or production state
is changed; review gates remain fail-closed.

## Audit precision on odd question counts and finite score arithmetic

The same post-journal question/value test must preserve *every* originally
planned source question, including the valid one-question case created by
`maximum_questions=1`. An unmatched question cannot establish a
two-question interaction. The readout therefore retains an explicit
`unpaired_source_questions` count and hashed identities, alongside
`all_planned_questions_accounted`. It neither silently drops the question
nor imputes another likelihood or comparison.

The symmetric binding score uses averaged per-token losses on the unchanged
source lexicon. We separately check input NLLs and every intermediate margin
and adapter-minus-frozen delta for finiteness, computing each half-margin
before addition to avoid an avoidable floating-point overflow. Any
unrepresentable cross-model effect fails closed, rather than being counted as
an arbitrarily large adapter gain. These are accounting and numeric-safety
changes only: no Reader/model call, training sample, cohort size, inference
prompt, or claim of parametric recall/generalization is altered.
