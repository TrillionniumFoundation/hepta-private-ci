# RSICD cached score file binding

This patch keeps the existing model and score SHA checks and binds the cached
score filename and gate to the current selected checkpoint. It reads the
expected archive once, verifies those exact bytes, and materializes the four
arrays used by aggregation from BytesIO with allow_pickle=False. The arrays
are read-only and are reused for every later aggregation, including best/final
selections of identical weights. Aggregation neither resolves a filename from
cached JSON nor reopens a checked NPZ path.

Base: 24ac9e35603ecb8d6a96377394fb3d7feba6a5ec.
Original evaluate.py Git blob: 0120c439acbdf7a699ebec16c91cce9128b232bf.

## Actual controls

The unmodified scores() function accepted a cache record whose hash described
literal-109-60.npz but whose score_file named alternate.npz. It read the different
file 20 times. The cached JSON means stayed unchanged, while the paired CIDEr
mean became -3.3333333333333335. An independent calculation from the two actual
NPZ files produced exactly the same value.

The first patch passed 6/6 tests; its exact source and logs remain in the archive.
A further deterministic control replaced the same NPZ path at np.load entry,
after its hash had been checked. That first patch still consumed the replacement
and produced the same -3.3333333333333335 paired mean. The final patch retains the
original arrays after the identical file replacement.

The final evaluator passed 7/7 tests with no skips in 0.529450949979946 seconds.
The controls cover a valid twelve-entry cache with all 24 best/final references,
a different basename, parent and absolute paths, a mismatched gate, same-path
replacement after checking, and the existing model/score digest checks. Correct cached inputs stay byte-identical.
The final invocation, including Torch import and the additional replacement
baseline, took 4.164315650006756 seconds and reached 205780 KiB maximum RSS.

These are synthetic integrity controls. The small files in training/ contain
explicit text saying they are not model tensors. Dataset and corpus are
synthetic fixtures. The actual metric code, NPZ files, aggregation and bootstrap
run, while model construction, generation and teacher-forced inference are
forbidden. There was no model training or inference, and these results provide
no scientific model-quality or speed claim.

The existing runtime was Python 3.12.3, NumPy 2.5.4 and Torch 2.8.0+cpu. The
process used one CPU in its affinity, nice 10, and OMP/OpenBLAS/MKL/NumExpr thread
limits of one. No packages were installed.

## Scope

This closes both the filename mismatch and the later NPZ-path reopening race
for arrays consumed by the current aggregation. It also rejects a cached gate inconsistent with
the selected checkpoint. The broader evaluation-context, source-code and input
currentness gaps remain open. This patch does not make local files immutable or authenticate an independently
mutable JSON-plus-NPZ pair. It retains the declared, hash-verified NPZ snapshot
for the current computation.

The archive separately preserves an actual baseline for the unmodified RAVDESS
complete.py controller: non-JSON prepared/source/output completion markers,
without models or NPZ files, still caused normal return and zero validation
subprocess calls. That issue remains open; no RAVDESS production source changes
are included here. It was measured on Python 3.14.4 in 0.0027045952156186104 seconds.

## Evidence and reproduction

RESULTS.json records the exact tested source hashes and runtime observations.
PROTOCOL.json describes the boundary and controls. raw-observations.tar.gz
contains the original and tested source, actual NPZ fixtures, baseline outputs,
unittest log, execution stdout/stderr, and the separate RAVDESS observation.
MANIFEST.json inside the archive gives the byte count and SHA-256 of each member.
Every member was read back after compression.

Run the new cache controls from a repository checkout with NumPy and Torch
available:

    python -m unittest discover -s qualification/hcsn_sustained_20261128/rsicd_external -p test_evaluate_cache.py -v

For the first round's two original-code baselines and six controls, copy
original/, use v1-tested/ as candidate/, and copy run_controls.py into a fresh
directory. For the final same-path baseline and seven controls, copy original/,
v1-tested/, candidate/, and run_controls_v2.py into a fresh directory. Invoke
the selected runner there. Each runner deliberately refuses an existing
evidence/run-1 or evidence/run-2 directory, respectively.

The archived candidate/ bytes are the exact native test subjects. Any later
format-only publication changes require their own source correspondence record.
Do not replace real scientific experiment directories with these fixtures.

## Repository formatting command

The exact repository just fmt command completed with exit 0 in 0.12747940979897976 seconds in a partial Git inventory containing these candidates and the original required byte fixtures. Its declared language scopes do not include qualification Python; stdout was 'No changed files need formatting.' This records execution of the original command, not Python formatting qualification or a full-repository check. Both final Python candidates parsed successfully and retained their exact tested SHA-256 values. The complete formatter receipt is included in the archive.
