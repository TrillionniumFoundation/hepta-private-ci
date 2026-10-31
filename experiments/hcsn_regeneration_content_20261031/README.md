# HCSN: regeneration, raw content, and action value

This additive experiment addresses five questions: exact repeated firing and
recovery; learning from raw observations; separation of content and policy;
agreement of action values with actual successors and full task costs; and
quality/cost across tasks and small widths on one CPU runtime.

The primary study compares equal-parameter ordinary and analytic renewal gates
on raw associative recall, finite categorical/waveform evidence, and handwritten
digit pixel rows. It is a deterministic content recurrence with a local analytic
feature. It does not silently inherit a continuous sampled-neuron interpretation,
the complete He-Xiong equity/default problem, or a production qualification.

Read `MATHEMATICS.md`, `CONTENT_CONTRACT.md`, and `POLICY_CONTRACT.md` for the
separate contracts. `PROTOCOL.json` fixes the primary matrix and the ordering of
publication, training, candidate freezing, and heldout evaluation. A secondary
LIF/Transformer comparison has its own implementation and freeze. `REPORT.md`
will report all results, including failures and limitations.

The repository baseline is pinned in `BASELINE.json`. All changes stay in this
namespace. The old finite-kernel qualification, native loader, Rust application,
and previous experimental results are not modified or requalified by this work.

## Reproduce

Dependencies: Python 3, NumPy, SciPy, scikit-learn, and matplotlib for figures.
Set `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`, and `MKL_NUM_THREADS=1`.
The installed sklearn digits dataset supplies fixed raw pixels without a network
download. Its exact content hash and split IDs are included in evidence.

After checking out the published source freeze, run `run_study.py` with the
recorded real source commit. Training and controller fitting must precede
candidate publication; test and controller evaluation must follow it. The runner
verifies code hashes and writes separate process output and resource receipts.
Existing training/evaluation directories are never overwritten by the runner.

## Timing scope

Training logs include data construction, BPTT, optimization, and evidence writes
up to the saved receipt boundary. Runner clocks include process startup and final
I/O. Diagnostics also measure repeated forward/readout calls on already loaded
raw input. These are different scopes and are reported separately. Abstract
action tariffs are never relabeled as CPU seconds, money, or measured energy.
