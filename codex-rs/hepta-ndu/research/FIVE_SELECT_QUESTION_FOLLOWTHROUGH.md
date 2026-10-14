# SELECT same-source question followthrough: saved models, no new fitting

Date: 2026-10-14. PR #1697. Parent/required training source:
644799a3ec45e18e77ce4ad772029f67fee55db7. At publication this is an
implemented protocol, not a completed model result. Local container/private
and visible Python returned ClientError; no local test pass is asserted.
No old source, loss, training budget, result, production owner or gate changes.

## Why the missing matched-question comparison matters

The question-relevance study trains on matched and mismatched questions with
IDENTICAL nonempty donor evidence. Its TRAIN generation includes both questions,
but its sealed SELECT generation contains only own sources, empty input and
mismatched donor sources. The original SELECT four-score content statistic
compares two answer bodies under different sources, not answer versus refusal
under two different questions on the SAME source. These are different questions.

A model that simply rejects every nonempty donor source could improve the
mismatched-refusal count without recognizing relevance. This new, separately
registered development protocol adds the missing original donor question on
that exact donor source. It requires both sides of the selective behavior to
remain visible. No new training is selected based on a hoped-for result.

The upstream training result was still running when work began. Its source and
run38512395172 are fixed. The workflow verifies COMPLETED/SUCCESS, exact source,
unique artifact name and GitHub artifact SHA before downloading its bytes.
The chosen metadata is saved. An unfinished or failed upstream run blocks the
study with a nonzero status BEFORE any Reader load, without old-checkpoint
fallback, automatic refitting or assertion of successful scientific execution.
It does not poll or silently repeat upstream training.

## Freeze the existing donor, recipient and checkpoint identities

Inputs are the exact prior SELECT result11863981474 (SHA
 aeb4113b6d2baace0a042f960876861c78b5449b6d9dac404dee2e5c041e46fa)
and the complete original question-relevance result. Every result-archive member
is verified before extraction; archived Python is never imported. The original
model archive retains its separate fixed SHA and existing clean-stage checks.

Keep all four prior SELECT recipients and each already chosen donor. Do not
expand the donor inventory, search for a shorter source, repair annotations,
read TEST labels or replace the missing-reference question. The donor's original
question and answer come only from the already sealed SELECT pool. There is NO
optimizer access to this material. SELECT remains exposed DEVELOPMENT, not
untouched independent confirmation. Weak donor annotation is not an external
sufficiency judgment and superficial entity cues remain possible shortcuts.

Build (q_d,D) and (q,D) with identical source bodies, dates, order, positions and
local S1/S2 citations. Options also remain equal. Only the question changes.
The donor's complete answer with the same citation suffix and the prescribed
refusal are scored in both contexts. Compile all four sequences before loading
any Reader; a failed selected pair cannot trigger another donor search.
All reference-bearing available pairs must compile. Missing references retain
null slots in every model's generation/audit denominator.

## Pay only the missing model work

All four saved candidates are included, fixed before observing this followthrough:
frozen_reader, repeat_empty, nonempty_aligned and nonempty_reversed. No best-arm
selection. Existing snapshot/compose/attach/verify_resident code owns loading.
The original rank4 q/v adapter and each exact saved receipt remain bound. No
unqualified projection, dynamic adapter switch or new model family is used.

Mismatched SELECT raw answers are taken from the completed upstream artifact.
Join every original trial by arm, slot, question, condition and exact input hash;
check all aggregate and arm-level seals. No answer is regenerated or edited.
Only the missing matched-question request is generated, once per unique public
input within each arm, with recipient multiplicities preserved separately.
With the current three reference-bearing pairs, there are at most12 new free
calls across four arms and48 likelihood forwards. These are expectations, not
results; deduplication or missingness can change observed call counts. Reused
answers are never counted as new calls or new independent tasks.

New free answers seal per arm before teacher-forced scoring. Counters retain
actual decoder dispatches, failures, late deadline outputs and process measures.
No energy/FLOPs/whole-model peak or matched-total-cost advantage is inferred from
reusing saved answers. Loading four distinct candidate instances costs resources.
All new models stay frozen and must pass final saved/base integrity checks.

## Separate likelihood, behavior and correctness

For the donor answer a and refusal r, report:
 m_match = l(a|q_d,D) - l(r|q_d,D)
 m_mismatch = l(r|q,D) - l(a|q,D)
 I_question = m_match + m_mismatch.

l is mean assistant-token log probability including the unchanged citation/end
suffix, not calibrated correctness. Both margins must be positive to satisfy
the weak two-direction criterion. Positive I_question alone is not sufficient.
The reversed training control is evaluated against the SAME intended orientation,
never regraded against its intentionally wrong supervision direction.

Generation separately records matched refusal, mismatched refusal and their
JOINT behavior on each pair. Always-refuse and always-answer fail the joint
nonrefusal/refusal proxy. But a wrong nonrefusal can still satisfy that proxy:
semantic_accuracy stays null, and exact sources/answers are retained for genuine
independent review. No reviewer forms or independent human identities are made.

Report all planned recipients, jointly observed pairs, missing/failed cases,
per-pair margins, task means and family-macro means. Donor reuse is dependent;
no iid confidence interval, significance, reasoning emergence or formal Reader
qualification is asserted. Tests and green execution are not semantic evidence.

## Implementation and initial validation status

New files: select_question_relevance.py, select_question_relevance_trial.py,
test_select_question_relevance.py, test_select_question_relevance_hf.py and the
scoped workflow hepta-select-question-relevance.yml. Pure tests exercise frozen
identity joins, all missing slots, nonempty input equality, unchanged donors,
common targets, null scoring and joint behavior. Three required official tiny
Llama tests exercise actual four-forward scores and full vocabulary shapes,
collapsed-tokenizer rejection and no truncation/alternative-donor fallback.
They are submitted definitions until the exact-source job is observed passing.
The workflow keeps the inherited official model/learning/regression suites.

No old training is retriggered by these new file names. No main/CURRENT update,
forced push, default projection change or admission bypass occurs. Five formal
causal experiments, independent final-answer improvement, shared-versus-replicated
lifecycle savings, learned Group/NDU benefits, actual multimodal/split transfer
and native FinalUse/target-device acceptance remain separate work.
