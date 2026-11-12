# Three legacy source suites on actual formatted Version V3

The three previously migrated suites now pass against the actual formatted Version V3 inputs: Selection **13/0**, NextUse **24/0**, and original Observer **6/0**, for **43 passing source tests**. This is a new actual run; the earlier mixed-prefmt run and its original failures are unchanged.

All forty Version files were verified against the actual formatting manifest before installation. Thirty-eight were installed as exact actual postimages. `lib.rs` and the receipt-test module were merged with the already present S/C additions using a clean physical three-way merge from the exact frozen preformat input to actual after bytes. Both original merged outputs are retained in `merge-evidence/`; there were no conflicts or manual resolutions. The Root caller v2 actual postimage was checked byte-for-byte equal to the previous work input.

The three QA files, their registry overlay, verifier and typed scanner remain byte-for-byte equal to the earlier frozen migration. No new test weakening or registry migration was needed for actual formatting. The source package's existing actual C14, S12, C11, Root12 and Current13 inputs remain in the same overlay.

Actual run logs and results are in `results/`. `INPUT_RECONCILIATION.json` pins all forty before/after/merged identities and the actual Root caller identity. `MANIFEST.json` binds these records and the resulting product-source inventory.

This result does not include Profile V4 progress, Root progress v3 or the new Root post-read patch; those have their own separate Root/source bundles and pending formatting. It is not a full source gate, a full caller scan, native execution or ordinary qualification. No production source, central registry or other agent's frozen artifact was changed. The deployable QA postimages remain those in `candidate-legacy-qa-migration-a96-v1/postimages/`.
