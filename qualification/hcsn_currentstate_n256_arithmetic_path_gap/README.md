# N256 cross-worker arithmetic-path gap

Status: **READ-ONLY GAP LOCALIZATION / HOLD / all_closed=false**.

The successful oracle run `44848445922`/`136673835596` and the terminal
candidate RED `44914033031`/`136875692405` used the same Ubuntu 24.04 image,
image provisioner, region, exact CPython executable, NumPy and SciPy records,
single-thread environment, and `_stream_action` body. They ran on different
hosted workers. The candidate rebuilt and checked all 68,105 frozen boundary
coordinates before its one dynamic step and two dense exponentials, then
failed 665 of 69,728 strict final comparisons with maximum ULP distance 98.

The two original records do not bind a CPU model, CPU feature set, or BLAS
vendor/runtime dispatch. The oracle also did not publish its pre-exponential
augmented matrices and seed bytes. Therefore the earlier Python-minor-version
explanation is eliminated, but input-byte equality at the actual exponential
boundary and the remaining hardware arithmetic path are not established. The
arithmetic/path cause remains **UNKNOWN**; this review does not assign the RED
to BLAS or hardware.

Any next numerical candidate must use a new frozen identity and key. It must
publish both pre-exponential matrices and seeds and bind the CPU/BLAS dispatch,
or use a separately validated deterministic non-BLAS action. It may not retry
the consumed key, copy oracle outputs, round values, introduce tolerance/ULP
rescue, or relabel the preserved RED.

This package executes zero numerical kernels, dynamics, exponentials, Torch,
or optimizer work. N256 qualification and production adoption remain false;
C2 full replay remains 0/6; HPCA remains NoUpdate; all historical negative and
UNKNOWN records remain authoritative.
