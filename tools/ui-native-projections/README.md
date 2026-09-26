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
npm run sbom -- --out native-evidence/ui-native-sbom.spdx.json
npm run receipt -- --out native-evidence/projection-receipt.json
```

`generate` derives the API registry, test registry, platform matrix, and
capability registry from the current Rust source and platform metadata.
`typecheck` is a closed-world reproducibility check: committed projections must
match a fresh source projection exactly.

The signing dry-run checks metadata and prints release-owner command templates.
It never loads signing credentials and cannot authorize release.
