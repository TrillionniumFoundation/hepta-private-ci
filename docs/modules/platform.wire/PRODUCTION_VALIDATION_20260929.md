# platform.wire production-validation convergence

Date: 2026-09-29. This is a development and operating contract, not an acceptance receipt.

## Candidate and source changes

The review began at `3abfbbaff117d20827e5add06a168515a98ba320`. Commit `59d60eee87045c20a2b52df1539174a1dbc4e952` fixed three test-only `u32`/`Generation` mismatches through lossless conversion, and allowed the legitimate zero fleet completion gap. Commit `e292f812f9d1f73aff58592a29506540ae899dff` added a seven-case contract against actual Rust fleet-emitter output. Commit `9efddb4ee1efee7519f40f9c3dba0057f9e2a2b7` introduced protected-host command evidence and failure retention. Subsequent changes are identified by the actual containing commit and its source tree, not by copying a parent pass into a new candidate.

The same `ManagedRecordStream` now reclaims excessive empty staging capacity immediately after authenticating a buffered record, before reading the next prefix. Previously, a large completed allocation could survive when the same feed ended with a tiny next-record fragment. The new regression covers four following-fragment boundaries, exact consumption, continuation, accepted-prefix delivery, and replay rejection. Active fragments are never dropped. Explicit retention limits, shared work budgets, sequence state, keys, egress, terminal retirement and consuming EOF retain their previous ownership.

No alternate authenticator, network listener, scheduler, authority grant or domain executor is introduced. Normal product execution continues through the existing worker, Agentd, domain adapter and final-use owner.

## Validation command matrix

| Scope | Actual owner / workflow | Evidence boundary |
|---|---|---|
| Core source and ordered merge | `platform-wire-core.yml` | Full wire all-targets, resource and public consumer contracts, strict Clippy, single/fleet release profiles, real emitter contract, HTTP parser, receipt and performance-validator tests |
| Integrated source and ordered merge | `platform-wire-exact.yml` | Existing registered adapter ports, cross-runtime loading, gateway build and strict lint, plus the same new evidence-validator regressions |
| Protected target host | `platform-wire-target-host.yml` and `platform_wire_target_qualification.py` | Pinned/offline native commands, existing normal worker-path regression, release profiles and process RSS on the selected host |
| Paired five-path performance | `platform_wire_performance_gate.py` | Owner-supplied frozen workload plan and raw paired candidate/reference measurements; no benchmark or external acceptance is fabricated |
| Lifecycle | `platform_wire_status.py` and `platform_wire_receipt_subject.py` | Evidence must match the selected source; independent reviewer, operations and release remain external inputs |

The dedicated wire floor remains 102; it is a lower-bound admission check, not the number of unique tests or a success claim. Resource and consumer floors remain 6 and 5. Fleet-validator self-tests increased from 9 to 11, and the real-output contract has 7 cases. Target command-evidence tests have 16 cases; source-subject tests have 10; paired-performance validator tests have 8. The legacy Lane A command set has its own scope and must not be confused with this dedicated matrix. Repeated execution of the same suite is not additional unique coverage.

## Protected-host evidence

The target workflow still requires `workflow_dispatch`, a matching operator-selected source SHA, fixed `self-hosted`/`hepta-target-host` labels and the protected `platform-wire-target-host` environment. No arbitrary runner or input ref is executed. The repository-selected Rust toolchain must already be installed; dependencies remain locked and offline. Build products and evidence live outside the source checkout, in separate run/attempt-owned directories.

The command list retains existing tests and adds resource contracts, the integrated gateway parser suite and the existing `real_agentd_worker_accepts_fresh_context_and_rejects_final_use_tombstone` regression. That regression exercises the normal worker/Agentd path with a mock provider; it is not proof of deployed peer authentication or a live provider acceptance.

Each command runs through the existing bounded `hepta_ci_exec` owner. The target receipt verifies the exact argv and floor, source/tree/parent identities, run and attempt, clean before/after identity, exit results, time/output bounds, log bytes and SHA-256. Test counts are independently re-parsed from the retained log using the existing parser. Missing, running, skipped, timed-out, cancelled, stale, malformed or tampered records cannot produce a passing receipt.

Failure evidence is uploaded with `always()` instead of disappearing at the first failed command. A failed setup is recorded as infrastructure-invalid when the runner can still execute the receipt step; runner loss can leave incomplete records, which remain nonpassing. Cleanup removes only that run's build directory. Release profiles retain their raw reports and GNU time resource observations. These profiles still do not measure real network queues, allocator-call counts or deployed multi-process pressure.

## Selected-source lifecycle reports

Agreeing receipt SHAs are insufficient: all of them could describe an old candidate. With a Git checkout, lifecycle rendering now binds the receipt source to its actual HEAD. An explicit `--expected-source-sha` cannot override a different HEAD. Git inspection failure is not treated as an archive fallback.

