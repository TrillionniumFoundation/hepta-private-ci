# Complete experiment evidence

The evidence archive has 1,072 payload files plus its internal manifest. It
contains all 75 checkpoints, 75 training curves, 75 main prediction archives,
225 extended query prediction archives, three audiovisual dataset splits,
source snapshots, numerical checks, development records, loss logs and cost
receipts. Original raw CREMA-D media and redundant per-clip caches are excluded;
their identities and extraction records remain available.

The archive is **111,476,686 bytes** and is published as 36 parts to stay below
per-file GitHub limits. Parts are named `full_evidence.tar.gz.part000` through
`part035`. Each is 3 MiB except the last. [PARTS.json](PARTS.json) fixes their
order, size, SHA256 and Git blob SHA; [EVIDENCE_MANIFEST.json](EVIDENCE_MANIFEST.json)
lists and hashes every payload file. The full archive SHA256 is:

```text
13e411eac843a44e6a168fa6e7f0e7e6a54a53fe10ea45633aa9efd6ef1bd1bd
```

After checking out this directory, verify all parts without creating a copy:

```bash
python3 -m experiments.hcsn_four_stage_flow_20261031.verify_evidence
```

To create a new assembled archive, add `--output /path/to/new_evidence.tar.gz`.
The helper refuses to overwrite an existing output and checks each part plus
the whole reconstructed archive. Extract into a fresh directory. Archive paths
are relative to the repository root; every member is a regular file, without
symlinks or parent traversal. A full decompressed readback already verified
all member hashes and sizes before publication.

The archive is an immutable execution snapshot. The final narrative report,
extended human-readable summary, publication receipts and verification helper
are provided separately in this research directory and may be newer than the
snapshot. Archive packaging CPU is separately measured and is not added to
model training or inference costs.
