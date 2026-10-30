# Seed-specific producer admission — context reconstruction

This file and its implementation/tests were reconstructed from conversation after workspace loss. Fresh hashes and new test evidence are required. The prior unpublished files and prior test outcomes are historical records, not proof of the reconstructed bytes.

Construct `ProducerAdapter(map_descriptor, import_receipt_descriptor, fresh_registration)` only from new-registration-pinned inputs. The map JSON is exactly `ancestry.producer_map(...)`; the constructor independently recomputes and compares it and uses `ControllerCore`'s validated import admission. Its public `imported_job`, `import_record`, `imported_result` properties bind the controller evidence.

Factories return independent `ModuleType` globals without changing original module objects, files or `sys.modules`. Unchanged functions retain original code objects. Apply further registered history/resource hooks to these returned namespaces. Original classes can retain their original operational module globals; resource integration must also preserve the existing scoped hooks for those classes.

| Factory | Explicit metadata adaptation | Preserved checks/work |
| --- | --- | --- |
| `for_followups` | Seed-specific A job/operation producers; seed-specific R source; map-bound freezes/previews | Entire A/B/C bank/head/path grids, other operation ancestry and dependency checks |
| `for_runner` | Closed A operation and frozen B/W/R input hashes; bounded W/R headers; reject another A17 execution | Original head loading, restores, transitions, runtime checks and limits |
| `for_endpoint` | Original full A collector followed by exact seed source checks; explicit mixed-source ancestry | Original role barrier, population, scoring, runtime equality and B/C collection |
| `for_summary` | Exact A17 IMPORT/RESULT replaces nonexistent new START; seed source/profile checks and old-source traversal | Other START/profile checks, 14-job population and 26 seals |
| `for_report` | Admit only the exact old A17 profile; verify map before efficacy decoding | Original numerical summaries, decision rules, retention, costs and pending behavior |
| `for_analysis_launcher` | Validate map and route report dispatch through `for_report` | Original process ownership, singleton admission, source and completion checks |
| `for_finalizer` | Require map/import artifacts in the finalizer freeze | Original inventory, literal reconstruction and source/artifact verification |
| `for_postseal` | Require new episode plan/map/adapter and exact imported controller evidence | Original 30/26 seals, 14 jobs and finite diagnostics |

Ten exact AST expressions across seven functions replace only embedded metadata assumptions: two followup single-A-parent checks, R's source comparison, summary parent traversal, summary A17 START, summary endpoint-parent matching, summary operation profile, report profile, postseal profile, analysis report dispatch. Each original whole-file SHA is fixed and each expression must match once. No general `require` override, equality proxy, fabricated descriptor or rewritten seal is used.

## B/W/R compatibility

B loads its seed's head and initializes a new B branch. W initializes from each stored parent's binding and restores it. R uses its seed's parent binding and preserves within-seed immutable-environment and current-runtime checks. A17's historical source binding remains literal. No numerical function or runtime requirement is relaxed. The extra gate reads only frozen hashes and bounded provenance headers.

New B/W/R, endpoint, aggregate and finalizer freezes bind `producer_map`, `actual_sources_A_by_seed` and the map/import/old-producer artifacts. `actual_source_A` is explicitly scoped to the primary execution05 producer, with the complete map authoritative for seeds. A endpoint ancestry identifies its mixed producers; former singular producer fields are null with an explicit scope.

REPORT_INPUTS and its provenance contain only the basic `producer_map` and `import_receipt` descriptors. Keep rich source descriptors in the separately pinned map file: the unchanged analysis launcher recursively requires path/bytes/SHA dictionaries to equal a basic three-field descriptor exactly.

## Required integration

The registered execution wrapper must select the appropriate returned module. Calling the original interface bypasses the adaptation and fails on imported A17. The analysis launcher's original `MODULE` still names its old child entry point: the root wrapper must route both parent and child through `for_analysis_launcher` and carry pinned producer configuration. This factory does not silently rewrite subprocess commands.

The postseal plan must name episode `execution05_backpressure_20261030` and exact `producer_map`, `import_receipt`, `producer_adapter` descriptors. Plan schema `.2` and pipeline completion schema `.4` remain; a different schema needs an explicit reviewed adaptation. The original postseal `implementation` descriptor still binds unchanged scientific diagnostics; the added adapter descriptor separately binds this operational source.

Cost accounting retains original A17 once in the complete A population and excludes it from the failure increment. Failed A29 work is separate. The adapter cannot convert unknown costs into measurements or a completed protocol into a positive scientific effect.

Run `python3 -B -m unittest operational.parameter_field_recovery05.test_producer_adapter -v`. Synthetic checks cover source/map tampering, seed/profile scope, IMPORT without fabricated START, independent globals, unchanged pending behavior, original B collection and literal B/W/R source bindings. Exact AST compilation imports no NumPy or Torch. These tests are not experimental results or full scientific execution.

## Fixed finalizer destination added for registration05

Before finalizer freeze serialization, the private encoder binds `evidence_id: verification05` and `evidence_relative: evidence_v2/verification05`. The finalizer namespace requires the verified producer-bound freeze and matching freeze hash before entering the original literal algorithm at that destination. Original finalizer source, algorithm, and sealed evidence are unchanged. A focused synthetic test covers wrong destination and invocation before source verification.
