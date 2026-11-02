# CPU CI fixture lane

`joint_ci.py` replays CPU mathematical/semantic fixtures. It does not start
formal preparation, fitting or confirmation, and it does not regenerate frozen
weights. The two optimizer updates inside the actual-loss audit are explicit
engineering checks, not admitted efficacy fits. Native build/ACK/fault-injection
qualification remains separate; this lane records `native_ci_executed=false`.

The selected source identity is explicit:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m tools.hcsn.digital_joint_20261102.joint_ci --source-freeze tools/hcsn/digital_joint_20261102/FORMAL_SOURCE_FREEZE_ATTEMPT2.json --out /tmp/new-joint-cpu-ci
```

The runner verifies the entire registered map, then copies those files and audit
helpers into a new isolated tree. Fixed-output audit CLIs write there. Every case
has a fresh output directory, stdout/stderr and complete child process CPU/wall
receipt. The original registered sources are checked again afterwards. No test
overwrites the formal evidence or source files; staged source bytes are recorded.

Six cases run: independent task semantics, the ten-check budget profile,
independent finite-kernel/gradient mathematics, actual model-loss finite
differences, public-only compiled DP, and four-family packed JSON/gzip reader
plus NumPy/Torch export inference comparison. The actual-loss and export cases
use hand-constructed legal histories, never a formal cohort or final model.

The suggested workflow is `.github/workflows/hcsn-joint-distribution.yml`:
Ubuntu24.04, Python3.12, exact NumPy2.3.5/SciPy1.17.0/PyTorch2.9.1 CPU versions,
contents-read permission only, no persisted checkout credential and SHA-pinned
Node24 actions. Exact package versions and CPU build are asserted after install.
Sparse checkout avoids downloading unrelated research archives; checkout's
official source enables `blob:none` for a sparse checkout. All fixture output is
uploaded with `always()`; the job has a 20-minute ceiling and cancels obsolete
same-ref runs. There is no GPU or energy result.

Official release/action provenance is stored in `joint_ci_PRIMARY_SOURCES.json`.
PyTorch2.9.1 is a published upstream release, whereas this study's actual training
runtime is 2.15.0+cpu. The CI lane deliberately tests math/semantics on a released
CPU build; it does **not** claim identical initialization, optimization updates,
final model bytes or training costs across these versions.

Local execution completed all six cases under Torch2.15.0+cpu, NumPy2.3.5 and
SciPy1.17.0, with all 20 attempt2 registered source hashes unchanged. An earlier
local run also passed against the original 18-source identity. These local
records do not establish that hosted GitHub Actions on Torch2.9.1 has passed;
that requires the actual workflow result after publication.
