# Evaluated NoUpdate: exact-source native qualification

The delivered change continues the existing native owner bridge in draft
[#5316](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5316).
It closes a missing binding between the complete learning `selected_bundle`
and the bundle digest in the verified selected manifest. It preserves the
original four-stage evaluated-NoUpdate protocol, host-pinned expected head,
signature/trust/time checks, owner-checkpoint receipt domain, operation domain,
and independently issued FinalUse boundary.

This is a development qualification of native mechanisms. It does not certify
external demand, independent customer funding, scientific model improvement,
production installation, or an integrated deployment with Trillionnium-Chain.

## Source and review scope

| Item | Exact identity |
| --- | --- |
| Repository | `TrillionniumFoundation/hepta-private-ci` |
| Base PR | #5316, itself stacked on #5315 |
| Base commit | `b8d12ad02a2d8311581a4aa69e6cdf07d18f9758` |
| Base tree | `fa3ebc76de39de4335dc8f923e7d00a88c1c2901` |
| Qualified source commit | `e0a3bd2bde77c58a0ae7d211214f326371a72a4a` |
| Qualified source tree | `a28ed8f9dbc3569b8108e7f5fe5096b16c881792` |
| Continuation branch | `fix/pon-evaluated-noupdate-bundle-20261107-525798` |

The source change is five files, 260 insertions and 26 deletions. Its production
delta is 19 lines: a private verified bundle cache/getter on the sealed
selection observation and a complete-bundle comparison in the existing common
`require_source`. The existing observation digest bytes and persistent protocol
domains are unchanged. Authentication and the previous source checks still
run before the added bundle comparison. The remaining changes are tests and
the existing profile documentation.

This branch is based on the exact controlled candidate above. It is not a
claim of integration with current `main`. The qualification leaves main,
production selection and production services untouched. The later evidence
commit changes only this qualification directory; the tested source remains
the commit and tree pinned above.

## Same-source results

All three invocations began and ended on the same clean source tree. Builds
used the pinned Rust 1.96.0 toolchain on HeptaRuntime's desktop Linux host,
an isolated target directory, and two Cargo build jobs. The native test run
also verified the helper executable hash before and after execution.

| Gate | Result | Wall time including command setup/build |
| --- | --- | ---: |
| `just fix -p codex-hepta-agentd` | Exit 0; source unchanged | 118.349 s |
| Same-source `hepta-joint-propose` build | Exit 0; source unchanged | 55.707 s |
| Original native nextest selector | 60 passed, 0 failed, 662 skipped; exit 0 | 138.038 s |

The nextest test phase itself took 17.696 seconds. The selector was unchanged:

```text
just test -p codex-hepta-agentd --lib \
  -E 'test(neuron_generation) | test(learning_iteration)' \
  --status-level all --final-status-level all
```

The repository's `just test` wrapper used its original local nextest profile.
The 662 skipped tests are outside that explicit selector; this is not a claim
that all tests in the crate or workspace ran. Clippy retained two existing
vendored `i18n-config` lifetime warnings. Native build metadata warnings remain
in the original output. This was not a warnings-as-errors gate.

The helper was built with `cargo build --locked -p
codex-hepta-infer-worker-host --bin hepta-joint-propose --message-format=json`.
Its executable path came from Cargo's actual compiler-artifact record and was
bound through the supported shell-valid `CARGO_BIN_EXE_hepta_joint_propose`
metadata key. The executable SHA-256 is
`63c46cd5945d191bf882884a218da576cf2dfdeeb10334894cb795f25fc1eff3`.

Full commands, source states, timings, resource observations and log digests are
in [the native receipt](raw/accepted-evaluated-noupdate-native-v1.receipt.json),
[helper receipt](raw/accepted-evaluated-noupdate-helper-v1.receipt.json),
[Clippy receipt](raw/accepted-evaluated-noupdate-clippy-v1.receipt.json) and
[environment record](raw/accepted-environment.json). The retained reproduction
scripts use the original source pin and output locations; use a new evidence
directory for a new invocation rather than overwriting these receipts.

## What the native cases actually exercised

The original evaluated-NoUpdate case and an independent CURRENT-change case
each use a fresh fixture. A real frozen two-weight F32 file is read by the
native worker, the new input `[6, 4]` produces the F32 value `2`, and the output
is written and fsynced before the actual acknowledgement. The tests call the
real drain operation, reopen native owners after shutdown, and verify replay
returns the original receipt without another model execution or FinalUse nonce.

The new cases also verify the following boundaries:

- The public learning handle reconciles a retained terminal result through the
  real owner channel. The fixture first generates its four signed stages with
  its fixed test clock; this is not fresh external learning or production
  cross-process checkpoint recovery.
- A separately generated and signed four-stage NoUpdate changes only the
  complete bundle's heads component. Both preparation and readback reject it
  with the specific bundle-binding error. This does not merely corrupt an
  existing signature to trigger an unrelated authentication failure.
- Another genuinely signed request and learning head cannot claim the original
  Control publication. Its exact publication-binding rejection is checked.
- Rejected preparation preserves Control, old/target journal and witness bytes
  and consumes no FinalUse nonce. Target handles may already be open before the
  validation call; the claim is about native owner mutation.
- Separate fixtures test artifact CURRENT advancement and FinalUse revocation.
  Each blocks live dispatch and cold recovery with one retained model execution
  and one retained nonce. One invalidation cannot mask the other.

The receipt lists 54 original exported fixture files totaling 146,271 bytes:
native journal and witness bytes, Control/grant material, the selected canonical
manifest, four learning signing payloads and signatures, actual weight/result
bytes, and sealed readbacks. Every file has its own SHA-256. The two scenario
directories deliberately retain their own originals; matching fixture bytes
do not establish two independent customers or two distinct external tasks.
The exported `current.json` is the generation Control publication, not the
artifact registry's CURRENT file or the repository's development-policy file.
Learning attestations come from the deterministic fixture port; their export
does not establish independent issuer custody or a production checkpoint log.

The readback's terminal requirement is STOP, no pending request and acknowledged
output. The observation has no separate drain flag; successful drain is a
separate runtime assertion in the test. Serialized readbacks confer `DENY_ALL`
authority and are not standalone portable authorization proofs.

## Failures and unselected work retained

The raw evidence preserves earlier attempts instead of replacing their results
with the final PASS. The index separates preparation, baseline, exploratory and
accepted-source invocations.

| Exact source / attempt | Observed result | Treatment |
| --- | --- | --- |
| Initial full materialization | Timeout, exit 124; no native tests | Retained; later bounded sparse materialization used |
| `d87f33a...` first native run | Compile exit 101; sparse fixture absent | Required tracked fixture materialized |
| `d87f33a...` materialized run | 53 passed / 5 failed | Actual helper metadata was missing |
| `d87f33a...` hyphenated helper key | 53 passed / 5 failed | Attempt retained; valid underscore metadata key used next |
| `d87f33a...` correct helper metadata | 58 passed / 0 failed | Exact baseline qualification only |
| Exploratory `bc76fc6...` Clippy | Exit 101, `Digest32` serialization error | Retained against its original source |
| Exploratory `6a4c9e8...` Clippy | Exit 101, ambiguous test assertion import | Retained against its original source |
| Exploratory `34060ab...` | Clippy exit 0 and 60/60 native PASS | Unselected alternative; no result transferred to delivered source |
| First accepted-source freeze attempt | Precommit EOF formatting failure | Original stdout/stderr retained; not a native compile result |
| Accepted `e0a3bd2...` | Same-source Clippy/helper/native PASS | Qualification reported above |

The earlier quoted 47-pass/15-fail result was historical context, not this
session's baseline rerun. It must not be relabeled as a current result or used
to claim that this change fixed all 15 historical failures.

The unselected alternative is preserved as
[a patch](raw/development-candidate-34060ab.patch) and
[a prerequisite-aware Git bundle](raw/unselected-development-34060ab.bundle),
with [a final selection decision](raw/unselected-development-final-decision.json).
Its duplicate API is absent from the delivered source. The bundle requires
the original `d87f33a...` prerequisite; it exists only to reproduce the archived
development attempts. Existing #5315/#5316 was retained because it already
reauthenticates the original four-stage signed evidence at prepare and observe.

## Remaining real acceptance material

The trainer, evaluator and issuer keys are explicit engineering fixtures. The
learning checkpoint port is memory-backed. The native reopen tests establish
the checked owner behavior, not OS power-loss safety or a production learning
owner's durable rollback/revocation implementation. Stable operation/receipt
identity is not independent demand, and successful steps must not be counted
as distinct customer tasks.

The available authorized records did not supply auditable independent customer
control relationships and external budgets, independent evaluation data,
prospectively frozen real cost-matched evaluation, or complete training,
evaluation, storage and service costs. The numeric model records an actual
inference wall-time observation; unknown CPU, energy and full-cost fields
remain unknown. No learning-improvement bonus or business-reuse ratio can be
inferred from this fixture.

Production canary approval, real installation, a real customer's next task,
withdrawal/rollback acceptance and combined qualification with the exact Chain
source remain separate open gates. Prior cross-repository evidence pinned a
different Chain revision; branch capabilities and PASS counts cannot be added
together to create a new combined qualification.

The user requested Colab/Kaggle priority. No callable configured provider entry
was found in the available HeptaRuntime tools or the scoped tracked project
metadata examined during this run. These CPU owner tests used the available
native desktop path; no Colab/Kaggle training or external resource allocation
is claimed. No third party was contacted for missing business evidence.
