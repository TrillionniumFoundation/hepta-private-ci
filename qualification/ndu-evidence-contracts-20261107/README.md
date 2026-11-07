# Finite learning outcomes and incumbent continuation

Status: **CONDITIONAL_CONTRACT_IMPLEMENTED / NATIVE_END_TO_END_HOLD**.

Final-source local verification: **176 tests passed, zero skips**, including
the original Torch feature contracts, 15 new replication tests and 22 new
learning-outcome tests. Source hashes were unchanged during execution.
[VERIFICATION.json](VERIFICATION.json) records that run; the complete logs,
earlier local attempts and five synthetic outcome examples are retained in
[execution-evidence.zip](execution-evidence.zip). [REVIEW.json](REVIEW.json)
records the implementation issues found and fixed during parallel review.
These assistant code reviews are not independent real-task evaluations.

[RESEARCH_WORK.json](RESEARCH_WORK.json) separates measured software-check
envelopes from unknown installation/review/energy costs. No full-cost claim is
made. [FORMAT_EQUIVALENCE.json](FORMAT_EQUIVALENCE.json) records unchanged Python
ASTs across the repository formatter; the final test receipt uses formatted source.

This follows the [#5198 replication extension in #5310](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5310).
It adds a bounded evidence checker
in `scripts/ndu_portfolio/learning_outcome.py`; it does not replace the existing
native learning state machine. Native evaluated NoUpdate already exists on
#5192. That branch's `OwnerDrainedSameModel` operation can continue an incumbent,
but its availability does not prove that a learning decision or next-task use
has occurred.

## Four results, two evidence levels

The conditional result has exactly four values:

| Conditional result | Required finite-decision meaning |
| --- | --- |
| Adoptable | At least one bound candidate passed every declared gate and the finite campaign evidence is complete; selection and adoption are separate |
| NoUpdate | A complete zero-eligible admission, evaluated finite candidates without a qualifying update, or a completed preregistered budget stop; continue to require incumbent-use evidence |
| Inconclusive | Missing admission, incomplete candidate inventory, unknown costs, unresolved jobs, incomplete gates or missing independent terminal evaluation |
| Failed | A separately receipted campaign execution failure or observed contract-budget/deadline violation |

A reconciled failed trial or retry is retained and charged. It does not veto
another completed candidate. If all attempted candidates failed and no candidate
evaluation completed, candidate exhaustion alone is Inconclusive; it is not a
negative learning finding. A complete, separately evaluated, predeclared budget
stop may still end that finite search.

This Python checker verifies declared structure and arithmetic only. Its
`conditional_outcome` can take the four values above, but `outcome` remains
`Inconclusive`, `status` remains `HOLD`, and native authentication is
`NOT_IMPLEMENTED`. Matching hashes, distinct actor names and a self-written JSON
receipt cannot promote a result to authenticated native evidence.

## Frozen contract and complete inventory

The caller supplies `expected_contract_digest` from the prospective owner
record. The checker does not obtain this trust pin from incoming evidence.
The contract binds the source bundle and registry, external objective,
incumbent complete manifest and checkpoint, evaluator identity and executable
identity, finite candidate slots, deadline and total cost budget.

Every candidate job must appear exactly once in its candidate's inventory.
Evaluated candidates require successful construction and matching evaluation
receipts for the same manifest. Evaluation must follow successful construction;
later construction cannot reuse an older evaluation. Training and search jobs
cannot escape the candidate inventory by claiming a null candidate ID.
Dataset admission is tied to its completed job, with eligible and
excluded counts reconciling to scanned rows. The independent terminal declaration
binds the full data-admission, candidate and job inventories. Its own evaluation
work has a separate metered job after the other jobs; its meter receipt differs
from the signed terminal receipt to avoid a circular hash binding. Unknown charges
remain null alongside a known lower subtotal; no failed or cancelled work is
silently removed.

The ledger covers the same nine disjoint physical categories as the factorial
audit, grouped across dataset, training, search and evaluation jobs.
True disjointness, meter authenticity, data eligibility and evaluator independence
still require their native evidence. This layer cannot infer them from labels.

## NoUpdate is not a model update

An evaluated candidate whose manifest equals the incumbent is rejected at this
declaration layer. This is a basic identity check, not a proof that different
manifests contain a meaningful parameter change. The production V5 no-op and
positive-gain rules are unchanged.

Every result has `chain_submission=null`, `reward_eligible=false`,
`adoption_authorized=false`, and `global_optimality_claim=false`.
NoUpdate says nothing about all possible future models and does not create a
zero-delta V5 update or reward.

A separate optional `next_task` declaration must bind the exact learning
evidence, prior checkpoint, unchanged incumbent, fresh task/run IDs, next
checkpoint and committed-step receipt, and the existing FinalUse purpose
`agentd.cell-generation.next-task-same-model`. Passing this structural check
still reports `verified=false`. Actual ACK/drain, writer fencing, selection,
revocation, generation/epoch transitions and FinalUse authentication stay with
the existing owner. A new task identifier is not proof of model use.
The declared new owner checkpoint must also differ from the old checkpoint.

## Current real-task disposition

[READINESS.json](READINESS.json) records the exact checked source snapshots.
The #5198 packet still lacks a registered five-family confirmation corpus,
retention panel, independent locked evaluator, complete real controllers,
authenticated per-episode receipts and complete physical cost.

Therefore this packet is **Inconclusive**, not NoUpdate. Absence of a material
packet is not a completed zero-eligible-data admission. Historical native tests,
the single-image gradient probe and the separate image-fingerprint repair cannot
supply the missing episode evidence.

The source anchors are #5198 `006e744f`, #5192 `09db432b`, and #4944 reviewed
`25fa6d6d` / executed `61921427`. Existing native learning NoUpdate ends before
Selection/NextUse; the authentic learning-to-incumbent-next-use chain is still
open. This package deliberately does not alter that production state machine.

## Reproduce and integrate

```python
from ndu_portfolio.learning_outcome import audit
result = audit(contract, evidence,
               expected_contract_digest=owner_frozen_contract_digest,
               next_task=optional_next_task_declaration)
```

The test module contains an explicitly synthetic schema fixture. To run the
adversarial tests and generate all four conditional examples:

```bash
PYTHONDONTWRITEBYTECODE=1 python \
  qualification/ndu-evidence-contracts-20261107/reproduce.py \
  --output /tmp/ndu-learning-contracts
```

The existing blocking NDU reference job discovers these new tests. The examples
are software verification, not an independent evaluator, real learning trial or
native receipt. The complete final-source contract suite is recorded separately.
