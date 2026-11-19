# Restore C2's actual partial epoch and finish the declared stopping rule

This independently identified follow-up starts from the exact archived
`update-00001757.pt` of seed 211 / learning rate 0.001. The source checkpoint has
SHA256 `6366cd79877232623cf510629efeb7e5b321dc72a85c0b73b47f92c99c586178`.
It contains complete model/AdamW/RNG state, last complete epoch 146, and the
already shuffled epoch-147 order with five completed effective batches and next
episode offset 160. The original 356-episode order and five weighted objectives
are retained; only the remaining batches execute before epoch 147 is scored.

## Separate additional budget, unchanged original limitations

The original seed-211 cumulative wall lower bound is 37,199.48737557721 seconds.
The previous independent continuation consumed another 5,805.587805787043
seconds. Their known sum is 43,005.07518136426 seconds; old unknown tails and
other diagnostic costs remain separate. Therefore at most 194.92481863574358
seconds would remain inside the old 43,200-second contract, which cannot cover
the previously observed cold setup. This follow-up **does not refresh or claim
eligibility under that contract**.

The user's latest request to close remaining blockers is applied to a new,
explicit additional research allowance: one fresh process, 3,600 wall seconds,
including imports, input verification, cold tables, inherited-best validation,
training, and final evaluation. The final 300 seconds are reserved inside that
limit. A separate 30-second cleanup interval carries no scientific credit.
Only seed 211 runs. Seed 307 already met the recorded plateau rule and does not
repeat. Original six-fit independent full replay remains 0/6, the original
controller remains UNKNOWN, numerical/scientific admission remains HOLD, and
the original QPR/phase model is unchanged.

Actual launch requires a fresh 8 GiB systemd MemoryMax / one-CPU quota, at least
7 GiB headroom at every finite cgroup ancestor, 16 GiB host available memory,
2 GiB free output disk, and no old or duplicate C2 process. The child receives
8 GiB address space, one pinned physical core / one numerical thread, and a
6 GiB peak-RSS stop. The controller records exact wait4 wall, user/system CPU,
peak RSS and terminal dispositions. Resource preparation reads have no model
or optimizer calls and are kept under `evidence/preparation/`.

## Restore, train, and audit

The original v8 source/data/numerical helpers are hash-bound. The new reader
validates complete optimizer state, moment ages, full episode permutation,
episode identities, cursor offset, batch policy and all earlier objectives.
Missing AdamW, inconsistent ages, duplicate order, offset/epoch corruption,
missing objectives and inconsistent weighted numerators are rejected. The
actual stored checkpoint passed these controls; no training occurred in the
controls. They use exact archived checkpoint bytes and original manifest
roster counts, not synthetic training episodes.

The unchanged stopping rule uses strict best-score selection separately from
the plateau anchor: delta 0.002, patience 10, minimum 30 cumulative epochs and
maximum 200. At restore, selected best is epoch 144 with development macro-F1
0.388353751030186, anchor is 0.38698437025179494, and stale count is eight.
Every newly completed update/epoch receives a complete immutable checkpoint.
The first real clipped gradient is also saved, enabling independent NumPy
verification of its AdamW moments and parameter update from the exact restored
state. This does not independently regenerate the gradient by backward.

The archive and independent reader are frozen before training. They retain all
generated outputs and costs, reconstruct both original and prior continuation
commit chains, check every newly saved state/cursor, replay episode shuffling
without model execution, and recompute metrics from saved full-D logits.
Checkpoint selection uses D; confirmation E is neither read nor scored.
The separate E proposal still needs its complete fixed 21-model roster and
declared custody/selection conditions. This work makes no test-set advantage,
full-network numerical qualification, or production-adoption claim.

## Source verification before execution

- Five stored-state/resource tests passed, including five cursor corruption
  subcases and three allocation/headroom subcases.
- Four earlier restore tests passed before the resource control was added;
  both runs executed zero forwards/backwards/optimizer calls.
- Python syntax was parsed without numerical execution.
- Source and input identities are recorded by `FREEZE.json` and `BINDINGS.json`.

The execution result and complete independent audit will be appended after the
single identified run terminates. Source files covered by `FREEZE.json` remain
unchanged after dispatch. Failure and budget stops remain visible outcomes.
