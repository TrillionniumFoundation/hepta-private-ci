# Evaluated cohort review evidence — 57b27c81

This evidence-only checkpoint preserves the final CALLERS row proof and the actual local source checks for the source published at [57b27c81d0d5321b873ee751fd0e58e1d905b988](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/57b27c81d0d5321b873ee751fd0e58e1d905b988), tree `3db894ee96d358c583bbf4ea15163a0d2bd96258`, reviewed in PR #6163.

The scoped tests ran on the physical actual component postimages before publication. They were not executions in a checkout of the subsequently published commit. Their complete input inventories, the publication compare, the original remote blob verification and six published input checks are separate records. The checkpoint branch retains its own earlier source ancestry and adds only this qualification directory.

| Check | First preserved result | Final preserved result |
|---|---|---|
| CALLERS merge and strict replay | Earlier v1 strict replay rejected the extra EOF blank line | v2: 607 boundaries, 425 protected rows, 183 exact before matches; strict replay passed |
| Four Version QA suites | 54 pass, 3 failures locating prefmt attack markers | 57 pass, 0 failures/errors; three actual-format locators repaired and attacks retained |
| All 13 cohort QA suites | 152 pass, 2 errors due to a missing exact-a96 overlay dependency | 154 pass, 0 failures/errors/skips; only the missing original dependency added |
| Central merged lib formatting | Single create-only request, original input preserved | Rust 1.96 formatter exited 0 and changed no bytes |

The original verifier, old forbidden marker order/multiplicity and original duplicate protected rows remain preserved. No raw failure was overwritten or relabelled as a pass. These are scoped source checks, not a complete Rust caller-index proof or a native execution result.

Full-source600 is a separate Root-owned run and its terminal result is not included here. Native and fullcaller acceptance for this reviewed source are not established by this package. Complete ordinary Adopt, complete ordinary NoUpdate, complete daemon + Root cold recovery and multi-generation improvement qualification counts all remain **0**.

## Package audit

Run `python verify_package.py` from this directory to check physical bytes, SHA256, Git blob identities, lossless compressed input originals, all four result/log pairs and preserved input inventories. This audits the evidence package; it does not rerun Rust or source QA.

`ARTIFACTS.json` inventories every other physical file in this directory. The index itself is bound by its published Git tree entry and the external publication verification record. Original local files were copied with byte reads and writes; line endings were not normalized.

Read `PACKAGING_NOTE.md` before attempting to rerun the captured builders or QA scripts. Their original workspace paths and physical source overlays are intentionally preserved as provenance, not silently rewritten.
