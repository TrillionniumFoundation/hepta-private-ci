## Problem and resulting behavior

A known failed metric could take precedence over missing applicable evaluation evidence. That could turn incomplete evidence into an `Ineligible` comparison and allow a completed `NoUpdate`.

This change gives missing applicable evidence precedence while retaining known failed metrics. Complete negative and complete eligible comparisons keep their meanings. The learning-stage regression combines a known negative comparison with a missing future window and requires the original Training cut to remain at Evaluation without issuing a NoUpdate receipt. Disposition and failed metrics remain digest-bound; current revalidation requires the current complete sealed decision.

**Draft / HOLD. Published source remains `c0f78493f815780f68b9bf5e390a21314d79311f`, tree `313ee34febc8ccc54c611ab56286e289518c63cb`. The fresh evaluator library and original full caller gate passed. The original focused native and source-closure gates failed. The fixed 86dd candidate has now been independently materialized, with no maintenance, compilation or qualification yet. No merge, production activation, real adoption, or complete net-utility result is claimed.**

## Published changes

- Preserve incomplete-evidence precedence and four evaluator regressions while integrating the fixed-b298 original-owner implementation.
- Refuse an eligible primary paired with a negative retention member at both the original panel and current material boundaries. This is a refusal, not aggregate NoUpdate, fraud or a payment decision. Complete primary-negative NoUpdate and missing-evidence refusal remain distinct.
- Correct observed fixture task/source bijection and inclusive-expiry preconditions while retaining authority and comparison requirements.
- Make the existing legacy NextUse Trainer reference explicit to the conservative caller collector, preserving the missing-owner error, readback arguments, await and evaluated branch.
- Box the oversized private panel-construction future and remove a forwarding future while retaining its construction/assertions. Actual c0f failures show that this did not resolve all stack overflows.
- Preserve exact original-caller registration and protection: 534 boundary rows and 409 protected rows over 338 paths. Gate definitions and budgets stayed unchanged during c0f qualification.

Original ordered parents are `e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd`, then `b29869e856d08db1bfb066116a9c443376ccc57d`. The canonical 1,293-byte commit and complete 14,851-file source inventory were independently verified. [Publication and native alignment proof](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/published-c0f/ROOT_PUBLICATION_AND_ALIGNMENT_REVIEW.json).

## Actual exact-source validation

| Gate | Actual result |
| --- | --- |
| Original fix / fmt | Exit 0 / 0; no source diff |
| Complete evaluator library | **163/163 PASS**, all four required incomplete-evidence regressions present |
| Focused native | **81 PASS / 28 FAIL**, 109 unique cases; original exit 100, 960.6167 seconds; no overall timeout or output cap |
| All / ordinary / Root native | **Not started** after focused failure |
| Source closure | **FAILED**, original 600-second deadline; exit 124, child -9, 602.9541 seconds; explicit functional failures preceded timeout |
| Caller self-test | Original command exit 0 |
| Full caller | **PASS_HEPTA_CALLER_CLOSED_SET**; original exit 0, 4477.5591-second wrapper within original 4800-second limit; 534 boundaries / 534 required IDs / 409 protected rows / 338 paths / 6,597 Rust files |
| Entire source-gate job | **FAILED**, original process exit 1; caller PASS does not override source-closure failure |

Original jobs: native `1a1d0137095-2564-1b21`; source gates `1a1d01a6652-2564-1b2d`. No earlier or preparation PASS transfers.

[Fresh evaluator XML](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/native-c0f-exact-validation-v1/eval-lib.xml) · [complete native terminal bundle](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/native-c0f-terminal-complete) · [original caller command record](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/source-gates/c0f78493-v1/verify/verify.json) · [original caller terminal](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/source-gates/c0f78493-v1/verify/gate-final.json) · [root terminal byte review](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/source-gates/c0f78493-v1/ROOT_TERMINAL_ADDENDUM_REVIEW.json).

The original full caller raw output is 251,757 bytes, SHA256 `c35b1087bfd1d113fe745ebba74dfaceab650c694842d93372b88ba07687ba2d`. Exact bytes were recovered only after matching the independent original full-file size/hash/Git identity and actual fixed-version prefix/tail reads. Two middle direct reads timed out. This is documented exact recovery, **not a new full on-site read or gate execution**. The receipt retains `authorityGranted=false`. Both original source inventories match the complete 5,474,911-byte JSON/SHA256 `cdb6cea4f3142702681a20476db2a078a08d7b3b981bbc1ceb568c886fe3aa57`.

