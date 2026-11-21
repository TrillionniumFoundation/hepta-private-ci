# Single-use outer campaign coordinator

This stdlib-only layer closes three execution gaps in the learning runners:
a global namespace/attempt registry, a complete child-process time budget shared
by fit and final, and receipt validation that never equates exit zero with passing.
It does not change a model, task, optimizer, hyperparameter or data generator.

## Root's immutable preregistration

Copy PLAN.example.json outside the source worktree and fill the final exact Git
commit and absolute source/output paths. The five stage names, modules, namespace
prefixes/suffix and seeds are fixed in campaign.py. Seeds are 1907341, 4812467 and
8629119. Every namespace ends in 20261121-e29f-independent-01.

Formal registration requires Linux, an actual Git worktree with HEAD equal to the
declared 40-character SHA, clean tracked/untracked relevant source, and committed
coordinator bytes equal to the coordinator actually running. Runtime source
files, including the learning closure and coordinator, are hashed and rechecked
before and after each child. Optional package/runtime identity is also checked
by the learning manifest. Evidence output must stay outside this source tree
until all admitted phases finish.

Registration preserves the absolute lexical Python invocation and separately
records its real path. Each phase verifies both; child commands use the lexical
invocation so a virtual environment retains its installed packages and prefix.

Registry: /home/qian-qi/hcsn-confirmatory-registry-v1. Each namespace gets a
SHA-256-named O_EXCL registration file binding its source, plan, manifest path and
one attempt path. Registration of all five stages must finish before any phase.
Each phase has a separate O_EXCL reservation; missing completion after a reserve
means unknown, not retryable success. No overwrite, resume, automatic new attempt,
or namespace reuse is provided.

```sh
python -m qualification.hcsn_sixwork.campaign register --plan /ABS/ROOT_PLAN.json
python -m qualification.hcsn_sixwork.campaign freeze --stage readout
python -m qualification.hcsn_sixwork.campaign fit --stage readout
python -m qualification.hcsn_sixwork.campaign final --stage readout --selection-sha256 ROOT_EXTERNALLY_BOUND_SELECTION_SHA256
```

Use the same explicit sequence for joint, architecture, feature and boundary.
Freeze creates an immutable second binding from namespace/registration to the
actual manifest SHA and unique attempt. Final never computes a selection SHA
and proceeds automatically: root must supply the exact externally reviewed SHA.
The supplied hash must equal both the original selection bytes validated at fit
and the current file; changing selection after fit cannot authorize new bytes.

## Complete process cost and lifetime

Fit+final share 180 child-process wall seconds for each stage, except boundary
which shares 90. Final receives only limit minus the measured fit-process wall.
Measurement surrounds process creation through wait/exit and output-handle close,
including Python imports, all serialization and exit. Freeze has a separate
90-second setup timeout and retained cost. Registration/setup and coordinator
validation time are reported separately, not hidden inside a learning advantage.

Stdout/stderr are exclusive files. Append-only JSON events retain start, actual
PID, end, return code, timeout, CPU usage and wait4 peak RSS when available.
RSS is a child high-water mark, not a sampled sum over all descendants.
Timeout kills the child process group. Linux parent-death signaling kills the
leader if the coordinator disappears; unfinished registry reservations remain
unknown and must not be retried. Root's host/cgroup admission still owns wider
allocation and descendants outside that process group.

## Exit zero is not evidence of a pass

After each fit/final child exits, integrity.py checks the complete frozen grid,
status/metric finiteness, parameter hashes and actual declared parameter counts,
NoUpdate semantics, identical final data across paired methods, metric arithmetic,
selection consumption and the cumulative hash-chained cost ledger. Pending,
unexplained failed or over-budget ledger work blocks continuation. A changed
source or manifest also fails the phase.

Predeclared missing official CfC is explicitly UNAVAILABLE: the phase returns
nonzero and is not PASS. If every required available cell is sound, root may still
explicitly seal its selection and evaluate those available models. Any failed,
missing, nonfinite, unexplained-unavailable or unknown cell blocks final.
No missing baseline enters a completed-method denominator.

Complete/failed/unavailable phase receipts remain separate from scalar quality
claims. Registry artifacts and process logs should be retained together with the
learning attempt. Three seeds support descriptive paired summaries only.

## Independent tests

`python -m unittest qualification.hcsn_sixwork.campaign_tests -v` uses temporary
files, artificial receipts, and tiny stdlib child processes. It never registers
a formal namespace, calls a model or generates a formal example. Tests cover
exclusive reservation, cumulative budget, timeout/failure retention, unfinished
cost work and an exit-zero-shaped receipt containing a failed cell.
They also cover actual temporary-venv prefix preservation, immutable fit-selection
binding, exact fit arm/case grids and a final success row missing its split.

