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
8 GiB address space, one pinned logical CPU / one numerical thread, and a
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

## Observed completion and independent audit

The sole native model job `1a1f369e64f-ffbe-d3f` completed with exit code zero,
durable complete output and `COMPLETED_PLATEAU`. It restored the full actual
partial state before the first model operation. It then completed the seven
remaining effective batches of epoch 147 and all twelve batches of epoch 148:
**19 new AdamW updates (1758 through 1776), 70 training micro-forwards, and 16
development forwards**. The latter comprise inherited-best, epoch-147,
epoch-148 and final-selected-best full-D passes. The four historical cold-probe
calls remain separately identified; they are not newly credited training work.

| Checkpoint / development pass | Macro-F1 | Plateau stale epochs |
| --- | ---: | ---: |
| Inherited selected best, epoch 144 | 0.388353751030186 | 8 at restore |
| Completed epoch 147 | 0.3831530988904557 | 9 |
| Completed epoch 148 | 0.38325004142328695 | 10 |
| Final selected best, epoch 144 | 0.388353751030186 | 10 at stop |

The final selected-best evaluation covers all 31,952 D events. There is no open
optimizer interval, no partial cursor, no late optimizer completion, no hard
kill, no scientific-budget overrun and no RSS-limit breach. The unchanged
recorded plateau and inherited memorization conditions are satisfied. This is
training adequacy under that recorded rule, not a proof of global optimality.
The new phase completes two epoch records, but only one entire epoch was newly
trained here: epoch 147's first five batches were inherited without replay.

The complete training child, including startup/imports, cold tables, input
verification, all training/validation and finalization, used **819.33570400998 s
wall, 808.816493 s CPU** (769.770313 user + 39.04618 system), and **3,490,128 KiB
peak RSS**. This cost is additional to all earlier costs. Energy was not metered.
The original old-budget eligibility remains false, and no historical cost,
unknown interval or uncommitted partial work is refunded.

The exact archive contains 298 members, including all 38 generated RUN_OUTPUT
files, all bound original inputs, native receipts and the frozen source. It is
17,023,928 bytes with SHA256
`fcd2d079441a3006ca55b41afb05282b211245c7d56d1ac96c3ff9379074e061`.
Every member round-tripped unchanged. Five lossless transport parts are stored
under `evidence/archive-parts/`. The immutable transport commit is
`2633a5d0292f9e9131f48869400081a57a392aff`. All seven immutable blobs uploaded on
their first attempt, and all five parts downloaded on their first attempt.

The independent reader was frozen at source commit
`fd052ccbd596a9667963d478735327605ab7d5c7` before dispatch, with SHA256
`24e7690d1d3e9906febdfed61ea9366240376db550461d019135eca4094db3a0`.
Its first and only process passed with unchanged source and empty stderr. It
verified all 298 archive members and 21 new update/epoch checkpoints, complete
restored tensor bytes, episode order/cursor/objective prefix, RNG representation,
commit chains, Adam ages, frozen tensors and the recorded stopping rule.
NumPy independently recomputed the first restored AdamW update over 11 tensors
and 17,356 scalar gradient coordinates: maximum absolute difference
`5.551115123125783e-17`, below the predeclared `1e-12` arithmetic bound. It also
recomputed final D metrics from saved logits: macro-F1 difference zero, NLL
difference `2.220446049250313e-16`, and ECE difference
`2.7755575615628914e-17`.

These checks do not independently regenerate gradients, forward inference or
the six original complete training runs. The reader cross-checks episode hash
strings and roster identities; episode payloads remain external and their
before/after byte verification is the frozen producer's receipt. The full
reader child cost, including imports, is 4.242280241996923 s wall,
4.234424 s CPU and 275,216 KiB peak RSS. Its exact report is
`evidence/independent-audit/attempt001/REVIEW.json` with SHA256
`1d66bc7adbef4199e331417639a743ce5041f80f420430b3052d7161a7beb564`.

Postprocessing is accounted separately: archive creation used 13.3911804420 s
body wall / 12.884274337 s body CPU; immutable upload used 29.4136607500 s wall /
1.636145 s parent-and-child CPU; exact download/assembly used 15.1952738000 s
wall / 0.384388025 s parent CPU. Native transport receipts, all per-blob attempts
and read/encode preparation errors are retained under `evidence/`. These body
measurements have their stated scope and are not full native-process costs.

The partial-epoch restoration and seed-211 declared-stopping blockers are now
closed for this independently identified continuation. The original UNKNOWN
controller, original six-fit independent full replay **0/6**, original scientific
admission **HOLD**, and sealed confirmation-E conditions remain unchanged.
No E payload or labels were read. The source covered by `FREEZE.json` is byte
identical before and after training and independent review.

To reconstruct the exact artifact from this checkout without network access:

```sh
python qualification/hcsn_c2_partial_resume_20261119/archive_parts.py assemble \
  --parts qualification/hcsn_c2_partial_resume_20261119/evidence/archive-parts/PARTS.json \
  --output /tmp/hcsn-c2-partial-exact-artifact.tar.xz
```

Use the retained first audit result for this run; rerunning the reader creates
new postprocessing cost and should use a distinct output identity.
