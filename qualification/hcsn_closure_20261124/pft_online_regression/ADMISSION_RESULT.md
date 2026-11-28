# First local rehearsal of the 20-control admission gate

The first local invocation passed all 20 explicit synthetic controls with zero
failures, errors or skips. Ledger/codec/JSON peer/binary peer/admission counts
were 4/5/4/4/3. Driver time was 8.34928202899755 seconds; the supervising process
observed 8.547306944004958 seconds, exit 0, without timeout. The registered
process-group limit was 120 seconds. This is not a hosted Actions result.

The admission case observed one validate_packet and one eigvalsh call for one
received TCP offer. Its complete receipt and packet identity matched the fixed
reference copied from the already-observed #7211 baseline. The earlier two-call
baseline and unsafe capacity schedule were not rerun. The original admission
qualification source and CLI remain byte-for-byte unchanged.

Two actual receiver processes, PIDs 55 and 57 in this invocation, shared one
SQLite database. Both requests began before the first commit; the first was
accepted and the second refused at capacity, leaving revision 1. Both processes
exited 0 without forced termination. Exact replay and refusal-priority controls
also passed. Optional per-call capacity is still not a global writer policy:
the control explicitly retains the fact that an uncapped writer can exceed it.

## Source and runtime identity

- Base: `1a5a264c4eda7bf29e3e35ca7127402932721223`.
- Prior registered protocol and fixture: `80eeaf44191cfddedad93329308817eb84226216`.
- Implementation frozen before execution: `c1366672bdef9bcb534ea52996ecd186244c1f8b`.
- Actual local Git capsule head: `d52f0e2f87b88f6847f62e313690ca2c8395410f`.
- Fixed fixture raw SHA256:
  `23b5ac14950e21c18dcdb636e0eca1a58fbc3104d3c85226356a0e87ce3321c5`.
- Executed driver SHA256:
  `8a83ef7edb2496c37480f3c31647060843fd4bd01a6428bc1e1613e43c150631`.
- Formatted driver SHA256:
  `b7a26e2544cdc9350a5ee6e7763ae1f2e1ad7b38a9af11465902f3d091e173dc`.

Local Python was 3.12.14, NumPy 2.3.5, with one BLAS thread. The workflow still
requires Python 3.12.3 on Ubuntu 24.04. The source capsule is a verified subset,
not a complete repository checkout. FROZEN.json records exact dependencies,
runtime observations and runtime_closure_complete=false. No historical cache,
DEV/final data, E1-E6 experiment or model training was accessed or executed.

Official just fmt ran after the tests. Ruff 0.15.13 reformatted only the driver;
its AST is identical before and after, and all eleven implementation/test files
passed the explicit formatting check. Local tests were not repeated afterward.
The archive contains the first logs, source copies, fixed fixture, process
observations, supervisor, raw results and formatting evidence. Hosted runs remain
independent evidence; local success must not substitute for a queued or failed
hosted execution. No training-time, learning-quality or adoption claim follows.

Archive `admission-local-attempt-1.tar.gz`: 47593 bytes, SHA256
`50ab986a06784d7ca79a62ee77702f8486a809e76e8c7cd380b342c141021a7f`.
