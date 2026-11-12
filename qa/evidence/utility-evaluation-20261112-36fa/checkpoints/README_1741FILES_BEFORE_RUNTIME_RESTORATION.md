# Hepta utility evidence: current status and preserved limits

Checkpoint prepared 2026-11-12 17:43 UTC. This directory contains 1,741 exact file paths. The immediately preceding 1,486-file checkpoint is preserved at commit `63f9f690307aca5a498c487cd7f9c6b7dc6baecc`; its [README](checkpoints/README_1486FILES_BEFORE_FRESH_MATERIALIZATION.md) and [PR body](checkpoints/PR6203_1486FILES_BEFORE_FRESH_MATERIALIZATION.md) are archived without edits.

**Draft / HOLD. Published PR #6203 source remains `c0f78493f815780f68b9bf5e390a21314d79311f`, tree `313ee34febc8ccc54c611ab56286e289518c63cb`. Its focused native and source-closure gates failed. A new fixed candidate has now been independently materialized for maintenance, but has not run maintenance, compilation or qualification. Real authorized task-chain qualified outcomes remain zero.**

## What changed since the previous checkpoint

The next candidate `86dd56a930277e0d1aef3e475e35c2b5d60b43b7`, tree `383ab85c39ef9d848252ef5c25922d13d9fae6c6`, was actually materialized in a fresh independent repository. Its ordered parents are the unchanged published c0f, then fixed upstream a96. It has 15,188 physical leaves. This is a preparation success, not a new test PASS or source publication.

The original a96 validation's three large audits were recovered exactly from the pinned inputs, original serialization and independently observed original size/hash/Git identities. All 52 original base64 parts have been saved and fully read back. This recovers prior output; it is not a fresh native execution or full new native read.

Fixed dependencies were identified from the frozen source and official release metadata: UV 0.11.3, Ruff 0.15.13 and V8 150.4.0. Their concrete recovery control is being prepared. Download, installation, offline-environment validation and maintenance remain unexecuted at this checkpoint.

## Published exact-source gates: c0f

| Gate | Actual result |
| --- | --- |
| Original fix and fmt | Exit 0 / 0; no source diff |
| Full evaluator library | **163 / 163 PASS**, including all four incomplete-evidence regressions |
| Focused native | **81 PASS / 28 FAIL**, 109 cases, original exit 100, 960.6167 seconds, no overall timeout/output cap |
| All / ordinary / Root native | Not started after focused failure |
| Source closure | **FAILED**, original 600-second deadline, exit 124, 602.9541 seconds; functional failures appeared before timeout |
| Caller self-test | Original command exit 0 |
| Full caller gate | **PASS**, exit 0, 4477.5591 seconds within unchanged 4800-second limit; 534 boundaries and required IDs, 409 protected rows, 338 paths, 6,597 Rust files |
| Whole source-gate job | **FAILED**, exit 1; caller PASS does not override source-closure failure |

Actual jobs: native `1a1d0137095-2564-1b21`; source gates `1a1d01a6652-2564-1b2d`. No prior, preparation or partial PASS transfers to 86dd.

The focused failures comprise 24 stack overflows, two actual 60-second per-test timeouts, one InvalidBinding and one OwnerUnavailable. The original 8 MiB stack and test deadlines are unchanged. One preserved failing ELF was stopped at its first SIGSEGV: caller use of 7,251,104 bytes plus a 2,284,152-byte reserve explains that chain's stack deficit. Four caller-local reserves account for 7,242,272 bytes; unavailable CFI was not invented. This does not diagnose every failed test.

The original source-closure output showed 344 partial cases: 337 OK, five failures, one error and one unfinished case, with no final suite summary. Its diagnostic and caller timing output are not qualification substitutes.

Evidence: [complete native terminal bundle](native-c0f-terminal-complete/), [source-gate records](source-gates/c0f78493-v1/), [first-signal diagnostic](native-c0f-first-signal-diagnostic/), [timing diagnostic](caller-performance-diagnostic/c0f-typed-timing-v2/), and [published alignment proof](published-c0f/ROOT_PUBLICATION_AND_ALIGNMENT_REVIEW.json).

## Actual independent materialization: 86dd v2

Unique key `hepta-utility-36fa-fresh-materialization-86dd-v2`, job `1a1d0c6996e-2564-1bc8`, actually ran **17:20:41.268822–17:22:17.324285 UTC**. Its normal supervisor terminal at 17:22:17.510 has exit 0, complete durable output, no timeout/cancellation/truncation. Stdout is 11,610 bytes; stderr is empty.

