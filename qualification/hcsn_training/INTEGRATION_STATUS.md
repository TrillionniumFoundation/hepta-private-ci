# HCSN integration: operating contract and qualification entry points

This is a runbook, not an aggregate pass report. Inspect each retained attempt's
receipts, source identities, runtime and exit status before describing its result.
CPU engineering qualification does not transfer the frozen CUDA campaign's
scientific conclusions to another numerical backend or establish production trust.

## Numerical backends and completed-block recovery

| CLI backend | Time integration | Checkpoint schema |
| --- | --- | --- |
| `value_kernel` | Actual elapsed seconds with previous-boundary Cell coupling | 1 |
| `population_grid` | Original fixed microsteps and refractory queue ceiling | 2 |
| `population_age` | Integer-microsecond expiry cohorts and `upwind_ctmc_v1` transport | 3 |

Each block unfolds logical Cells in one tensor graph; external inputs are held over
admitted intervals. Task-loss autograd supplies parameter derivatives. NDU, credit
receipts, eligibility and local plasticity scores cannot substitute for them.
TaskFlow handles authorized launch, cancellation and recovery; workers perform
numerical steps. The existing fenced artifact owner handles candidate publication.
A worker receipt and a published candidate do not themselves authorize adoption.

The saved checkpoint binds parameters, all numerical state slots and the completed
clock position. A second training block authenticates that saved state and begins
with a detached copy. Every optimizer iteration reuses the same admitted initial
state. This preserves numerical continuity without persisting an autograd graph
across blocks. Inference continuation and second-block training are distinct checks.
For age-cohort expiry, spatial approximation and explicit legacy migration, see
[POPULATION_AGE.md](POPULATION_AGE.md); schema-2 loading keeps its original semantics.

## Signed worker qualification

The Linux `hcsn_signed_worker` test executable drives real signed TaskFlow dispatch,
SQLite recovery, the pinned supervisor and an actual CPU worker. Its authority is
`synthetic_ed25519_v1`; the lost first reply is deliberate test fault injection.
It checks rejection before provider contact, nonce consumption, cold recovery and
observation of the same job without another launch. It does not register Agentd.

The `verify_bridge` and `verify_host` wrappers below invoke this test themselves.
Its exact standalone invocation
requires a separately prepared, unused attempt containing `request.json`,
`supervisor-config.json` and an initialized empty private `supervisor-store`:

```bash
HEPTA_HCSN_SIGNED_WORKER_ROOT="$HCSN_ATTEMPT" \
  "$HCSN_SIGNED_WORKER_EXECUTABLE" --ignored --exact \
  signed_authority_real_worker_cold_recovery --nocapture
```

Do not invoke it again on an attempt already dispatched by a wrapper. Keep
`HEPTA_HCSN_SIGNED_WORKER_PHASE` unset; the executable owns its cold-recovery phase.
Retain the successful Cargo artifact stream, executable SHA and native build/source
linkage receipt when selecting this executable; a pathname alone is insufficient.

## Full bridge through the existing artifact owner

Run from the repository root with the selected CPU Python environment. Use the
locked Cargo build procedure in [the bridge workflow](../../.github/workflows/hepta-hcsn-training-bridge.yml).
`HCSN_CARGO_ARTIFACTS` must identify one successful JSON artifact stream for the
required native libraries. Preserve the exact libraries and toolchain it names.
`CARGO_TARGET_DIR` must match that build; the signed test binary has its own retained
successful artifact stream. Do not combine build attempts or guess among libraries.

```bash
CARGO_TARGET_DIR="$HCSN_TARGET" python -m qualification.hcsn_training.verify_bridge \
  --rust-workspace "$HCSN_REPO/codex-rs" --rustc "$HCSN_RUSTC" \
  --cargo-artifacts "$HCSN_CARGO_ARTIFACTS" \
  --signed-worker-executable "$HCSN_SIGNED_WORKER_EXECUTABLE" \
  --backend population_age --output "$HCSN_ATTEMPT"
```

Choose each of the three backend names explicitly and use a new output directory
for each attempt. The bridge builds its native fixture from the retained library
selection, requests native time plans, dispatches training, publishes a candidate
through the owner, reopens it, and checks continuation and second-block training.
These are fixture-authority operations; evaluation and production adoption remain
separate decisions. Preserve successful and failed directories in full.

## Configured Linux host acceptance without a compiler

Upload the source package and separately selected signed test binary. Include the
four fixture helpers: `test_joint_graph.py`, `test_population_graph.py`,
`test_population_age_graph.py` and `test_training_state.py`. All four CLI arguments
below are mandatory; the output directory must not already exist.

```bash
python -m qualification.hcsn_training.verify_host \
  --signed-worker-executable "$HCSN_SIGNED_WORKER_EXECUTABLE" \
  --signed-worker-sha256 "$HCSN_SIGNED_WORKER_SHA256" \
  --backend population_age --output "$HCSN_ATTEMPT"
```

