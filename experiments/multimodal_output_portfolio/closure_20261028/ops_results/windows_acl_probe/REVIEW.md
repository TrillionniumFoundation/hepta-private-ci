# Native Windows ACL diagnostic

This bundle adds an observation job for the three real Windows sandbox failures from run 40661665726, job 122730593546. Existing tests and production token flags, ACL grants/denials, full-disk-read requirements, Cargo workspace and helper fixtures are unchanged.

## Exact executed source

The driver verifies the requested committed HEAD, blob identity, mode, live bytes and index before execution, and verifies them again afterward. It copies committed token.rs, acl.rs and winutil.rs byte for byte into an owned temporary crate. The minimal exact anyhow 1.0.103 / windows-sys 0.52.0 dependency closure and registry checksums come from that commit's Cargo.lock. The separate lock is executed with --locked and checked unchanged. Python 3.12.14 is installed with the repository's pinned setup action; the Rust release comes from the committed toolchain file. Git core.autocrlf=false is set only on this ephemeral diagnostic job before checkout to preserve committed bytes.

## Observation and permissions are distinct

The two fixtures reproduce the partial DELETE-only deny repair and the broad Everyone/logon grants from the failing tests. A protected .git directory is also created inside the fixture. The harness calls the existing production token and ACL functions, records raw and mapped ACE masks/flags, user/normal/restricting SIDs, 84 native CreateFile access probes, and actual read/write/create/delete results. All mutable filesystem objects are descendants of a newly created temporary fixture. It never calls the production NUL-device ACL modifier and never changes token flags. The child-process legacy spawn path is not reproduced by this small diagnostic; its original Windows integration test remains a gate.

A completed diagnostic can contain failed security invariants. The JSON always says qualification=false and lists every failed invariant. Completion requires exactly 26 named CHECK records, all 84 OPEN triples, 12 ACL groups and their full ACE index sets, all nine token category headers and their complete SID index sets, 16 actual operation records, four repair results, three token flags, and one final marker. A DONE marker alone is rejected. A base token with zero restricting SIDs has an explicit zero-count header.

## Review and validation

The independent peer review found a real Windows path-separator mismatch between pathlib strings and Git paths; all blob dictionary and Git paths now use as_posix(). Root review found that a lone completion marker could be accepted; the exact observation contract and 11 deletion/duplication counterexamples close that diagnostic gap. A Windows LPWSTR argument is explicitly mutable, matching the production API. The four local Python integrity tests pass. Scoped repository Rust formatting and git diff --check pass. No local Windows compile or native access result is claimed.

The new job is acl-observe in .github/workflows/ndu-windows-storage-probe.yml. The existing storage observe job is unchanged. On the actual candidate it installs the pinned Python and committed Rust release, runs the four custody tests, executes the diagnostic, and uploads OBSERVATION.json plus the raw TSV, compiler/native stderr and exact isolated manifests. The actual native results are needed before changing the production permission rules.
