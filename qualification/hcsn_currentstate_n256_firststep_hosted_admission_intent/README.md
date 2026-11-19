# N256 warm-1 hosted admission intent

Status: **SOURCE_FROZEN / ZERO_MODEL / HOLD_ADMISSION / all_closed=false**.

This isolated successor binds the already frozen warm-1 dense-oracle source to
the exact hosted runtime observed by Draft #6627 and defines fail-closed,
same-job preflight rules for a future numerical request.  It does not issue
that request or convert the point-in-time observation into an allocation.

The future bounded child would be limited to one process, one dynamic step,
two dense matrix exponentials of orders 258 and 259, and one 69,728-coordinate
serialization.  Before numerical imports, a future launcher must confirm the
exact Python/NumPy/SciPy identity, at least 10 GiB MemAvailable, at least 1 GiB
SwapFree, at least 6 GiB headroom at every finite ancestor cgroup limit, four
effective CPUs, zero prior OOM/OOM-kill events in readable ancestors, low
instantaneous memory pressure, and a fresh same-session capture.  The child
must receive a 4 GiB `RLIMIT_AS`, one-thread BLAS settings, a 600-second child
deadline, and a 20-minute job deadline.

The 4 GiB address-space limit is an enforceable future upper bound, not an RSS
measurement.  The visible FP64 arrays are much smaller, but SciPy/LAPACK
workspace and Python object overhead are deliberately not inferred from source
alone.  Actual RSS, wall time, end-of-run cgroup event deltas, output bytes,
and complete cost still require one separately frozen execution.

Current evidence has no allocation or calendar reservation.  Therefore this
stage intentionally returns only `preflight_contract_satisfied`; it cannot set
`runtime_admitted`, `resource_admitted`, or
`n256_numerical_execution_allowed`.  Synthetic tests exercise validator shape
only and are not resource originals.

The first local verifier invocation is preserved in `DEVELOPMENT_RED.json`.
It addressed the hosted observation's top-level admission flags as if they were
inside its nested observation record and failed with `KeyError` before any
numerical action.  The repair changes only those two JSON paths.

Historical RED/UNKNOWN, the unintended duplicate observation, C2 full replay
0/6, HPCA NoUpdate/external custody, equal-budget benefit, asynchronous
complete cost, production adoption, and `all_closed=false` remain unchanged.