The host wrapper initializes its private store, pins the executable and request,
records the actual Python/Torch/NumPy/SciPy runtime, and compares source manifests
before and after dispatch. It checks actual candidate/receipt/handoff bytes and
replays the complete candidate state from the admitted initial state. Raw outputs
remain under the retained job; `worker-output.json` identifies them. Preserve the
whole tree, including process records, both output streams and `retained-files.json`.
The external native build/source linkage receipt is still required:
`native_build_linkage_verified_here=false`. Host acceptance records
`host_registration_exercised=false`, `production=false` and no CUDA campaign.

## Signed real-worker cancellation acceptance

The separate `verify_cancel` wrapper prepares a fresh bounded CPU attempt and
invokes `signed_authority_real_worker_cancel_cold_recovery` in the same selected
native executable. It requires an observed live worker before a distinct signed
Cancel, independent kernel evidence of that worker's exit, and fresh-process
recovery of both effects. Start must settle as failed and Cancel as succeeded;
the deliberately lost replies remain historical indeterminate observations.

```bash
python -m qualification.hcsn_training.verify_cancel \
  --signed-worker-executable "$HCSN_SIGNED_WORKER_EXECUTABLE" \
  --signed-worker-sha256 "$HCSN_SIGNED_WORKER_SHA256" \
  --backend population_age --output "$HCSN_CANCEL_ATTEMPT"
```

Choose each backend explicitly and use a new directory per attempt. The admitted
64-step ceiling does not prove any optimizer step started: the worker may be
cancelled during import. This fixture uses `synthetic_ed25519_v1`, records
`optimizer_entry_proven=false` and `host_registration_exercised=false`, and makes
no production or CUDA claim. The new combined cancellation path needs a retained
successful acceptance run for the exact candidate source and executable.

Both cancellation wrappers use [one shared preparer](cancellation_fixture.py).
Their B workloads select an explicit 8-bin spatial grid and longer real traces
within the unchanged 1,048,576-element, 64-step and 24-KiB request ceilings.
The default numerical fixtures remain 32-bin; their canonical serialized specs
and graph identities omit the default field exactly as before. An explicit
nondefault grid is bound through graph/model/checkpoint identity; the temporal
profile digest retains its existing meaning. Each attempt first retains a
separate uncancelled one-step proposal proving that its shape and initialization
pass actual worker admission. Its timing does not measure a complete 64-step run
or prove optimizer entry in the subsequently cancelled process.

## Agentd registration and production boundary

Both host schemas require `provider="hcsn_process_v1"` and an explicit profile:

| Schema and profile | Implemented admission boundary |
| --- | --- |
| Schema 2, `engineering_ed25519_v1` | Test builds only; ordinary debug/release builds refuse this engineering entry. |
| Schema 2, `production_ml_dsa65_v2` | Refused; schema 2 cannot select or downgrade production trust. |
| Schema 3, `production_ml_dsa65_v2` | Linux candidate composition with a signed deployment contract, ML-DSA final-use grants and revocations, and separately keyed external clock/frontier services. |

See [schema 2 guards](../../codex-rs/hepta-agentd/src/automation_hcsn_host.rs) and
the [schema 3 candidate](../../codex-rs/hepta-agentd/src/automation_hcsn_pq.rs).
The final contact guard binds the authenticated head to the consumed token and
rechecks clock, signed feed and external frontier before spawning the pinned
supervisor. A completed local receipt remains readable without fresh dispatch
authority. The candidate's validation is pending; implementation is not a pass
report or a production deployment.

The [PQ host tests](../../codex-rs/hepta-agentd/src/automation_hcsn_pq_tests.rs)
use real ML-DSA with local test keys/services and a pinned subprocess probe, not
a training worker. The real-worker cancellation fixture above exercises a
different, synthetic classical authority path. Keep those evidence scopes
separate. A further [PQ real-worker acceptance](verify_pq_host.py) composes the
actual schema-3 host, signed complete Python source inventory, actual supervisor
and worker, distinct ML-DSA Start/Cancel grants, and fresh native host recovery.
It preserves actual initial responses; it does not inject lost replies. Invoke
it with the separately selected Agentd **library-test executable**:

```bash
python -m qualification.hcsn_training.verify_pq_host \
  --agentd-executable "$HCSN_AGENTD_EXECUTABLE" \
  --agentd-sha256 "$HCSN_AGENTD_SHA256" \
  --backend population_age --output "$HCSN_PQ_ATTEMPT"
```

This new path also awaits exact-source acceptance evidence. Its local key and
clock/frontier services remain fixtures. It exercises the host module, not an
Agentd daemon boot or AuthBus ingress. Actual
[AuthBus ingress trust](../../codex-rs/hepta-agentd/src/authbus_trust.rs)
still uses Ed25519. Independent service/key custody, deployed host configuration,
and end-to-end production authorization/recovery remain unqualified; no production
deployment has been performed.

An unresolved observation is not proof that no work occurred. Preserve the attempt,
query the same retained job through the authorized recovery path, and use an
explicitly authorized cancellation when required. Never relaunch an uncertain job
or overwrite its receipts to obtain a cleaner result. Missing or incomplete logs
and success receipts remain an evidence gap, even when a surrounding command exits.
