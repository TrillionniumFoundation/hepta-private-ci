# Production qualification preparation

This is an independent, write-once qualification layer. Existing benchmark code,
reports, performance results and runner ownership are unchanged. It implements
the plan/result contracts, complete representative corpus, immutable freeze,
fixture-runner adapter and report gates. **Production qualification remains held.**

## Run

Use Python 3.11 or later; there are no third-party Python dependencies.

```sh
python3 -m unittest discover -s qualification/native-agent-v1/production-qualification -p 'test_*.py'
python3 qualification/native-agent-v1/production-qualification/qualify.py \
  --plan qualification/native-agent-v1/production-qualification/plan.example.json \
  --output /absolute/new/run-directory
```

The example deliberately contains null paths, binary hashes and unresolved model
revision evidence. Preflight performs no model or runtime calls and writes held
reasons. Exit status 2 means held, including after successful diagnostic controls;
it must not be converted to CI success for production qualification. An existing
output directory is an error. After a crash retain the incomplete directory and
reconcile unknown operations through their original owners; do not resume by
re-running its commands.

To run the existing controls, fill and freeze every file/binary fingerprint and
full source revision, supply a private fixture directory containing pinned
`fixture_tool.py` and `fixture.txt`, and add `--execute-fixture-controls`. The adapter
invokes the existing `benchmark_v2.py` for each resident lane in the frozen order.
That runner requires its real Linux runtime/SSH setup and model gateway; it is not
replaced with a mock. Tests use a simulated subprocess only to test adapter contracts.
Execution never falls back to another backend or retries a failed lane.

The example source hashes identify the audited old benchmark implementation. The
revision fields are audit starting points, not attestations that newly built
binaries contain this implementation. Before measurement replace them with the
actual source revisions and record the builder's binary-to-source provenance.
The original #4151 binary used an earlier runtime revision than runtime #75's
current head. Its historical results cannot be assigned to a rebuilt executable.

## Contract and coverage

`contracts.py` is the executable schema: versioned objects reject unknown fields,
all three lanes and all fourteen unique cases are mandatory, revisions use full
SHAs, and executable/input/source files require exact SHA-256 checks before and
after a lane. The frozen plan hashes the complete configuration and corpus before
any process launch; actual generated configuration hashes and raw report hashes
are also retained. Fixture files are not mutable benchmark outputs.

`behavior_matched` requires equal configured ceilings. `individually_optimized`
requires explicit nonempty text descriptions for each lane. They must use separate
run directories, as must replay and live modes. The old adapter has a fixed model
and fixed ceilings, so unsupported optimizations remain held. Equal ceilings do
not prove equal model request bodies; actual tool inventory, instructions,
context, provider options and model revision evidence require a subsequent
parity audit before comparisons. A live model alias does not freeze model weights.
Replay usage is synthetic. Rotate lane order in separately frozen repetitions to
study order effects; do not pool unequal profiles or modes.

The checked-in example is one `behavior_matched` / `replay` plan: three lanes,
fourteen cases and two repetitions give **84 planned slots for that one group**.
It is not a frozen or measured two-group comparison. The full per-lane optimized
configurations have not been registered, frozen or measured; descriptive notes
alone do not supply or apply those configurations.

Three controls reuse the old sum/line-count/digest fixture. Eleven representative
cases specify exact inputs, required capabilities, independent oracles and fault
injection points: large output, PTY, edits, observed failure repair, multiple tools,
MCP, a live third-party read, cancellation, lost tool acknowledgement, controller
restart, and lost model acknowledgement. Live service identity and immutable
resource are intentionally unset until authorized and frozen. The corpus itself
does not implement a PTY, MCP server, credentials or fault injection.

Each fixture control is bound to its complete registered input, capability list,
oracle and fault contract in `contracts.py`. Changing any of these fields is
rejected before the run directory is created or a process is launched. Keeping
the old prompt cannot relabel a fixture result as a production, PTY or injected
failure result. Every new run freezes the changed contract-validator source hash
in `FROZEN.json`; existing run evidence is never rewritten.

Adding production execution requires a separate adapter using the actual Agentd
ThreadStore/queue/writer/FinalUse path and independent checks for every oracle.
A caller-supplied capability flag or fixture owner cannot satisfy that gate.
Unknown effects must retain their original operation and cannot be re-enqueued.

## Statistics and resources

Every planned slot is reported as passed, failed, held or not_run. Missing,
duplicate or cross-mode rows are rejected. Aborted lanes retain failed samples
and subsequent not_run slots. Successful-only latency and all-attempt latency are
reported separately. For fewer than 100 observations, report min/median/max and
omit p95. Larger samples have a finite-sample empirical p95, never a claim of a
stable tail. No performance ratios or production pass are emitted by this stage.

Resource evidence is retained without recomputing sums: simultaneous sampled
process-tree PSS, process and non-overlapping cgroup CPU, missing coverage, sampling
cadence, observer cost, and actual request inventory. Process CPU and cgroup CPU
overlap and must not be added. RSS sum is not unique memory. Resource windows are
whole resident lanes including startup/shutdown/warmup/observer, whereas case
latency has a different window. There is no per-case CPU allocation or global
remote-model/SSH resource claim. Output retention size, model context/usage and
functional coverage remain separate dimensions from process memory.
