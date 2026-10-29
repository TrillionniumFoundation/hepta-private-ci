# Representative qualification status — 2026-10-29

The recorded remote baseline is **12 successful replay cases: three lanes × four
tasks**. Live model identity is not fixed. Remote long-output and controlled-fault
completion evidence has not been obtained. The newer build/test operation has an
unresolved original-owner outcome. These latter items are not counted as passes
or described as running.

This is a qualification `SessionOwner` result, separate from production Agentd,
ThreadStore, QueueStore and FinalUse acceptance. The complete production corpus
verdict remains **held**.

## Observed evidence

| Work | Result recorded in this snapshot | Evidence scope |
| --- | --- | --- |
| App-server: edit, repair, multi_tool, mcp_readonly | 4/4 remote replay passes | Existing runtime jobs; real file actions, test processes and MCP stdio fixture |
| Facade: the same four cases | 4/4 remote replay passes | Distinct source-pinned `hepta_facade` binary |
| Native: the same four cases | 4/4 remote replay passes | Native qualification runner and its original admissions |
| Candidate Python representative/fault tests | 6/6 local passes | Real Python fixtures plus capture, identity and control-boundary tests |
| Candidate protocol boundary tests | 14/14 local passes | Protocol, call identity, feedback and deadline tests |
| Candidate v3/v4 remote Rust build/tests | Outcome unknown | Original operation key awaits owner reconciliation |
| Long-output runtime comparison | No remote case result available | Implementation and local generator tests only |
| Runtime cancellation and process restoration | No remote case result available | Implementation, local process fixtures and boundary tests only |
| Live behavior-matched comparison | Not qualified | Weight/model identity and provider revision are not fixed |
| Individually optimized comparison | No run result available | Applied-budget profile interface exists; no optimization result |
| PTY and live third-party connector | No result in this slice | Separate production corpus requirements |

The remote 12/12 result was reported by the operator after checking captured
requests/responses, workspace oracles and original admissions. Its primary
artifact directory on host `main` is:

```text
/home/qian-qi/work/hepta-cell-meta-evidence-20261029/representative-replay-02
```

The full remote artifact index and hashes have not been imported into this
documentation package. Preserve that distinction when publishing the result.
The earlier failed attempt remains in the sibling `representative-replay-01`
directory. Its observed startup error was:

```text
Error: operator host `qualification` requires explicit allow_job_network=true
```

The corrective change set that field in the experiment's generated private
configuration. This uses the existing operator contract and does not establish
OS network isolation. The successful baseline used the same capability across
all lanes. The failed attempt remains part of the evidence history.

Local raw test output, exit codes, test counts, Python identity and source hashes
are retained in
[LOCAL_VALIDATION.json](evidence/representative-status-20261029/LOCAL_VALIDATION.json).
That record contains no Rust build or real Hepta runtime-owner acceptance result.

## Source and binary identity

The candidate branch is `codex/native-representative-full-20261029`, based on
`709e67c8ce3077e5a3d53abc28c47d0fad64e377`. No final commit, push or PR receipt is
asserted by this status snapshot.

| Artifact | SHA-256 | Bytes |
| --- | --- | ---: |
| Runner used for the four-case remote baseline | `363febe62404b70b6dd6531d40e16a99ee82c32934876767b0acca221884e044` | 227,761,256 |
| Codex v0.165.0 qualification build | `7b9a74955391ef21e56a021cd119c0e934d42d4b24339bccf0af8c74abc331cc` | 1,506,256,128 |
| Distinct v0.165.0 facade build | `4f96fb3aa150f7f182f4527da2e83ce836a7a77d08206ce69dee294a049563a8` | 1,090,831,136 |

The two Codex builds are pinned to upstream source commit
`360319d8dee62d87e2d59fc0c21805d79519cfed`.
[OFFICIAL_BUILD.json](evidence/representative-status-20261029/OFFICIAL_BUILD.json) records upstream
toolchain 1.99.1, qualification toolchain override 1.95.0, and wrapper, bootstrap
patch and lock hashes. Its SHA-256 is
`30df8de393e58f958d1ccd0890c1b3aa2bc5db0c485c73b4a5d048161e616e85`.
They should be described as source-pinned qualification builds, rather than
unaltered downloaded release binaries. These file sizes identify artifacts;
they are not a controlled memory, CPU, latency or deployment-size comparison.

The live service advertises alias `qwen38-flash-next-uc` with owner
`ai-max-local` at the previously observed local `/v1/models` endpoint. That
advertisement does not fix weights, service revision or a deployment history.
Live requires the independent nonsecret identity evidence described in
[REPRESENTATIVE_EXECUTION.md](REPRESENTATIVE_EXECUTION.md), followed by actual
captured response-model and usage checks. Replay usage remains synthetic.

## Unresolved original operation

The outstanding key is:

```text
p1-representative-v3-v4-build-tests-20261029
```

Its authoritative admission/job identity and terminal outcome must be recovered
through the original owner with the original payload. A client/tool timeout is
not evidence of completion, non-admission or failure before execution. This
snapshot records the outcome as unknown; it does not replace the request with a
fresh key or infer that a build is still running. Keep the original request,
owner receipt, job identity, terminal publication and complete logs together
when reconciliation becomes available.

## Publication groups

| Group | Concrete contents | Honest publication status |
| --- | --- | --- |
| A — Four-case qualification baseline | Representative tool surface, workspace/MCP fixtures, replay feedback audit, source/binary pins, failed attempt and 12/12 baseline evidence | Functional replay result recorded; attach the original artifact index before claiming a complete published evidence bundle |
| B — Long-output and controlled-fault extension | Separate retention/presentation budgets, original-output reference checks, cancellation and single owned-runner restoration, local tests | Implementation candidate; remote build and new case acceptance remain unverified |
| C — Live/profile entry points | Real provider forwarding, model identity requirements, applied equal/individual budget profiles and raw captures | Interface available; live and optimized comparison results remain unqualified |

Keep result groups separate in reports. The individually optimized interface
currently applies budget ceilings; it is not evidence that each engine received
exhaustive tuning. A new mode, profile, source or binary set requires a fresh
frozen run directory. The v3 baseline-core patch must not overwrite P0's shared
checkpoint projection; use the P0 bounded-presentation implementation when
integrating into the owner-integration tree.

The supported baseline claim is execution and feedback compatibility for the
four bounded tasks under fixed Responses replay. Model reasoning quality,
production replacement, general capability and resource efficiency remain
separate questions. No p95 or performance ratio is established here.

## Required evidence collection

The machine-readable path inventory and unresolved fields are in
[EVIDENCE_INDEX.json](evidence/representative-status-20261029/EVIDENCE_INDEX.json).
It distinguishes known original paths from future paths that must come from an
actual admitted run. It contains no placeholder success records.

For the known baseline, retain top-level `FROZEN.json` and `REPORT.json`, each
lane/case `FROZEN.json` and `RESULT.json`, raw model captures, backend/executor
logs, original session manifests/admissions/checkpoints, and runtime controller
and remote-job records. Hash the original files after the run is quiescent; do
not replace an active owner database with a convenient file copy.

For long output, add the complete original stdout/stderr, terminal publication,
matching retained-output reference and actual model-item byte measurements.
For faults, add `BEFORE.json`, the exact original command/config, injection and
reconciliation evidence, original child/job bindings, terminal output and the
original Codex interruption notification where applicable. For live, add the
deployment/weight identity source, frozen profiles, actual model identities and
actual usage. None of these missing records can be substituted by a local unit
test or a replay result.
