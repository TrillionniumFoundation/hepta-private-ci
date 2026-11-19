# Current-owner native memory: engineering evidence and open research gates

This iteration implements an exact-query current-owner path in the default Agentd build. It connects real Objective and NDU owner observations to the existing source-bound model, shadow journal and `NeuronModelPort`. The local path and the independent hosted qualification have each executed an actual pretrained decoder through the current-owner factory. The eight research and production blockers remain open; the narrower engineering results below do not replace their acceptance criteria.

## What changed

`AgentdState::checked_current_objective` reads the attached Objective runtime, signed durable run record, AuthBus and current Fleet/readiness state. Its opaque proof binds the run incarnation, subject, objective, revision, phase, authority epoch, host generation, fence and deadline. A cancelled/released/re-admitted run cannot reuse the old proof. Unrelated run appends do not invalidate a different run's unchanged proof.

The NDU owner now accepts a signed read-revocation feed and an injected authority clock. It binds a read to the actual selected projection and owner journal, claims exactly one signed grant, and can revalidate the opaque proof without claiming another grant. Selection changes, grant revocation, expiry, stale feeds, unavailable clocks, reversed time and selection ABA fail closed. Any NDU journal change conservatively invalidates the previous proof.

`AgentdNativeMemoryRegistrationV1` is installed through `AgentdConfig`. Runtime attachment uses the actual recovered writer and Objective owners; attachment during `Starting` does not manufacture an admitted run or claim that `Running` has already been observed. A prepared read binds the complete typed query and actual run proof. The external issuer signs that exact binding. The default factory requires the resulting concrete context and validates the source manifest against the actual native source bytes.

The shadow namespace now includes the checked owner context. Source admission is revalidated, then the real Objective/NDU/query context is checked again immediately before entering the decoder. A direct tick-bound model call cannot bypass that guard. Currentness is checked again before a successful tick and delivery. Runtime cancellation also closes externally retained handles. The compatibility path using a caller-defined context remains qualification-gated.

The currentness observations are not an atomic lease spanning independent owners. The clock and grant issuer remain explicit host capabilities. This change supplies neither clock attestation nor replicated authority. Output remains an uncalibrated, authority-free shadow abstention.

The exact query here is the existing `MemoryCellQueryV1`: request ID, typed key and deadline. The worker question is deterministically rendered from that key; this does not independently validate a free-form user's intended question-to-key mapping. The current factory also requires a single-source adapter ancestry. General source intake, multi-source cells and a production question interpreter still need their own qualification.

## Local execution evidence

[local-evidence.json](local-evidence.json) retains all eleven test attempts, source-inventory hashes, command/log hashes, failure explanations, the raw current-factory report and an independent 35-check artifact audit. The local source baseline is `ba32a22de7c586ae6a1ac6ebeb5d67b54259021b`; these tests ran with the recorded uncommitted changes before final formatting.

| Check | Observed result |
| --- | --- |
| Qualified Agentd and NDU libraries | 292 tests passed; one ignored real-model test |
| Default Agentd library | 193 tests passed; one ignored real-model test |
| Strengthened decoder-entry race test | 1 passed; selection change, grant revocation and expiry all reached the source barrier and refused the decoder |
| Explicit real-model current factory test | 1 passed, `--retries 0`; 193 other tests filtered/ignored |
| Real-model worker | One completed fresh worker, one decoder query, one explicit feature forward |
| Additional training in this local current-factory invocation | Zero; reused a previously trained 96-update checkpoint |
| Raw answer and denominator | `order`, 1/1 previously exposed case |
| Base/checkpoint integrity | Six base files and all four checkpoint files matched their registered identities |
| Worker inference / test / harness time | 3.601510 s / 14.975 s / 16.074729 s |
| Model parameter bytes / worker peak RSS | 539,903,232 B / 1,132,281,856 B |

These test counts are overlapping build configurations, not a sum of independent tasks. One decoder query plus one explicit feature forward does not count every autoregressive internal forward. The real-model test uses actual durable owners with fixture authority and a fixture clock. It does not execute the default daemon process or establish future-task accuracy.

Earlier failures are retained. They exposed a missing sparse-checkout manifest, an unavailable test-only assertion dependency, local socket sandbox restrictions, owned AuthBus fixture permissions, and a fixture output width below the existing runtime minimum. The manifest was restored and verified, only fixtures/imports were corrected, and the existing validation rules were preserved. The final passing test inventories were unchanged during execution. A later test-only assertion strengthened proof that the actual source barrier, rather than a timeout, caused refusal.

## Independent qualification path

The native workflow now covers NDU, the default current-owner registration tests, and one explicit pretrained callback through the new factory. The new `scripts/memory_cell_native/current/native_current_ci.py` driver requires an exact clean committed source, the existing v1/v2 success records, frozen pretrained inputs, and an independently retained raw worker directory. It verifies the request, full tick binding, source use, process counters and unchanged checkpoint after the Rust test.

