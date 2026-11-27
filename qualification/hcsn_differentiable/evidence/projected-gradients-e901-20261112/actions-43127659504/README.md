# Exact-source projected-gradient execution and delay disclosure

The source candidate `5a1db6f9da54d877e1660c4c964df0e227745719` passed the declared CPU fixtures. A subsequent [independent arithmetic review](../native-review/README.md) verified the native archive and all 675 retained partial derivatives; the CI ZIP-copy operation remains separate. Scientific admission and full numerical admission remain **HOLD_NO_GO**. The successful fixtures establish the specific numerical/program properties below; they do not establish a real-task advantage or qualify a replacement cell.

## Execution identity

| Item | Identity |
| --- | --- |
| Parent research source | `a83b2ecda37b0e18b05e7fedcaee0a63037c464f` (#6028) |
| Tested source | `5a1db6f9da54d877e1660c4c964df0e227745719` |
| Tested source tree | `5c373022c6bbbf3104e956e490a3fea892e0db82` |
| GitHub Actions run / job | `43127659504` / `130887082387` |
| Actions conclusion | Completed / success |
| Original Actions artifact | `13905662105`, 181,888 bytes |
| Original ZIP SHA256 | `c632d49e4fe62b656ce6ea6557b25750dd153d3fddb2e0160404b4d07921b89d` |
| Separate native evidence commit | `c065466c3d5dcdd547eb1eb6633d4deea966f1fb` |
| Native tested source | The same `5a1db6f...` source, not the evidence successor |

The [original Actions run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43127659504) and [original artifact](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43127659504/artifacts/13905662105) retain the complete CI execution. The GitHub artifact metadata and upload log agree on the ZIP digest above. At this receipt's preparation, the permanent CI ZIP copy and independent arithmetic over its arrays were still pending the read-only artifact reader run `43133623994`. No ZIP-copy completion or array recomputation is inferred from that reader being queued.

This directory permanently retains the complete decoded CI job log as the `log` string in [JOB_LOG.json](JOB_LOG.json), its byte count and SHA256, API identities and step receipts in [PROVENANCE.json](PROVENANCE.json), the original phase-disclosure record in [PHASE_PROJECTION.json](PHASE_PROJECTION.json), and the separate attempts in [ATTEMPTS.json](ATTEMPTS.json). JSON escaping preserves all log characters without changing ANSI sequences, newlines, or trailing spaces.

The separate native original [NATIVE.zip](../NATIVE.zip) is already retained in the repository, with [native PROVENANCE.json](../PROVENANCE.json). Its SHA256 is `882510d2d4fe504b1ea252d00d0d469e8ea938a49a1ba1d8371c1aeebb353faa` and its size is 41,189 bytes. It includes the full native derivative arrays, input trace, runner, logs, runtime freeze, source materialization receipt, and preceding failed attempts. That native archive is a separate execution identity from the Actions ZIP.

## What actually ran

| Actions suite | Executed tests | Outcome |
| --- | ---: | --- |
| Existing differentiable qualification | 95 | Passed; source unchanged |
| Recovery and receipt guards | 97 | Passed; no C2 training admission |
| Strict trace parser | 10 | Passed |
| New recorded-prior projected gradients | 9 | Passed |
| Finite DP/QVI oracle | 3 | Passed |
| Non-diffusion memory-control semantics | 3 | Passed |

These are **217 test executions** across the stated CI suites. The nine new tests took 3.227 seconds in the CI test log; the 95-test suite took 9.955 seconds. These timings are not complete training, hardware-energy, or deployment costs. The numerical-budget command exited 0, evidence verification checked 1,983 files with 0 errors, and all 13 required workflow outcomes were success. Generic repository checks and merge integration are outside this statement.

A separate native producer receipt records 9 new tests plus 14 existing trace regressions, all passing without skips or errors, using Python 3.12.3, Torch 2.8.0+cpu, NumPy 2.5.4 and mpmath 1.3.0. Its child exit code is 0 and its source-before/source-after hashes match. All 13 retained source-file SHA256 values were additionally compared with the frozen GitHub source; all matched. The exact retained external runner also matches its manifest hash and inserts the isolated repository root first on its import path.

The native report records 12.969631324987859 seconds of runner wall time, 11.133391671 seconds of process CPU time, and 296,820 KiB peak process RSS. Its producer result and raw archive were published despite the MCP launch/readback timeout. The durable supervisor's terminal receipt has not been retrieved, so it is not inferred from the published producer result.

## What the new gradient check covers

The synthetic mechanism fixture performs two Adam updates, retains three model identities and update indices 0/1/2, and records nine interval visits. For each fixed recorded prior, the auditor covers every transported probability coordinate plus exactly five readouts: `expected_events`, `discounted_events`, `discounted_active_time`, `call`, and `margin`. It differentiates those outputs with respect to `log_boundary`, `mu`, `sigma`, `absolute_reset`, and `discount`.

The passing test asserts 675 partial-derivative coordinates, complete retained coverage, unchanged source, baseline event replay, and agreement between first-order reverse AD and two central-FD step sizes. The declared error gate is `1e-7 + 5e-4 * max(abs(AD), abs(FD))`; the coarse/fine stability gate has the corresponding form. A source mismatch, truncated recorder, omitted visit, expired budget, detached gradient, corrupt event count, or out-of-domain stencil cannot earn the complete-fixture pass.

The native producer's summary reports a maximum absolute AD/fine-FD difference of **1.268078309024645e-9** and maximum tolerance ratio **4.8071145460457015e-5**. The native maximum absolute AD signal is nonzero for all five parameters: log boundary 1.346982740849868, drift 0.12243049566719796, diffusion 0.9705235305382852, absolute reset 0.9778099259997853, and discount 0.019631174038891974. These values were initially recorded from the native producer summary and have subsequently been confirmed by [the separate arithmetic review](../native-review/INDEPENDENT_ARRAY_REVIEW.json). That review also preserves the approximately 3.7313% maximum defined ordinary relative error on a derivative of order 1e-14, and the 246 undefined zero-reference ratios; it grants no relative rare-tail certificate.

The check holds the prior fixed. It does not qualify every transition-matrix entry, general signed/correlated content-mass derivatives, the raw-to-physical parameterization, observation filtering, end-to-end task-loss differentiation, an entire training trajectory, continuum accuracy, or relative accuracy for rare-tail gradients. Very small derivatives can pass through the absolute part of the tolerance. These visits use synthetic mechanism inputs, not a new UCI task replay.

## A passing disclosure test still shows a phase-projection error

The existing test
`test_operator.OperatorNumericalTests.test_phase_projection_early_release_and_refinement_are_disclosed`
ran again in this exact-source CI. Its complete numerical record is preserved without changing its numeric values as a JSON object in [PHASE_PROJECTION.json](PHASE_PROJECTION.json), and remains in the original job log and original qualification artifact.

At every resolution, the initial remaining-time law is uniform on [0.06, 0.08]. The fixture applies six equal steps of 0.013 in the declared **model time units**. Its deterministic release-CDF reference is `clip((t - 0.06) / 0.02, 0, 1)`. The parameters are log boundary 0, drift -0.1, diffusion 0.15, and absolute reset exp(1); the large reset distance makes a subsequent hit negligible in this short fixture.

| Phase cells | Active probability at t = 0.052; reference = 0 | Maximum absolute release-probability/CDF discrepancy over the six recorded times |
| ---: | ---: | ---: |
| 10 | 0.04590000000000019 | 0.16891199999999995 |
| 20 | 8.992806499463764e-17 | 0.06998399999999994 |
| 40 | 1.1102230246251564e-18 | 0.014687999999999812 |
| 80 | 0 | 0.0028159999999997076 |

The errors are **dimensionless absolute probability differences**. The 10-cell maximum is 16.8912 percentage points; the 80-cell maximum is 0.2816 percentage points. They are not timing errors measured in seconds or model-time units, not relative errors, and not bounds over every time or training state. The coarse projection releases approximately 4.59% probability mass before this fixture's deterministic reference permits any release.

The test intentionally discloses early release and checks improvement on refinement. Passing it therefore does not establish exact deterministic per-path delay. This is one concrete reason that a green fixture workflow does not remove the scientific HOLD.

## Qualification and retained failures

The existing archived real 32-cell, two-update task-loss AD/FD result remains separate evidence. This new fixed-prior output audit does not recreate or replace it, and does not close its reported coarse-grid value error or the full numerical admission gate.

Original C2 assets and jobs were not modified or restarted. This work adds **0 independently admitted full C2 training replays**. Recovery/receipt unit tests cannot be substituted for such replays. No baseline superiority, task benefit, energy savings, default-cell selection or production adoption is claimed.

[ATTEMPTS.json](ATTEMPTS.json) preserves the first zero-test runtime-selection failure, the second zero-test sparse-source failure and its original logs/runtime freeze, the later native producer publication, and still-indeterminate transport requests. No unsuccessful attempt is relabeled a passing execution.

The native formatting receipt finds `just` and `rustfmt`, but `codex-rs` is absent from the isolated sparse checkout, so `just fmt` was not performed. No whole-repository test or formatting pass is claimed. Evidence commits are successors of the tested source; they do not retroactively change the execution identity above.
