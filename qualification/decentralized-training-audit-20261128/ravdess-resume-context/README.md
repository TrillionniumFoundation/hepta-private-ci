# RAVDESS scoring resume and consumed-input binding

The original outer controller accepted an existing score terminal without
calling the scorer. The original scorer independently returned on any existing
terminal after checking only the source inputs and external archive; it did
not reach source selection or model checks on that path.

Both shortcuts were reproduced. The outer stdlib control returned with invalid
JSON markers and zero child invocations. A separate native control of the
original inner run returned on an empty JSON terminal even though the two
source-selection files had been removed and a selected scalar-weight fixture
had changed. The source selection and inference functions were never called.

This change makes the outer controller invoke the scorer for every ready group.
The scorer owns an output lock and validates a current context before reusing
a terminal. That context includes the exact source modules, declared source
inputs, prepared external input, source selection records, selected models,
scorer source and Python/NumPy/Torch versions. The terminal must also match the
model set and the hashes of its saved score arrays, controls and model mapping.
An old terminal without this context is retained and refused. No historical
terminal is upgraded or silently recomputed.

## Bytes consumed by a new run

The model code is compiled from captured source bytes with explicit local
dependency bindings. It uses the encoder and temporal source whose hashes are
declared by the original study. Ambient modules with the same import names
cannot substitute for them. The actual original module definitions were loaded
in the controls; no network was constructed.

Declared source inputs and the external NPZ are copied into private ordinary
read-only files before the numerical stage. Each weight is hash-checked and
loaded through a BytesIO over the same captured bytes, with weights_only=True.
The terminal uses the captured external identity. Saved NPZ hashes are derived
from the bytes written. The live input identities are sampled again before
writing a terminal, and the saved output identities are checked.

This is content and version binding, not a signature from the independent
source owner. It does not establish a continuous filesystem lease against an
uncooperative writer, authenticate independently changed declarations and
payloads, or recompute the mathematical summaries when resuming. The terminal
and its claimed hashes are not independent proof of scientific validity.

## Actual controls and retained failure

The first candidate passed 9/9 controls. Independent review then found that
its JSON reader still opened a FIFO before checking regularity. Two owned
child processes reached the actual terminal.json and source_models.json
read paths and each blocked until its explicit 8-second deadline. The tested
first candidate, both timeouts and all raw observations are retained.

The final candidate routes JSON loading through the captured regular-file
reader. It passed 10/10 controls, with zero errors, failures or skips, in
0.6254315569531173 seconds. The controls include:

- Valid new and resumed contexts for all three source-selection profiles.
- Refusal of legacy terminals, changed inputs/code/runtime and changed outputs.
- Actual controller child invocations, including propagation of an exit-7 child.
- Actual NumPy reads from private snapshots after a live input is replaced,
  followed by refusal to commit the changed context.
- Actual Torch loading of a small declared scalar fixture from the checked
  bytes after the live weight path is replaced.
- Actual original module loading with poisoned ambient module-cache entries.
- FIFO refusal in the regular readers and both actual resume JSON entry points.

These are filesystem and context integrity controls. The scalar state files,
source/data fixtures and completion receipts are explicitly synthetic.
The numerical score_panel function is replaced in these controls. No scientific
model construction, forward pass, training, quality estimate or speedup was
performed or inferred. A static AST comparison found the original losses,
measure, features, source_only_control and score functions unchanged; that is
not a numerical equivalence claim for historical runs.

Runtime was Python 3.12.3, NumPy 2.5.4 and Torch 2.8.0+cpu, with one CPU affinity,
nice 10 and all four recorded numerical-thread limits set to one. Total final
runner time including imports and the original inner baseline was
4.770458450075239 seconds; maximum RSS was 207288 KiB. Both tested source
snapshots were unchanged during their respective executions. The existing
per-model and source-fit timers retain their original scope and do not include
the added context hashing or private-copy overhead.

## Reproduction and evidence

From a checkout with NumPy and Torch available:

    python -m unittest discover -s qualification/hcsn_sustained_20261128/ravdess -p test_ravdess_resume.py -v

The raw archive contains the eight pinned source files, both tested candidates,
the original outer and inner controls, actual synthetic input files, exact
runners, stdout/stderr, the two FIFO timeout observations and their node records.
The FIFO nodes themselves are not archived as special filesystem objects; the
baseline runner recreates them. MANIFEST.json enumerates every regular archive
member with its byte count and SHA-256, and every member is read back after
compression. Restore tested-v1/ as candidate/ to replay the first-candidate
controls. For a replay, copy the chosen source directories, source_manifest.json
and runner into a fresh directory; keep the archived observations unchanged.
The final runner uses candidate/ and refuses to overwrite run-2.

The original repository just fmt receipt is included with its actual scope.
Qualification Python is excluded by that formatter's language selection, so
command success is not Python-format or full-repository qualification. The
original blob-size checker is run on an explicit seven-file synthetic Git
inventory; that inventory is a policy control rather than project history.

The separate generation training/selection resume and full provenance gaps
remain outside this patch. No existing scientific output directory was modified.
