# Source-value margin development screen

This Linux CPU experiment diagnoses the exposed three-seed terminal states from
`memory_cell_evolution/longitudinal-campaign-002.json`. It does not qualify future
natural-task retention or establish an advantage over a retrieval system.

## Diagnosis and intervention

The old longitudinal service calls `training_backend.train_candidate` for every
clean publication. That function creates a new `SourceMemoryCell`, resets it,
and trains on all current unconflicted facts. It does not continue the previous
adapter. The final unchanged-retention results of 3/8, 6/8, and 1/8 therefore do
not, by themselves, demonstrate incremental catastrophic forgetting. Each
publication used 256 single-example updates across 32–40 source/template
examples. Limited exposure, optimization strength, and transfer to heldout
wordings are distinguishable hypotheses.

The screen compares two learning rates under the old completion CE objective
and a new explicit `source_value_margin_v2` objective. The new loss is:

`CE(positive value + EOS) + relu(1 + mean log p(negative value) - mean log p(positive value))`.

Both completions use the same source-only prompt. The positive forward supplies
both CE and its value score. EOS belongs to positive CE and to neither margin
score. Negative values may have different token lengths. Each positive source
cycles deterministically over distinct tokenized values from current live
facts; duplicate values cannot become false negatives. Actual negative source
roots enter checkpoint ancestry. The old `source_margin` objective, including
its equal-length condition, remains unchanged.

## Frozen comparison

| Arm | Learning rate | Optimizer updates | Actual training forwards |
| --- | ---: | ---: | ---: |
| `ce_001` | 0.001 | 256 | 256 |
| `ce_01` | 0.01 | 256 | 256 |
| `margin_01` | 0.01 | 128 | 256 |

Every arm runs at each of seeds 24019, 24023, and 24029, from the same pinned
SmolLM2-135M-Instruct base with a fresh rank-8 adapter. The order rotates across
seeds. Torch uses two CPU threads. No base-model copy is saved. All nine source
histories, training requests, diagnostic panels, source hashes, and the complete
selection rule are frozen before the first pretrained execution.

The total reservation is 2,304 training forwards and 1,920 optimizer updates.
The reader runs 900 queries in 27 fresh processes: each adapter receives its
40 training-wording and 20 heldout questions; disabled and shuffled controls
receive the identical 20 heldout questions. These repeated questions and shared
source streams are correlated observations, not independent natural tasks.

The selected arm maximizes the worst seed's minimum of current-source accuracy
and unchanged retention, then the mean of those seed minima, then the fixed
order in the table. Each current source and retained source must match both
heldout wordings. Training-wording scores are reported separately and never
select the winner. Missing or failed arms prevent selection. The stronger
development gate additionally requires current accuracy and retention at least
0.9 for all seeds, exact final corrections, and adapter accuracy above both
controls in every seed. A selected arm need not pass this gate.

Equal forward counts do not establish equal optimizer updates, token counts,
FLOPs, latency, or full system cost. Those actual measurements are retained.
The margin-versus-high-rate-CE contrast includes the deliberate update-count
tradeoff required by the forward reservation.

## Source and parameter boundaries

Preparation replays actual `MemoryService` writes, corrections, conflicts, and
withdrawals. The worker claims the real final source lease, checks the frozen
snapshot, trains only live facts, saves and verifies the candidate, then uses
the actual publication CAS. A parameter-only reader receives questions and
checkpoint metadata; it receives no facts, answers, retrieval, or answer list.
The parent scores raw generated output with the original whitespace-trimmed
exact-match rule. Immediate source-overlay answers never enter parameter scores.

Reads run inside live owner/frontier admission with the exact source snapshot
and selected version checked before and after the batch. After all quality
panels, a real source revocation must deny both the revoked key and another
live key through the now-stale parameter binding, with zero decoder callbacks.
This checks use denial. It does not claim physical parameter erasure or
authentication of an external production source authority.

## Receipts and execution

Public model hooks independently record entered and completed training forwards
and their input lengths. Failed or timed-out attempts retain their reserved
256-forward budget without refunds; measured partial work remains explicitly
partial or unknown. No retry or post-observation hyperparameter change is
automatic. Execution, source-integrity, or resource failures stop the screen
and leave the remaining planned trials marked unexecuted.

Checkpoints retain aggregate loss-component/token charges plus complete positive
and negative schedules. Detailed per-step charge objects are excluded from the
manifest. The new objective checks the exact existing manifest serialization
size before accepting a fit; it cannot return a successful oversized receipt.
Tests cover 4,096 updates with save/reload, EOS boundaries, unequal values,
positive-forward reuse, negative ancestry, partial-write quarantine, source
withdrawals, forward accounting, failure receipts, and the selection rule.

Prepare once using the installed model runtime, without executing the model:

```sh
python scripts/memory_cell_retention_v2/retention_protocol.py --base /path/to/pinned-base --output /path/to/new-screen
```

After reviewing the frozen protocol and source tests, execute the exact digest:

```sh
python scripts/memory_cell_retention_v2/retention_runner.py --output /path/to/new-screen --protocol-sha256 SHA256
```

The experiment must run serially within the shared compute allocation. Raw
requests, journals, subprocess diagnostics, source-event receipts, adapter
checkpoints, and separate cost/quality summaries stay in that output directory.
The total artifact limit is 150 MB. No follow-up stream starts automatically.

A subsequent retention study still needs a separately preregistered multi-round
stream across all three seeds, repeated corrections/withdrawals and clean
publications, an equally bounded CE baseline, and every round's retention
panels. Even that would leave the full future natural-task and strong-retrieval
comparison gate open. The present final-state development screen is not such
a longitudinal qualification.
