# Original vendored maintenance patches

The [inventory](raw-evidence-storage.json) records the original Git blob and
SHA-256 for each preserved patch. Only the patch storage changed. Source,
licenses, test fixtures, and upstream provenance manifests remain as recorded.

From the repository root, restore into a path that does not yet exist:

    python3 qa/repository-consolidation/20261115/restore_raw_evidence.py /path/to/new-output

Use the restored patch at its original repository-relative path. For example,
when replaying a documented upstream backport, pass that path to the existing
patch application command. Validate the upstream preimage against the package's
original provenance before applying the restored patch.
