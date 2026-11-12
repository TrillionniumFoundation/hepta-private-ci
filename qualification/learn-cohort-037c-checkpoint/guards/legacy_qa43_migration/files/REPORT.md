# Legacy source QA migration, exact a96 base

All 41 original native-independent source test cases remain. Two new NextUse cases explicitly protect extracted-binding forbiddens and actual host delegation/order, bringing the three suites to 43 cases. Actual isolated after runs: Selection 13/0 (2.526 s), NextUse 24/0 (4.979 s), Observer 6/0 (3.450 s). The unchanged original suites were first run against the same assembled inputs; their 1 / 6 / 2 failures remain in evidence/before/.

## Inputs and scope

The overlay consumes independently verified actual formatted C14, S12 and C11; Root12 actual formatted plus its exact one-file V2 caller spelling draft; Version40 frozen prefmt V3; and Current13 actual formatted. Input manifests and bytes are recorded in INPUT_MANIFEST.json. Root V2 and Version40 are explicitly temporary preformat inputs and must be reconciled to actual after images before final source qualification. No whole-source, full Rust-index, native, ordinary or Root qualification is asserted.

All three old QA bases were independently matched to exact a96 GitHub blobs before editing. The verifier, product files and fourth published-read/readiness QA were not edited by this migration. One mechanical fixture merge retained both independent trailing module mounts after proving the base is an identical byte prefix of both inputs; the initial conflict record is retained. lib.rs merged cleanly with git merge-file, preserving both independent additions.

## Deliverables

postimages/ contains only the three migrated QA files. legacy-source-qa-migration-v1.patch applies to their exact a96 bases. MIGRATION_MAP.json documents all moved and added negative semantics.

BINDING_FORBIDDEN_DELTA.json is a separate single protected-row delta on top of the already delivered command V2 plan. It appends the 17 missing old-host forbidden markers to the extracted shared binding while retaining every existing forbidden and every other registry value. Counts remain 573/402 in this isolated overlay. Do not replace central CALLERS with this overlay. Central integration should apply this row addition while preserving other agents' deltas.

Seven representative mutations were accepted by that individual binding row before the migration and rejected afterward; exact evidence is preserved in evidence/binding-forbidden-before-after.json. This is a claim about the individual row, not a claim that every former combined QA gate accepted those mutations. The actual product never contained these additions.

The moved tests continue to exercise exact original context, request correlation, current signature windows, full signed result identity, role/custody pins and no execution/signing exposure. New host mutations prove a correct unused binding function cannot substitute for its live call or its before-I/O ordering. Existing unknown caller, empty caller set, cold-to-fresh, journal reuse, Source/Cell and signature renewal attacks are retained.
