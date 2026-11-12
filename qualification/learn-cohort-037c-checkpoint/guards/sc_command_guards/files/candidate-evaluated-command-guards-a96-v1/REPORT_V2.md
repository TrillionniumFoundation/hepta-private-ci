# Evaluated remote C and S/C command source closure, V2

Inputs: exact published a96d1b821d10ed3d9e99dd06c5141f9f242ae318 plus the three independently verified actual Rust 1.96 formatted C14, S12, C11 postimage sets. Product and verifier bytes were not edited by this guard work.

The new suite completed 16 tests in 19.002 seconds, exit 0; 681 mutations were rejected. Source-only evidence: native, complete Rust-index caller proof, ordinary NoUpdate/Adopt and daemon+Root cold qualification are not claimed.

## Integration

Use CALLERS_DELTA_PLAN_V2.json as row-level input to the central merger. It contains before/after rows, exact new inventory IDs, input identities and all actual own product hashes. Do not replace central CALLERS.toml with the isolated overlay. Counts are 541 boundaries/389 protected at a96, 573/402 in this isolated plan: 32 new boundaries, 13 new protected rows, 49 changed boundary rows and 21 changed/new protected rows. Preserve concurrent Root, Current and Version deltas. The plan already includes actual shared Version factory/readiness caller paths; deduplicate identical paths when merging.

All old forbidden markers remain present. Full function bodies plus actual top-level ordering reject moved-to-unused-closure validation, early cached returns, missing live predecessor reads, wrong/renewed full signatures, lost ACK authority promotion, cold-to-fresh promotion, reused consumed channels, enlarged bounds, unknown wire fields and opaque-field visibility changes. Old readonly S factory's definition marker is explicitly migrated to binding::original_context(config, &selection)?; the extracted complete original_context and before/after-read logic have their own protected row and attack cases. No signing, writing, or execution capability is added by the readonly S endpoint.

External callers are snapshots for checking these API edges, not approval of the other agents' product blocks. The final overlay records 59 unique external paths. Three historical duplicate paths from sequential Root/Version copies are retained in the V1 plan; V2 records the actual last-applied bytes. The builder now reuses those frozen physical snapshots rather than re-reading mutable work directories.

## Preserved observations and pending old-QA migrations

source-qa-attempt-01.log retains the initial 4 marker-target failures and 3 missing external-path errors (596 mutations rejected; no accepted mutation). attempt-02 is the previous 16/0, 679-rejection run. attempt-03 is the final 16/0, 681-rejection run including the migrated original factory boundary.

The four old relevant suites were also observed unchanged against this isolated mixed overlay. Their original failures remain in legacy-compatibility-observation/. They are not counted as PASS. Exact remaining migration owners:

* test_evaluated_published_read_source_closure.py: profile owns the explicit Version readiness decision-vs-legacy guard and exact caller tuple updates; the existing readiness protected row in this partial overlay has not yet received profile's Version delta.
* test_evaluated_selection_source_closure.py: public method inventory needs the real into_evaluated_command_owner factory. No prior public method is removed.
* test_evaluated_next_use_source_closure.py: readonly S original_context/before_read/after_read checks moved from the old host methods into circuit_evaluated_selection_readback_binding.rs. Migrate each attack to its exact new function, retaining host delegation/order attacks. Its factory definition-marker failure has already been fixed in V2 and covered by the new suite.
* test_original_circuit_observer_source_closure.py: exact function inventory adds require_profile/evaluated_owners; exact evidence-read caller tuple adds the real circuit_evaluated_version_commands.rs path.

These test migrations are explicit remaining integration work. They must preserve all original negative cases, not delete expectations. No full source-suite PASS is asserted.