| Object or observation | Actual identity |
| --- | --- |
| New repository | `/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1` |
| Source commit / tree | `86dd56a930277e0d1aef3e475e35c2b5d60b43b7` / `383ab85c39ef9d848252ef5c25922d13d9fae6c6` |
| New object database | 16,618 raw objects independently read back; ten complete snapshots; no alternates or shared object store |
| Final physical inventory | 15,188 tracked and physical leaves; 5,611,182 bytes; SHA256 `bca1a7399820966d3167a26f89355898a9ea9a7169938ffa27e7dd9576fc1711` |
| Original source inventory before and after | 5,474,911 bytes; SHA256 `cdb6cea4f3142702681a20476db2a078a08d7b3b981bbc1ceb568c886fe3aa57` |
| Imported pack | 93,806,896 bytes; SHA256 `c0d99f9b71c85a2b96045a7f7165e9dd1ce19bd4251326b5586e26ed4f9cde61` |
| Complete original RESULT | 69,974 bytes; Git blob `456f749e7558e18df99172d9c9273cda890b8feb` |
| Original normal terminal | Git blob `3e60d21bec849a19efb5d818b43152bfc72486fe` |
| Root complete original readback review | Git blob `35ba7c51786fcac49b44a6967e79865debec8d9e` |

All 34 recorded Git commands returned zero. Five final audits verified owned-helper closure, original source and Git metadata, original object lookup, new destination, and 18 unchanged inputs. Root independently joined both original binary-result chunks, checked consecutive offsets, stable version, EOF and the complete original RESULT identity; it also checked 14 originals in the small-file read and all 40 placement paths, including the binary Git-metadata gzip through its exact base64 companion.

The old source has a fixed four-directory object lookup chain. It was observed before and after and preserved. The fresh repository itself has no alternates. This validates the actual source snapshots and objects used, **not donor-wide worktree/history inventories or whole-history fsck**. The historical fsck limitations remain.

The final physical inventory was separately recovered from the exact materialized leaf map and original inventory serializer. Both original raw and gzip identities and all five original encoded parts matched. These five parts, recovery program and review are included. It is exact recovery of the observed native output, not a new physical observation.

See [actual placement](fresh-materialization-86dd-v2/ACTUAL_EVIDENCE_PLACEMENT.json), [complete RESULT](fresh-materialization-86dd-v2/run/RESULT.json), [Root original-readback review](fresh-materialization-86dd-v2/ROOT_ACTUAL_ORIGINAL_READBACK_REVIEW.json), and [recovered final inventory](fresh-materialization-86dd-v2/recovered-final-inventory/). Other large v2 audits are pinned by their actual size/hash and not all copied off-host; they are not represented as complete originals here.

### Preserved preparation failures

Materialization v1 was a known failure, not Unknown execution. Job `1a1d0badea9-2564-1bbf` exited 1 at 17:07:52 because the control incorrectly rejected the old read-only source's existing alternates. It had not created a target, imported objects, performed a full physical baseline, or started Cargo. Its original-source-unmodified field is null; four read-only Git commands alone do not prove full physical equality. All original failure records are retained in [v1 evidence](fresh-materialization-86dd-v1/).

The first read-only alternates probe also failed before commands because its own index size ceiling was too small. The corrected observation and both failures are retained. V2 changed the source lookup admission based on actual exact directory/file identities while preserving the new destination's independent-object requirement. It used a distinct execution identity and never overwrote the failed run.

Earlier, the old review directory failed its physical-source prerequisite at 15:29 because a tracked archive was absent. Fetch did not start. Cause remains Unknown. Nothing in the new materialization repairs that historical observation.

## Exact a96 audit recovery

Original read-only validation job `1a1d09b7b3e-2564-1ba7` completed at 16:33:48 UTC. It verified 395 transport objects, seven canonical commits and the exact 16,082-object required existing closure. The older 16,136-object union is a different set and is not substituted.

Recovered original large artifacts:

| Original audit | Raw bytes | Gzip bytes | Original gzip SHA256 |
| --- | ---: | ---: | --- |
| SNAPSHOT_LEAVES | 32,945,102 | 10,388,682 | `de21c2a0b0321c91376fdd26a84a0e67915a507f445932e1067b435ac5fca8ec` |
| OBJECT_AUDIT | 5,086,531 | 1,916,374 | `6ba1a292e89231b552011dccab1a73e173e805cf006dac55f1430faa177dd473` |
| TREE_AND_ANCHOR_RAW | 1,987,695 | 920,740 | `a86aa06f6f1752ae604362b4af4d34842487d50a9511e5c4978d63840fa1b9d7` |

