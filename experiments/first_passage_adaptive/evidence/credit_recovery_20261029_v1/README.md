# Cold reconstruction of the research credit account

This separate recovery layer closes the cold-process credit-account gap left
explicit in the earlier credit execution run. It preserves that run's source,
freeze and all original evidence. It operates on retained requests, results,
settlements and native owner anchors; it performs no new task execution and
does not rerun training or scientific confirmation.

The independent pre-validation source freeze is
`bedb376934ff2947d2af146e4573976d803ab69305e44666e8d69c30a27bdf97`.
Five focused recovery tests passed; their actual console output is retained in
`UNIT_TESTS.txt`. The subsequent validation passed all eight checks.

## Recovery contract

`credit_recovery.py` reconstructs the account without calling
`CreditAccount.settle` to restore it. For each retained decision, it verifies
the immutable step against the original native request and result; request,
FPT and NDU receipt digests; task and owner predecessors; the credit record's
hash; and the credit state in the next NDU snapshot. It independently
recomputes actual resource usage, base fee, shadow charge, the clipped price
update and the complete expected settlement record. It rejects a historical
zero-usage replay as a source for recovering an original charge.

The rebuilt state includes the complete `records` map, price, previous credit
hash and decision count, together with the retained final task state and
observed answer status. Those must match the externally frozen terminal
expectation. The original native bridge then performs `--inspect`; its current
anchor and sequence must match the restored ledger's terminal owner anchor.
An inspection-only capability wrapper rejects execution requests before a
process could be started.

The independent reference uses the original `CreditAccount` in one uninterrupted
in-memory replay of the retained original native responses, checking every
produced settlement against the original receipt. It does not call the recovery
function. This provides a live settlement reference without rerunning a source
read. Each cold result comes from a separate Python process and is compared
with that reference in full.

## Recorded verification

| Check | Actual evidence |
| --- | --- |
| Cold reconstruction | Three fresh Python processes reconstruct all seven original settlements |
| State comparison | Snapshot, price, prior hash, record map, task state and answer status match the uninterrupted reference |
| Already-settled replay | Three replays leave price and records unchanged; no double charge |
| Subsequent settlement arithmetic | Three isolated synthetic accounting messages produce the same next receipts and account states from cold and uninterrupted copies |
| Native terminal binding | Original native owner inspections agree before and after probes |
| Fault rejection | Seven specified corruptions rejected |
| Original evidence preservation | All retained metadata, receipt, checkpoint and owner-file hashes unchanged after validation |
| Execution restriction | Seven native inspection calls, zero native execution requests |

The synthetic next messages are explicitly marked hypothetical. They are
applied only to isolated copies of the account, never sent to the native owner,
and never added to the original task's cost or return ledger. A stopped task is
not resumed by this validation.

Fault injection uses temporary copies with the task source directory omitted.
The retained result records all seven failures:

1. Missing settlement: rejected as an incomplete/noncontiguous sequence.
2. Changed price without a matching hash: rejected by the record hash.
3. Changed price with a newly computed hash and matching step copy: rejected
   by independent accounting recomputation.
4. Reordered settlement files: rejected by step/settlement identity.
5. Missing original owner result: rejected as an incomplete owner record set.
6. Claimed zero attempts despite the original budget increment: rejected by
   resource accounting.
7. Corrupted native witness bytes: rejected by the actual native owner with
   `Corrupt`.

The original source files and evidence were not changed to make these cases
pass. Disposable corrupt copies are removed after their rejection; the frozen
fault recipe and observed error for each case are retained.

## Scope and reproduction

This is a serial trusted-writer recovery protocol for completed, readable
research records. It does not provide a concurrent transaction, a power-loss
atomicity guarantee, production Organ Credit ownership, or a mechanism for
reexecuting an action whose outcome is uncertain. Physical lambda remains zero
in the underlying retained fixtures. The earlier price-feedback result still
has task return -0.05 versus 0.85 with feedback disabled; reconstruction adds no
efficacy or convergence claim.

The validation files under `run/` retain full uninterrupted and cold account
states, original terminal owner inspections, replay outcomes and isolated
hypothetical continuations. `CREDIT_RECOVERY.json` is an exact readable copy
of the summary, and `MANIFEST.json` hashes each retained file.

For a new validation, choose fresh paths and the exact built owner manifest:

```bash
FPT_OWNER_BUILD=/absolute/path/to/native-owner-build/NATIVE_BUILD.json
FPT_RECOVERY_FREEZE=/absolute/path/to/new-credit-recovery-freeze.json
FPT_RECOVERY_OUTPUT=/absolute/path/to/new-credit-recovery-output
FPT_CREDIT_INPUT=experiments/first_passage_adaptive/evidence/credit_execution_20261029_v1/run

python -m unittest experiments.first_passage_adaptive.tests.test_credit_recovery -v
python -m experiments.first_passage_adaptive.credit_recovery freeze \
  --input "$FPT_CREDIT_INPUT" --owner-build "$FPT_OWNER_BUILD" \
  --output "$FPT_RECOVERY_FREEZE"
python -m experiments.first_passage_adaptive.credit_recovery run \
  --input "$FPT_CREDIT_INPUT" --owner-build "$FPT_OWNER_BUILD" \
  --freeze "$FPT_RECOVERY_FREEZE" --output "$FPT_RECOVERY_OUTPUT"
```
