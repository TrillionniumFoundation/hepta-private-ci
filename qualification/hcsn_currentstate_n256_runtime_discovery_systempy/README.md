# N256 system-Python runtime discovery source

Status: **SOURCE_FROZEN / ZERO_MODEL / HOLD_RUNTIME_IDENTITY / all_closed=false**.

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
