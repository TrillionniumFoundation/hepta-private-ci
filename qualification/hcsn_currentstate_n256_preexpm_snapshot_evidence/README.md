# N256 pre-expm snapshot evidence and duplicate-run RED

Status: **INPUT BYTES EXACT / EXECUTION PROTOCOL RED / HOLD**.

Creating the frozen run branch triggered GitHub Actions immediately at source commit `589622451d292792c02d9d3aafea7bd7a45263e4`. Before that run was observed, the branch was fast-forwarded once to the explicit activation commit `87e7947d5d8b3279cf621847e01712a43b16ce43`, which triggered a second run with the same frozen key. Both runs completed naturally; neither was cancelled, rerun, or replaced. The duplicate violates the one-run protocol and is permanently recorded as RED.

Runs `44916753930`/job `136883924300` and `44916786884`/job `136884030761` both published all twelve raw pre-expm arrays. Within each run, oracle, attempt002 candidate, and #6901 rebuilt inputs are byte-identical for both undiscounted and discounted augmented matrices and seeds. All twelve raw files are also byte-identical across the two different workers. The two RESULT files are byte-identical; HOST files differ as expected and preserve each CPU/NumPy/OpenBLAS record.

Across both runs the actual work was six boundary decodes, twelve augmented builds, twelve seed builds, and zero dynamic steps, exponentials, SciPy imports, Torch calls, or optimizer steps. This evidence only closes the current-source pre-expm construction question. The original successful oracle run did not publish its actual pre-expm bytes, so retroactive original-run equality remains unavailable. The exponential arithmetic path and the cause of #6901's 665-coordinate RED remain `UNKNOWN`.

The duplicate protocol RED prevents this identity from satisfying its single-execution contract. No retry, replacement key, or qualification transfer is permitted. N256 dynamics, later cycles, N512, full state, C2 full replay, HPCA custody, production, adoption, and `all_closed` remain false/open as previously recorded.
