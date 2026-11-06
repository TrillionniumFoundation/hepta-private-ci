# Core reporter v3 and attempt 5127 evidence

This additive immutable packet preserves 130 original files and
769,986 bytes. It contains the fixed nextest 0.9.103 source
audit, both original one-case reporter probes, the reviewed reporter correction,
26 narrow local checks, independent and root reviews, strict A4/B3 source
publication identities, and the actual terminal result of run 42285333978.

The first one-case probe passed but produced no JUnit; its failed report
postcondition is preserved. The second probe produced the report under the
workspace after adding only the local-profile report setting. Neither is a
Core product test. The report flag also changes the existing wrapper to its
full-metadata path; the actual command is not claimed byte-identical.

Actual attempt #5127 built and listed seven cases, then original just returned
100. Source checks passed afterward. Fixed diagnostics report two Guardian
failures with two attempts each, and five JUnit passes with one attempt each.
Those five remain unqualified: the original scanner rejected compile stderr,
and the unchanged collector withheld every raw file. The official artifact
contains only its original rejection manifest. JUnit now has a collected
12,920-byte identity, but its bytes and the detailed runtime errors are absent.
No missing content or macro-skip absence is inferred from a hash or diagnostic.

The earlier #5114 failure and #5120 historical checkpoint are preserved and
not repeated. A future partial-evidence design is outside this packet. Every
candidate and receipt remains frozen at its original scope and time. Building
or restoring this packet runs no embedded code or tests.

## Restore

```sh
python -O restore.py /absolute/path/to/bundle /absolute/path/to/new-destination
```

The archive is 86,172 bytes with SHA-256 `7e9461646b2495d01ff39a3574cf4515647d83828013f1065e75fef93d2f78a0`.
It is transported as 1 bounded single-member gzip container(s),
each at most 450,000 bytes. The reader is byte-identical to the reviewed
Core21/22 reader except its two fixed seals; historical transport filenames
retain the original encoding prefix. It rejects an existing destination,
unsafe paths, duplicates, extra members, invalid modes and malformed containers.
It writes nothing into the input bundle. Exact original bytes and safe regular
permissions are restored; ownership and timestamps are not restoration targets.
INDEX preserves both the restoration path and original source path. External
review receipts are mapped under the packet's supplement input directory.
Reproducible probe Cargo targets and bytecode are excluded, not result evidence.