All original raw hashes and all 52 original encoded-part identities matched. Original canonical commit bodies and the complete 121,293-byte canonical diff audit are retained. The locally reformatted root-result JSON is only semantically equal to the original 38,525-byte result and is not called byte-identical.

Four retained native TREE prefixes independently anchor the recovered parts. A later observed read batch lost its in-memory SDK records when the control cell terminated; that provenance gap remains explicit. The actual retained OBJECT prefix covers only the first 262,144 bytes. No new native large-file reads were run to disguise these limits.

See [recovery manifest](native-a96-canonical-validation-v1/recovery/RECOVERY_MANIFEST.json), [recovery notes](native-a96-canonical-validation-v1/recovery/README.md), [original encoded parts](next-profile/a96-canonical-independent-validation-v1/recovered-original-audits/), [TREE prefix records](native-a96-canonical-validation-v1/tree-audit-partial-reads/) and [OBJECT prefix records](native-a96-canonical-validation-v1/object-audit-prefix/).

## Maintenance prerequisites and remaining source work

The actual runtime observation found the specified old Cargo target and V8 archive absent and did not resolve uv/ruff in the two observed PATH values. This is not a whole-machine absence claim. Cargo/just/rustup resolved in the task environment. No global tool installation, profile editing, source changes or recovery commands were run by that observation.

The fixed plan pins six original artifact URLs, sizes and SHA256 values for UV 0.11.3, Ruff 0.15.13 and V8 150.4.0. Tools, project environment and caches will live in a new task-owned external depot. The old V8 locations are preserved. Proxy/CA/TLS controls remain intact.

The first proposed fresh-cache offline sync plus find-links is **unexecuted and not assumed sufficient**: the original registry lock preserves its index/URL distribution. The selected recovery design instead uses a normal external UV venv, installs the exact named requirement `ruff==0.15.13` from the sole verified offline wheel, then requires the original frozen/offline sync check to return zero. The concrete native control and actual result are still required; no prepared CLI reasoning is a successful installation claim.

Original scoped maintenance remains `just fix -p codex-hepta-intelligence-eval -p codex-hepta-agentd` with 7200 seconds, then `just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f` with 900 seconds. Failed or Unknown fix does not start fmt. The HOLD wrapper preserves complete before/after source inventories and all changed postimages. Its final environment must explicitly bind actually recovered tools/V8, external UV/Ruff paths and the observed CODEX_REPO_ROOT/PYTHONPATH; the archived first draft is not approved for launch.

Ten new protected rows, 39 existing protected updates, adversarial QA and final blob-size allowances remain incomplete pending actual formatted bytes. The current 86dd preparation contains structural registration, ordinary evaluated NoUpdate mechanisms, three reviewed Rust increments and two conservative literal prechecks before existing regexes. Its ten new ordinary tests have not compiled or run. No verifier collector, verdict, gate budget, test deadline or stack limit is relaxed.

See [dependency proposal and fixed sources](preparation/runtime-dependency-recovery-v1/), [maintenance HOLD structure](maintenance-preparation/v1/), [canonical 86dd preparation](next-profile/preparation86dd/) and [postformat protection preparation](next-profile/).

## Utility and authority remain external

A known failing metric cannot convert missing applicable evidence into a completed Ineligible/NoUpdate. Adopt, complete NoUpdate, InsufficientEvidence/Unknown and reproducible Objective Fraud retain distinct meanings. The evaluator changes preserve the external task objective and digest-bound evidence; they do not authorize objective, reward, permission or observation-standard rewrites.

Real authorized A → original training T → independent B → Adopt or complete NoUpdate → new C → daemon and Root cold-recovery qualified outcomes remain **0**. Missing original Model, Selector, Version or FinalUse owners remain closed. Even a NoUpdate path still needs the actual original Model owner where required.

The matched expert is not proof of the strongest deployable baseline. Frozen cost scope remains `TaskLedgersBeforeFinalHoldout`; full post-cut evaluation, download, activation, serving and maintenance costs are not established. Different keys/controllers do not establish independent task source, training lineage, evaluator or operational control. Action-changing comparisons without identification support remain Unknown. Content roots identify bytes without proving continuous availability, lawful authorization or actual consumer adoption.

No merge, production activation, payment/fraud determination, or completed net-utility improvement is claimed.