The complete workflow retains the existing 96-update training and base/shuffled controls. The added current-factory phase performs zero training and one decoder query with automatic retries disabled. The independent raw-artifact audit below verifies whole-workflow accounting of five decoder queries and three explicit feature forwards, including the earlier v1/v2 phases. The historical local evidence remains unchanged; the separately attached hosted result qualifies the committed source for this bounded engineering path.

The published source is `35e1a0d42bf2607ce216d9d1d16a38d7bc1972bd` (tree `4e442ad23fa604b6e2c21b150f0d2b33b4bf1023`). [Native run 40188170696](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40188170696) started at 2026-10-25 11:16:27 UTC and completed successfully. The downloaded raw artifact, source identities, final-tool diff and actual callback receipts have now been independently checked.

## Independent hosted native qualification — 2026-10-25

[Run 40188170696](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40188170696) completed successfully on source `35e1a0d42bf2607ce216d9d1d16a38d7bc1972bd`, tree `4e442ad23fa604b6e2c21b150f0d2b33b4bf1023`. [hosted-result.json](hosted-result.json) records the compact evidence and scope. [hosted-audit.json](hosted-audit.json) retains the complete JSON values of both independent audits, raw worker reports and command receipts, with original audit-file digests.

The downloaded artifact `native-memory-40188170696-1` (ID `12598070717`) is **62,788,755 bytes**, SHA-256 `85a4895749a6c2cc2a37e74e22d1f6658d7be1ac66e75a202e9daa553fd2c52d`, matching GitHub's metadata. A read-only audit checked all 5,758 ZIP members and passed **72 checks**: 59 general checks and 13 additional current-chain checks. It verified both 360-file source archives, byte-identical clean source identities before/after all three phases, the current phase's 40 NDU source hashes, and all 39 frozen publication paths.

| Hosted gate | Result |
| --- | --- |
| Evidence-driver / closed tick-wire regressions | 3/3 and 4/4 passed |
| Scoped suite with `qualification-cognitive-write` | 762/762 passed; 14 skipped; 106.193 s |
| Default current-owner filter | 9/9 passed; 185 skipped; 2.554 s |
| Explicit ignored pretrained default-factory callback, retries 0 | 1/1 passed; 193 skipped; 10.004 s |
| Scoped lint fix and final format | Successful; patch, stat, and final worktree status each **0 bytes** |

The NDU-change-during-source-revalidation guard regression passed in the hosted **feature suite** in 2.223 s. The default filter did not select that test. The separately retained local full-default and focused guard runs provide the default-profile evidence. CI ran no tests after final formatting; formatting proposed no changes.

Fresh training used the fixed rank-8, seed-24031, learning-rate-0.01 completion-CE protocol: **96 updates / 96 actual forwards**, 96 loss rows, 96 visits to one source fact, 7,296 input tokens and 192 supervised tokens. The later shadow and current phases reused identical checkpoint bytes and pins, with **zero additional updates**. Raw process evidence establishes one training process plus five fresh inference processes: five decoder queries and three additional feature forwards. All three native worker exits were zero, with complete stdin and no timeout or cancellation.

| Read arm | Exact match on the same previously exposed case |
| --- | --- |
| Actual v1 daemon/control socket | 1/1; raw answer `order` |
| Controlled v2 shadow callback | 1/1; raw answer `order` |
| Default-build current-owner factory callback | 1/1; raw answer `order` |
| Base control | 0/1 |
| Shuffled-adapter control | 0/1 |

The raw current chain agrees from configuration/source/request hashes through the canonical source-binding and execution digests, independently recomputed v2 tick/joint hashes, model vectors, and the actual **520-byte journal / 224-byte witness**. Their checksums and sequence-one checkpoint agree with the reported result. The passing real-factory test refuses query substitution and delivery after runtime cancellation while retaining exactly one worker process; the resulting shadow observation abstains and grants no authority. The separate controlled shadow run retains precise replay and source-tombstone refusals, unchanged journal/witness anchors, and no extra backend dispatch.

Measured training fit time was **42.320753 s**; the training child took **48.900217 s**. The saved adapter contains 120 F32 tensors, 460,800 parameters, and 1,843,200 tensor bytes. Parameter, gradient and optimizer tensors total 7,373,280 bytes, excluding the frozen base, activations and runtime. The six pinned base files total 271,170,520 bytes; the four-file checkpoint totals 1,890,161 bytes. Each native worker reports 539,903,232 model-parameter bytes. Worker intervals were 3.810136 s (v1), 3.844293 s (controlled v2), and 3.838168 s (current); current process peak RSS was 1,142,804,480 bytes. These single observations establish no latency quantiles.

