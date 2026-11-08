# Common Cell candidate: 2026-11-08

This candidate combines the stage implementations at the source pins in
[source_manifest.json](source_manifest.json). The same candidate must pass its
source-head engineering checks before its outputs can be considered by a stage
review. Research readiness follows the existing research gate and retained
CURRENT_RESULT. All six research stages currently remain **HOLD**.

## Engineering changes

The integration preserves the current journal identity/length checks, claimed
revocation head, fresh dispatch clock and Windows store path while adding HCSN
PQ authentication profiles. Its retained-result regressions exercise current
revocation and journal replacement. HCSN call sites use the current authorized
request structure without dropping binding, payload, fence, grant or time.

Native terminal training now has a durable, registered Host CAS job record. A
claim precedes native work. A committed result can be read back after a fresh
process opens the original owners; replay reacquires current Memory permission
and validates the original dataset/ledger binding. Uncertain claims cannot
silently start training again. Payload, original receipt and native elapsed
measurement are retained. This is the terminal operator path; the broader
ordinary-daemon learning composition is specified in
[daemon_wiring_gap.md](daemon_wiring_gap.md) and its
[machine-readable source map](daemon_wiring_gap.json).

Dependency repairs retain the current AWS versions and Rama 0.3.0 family.
Reviewed pin-utils backports remove its product edges. Matrix moves to 0.19.1
with vodozemac 0.11.2 while preserving the existing on-disk session directory.
The Starlark and SQLite compatibility ports preserve the shared BLAKE3 and
native SQLite graph. Bindgen 0.73.2 keeps its formatter and syntax-tree library
on compatible major versions. Rama's upstream time constraint repair permits
the maintained Matrix graph. Vendor provenance and original byte inventories
are retained beside the source; Cargo and Bazel generate their own root locks.

CI selects this common branch, retains source-bound execution evidence, and
runs one explicitly selected protected Host CAS recovery test through the
existing root test runner after ordinary-user compilation. Caller analysis
memoizes immutable parsing results within one scan and preserves its full
closed-set checks. Source-head receipts and binary hashes remain the basis for
assessing each execution.

## Observed intermediate checks

| Exact source | Check | Observed result |
| --- | --- | --- |
| 1eb72a1131285f5de98beeb7c95a27eab72d647e | Original terminal-learning library selection | 4 passed |
| d74efedeed3b3f5ec62e35ce6133eccf6e44256d | Durable terminal-learning library selection | 9 passed |
| d74efedeed3b3f5ec62e35ce6133eccf6e44256d | Protected original Host CAS parent/fresh-child regression | 1 parent test passed; the child reopens the original owners |
| cadc31bc50a749c3bc23069da5094448f113efb8 | Research gate / joint configuration / successor binding | 19 + 23 + 8 passed; CURRENT_RESULT comparison passed |
| cadc31bc50a749c3bc23069da5094448f113efb8 | First combined native core build | Failed at the bindgen/prettyplease syn-major mismatch; the failure is retained |

These are intermediate source identities. The exact final source, complete
commands, helpers and JUnit records must accompany source-head CI artifacts.
The [pre-freeze history manifest](pre_freeze_history/execution-history.json) and
[original execution records](pre_freeze_history/execution-evidence.tar.gz) retain
both failed and successful attempts available at capture time. They are not a
claim of complete execution history or a final candidate pass. The reusable
[collector](../tools/collect_execution_history.py) preserves later attempts in
separate source-bound evidence without changing this frozen snapshot. Each
command's wall interval describes that command; overlapping commands and shared
caches prevent treating a sum as CPU cost or complete learning-history cost.
Physical and full history costs remain unknown where they were not measured.

## Research acceptance remains open

| Stage | Remaining acceptance requirement |
| --- | --- |
| S0 | Ordinary daemon composition with legitimate original owners; real evaluation, selection and successor consumption; complete cost and recovery evidence |
| S1 | Independent real tasks with matched budgets and strong retrieval/rule/control baselines; calibrated false acceptance and retention |
| S2 | Real execution gains attributable to state/prediction, fewer ineffective evidence/actions, and correct failures |
| S3 | Additional HCSN/local-credit benefit against sufficiently trained recurrent/state-space or other appropriate baselines |
| S4 | Plasticity beats a fixed graph with a strong scheduler after migration and organization costs |
| S5 | Common start, component swaps, independent tasks and multiple generations of genuine adoption with complete historical cost |

The existing Root FinalUse transport can be reused when its registered policy
matches the operation. Learning receipt roles, the original checkpoint/CURRENT
capabilities, real owner composition and an explicit effective-weight mapping
still require the implementation/deployment work described in the source map.
