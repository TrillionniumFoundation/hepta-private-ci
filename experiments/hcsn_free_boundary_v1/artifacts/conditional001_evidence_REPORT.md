# Conditional001 evidence archive

The stable `results/conditional001` tree was archived in full: **397 files**, **15,300,473 original bytes**, stored as **7,971,636 compressed bytes** in **2 parts**. Full parts are 4 MiB; the final part contains the remaining bytes. The archive preserves the logical prefix `results/conditional001/`.

- Manifest: `conditional001_evidence.json`
- Verification receipt: `conditional001_evidence_VERIFICATION.json`
- Whole compressed archive SHA256: `0c1d90c87908ce20ba8c454073609cd61415397db67f62603d428bb33ec26463`
- Reviewed streaming archive source SHA256: `7aefcc785977bb391116750d04e9abd8bfa1db28381ee06227bac501c61eceab`

Independent hardlinks staged the original files without copying their data. Every member was matched to the source inventory, byte size and SHA256. Every part's size, SHA256 and Git blob SHA1, plus the concatenated archive SHA256, were independently checked.

Restoring to the existing package root verified all **397 identical files**. `TemporaryFile` was forbidden during this restore, proving that no whole archive or member copy was created. Original file inode, mtime, size, SHA256 and final hardlink counts were unchanged. All **38 original frozen files** and **41 conditional registered files** remained unchanged. Only this job's hardlink staging directory was removed.

The minimum observed free space was **79.53 MiB**, above the required 50 MiB reserve. Each part write checked reserve plus its bytes and a metadata allowance. Packing consumed **6.3997 process CPU seconds**; identical-file restore consumed **0.3868 seconds**. No Git writes occurred.

This bundle excludes the independently running `equal_updates_core002` and does not alter any original protocol or result. The complete conditional comparison, registrations, checkpoints, predictions, gradient/update logs and execution receipts remain under their original paths inside the bundle.