A detached source archive requires explicit `--expected-source-sha`. The operator must verify the archive digest and workflow origin separately; the argument is subject selection, not authentication. Receipt loading is bounded to 4 MiB, rejects symlinks and duplicate JSON keys, and still applies existing kind/schema/approval-role checks. No ordinary GitHub review, arbitrary JSON approver name or developer-authored document substitutes for independent authenticated acceptance.

## Five-path paired performance intake

The package-size ratio <= 0.70 and p99 ratio <= 0.80 remain unchanged and apply to **each** of the five paths, not their average. The validator does not invent the five production paths or choose a convenient reference implementation. The existing benchmark/transport owner must provide a frozen plan with schema `hepta.platform-wire.performance-plan.v1`, exactly five unique `path_id`/`workload_sha256` definitions and `minimum_samples` in 100..100000. The exact plan bytes are selected by SHA-256.

The raw report has schema `hepta.platform-wire.paired-measurements.v1`, exact `source_sha` and `plan_sha256`, `profile=release`, `reference_transport=grpc`, and nonempty host, runner, toolchain and run identities. Each path must carry the frozen workload digest and both `candidate` and `reference` observations: artifact digest, positive `package_bytes`, raw positive integer `latency_ns` samples, matching completed-operation count and zero failed operations. The compared package artifacts must use the same owner-defined packaging boundary. Host/run context and input hashes still require external provenance verification.

The checker recomputes nearest-rank p99 from samples, requires equal candidate/reference sample counts, and compares integer ratios without rounding. One failing path, missing or duplicate path, stale source, changed workload, missing sample, noninteger measurement or failed operation rejects the report. Inputs are bounded; a fixture is never used when a real report is missing. Example operator invocation:

```sh
python3 scripts/platform_wire_performance_gate.py \
  --plan "$REGISTERED_FIVE_PATH_PLAN" \
  --plan-sha256 "$REVIEWED_PLAN_SHA256" \
  --report "$PAIRED_RAW_MEASUREMENTS" \
  --source-sha "$EXACT_SOURCE_SHA"
```

A successful check is measurement validation, not source authentication or independent acceptance. This intake is ready for the owner-supplied benchmark output; no five-path gRPC run or threshold pass is claimed by adding the checker. The existing throughput workflow remains an in-process measurement workflow and now pins the toolchain, passes dispatch inputs through environment variables, exercises the real fleet-output contract and retains available evidence on failure.

## Remaining production facts

Production closure still requires the registered five-path definitions and reference artifacts; raw paired target-host runs; real authenticated ingress through the selected existing transport owner; independently established peer/channel/key provenance; bounded active connections, active fragments, consumer-retained frames and transport queues; deployment-level deadlines/cancellation/backpressure; reconnect/restart and mixed-version observations; and distinct independent semantic/security, operations and release decisions.

These are not permission to add a parallel execution path. Wire integrity or an HPTM MAC does not grant final-use authority. Unknown domain effects are not replayed as codec recovery. A source archive, local test key, mock-provider regression, measurement validator or passing core job does not supply the missing deployment facts.

## Evidence obtained during development

The `e292f812f9d1f73aff58592a29506540ae899dff` core run `36537350615` passed both source-head and ordered-merge jobs. Its merge artifact binds tested commit `afc5d357adca98730f6338cf10c52bf1dd458dca`, source tree `8d7f718b19232e26922f9f7ec278e336d39f40eb`, 145 wire tests, strict Clippy and the seven-case real emitter contract. Those results describe that historical candidate only. The current containing commit requires new source and ordered-merge execution, integrated qualification and protected-host evidence.

Python validator regressions were executed in the editing environment. Rust/Cargo/rustfmt were unavailable locally; Rust claims must come from the actual remote candidate's workflow output. Independent acceptance, activation and release have not been self-issued, and `STATUS.md` remains evidence-derived.

## Existing gateway connection owner

The normal `run_native_gateway` listener now uses one bounded `JoinSet` through its private `connection_loop` module. At most 64 accepted connection tasks, including completed tasks awaiting reaping, are retained. When full, it stops accepting rather than accumulating a second userspace pending queue. The operating-system backlog is not included in this bound. Each task still runs the original `serve_connection`, request/header ceiling and read/write deadlines; the JSON and HPTA V2 routes and all closed effect gates are unchanged.

Shutdown closes the listener, aborts outstanding read-only connection futures and awaits task reclamation under the existing response timeout. A shutdown timeout is an error, not a successful drain. Dropping the listener future drops its `JoinSet` rather than detaching accepted tasks. This does not claim preemption of synchronous work or bound the runtime snapshot's own memory. It is a resource fix on the existing loopback-only read surface, not a new authenticated network service or HPTM transport.

Four real loopback tests exercise saturated admission and slot reuse with the normal V2 route; shutdown with incomplete headers; malformed-request slot reclamation; and invalid private limit rejection. Their `http_accept_` names place all four in the existing exact/merge and protected-host `--lib http_accept` command selection, alongside the eight content-negotiation parser cases. Existing test floors are not reduced. No new Cargo dependency or transport credential was introduced. These tests require the current candidate's native gateway build; the wire-only core suite is not substituted for them.
