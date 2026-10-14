# SELECT content validation after a zero-coverage donor study

Date: 2026-10-14. PR #1697. Parent: 051c21c6dd0abe9a610bf0a2c6666727fd727e4e.
At initial publication these are submitted sources, NOT completed tests or
model observations. Local container and Python probes returned ClientError.
No main, CURRENT, production Reader, admission rule or old result is changed.

## Observed reason for this new protocol

The latest saved-model content study (7a94d9e5, run38493158981) completed with
356 distinct tests and100 real generation calls. Its TRAIN content interaction
was stronger on average for aligned8 than frozen or shuffled8, but not uniformly
better. All three reference-bearing SELECT comparisons lacked a valid donor
under the old selected-recipient pool. The old result is missing validation,
not zero validation effect and not proof of transfer. Its signed/raw evidence
and missingness remain unchanged in FIVE_CONTENT_SWAP_COMPLETED_7A94D9E5.md.

Increasing training again before resolving that missing comparison would not
answer whether the already saved content signal transfers. This increment
therefore performs ZERO optimizer updates and adds no model. It reuses the
original frozen Reader plus exact saved aligned8 and shuffled8 adapters from
artifact11838105827. The failed assistant-projection path remains unqualified;
all likelihood calls retain full-logits-v1 and original tolerance semantics.

## Separately registered SELECT-only donor inventory

The NEW profile is hepta.reader.select-donor-inventory.v1. Recipient questions
are exactly the prior fixed-budget SELECT generation questions. No TRAIN
recipient or TEST target is evaluated in this run. Only the donor inventory
expands: census ALL questions in the existing SELECT source partition, then
retain every eligibility decision. Donors require an available answer and
1--3 resolved annotated sources. Source body, order, session time and exact
answer annotation are not repaired. No count truncation, date inference or
replacement of a missing recipient answer is permitted.

The actual original reader_content_swap.build_comparisons function still selects
same-partition, cross-family, equal-source-count, distinct normalized answer and
source-body pairs by its original identity hash. This is not a looser pairing
predicate, but it IS a new inventory and new development experiment after the
old missingness was observed. It must not be relabelled as the old preregistered
result. Donor labels are weak annotations, not independent proof of semantic
falsity or insufficiency. All SELECT donors have now been exposed by inventory
preparation; do not call them untouched future confirmation.

TRAIN/SELECT/TEST family, source-scope and root metadata are checked before
SELECT-only target reads. Unknown or mixed partitions fail. Common short text
alone is not asserted to prove duplicated provenance; true novelty/independence
still requires separate review. Entire source and pool identities are sealed.

Original selected recipients, including a missing reference answer, remain in
the public generation census and the audit denominator. Missing scores are
null, never zero effects. Same question/options, neutral S1,S2,... citations and
original body/date representation follow the old control. Different source
lengths are not an equal-token/compute design. Provenance and donor answers stay
outside each target-free generate call.

## Coverage BEFORE model execution

Seal inventory-plan.json and public-inputs.json before model loading. Compile
all four context/answer combinations for each selected donor under unchanged
input/response limits. A long selected donor is NOT replaced with a shorter
one. If any reference-bearing recipient is unpaired or cannot compile, the new
trial records blocked_pair_coverage_before_model_load and exits nonzero before
loading any Reader. A coverage pass only means the registered comparisons can
execute; it is not evidence of Reader adequacy.

A missing reference recipient still receives its original own-source and empty
free-generation inputs; its donor/teacher-forcing slots remain unavailable.
Report both all-planned and reference-bearing coverage rather than silently
claiming all four questions were scored. No capability flag opens on coverage.

## Execution and paired readout

Three arms: frozen_reader, aligned_8, shuffled_8. Reload through the existing
strict snapshot and adapter compose/attach/verify_resident owners, bound to the
fixed budget artifact's saved tensor receipts. Do not import Python from the
archive. Verify the full archive and every listed member before extraction.
The original model archive is pinned separately. No projection-artifact replay
or old fitting is repeated merely to run this comparison.

Free generations seal per arm before teacher forcing. Four likelihood scores
reuse the old uncited-body evaluator. Every fixed recipient has an audit slot,
including missing labels, failures and blocked calls. Model weights must remain
frozen before/after. Deadline overruns and errors retain raw observed outputs
and known work; no silent retry. Energy/FLOPs/allocator peaks remain unmeasured.
Start/end RSS is not a process peak. Process resource output is stored separately.

Compute paired interaction differences on identical recipient/donor identities:
aligned8 vs frozen, shuffled8 vs frozen, and aligned8 vs shuffled8. Report task
means, equal-recipient-family means, signs and missing/failed identities.
Directed donor reuse remains dependent; no iid confidence intervals or semantic
accuracy claims. Fixed arm order and only the existing two SELECT source
families also limit generalization. A positive mean alone does not qualify a
Reader, SYSTEM2, NDU or any of the five formal causal experiments.

## Scope and test ownership

New files: select_content_inventory.py, select_content_validation_trial.py,
test_select_content_inventory.py and the dedicated workflow. No old training
source or protocol is modified. New tests cover successful recovery of coverage
from an expanded inventory, original subset missingness, target-partition
isolation, missing references, unresolved/excess support, immutable inputs,
exact original comparator, date/body provenance, no length fallback, and paired
readout with failures/nulls. They are fixture definitions until actually run.
The workflow first runs them without neural dependencies, then all inherited
required suites, and only then permits real saved-model execution.

Unsubmitted local content-objective work from a previous session is not silently
introduced or claimed tested here. Native content training, genuinely unseen
families, independent grounding, Group/NDU gains, multimodal/split transfer and
matched-quality shared/replicated lifecycle comparisons remain separate work.
