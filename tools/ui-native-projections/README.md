# ui.native generated projection tooling

This package is **non-product tooling**. The canonical shell is the Rust product
under `apps/hepta-native`; this package has no native or final-use authority.

Commands:

```bash
npm ci
npm run generate
npm run lint
npm run typecheck
npm test
npm run signing-dry-run
npm run sbom -- --out /absolute/output/ui-native-source-sbom.spdx.json
npm run receipt -- --out /absolute/output/projection-receipt.json
```

`generate` derives the API registry, test registry, platform matrix, and
capability registry from the current Rust source and platform metadata.
`typecheck` is a closed-world reproducibility check: committed projections must
match a fresh source projection exactly.

The sole current qualification workflow is
`.github/workflows/ui-native-qualification.yml`. `receipt` validates current
projections, fingerprints that workflow and records whether the worktree is
clean. It produces a local `hepta.ui.native.projection-receipt.v2` observation,
not executed workflow, keyboard/focus, physical acceptance or release evidence.
Historical projection receipts retain their original provenance; they do not
qualify a current candidate.

`sbom` remains an optional source-only SPDX 2.3 inventory. The current
qualification workflow emits the package-bound CycloneDX 1.6 SBOM and in-toto
provenance through `scripts/hepta_ui_native_supply_chain.py`. An optional local
SPDX inventory does not replace that bundle or its independent acceptance.

The platform projection checks that the AccessKit feature remains declared.
Keyboard navigation and focus behavior require executed behavioral tests and
physical installed-artifact acceptance; source projection cannot establish them.

The signing dry-run checks metadata and prints release-owner command templates.
It never loads signing credentials and cannot authorize release.
