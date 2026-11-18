# N256 system-Python runtime discovery source

Status: **REAL RED / ZERO_MODEL / HOLD_RUNTIME_IDENTITY / all_closed=false**.

Draft #6622 preserved two real pre-input failures from the selected old venv:
NumPy had no concrete module file both with and without the first attempt's
`PYTHONNOUSERSITE` override.  This isolated successor does not repair or mutate
that venv and does not create another resource-snapshot retry.

The source here is a separately keyed, stdlib-only discovery probe for the
existing `/usr/bin/python3`.  It records the interpreter bytes, `sys.path`, user
site state, NumPy/SciPy module specs, distribution RECORD identities, and any
concrete distribution-owned `__init__.py` anchor bytes.  It does not import
NumPy or SciPy, read N256 inputs, import HCSN code, run a dynamic step, or call a
matrix exponential, Torch, or an optimizer.

A successful discovery is not runtime admission.  It can only establish
whether a concrete candidate exists for a later, separately frozen resource
snapshot.  Allocation, calendar, numerical execution, production adoption,
C2 full replay, HPCA custody, equal-budget benefit, asynchronous cost, and
`all_closed` remain unchanged.

## Attempt 001 result

The one frozen job `1a1ecf46cc4-392-45bb` used the exact v1 key and launch
contract.  It failed with exit code 1 before emitting stdout because the
system-Python NumPy distribution exposes no `importlib.metadata` file list.
The authoritative terminal receipt reports neither timeout nor cancellation.

That result is an identity-discovery RED, not runtime admission.  In
particular, the absent file list prevents the requested RECORD/file inventory
from being hash-bound.  No retry key is assigned here.  Candidate imports,
N256 input reads, dynamic steps, matrix exponentials, Torch calls, and optimizer
steps all remain zero.