This remains one previously exposed case, with no independent future tasks or future-accuracy estimate. Training ancestry remains one source root. The current path exercises the actual factory in the default test build with explicit test-controlled real durable owners and clock. It does not claim a default current-owner daemon process, calibration, production qualification, external GitHub permission authentication, or independent hardware attestation. Base-weight byte verification is recorded by the hosted acquisition/runtime receipts; the uploaded adapter bytes were independently hashed directly from the ZIP.

## Reviewable publication stages

| Stage | Pull request | Changed lines |
| --- | --- | ---: |
| NDU current owner | [3862](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3862) | 297 |
| NDU current tests | [3863](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3863) | 262 |
| Objective current owner | [3864](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3864) | 245 |
| Objective current tests | [3865](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3865) | 370 |
| Shadow binding and entry guard | [3866](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3866) | 329 |
| Concrete current context | [3867](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3867) | 319 |
| Current context tests | [3868](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3868) | 434 |
| Source-barrier regressions | [3869](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3869) | 442 |
| Runtime registration | [3870](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3870) | 317 |
| Registration tests | [3871](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3871) | 446 |
| Startup and draining | [3872](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3872) | 93 |
| Actual pretrained callback and CI | [3861](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3861) | 465 |

## Related results from this iteration

- [Current-evidence relay](../memory-current-relay-20261025/README.md): the target accepts and signs an acknowledgment for current source bytes before the source rechecks and revokes them. The hosted result records separate runner/boot identities, exact artifact transfer hashes and durable withdrawal state.
- [Procedural development](../memory-development-20261025/README.md): all three fixed seeds produced an action that passed the original Ruff gate and 76 semantic tests on one exposed historical task. Base/shuffled controls failed. Typed tool retrieval also passed, so this is not a retrieval-superiority result.
- [Common repair executor](../../scripts/memory_cell_evaluation/README.md): the new pinned development judge passes 9/9 controls, admits the known fix with all 76 exact original test IDs, and refuses lint-clean semantic failure and a SkipTest false green. [Raw qualification and publication evidence](../memory-common-executor-20261025/summary.json) is retained; this is one exposed incident, not a general solver or future benchmark. Stacked executor PRs are [3881](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3881), [3882](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3882), and [3884](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3884).
- [Historical development catalogue](../memory-development-catalogue-20261025/README.md): four real incidents retain original source/command/test identities and restoration gaps. These are development material; none enters the future denominator.
- [Future-method readiness](../memory-future-readiness-20261025/README.md): the proposed five-arm comparison is not frozen or executed; full solver, diverse corpus, common cost meter and prospective independent tasks remain prerequisites.
- [Prior frozen program evidence](../stem-bakeoff/evidence/20261025-memory-program-final/README.md): longitudinal retention, matched-budget attempts, edge ablations, older relay and native qualification remain unchanged.

## Full blocker status

| Blocker | Status after this iteration | Evidence still required |
| --- | --- | --- |
| Long-term correction and retention | Open. Prior frozen retention ended at 3/8, 6/8 and 1/8 across three seeds. | A new prospectively frozen continuous task stream meeting registered retention and task-success thresholds. |
| Real sources and query binding | Open; native exact-query/source/Objective/NDU engineering path advanced. | Deployed source authorization and independently qualified real host authority/clock/query intake, including correction and withdrawal. |
| Future-task advantage over strong retrieval | Open. New development task succeeds, and retrieval also succeeds; eligible independent future tasks remain zero. | Unseen independent task families, actual task outcomes, locked competing methods and total budgets, no evaluation-driven tuning. |
| Split benefit at equal total budget | Open. Old data/random split results and cost mismatches remain. | Continue/expand/retrieve/data-split/random-split comparisons under full fixed-capacity and priced-growth budgets across seeds. |
| Learned edges and autonomous growth | Open. Prior learned edges tied fixed/random task utility. | Same-cell graph ablations and genuinely data-driven split/merge/rollback lifecycle benefit. |
| Multiple physical nodes and locality | Open; current-before-withdrawal positive relay now exercised on separate runners. | Physical host evidence appropriate to the claim, online source-access boundaries, partitions/recovery and authority failure handling. |
| Net compression and scale cost | Open. Parameter bytes, source/base retention and serial cold-start costs are reported. | Quality-matched complete storage/runtime accounting plus sustained concurrent throughput and latency. |
| Native production integration | Open; default-build registration and the actual current-owner factory now pass independent qualification on the exact committed source, including clean final tools. | Real current-owner daemon/host integration, independently qualified production authority/clock and query intake, calibrated product behavior, multi-source ancestry and operational failure evidence. |

No acceptance threshold, prior frozen result or future denominator is changed by this report.