The source-closure forwarded stdout and complete internal helper compiler JSONL remain incompletely recovered; summaries and file-info are not labeled complete originals. [Recovery details and retained limits](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/README.md).

## Failures and next preparation

The 28 focused failures comprise **24 stack overflows, two actual per-test 60-second timeouts, one InvalidBinding and one OwnerUnavailable**.

One preserved original ELF was run once under GDB and stopped at its first SIGSEGV in a future stack probe. The caller already used 7,251,104 bytes of its original 8 MiB stack, leaving 1,137,504 writable bytes before a 2,284,152-byte local reserve plus saved registers/return address. Four caller-local reserves independently explain 7,242,272 bytes; unavailable CFI is not invented. This diagnoses one actual chain, not every failure. [Original diagnostic and source audit](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/native-c0f-first-signal-diagnostic).

A separate 220-second diagnostic used the unmodified original verifier and all 6,597 Rust files. It stopped with exit **3**, as a diagnostic rather than PASS, with exact before/after source equality. The actual hotspot was repeated type-name regex scanning: 25,251 `has_authority_call` calls, 152.749 inclusive wall seconds. Nested measurements are not added into a total. [Actual measurements](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/caller-performance-diagnostic/c0f-typed-timing-v2/timing-metrics.json).

The next source is saved only as **PREPARATION/HOLD commit `86dd56a930277e0d1aef3e475e35c2b5d60b43b7`**, tree `383ab85c39ef9d848252ef5c25922d13d9fae6c6`, 15,188 leaves, parents c0f then fixed a96. It includes the 59-file ordinary evaluated NoUpdate preparation, three reviewed Rust increments, structural non-Rust registration, explicit Root case, and two necessary literal-containment checks before existing regexes. These checks preserve the verifier's source set and verdict logic. Optimized gate performance is not yet observed.

**Ten new protected rows, 39 existing protected literal updates, new adversarial QA and final blob-size allowance synchronization remain incomplete.** Actual maintenance, compilation and original exact-source gates have not run on 86dd. [Canonical preparation object](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/next-profile/preparation86dd/CANONICAL_COMMIT.json) · [root independent commit/tree review](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/next-profile/preparation86dd/ROOT_REVIEW.json).

The old review directory failed a full source-byte prerequisite at 15:29 because a tracked archive was absent. Actual `fetch_started=false`: no Git fetch or Cargo ran. Cause remains Unknown; later git-clean/ELF checks do not prove physical completeness. The directory is preserved. A distinct fresh independent repository has now been materialized from validated canonical objects as detailed below. The separate source-gates clone again matched its complete physical source inventory before and after that operation. [Actual prerequisite failure](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/a96-origin-object-fetch-v1/RESULT.json).


## Actual independent materialization completed; dependency recovery pending

Unique job `1a1d0c6996e-2564-1bc8` (`hepta-utility-36fa-fresh-materialization-86dd-v2`) actually ran at **17:20:41.268822–17:22:17.324285 UTC**, with normal exit 0 and complete durable output. It created an independent repository at `/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1`, read back **16,618 raw objects**, validated **ten full snapshots**, and materialized all **15,188 physical leaves** at the fixed 86dd tree. The new repository has no alternates or shared object store.

The complete final physical inventory is **5,611,182 bytes**, SHA256 `bca1a7399820966d3167a26f89355898a9ea9a7169938ffa27e7dd9576fc1711`. The original source again matched **5,474,911 bytes / cdb6cea4...** before and after. All 34 Git commands returned zero, and all five final audits verified: owned helper closure, original source/Git metadata, the fixed four-directory original object lookup chain, new destination, and 18 immutable inputs.

Root independently joined both original binary-result reads and checked offsets, stable version, EOF and the full 69,974-byte RESULT. It verified all 40 small evidence paths and the actual complete supervisor terminal. The final source inventory was exactly recovered using the original serializer, matching raw and gzip identities and all five original encoded parts. Other large v2 records remain pinned and are not all copied off-host. **This is preparation success, not a test PASS, whole-history fsck, source-ref update or real task-chain outcome.**

