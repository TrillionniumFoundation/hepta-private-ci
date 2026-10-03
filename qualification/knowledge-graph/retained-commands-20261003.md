# Exact KG qualification command retention

## Observed gap and bounded repair

At PR1330 source `d582de6405836fda69336003c9b5bcadbf004f0f`, tree
`fdb515af71d9c89d70efecb457f42ef1c779e1d2`, the deep KG workflow had only
manual/reusable entry points and no workflow caller. Ordinary aggregate tests
exclude the explicitly ignored crash and capacity cases. The workflow also
retained no immutable command artifacts or nonzero-selector guard.

The repair adds narrowly scoped pull-request/main triggers to that existing
workflow. Existing `hepta_ci_exec` binds each actual command to the clean exact
source or independently recomputed two-parent merge tree; every required outcome
and bounded log survives failure. The KG fan-in rechecks command, source/tree,
workflow identity, terminal count, log byte length and SHA-256, and fails if any
required command is failed, missing, rejected, empty or inconsistent. Failed
commands remain failed while subsequent diagnostic commands can execute. The
repository-wide detailed-design observation keeps its preexisting advisory role.
Workflow permissions remain `contents: read`; no aggregate router was changed.

The kernel, prompt owner/consumer, Memory owner, default Agentd profile and
explicit qualification writer profile remain distinct. The named ignored
crash-window case runs in both lanes with exact selection and minimum one passed
test. Only the source lane runs the full declared capacity workload: 256 writes,
20 product queries and five ordinary reopens. A dedicated nextest profile allows
35 minutes of measurement, with an outer 40-minute command watchdog and no
retries. This is a test budget, not a target-host latency promise. No Rust source,
ignore marker, SQL or paused path is changed, and no local Rust build was run.

## Tests and limits

Seven focused Python tests exercise the actual recorder in temporary repositories:
empty success and explicit failure keep the aggregate red but retain later logs;
log removal/tamper, command/source/tree/lane/run relabeling and forged counts
reject; existing or in-checkout outputs reject; exact ignored selectors and
workflow failure retention stay connected. The shared recorder's 45 negative and
execution tests passed. Python lint, scoped formatter, YAML parsing and nextest
configuration parsing passed. These do not replace future hosted native results.

The actual-daemon production path with the sealed, independently recovered
mutation capability remains unqualified. The feature-only E2E uses an explicitly
allowed qualification store-write path and cannot replace that evidence. All
production qualification, independent acceptance, activation and release claims
remain false.

## Navigation provenance

The original map is retained at
`d582de6405836fda69336003c9b5bcadbf004f0f:docs/modules/knowledge.graph/IMPLEMENTATION_MAP.json`,
blob `362535dd60d2a77eb1a544c9d407ab93d25fd365`. Its historical `sourceBase`
`e5f7755fec463050fda183a6f79913749722a8dd`, tree
`8e508a8dae0b62ad8f30f554af076e8f75a7266f`, is unchanged. Existing v3
`exact_blob` navigation semantics bind current mapped content plus the complete
observation closure to the published source commit, independently of this
historical provenance. No source ancestry, old test claim, false evidence flag
or unrelated module map is replaced.
