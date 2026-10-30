# Explicit A17 inheritance in the recovery controller

**CONTEXT_RECONSTRUCTION.** This unpublished operational adapter was rebuilt after the prior workspace disappeared. New hashes and newly executed tests below establish the reconstructed source; prior local tests are not reused. Frozen scientific source and old evidence are unchanged.

## Public API

Construct `ControllerCore(actual_materialized_import_receipt_descriptor)` using the exact `{path,bytes,sha256}` returned by `ancestry.materialize_import`, not its earlier VerifiedImport plan. The real receipt must exist under `fresh_raw/imports/execution04/A-17/IMPORT_RECEIPT.json`. Construction validates metadata and imported bytes but does not start a controller or worker.

`core.imported_job`, `core.import_record` and `core.imported_result` return independent deep copies. The latter two exactly match the controller's A-17.IMPORT.json and A-17.RESULT.json. The root caller binds the registered resource adapter's budget_type to this object's StorageBudget and runs the owner outside the entire registered envelope. Its subprocess reference is also object-local; strict legacy helper functions remain unchanged.

## Verified inheritance

The constructor and run entry hash the actual import receipt and external pins, original profile/freeze/config/initial queue, original controller result and operation/scientific seal chain, and every materialized imported file. Only completed execution04 seed 17 may enter execution06. It must preserve original seals and add zero scientific work. The original A17 job is verified through the original load_registration, verify_job and completion_matches against its actual original profile. New jobs keep the same strict checks against the new profile.

Only the single A17 argv value after --root changes to fresh RAW. IMPORT preserves original_job, accepted_import_job and the explicit one-field difference. The original source freeze, profile, protocol, producer and other argv values remain unchanged. A17 is never passed to Popen, never gets a new PID and has no A-17.START.json. The original RESULT bytes remain under imports/execution04/A-17/ORIGINAL_CONTROLLER_RESULT.json.

The new A17 RESULT is explicitly imported=true and executed_here=false. Its complete/exit status refers to the verified original completion; its new scientific wall, CPU and microsteps are zero. Its origin points to the actual import receipt and old anchors, with scientific cost owner execution04_durable_20261030:A-17. The old process peak is retained only with explicit original provenance for the original completed-family reservation formula, not as a new RSS measurement.

Import copying/validation CPU belongs to its actual operational process. Validation repeated inside the controller is nested inside its eventual outer wait4 and must not be added twice. Original operation/scientific cost fields are preserved rather than relabeled.

## Full original controller loop

Only A17 initially enters results/submitted. Its verified completion satisfies the existing A29 prerequisite. The queue must retain the fixed original ordered prefix and each serial predecessor; the legacy validator still requires all fourteen jobs at finalize. A fresh controller directory is mandatory and legacy admission resume/zero-work recovery flags are rejected.

The complete original loop is mechanically retained. The AST audit reverses only helper qualification to this core object, removes import explanation fields and the actually-started-worker bookkeeping, then compares the entire while tree to the restored frozen original. The bookkeeping correctly excludes imported nonexecution from scientific_workers_started during admission failure.

Worker ceiling two, group restrictions, dependencies, family reservation, memory admission and pending growth, source verification before Popen, executable/argv/cwd/environment expression, 65,536-byte reads, 4 MiB log bound, completion predicate, 300-second admission rule, 10-second status condition, 0.3-second sleep, 12-hour window and fixed-grid finalization remain unchanged inside that loop. Owned-child cleanup and registered resource backpressure are separate adapters.

Postseal code may compare entire IMPORT and RESULT objects with these public properties, compare the imported queue job, and require A17 START absent. All remaining START validation is preserved.

## Newly executed validation

The original execution05 `evidence_controller_import/reconstruction_tests_20261030T120311/WAIT4.json` remains historical. The eight current execution06 controller-import tests passed as part of the 51-case run in `execution06_recovery_20261030/measurements/root_behavior_checks01/WAIT4.json`. Its synthetic integration executed thirteen tiny stdlib substitute modules through the complete controller loop; all thirteen had real wait4 exit zero and no remaining PID; all fourteen logical jobs closed. A17 had no START/Popen, exact written import/property equality and zero new scientific work. A29's original reservation formula yielded 671,088,640 bytes.

The suite also rejects changed imported bytes, changed original seals, wrong import seed, changed A17 producer metadata, missing final job, removed serial predecessor, legacy resume, existing controller directory and a successor using the old profile. It checks deep-copy properties and preserved original RESULT bytes.

These tests use synthetic import metadata and harmless temporary substitute worker modules, not real scientific tasks. They do not establish durable remote closure or readiness of an unbound root caller. No actual import materialization, science execution, uploads or commits were performed by this suite.