[Original complete RESULT](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/fresh-materialization-86dd-v2/run/RESULT.json) · [Root actual original-readback review](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/fresh-materialization-86dd-v2/ROOT_ACTUAL_ORIGINAL_READBACK_REVIEW.json) · [actual placement](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/fresh-materialization-86dd-v2/ACTUAL_EVIDENCE_PLACEMENT.json) · [recovered final inventory](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/fresh-materialization-86dd-v2/recovered-final-inventory/).

The distinct v1 materialization job failed before target creation/import/full physical baseline because its control incorrectly rejected the old read-only source's existing alternates. This is a known preparation failure; its source-unmodified claim remains null. The initial read-only diagnostic's own index-size ceiling failure is also retained. V2 admitted the actual fixed source lookup chain while preserving the new target's independent-object requirement. No failed operation was overwritten or silently replayed. [Preserved v1 records](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/fresh-materialization-86dd-v1/).

The original a96 read-only validation completed at 16:33:48 UTC: 395 transport objects, seven commits, and the exact 16,082-object existing prerequisite closure. All three original large audits were subsequently **recovered byte-exactly**, including both raw/gzip hashes and all 52 encoded parts. This is recovery of prior output, not a new native execution or a full fresh native read. The observed partial-read provenance gaps remain recorded. [Recovery manifest and scope](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/native-a96-canonical-validation-v1/recovery/RECOVERY_MANIFEST.json).

### Concrete next preparation

Actual runtime observation found the specified historical Cargo target and V8 archive absent, and uv/ruff unresolved in the observed PATH values. It did not scan the whole machine or install anything. Fixed source/release evidence identifies **UV 0.11.3, Ruff 0.15.13 and V8 150.4.0**, with six explicit artifact URLs, byte counts and SHA256 pins.

The selected recovery design uses a new external depot and virtual environment, installs the sole verified wheel as named `ruff==0.15.13`, and requires the original frozen/offline sync check, original UV-run Ruff version and final check. The earlier fresh-cache offline sync/find-links proposal remains unexecuted and is not assumed to satisfy a registry lock. The native control is being finalized after static review; no download/install success is claimed at this checkpoint. Existing proxy/CA/TLS policy and historical V8 paths remain intact.

Original maintenance stays scoped to `just fix -p codex-hepta-intelligence-eval -p codex-hepta-agentd` (**7200 seconds**) then `just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f` (**900 seconds**). Failed or Unknown fix does not start fmt. The final wrapper will pin actual recovered tools and explicit external UV/Ruff/V8 environment and retain all actual changed postimages. Its archived first structure is HOLD, not a launch approval.

[Fixed dependency evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/preparation/runtime-dependency-recovery-v1/) · [maintenance HOLD structure](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/maintenance-preparation/v1/) · [canonical 86dd preparation](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/next-profile/preparation86dd/).

Final protection/QA/allowance synchronization still requires actual formatted bytes. A separate complete-collector membership-test proposal preserves original ignored-path semantics and attacks; it remains conditional on the actual formatted preimage. No gate budgets, stack limits, per-test deadlines, collectors or verdicts are relaxed.

The most recent retained hosted-CI observation for exact c0f is explicitly historical: 16:21:52–16:21:53 UTC, zero check runs/suites/workflow runs and pending combined status with zero entries. This does not establish present CI status.

## Utility and authority boundaries

Real ordinary Adopt, real evaluated NoUpdate, and real daemon plus Root cold-recovery qualification each remain **zero**. The required authorized A → original T → independent B → Adopt or complete NoUpdate → new C → daemon and Root cold recovery still needs authentic owners/outcomes, retrievable authorized model material and actual consumer readback.

The matched expert is not proof of the strongest deployable baseline. The frozen cost scope remains `TaskLedgersBeforeFinalHoldout`; complete lifecycle cost and independent task/lineage/judge/operations provenance are not established. Unsupported action-changing comparisons remain Unknown. Original Model ownership remains necessary, and missing original Model/Selector/Version/FinalUse owners do not gain an Adopt path. Chain content roots identify bytes without independently proving availability, lawful authorization or adoption.

[Current evidence checkpoint: 1,741 independently matched paths at `d15b0b8c`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa) · [current full status and limits](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/README.md) · [unchanged previous checkpoint](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d15b0b8c7aff900950905bc239bc1f289c337f2a/qa/evidence/utility-evaluation-20261112-36fa/checkpoints/README_1120FILES_C0F_FULLCALLER_PENDING.md).
