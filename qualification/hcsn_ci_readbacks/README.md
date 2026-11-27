# Historical hosted readbacks

The complete original console streams listed in the
[storage inventory](../../qa/repository-consolidation/20261125/hcsn-hosted-console-custody/raw-evidence-storage.json)
are retained as verified gzip records. Original readback receipts still refer
to the decoded bytes at the original paths. Restore into a new directory from
the repository root before replaying those historical checks:

    python3 qa/repository-consolidation/20261115/restore_raw_evidence.py /path/to/new-output

No source snapshot, test output classification, or qualification claim is
changed by the storage format.
