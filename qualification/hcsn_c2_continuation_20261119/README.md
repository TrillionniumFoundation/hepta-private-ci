# Two bounded continuations from surviving C2 checkpoints

This experiment resumes two interrupted C2 fits under new identities. The
scientific execution source and input hashes were frozen before launch. The
native process is `1a1f286aa59-ffbe-b5c` on `desktop`, with parent identity
`hcsn-c2-independent-continuation-20261119-d741-001`.

The execution source was published in [draft PR #6747](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6747).
Its initial remote tree `e02c6a77c88e5a780ba2fe15e6905c0d455675d9`
equals local frozen source commit `ff281e36f7e1a5480ca30ff3cf8a1efaac0114c6`.
`FREEZE.json` has SHA256
`4e537af088a70a4b5ea84ab4493184632b92ba7619663d8e59916f71f4b9f99b`.
Postprocessing and evidence files are separate from that execution freeze.

## Outcome

Both children have reviewable terminal records and exited with code 0. The
native parent independently reports `succeeded`, complete durable output, and
a confirmed terminal publication at Unix millisecond `1795076081314`.
The child outcomes differ:

| Fit | Actual terminal | Last complete epoch | New completed optimizer updates | Selected epoch | Selected development macro-F1 | Training adequacy field |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| s211, lr 0.001 | `BUDGET_STOP` | 146 | 245 | 144 | 0.388353751030186 | false |
| s307, lr 0.001 | `COMPLETED_PLATEAU` | 136 | 108 | 126 | 0.33231907785802234 | true |

Both selected checkpoints were reloaded and evaluated on all 31,952 development
events. The s211 selected score improved by `0.01045075840678146` from its
inherited best. The s307 selected score did not improve. The s211 strict best
is epoch 144, while its plateau anchor remains epoch 138 at
`0.38698437025179494`, with eight stale epochs. A small strict-best gain did
not reset patience. Its budget stop is not convergence. The s307 plateau has
ten stale epochs and retains the inherited epoch-126 best.

The s211 process stopped training at phase `5703.109546249034` seconds after
the cooperative guard reserved the final 300 seconds inside the 6000-second
scientific limit. Its epoch-147 cursor retains five completed effective batches,
the already shuffled 356-episode order, next episode offset 160, and five
weighted-objective receipts. The sixth batch's four micro-forwards consumed
work without an optimizer update; epoch 147 is not labelled complete. Its last
complete optimizer state has logical update 1757; its last complete epoch state
has logical update 1752. Those states are preserved separately.

There are **353 actual new optimizer updates**, 1329 recorded training
micro-forwards, and 132 development forwards across the two fits. Started and
completed optimizer counts agree, no optimizer completion occurred after the
scientific deadline, and both open completion intervals are `[0, 0]`.

| Fit | Fresh-process wall seconds | Exact child CPU seconds | Peak RSS, KiB | External stop / hard kill / scientific overrun |
| --- | ---: | ---: | ---: | --- |
| s211 | 5805.587805787043 | 5721.835218 | 3503780 | none |
| s307 | 2817.803326756053 | 2783.2699629999997 | 3536760 | none |

The two children used `8505.105180999999` CPU seconds. Their concurrent
dispatch-to-reap makespan is `5805.587805787043` seconds; the sum of their
individual wall times is `8623.391132543096` seconds and is not elapsed campaign
time. These are exact training-child `wait4` costs, not whole-system energy or
native-supervisor CPU accounting.

Exact early terminal copies are in `evidence/terminal-hcsn-s211-lr0.001/` and
`evidence/first-terminal-hcsn-s307-lr0.001/`. Complete archival has finished;
all 35 transport parts and the assembled archive were verified locally. The
independent archive reader completed successfully in a fresh process. Native
success and the producer's adequacy field
do not independently establish numerical qualification or a six-fit replay.

## Model and task scope

The numerical model is the original v8 C2 **QPR/phase projection** model. Its
actual `cores.py` SHA256 is
`95fcf93747520414a062183affd546f599bc415b2a9daa47e59db20f67412302`.
It has one HCSN layer, width 16, `cache_frozen_tables=true`, and
`learn_core_adapter=true`. The original implementation explicitly sets
`layer.physics.requires_grad_(False)`. The physical parameters and common
frozen tensors remain frozen; the content, likelihood, write, readout, and
temporal adapter parameters receive the original gradient updates.

These results belong to that original model and data pipeline. They do not
measure the new complete regenerative flow operator in #6741, the endogenous
free boundary in #6739, or a new multimodal backbone. They also do not establish
a same-budget advantage over Transformers, SNNs, or ordinary recurrent gates.

The original training population contains 89,216 events, and every complete
development evaluation contains 31,952 events in 11 classes. No sealed
confirmation evaluation is performed. Development macro-F1 over all 11 classes
selects the best checkpoint, so its score is a selection statistic rather than
an independent test result.

The fresh runtime is Python 3.12.3, Torch **2.8.0+cpu**, and NumPy 2.3.5. The
original C2 runtime was Torch **2.8.0+cu128**. Exact observed state and metric
agreement in the preceding four-call probe does not make these platform
identities equal. Runtime preparation failures remain preserved in
`../hcsn_c2_cold_resume_20261119/` and draft PR #6746.

## Exact recovery points

| Fit | Complete epoch resumed | Logical updates | Inherited strict best | Plateau anchor | Stale epochs |
| --- | ---: | ---: | --- | ---: | ---: |
| s211, lr 0.001 | 126 | 1512 | epoch 124, F1 0.37790299262340454 | 0.37790299262340454 | 2 |
| s307, lr 0.001 | 127 | 1524 | epoch 126, F1 0.33231907785802234 | 0.33231907785802234 | 1 |

The original full checkpoint, optimizer groups and AdamW tensors, Torch RNG,
episode-order RNG, model configuration, and data-manifest identity are restored
and serialized before the first new update. All frozen tensor bytes are checked
against the exact original initial checkpoint. The inherited best is evaluated
on the complete development population, then the entire last-state and RNG are
restored again before continuation.

The two target `initial.pt` paths were absent. The first preparation attempt
failed and remains in `preparation-attempt1/`. Surviving same-seed lr 0.003
initial files matched the original target admission's byte length and SHA256
exactly; `BINDINGS.json` records those alternate source paths. Nothing was
written back to the missing original paths.

The full inherited histories contain 126 and 127 contiguous complete epochs,
including 80 and 81 complete original C2 epoch commits. Their hash chains and
stopping states were verified before launch. The original partial tails contain
10 and 11 known completed updates after these recovery checkpoints, plus
unobserved/truncated work. Those tails are not synthesized into checkpoints.
Recomputing their known updates consumes new time and is retained as duplicate
work. The separate four-call cold-resume experiment is also not refunded or
counted as continuation progress.

## Preserved optimization and stopping semantics

The original global class weights, effective batch size 32, micro-batch size 8,
full effective-batch padding, valid observation mask, full BPTT, and AdamW
configuration are retained. Micro-batch summed weighted losses use the whole
effective batch's weight denominator; clipping at norm 1 and the optimizer step
occur once per effective batch. Epoch loss is aggregated from weighted
numerators and denominators, rather than averaging batch means.

Strict-best selection uses `score > best`. Plateau reset separately requires
`score > plateau_anchor + 0.002`. A small strict-best improvement does not reset
patience. Minimum cumulative epochs remain 30, patience 10, and the original C2
contract's cumulative cap remains 200. The earlier parent plan's cap of 100 is
recorded in `REQUEST.json`; it is not confused with the active C2 contract.

Every completed optimizer step receives an immutable complete state checkpoint
with a mid-epoch cursor. The cursor retains the already shuffled episode order,
next episode offset, completed batch count, and completed weighted objectives.
Every complete training epoch plus complete development evaluation receives an
immutable checkpoint and chained commit. The last complete epoch and last
complete optimizer state remain distinct when a budget ends mid-epoch.

## Fixed resources and costs

Each child is pinned to a different observed physical CPU core with one numeric
thread, an 8 GiB address-space limit, and a 6 GiB peak-RSS stop. The two children
run concurrently, so the aggregate envelope is two compute CPUs and at most
12 GiB child RSS. The controller's bookkeeping is pinned to those same CPUs.
Fresh resource observations required at least 16 GiB available memory, 2 GiB
free output disk, and no original or duplicate C2 process.

Each fresh process receives **6000 wall seconds**, including imports, original
input verification, cold table construction, and inherited-best validation.
Training reserves the final **300 seconds inside that budget** for best-state
evaluation and evidence. A separate **30-second cleanup grace** can contain an
in-flight operation and finalization after an external deadline; that time is
reported and does not confer extra scientific budget or qualification credit.
Exact per-PID `wait4` receipts retain wall, user CPU, system CPU, exit status,
and peak RSS. No whole-system energy measurement is claimed.

`BUDGET_STOP` is a reviewable bounded outcome when its state and terminal
receipts are complete. It is not labelled convergence. Partial backward work,
started versus completed optimizer calls, any unknown optimizer completion
interval, late completions, and incomplete development finalization are
reported explicitly. The controller only signals its own process groups.

The original six-fit C2 logs give a **23.1924145573 CPU-hour lower bound** for
their retained continuation work, before earlier parent training and unknown
tails. The present experiment does not replay that six-fit lifecycle. The
four-call cold probe and this two-fit continuation each have separate costs.

## Evidence and review

`archive_results.py` is a standard-library postprocessor. It may run only after
an authoritative native terminal and both child dispositions are available.
It archives every generated file, every update and epoch checkpoint, the
frozen source, all 182 bound original evidence inputs, and the actual original
v8 numerical source. It hashes every original file before and after archival
and verifies each decompressed tar member. Episode payloads remain referenced
by the original manifest and complete `INPUT_IDENTITIES.json`; archival does
not open additional dataset payloads.

Lossless tar.xz compression and, if needed, reversible transport parts preserve
the exact original bytes. They do not select only the best checkpoints or omit
the trajectory. Archival and independent review execute no model forward or
optimizer calls and consume no additional training budget. The synthetic
fixtures under `controller-control/` check process bookkeeping only and are
not model-validation results.

The original controller remains **UNKNOWN**, the complete independent six-fit
replay remains **0/6**, and scientific admission remains **HOLD**. The old
posterior/optimization-window recording contract is not retrospectively
completed by these new recordings. New terminal receipts and development
results do not overwrite the original evidence or make the v8 numerical
operator qualified.

### Reconstructing the exact archive

The final artifact uses `evidence/archive-parts/PARTS.json` to bind every
transport part and the complete tar.xz SHA256. From the repository root, the
following commands reconstruct the original archive and run the independent
reader with the pinned Torch/NumPy environment:

```sh
python qualification/hcsn_c2_continuation_20261119/archive_parts.py assemble \
  --parts qualification/hcsn_c2_continuation_20261119/evidence/archive-parts/PARTS.json \
  --output /tmp/c2-continuation-exact-artifact.tar.xz
python qualification/hcsn_c2_continuation_20261119/audit.py \
  --archive /tmp/c2-continuation-exact-artifact.tar.xz \
  --receipt qualification/hcsn_c2_continuation_20261119/evidence/ARTIFACT.json
```

The reader verifies actual archived source and checkpoint bytes, and recomputes
metrics from the stored development logits and labels. Dataset payloads remain
external: matching their recorded hash strings and roster is not a fresh local
rehash of those payloads. The frozen producer records its before/after input
checks. The reader performs no model inference, backward pass, or optimizer
update; its success does not constitute an independent training replay.

### Actual independent review

The only archive-reader run is
`evidence/independent-audit/attempt001/`. Its `COST.json` records exit 0,
`PASSED`, no timeout, and an empty stderr. The exact `REVIEW.json` is 38,605
bytes, SHA256
`617758a0a23e69cf7687c3faa70a51b174514d472a0d0225bce5c9ad126f5a3c`.
It records `VERIFIED_ARCHIVED_CONTINUATIONS` and the following observations:

- All 667 archive members, the six frozen execution files, all bound original
  evidence inputs, and the actual original numerical source pass byte checks.
- Full restored model, AdamW, and RNG tensor bytes agree with the surviving
  original checkpoints. The 265 s211 and 117 s307 newly written update/epoch
  checkpoints are checked, along with frozen tensors, optimizer ages, episode
  ordering, complete epoch commits, and the retained partial-epoch cursor.
- The 245 and 108 actual optimizer completions agree with the journals and
  exact child `wait4` receipts. No optimizer completion occurred after the
  5700-second training-reserve boundary or the 6000-second scientific limit.
  The extra s211 micro-forwards before its guard stopped batch 6 remain counted.
- The old tails' 10 and 11 known completed updates are all matched by logical
  update number. Their recorded loss, gradient norm, event count, and micro-call
  count have zero differences. These are scalar journal comparisons, not a
  new independent gradient-vector or full-lifecycle replay. Duplicate work is
  retained and not refunded.
- Independent NumPy calculations from the saved development logits reproduce
  confusion matrices and both macro-F1 values exactly. The largest scalar
  difference is `2.220446049250313e-16` (s211 NLL), below the reader's declared
  `1e-12` arithmetic comparison bound. That bound changes no scientific gate.
  The inherited-best metrics and final selected metrics versus their recorded
  best epochs also have zero recorded scalar differences.

The reader uses Python 3.12.14, Torch 2.8.0+cpu, and NumPy 2.3.5. Its unchanged
source SHA256 is
`d3da9e6357473d2440fdc0bca46f6880b056489b71935b1253941dbab0945776`.
The complete fresh-process cost, including imports and archive decoding, is
14.652553780000744 wall seconds, 14.41462 CPU seconds, and 552,816 KiB peak RSS.
Its configured limits were 4 GiB address space, 300/310 soft/hard CPU seconds,
360 wall seconds, and one CPU/thread. Zero model and optimizer calls were made.

The complete archive contains 667 members, including all 437 generated run
outputs. Its original members total 200,305,468 bytes, plus the 281,746-byte
manifest. The exact tar.xz is 144,225,308 bytes with SHA256
`05b10e450be5e234db9d89512c243e8267764d7ff19b777d1e479d0300154050`.
All members were decompressed and individually verified on the producer host;
the source files and output membership were checked again afterward.
`evidence/ARTIFACT.json` records 102.29676242097048 seconds of archival-main
wall time, 100.603654917 process CPU seconds, and 118,394,880 bytes peak RSS.
Native launcher startup is outside that self-reported wall time. This is
separate postprocessing cost, with zero model and optimizer calls.

Transport preserves host-key checking and uses only the existing account.
The repository was observed to be public. Official public raw downloads use no
credential, and immutable transport blobs/commits can be verified before the
existing draft branch is updated. Transport failures and successful byte
identity checks remain separate from training and numerical qualification.
The first immutable-blob upload stopped after ten successful parts because a
connection to `api.github.com:443` timed out on part 10. Its confirmed failure
and original receipts remain in `evidence/transport/attempt001/`; the complete
archive and every part were already retained. `resume_archive_upload.py`
reuses matching successful content-addressed blobs and allows at most three
bounded attempts for a remaining part only for selected transient network
errors. It does not retry authentication or permission failures and never
changes a branch ref or invokes training.

That continuation completed successfully and retained the three further
connection timeouts (parts 20, 24, and 33), each recovered on its second bounded
attempt. It reused the ten successful blobs, created the remaining 27 blobs,
and took 259.995243958 wall seconds. The first failed upload took
96.28831154199999 seconds through its recorded failed request. Transfer CPU
time was not measured. Both native terminal receipts and all failed request
receipts are retained; successful responses are in `evidence/transport/UPLOAD.json`.

The immutable transport commit `64350ae864293c54061d7ea845e3e13561113d5d`
was created without moving a branch ref. All 35 official public raw downloads
succeeded on their first attempts and were reassembled in 47.04961711099895
wall seconds, with the complete archive SHA verified again. This record is
`evidence/PUBLIC_RAW_DOWNLOAD.json`. `ARCHIVE_MANIFEST.json` and
`CONTROLLER_TERMINAL.json` are byte-identical readable copies from the archive;
their separate extraction cost is 7.262876208002126 wall seconds,
7.1793796819999995 CPU seconds, and 21,045,248 bytes peak RSS. Those costs are
postprocessing, not additional scientific training.
