# Recovery evidence archive contract

`recovery_archive.py` is a standard-library-only packager and verifier with
schema `hepta-recovery-evidence-v1`. Its first archive member is
`HEPTA_RECOVERY_MANIFEST.json`. This contract is distinct from the original
`release.py --phase complete` contract. It does not assert that the missing
original complete archive, original final audit or original timing logs have
been recovered. Both `original_archive_recovered` and
`all_research_blockers_closed` remain `false`.

The archive includes the three stable-flow source packages, all current
stable-flow evidence and the separate historical recovery evidence directory.
It excludes Python bytecode/cache directories and every file under the
stable-flow `releases/` directory, preventing recursive archive inclusion.

Creation requires an independently completed `final_recovery_audit.json`.
Every audit binding must exist in the archive scope and match its digest.
The audit must bind the current recovery report receipt, exact primary
reconstruction, original primary scores, new numerical summary, new runtime
summary and raw timing events. The tool then checks the report's input/output
bindings, all 61 original primary artifacts, the 24/8 numerical coverage with
no execution errors, and the 20-model/40-case/440-event timing coverage.
Scientific failure flags remain part of the evidence; passing a performance
or numerical-accuracy gate is not an archive-completeness requirement.

The archive uses sorted paths, fixed zero timestamps and deterministic gzip
and tar metadata. Every file has a size and SHA-256. Unsafe paths, duplicate
members, symbolic links, overwritten outputs and a changing input inventory
are rejected. Verification also rechecks the recovery gates using only the
bytes present in the archive or extracted package.

## Creation and verification

Run from the repository root after the final recovery audit is complete:

```bash
python -I -S research_evidence/hepta_stable_flow_20261029/recovery_20261030/recovery_archive.py create --output research_evidence/hepta_stable_flow_20261029/releases/hepta_recovery_evidence_20261030.tar.gz
python -I -S research_evidence/hepta_stable_flow_20261029/recovery_20261030/recovery_archive.py verify --archive research_evidence/hepta_stable_flow_20261029/releases/hepta_recovery_evidence_20261030.tar.gz
```

Creation also writes adjacent `.manifest.json` and `.receipt.json` files.
Existing archive or sidecar paths are never overwritten.

After extracting into a fresh directory, invoke the verifier shipped inside
the package:

```bash
python -I -S EXTRACTED/research_evidence/hepta_stable_flow_20261029/recovery_20261030/recovery_archive.py verify-tree --root EXTRACTED
```

## Generic public parts

The unchanged `release_parts.py` supports byte splitting, part verification
and reassembly for this archive as well:

```bash
python -I -S experiments/call_put_stable_flow_analysis/release_parts.py split --archive research_evidence/hepta_stable_flow_20261029/releases/hepta_recovery_evidence_20261030.tar.gz --output research_evidence/hepta_stable_flow_20261029/releases/recovery_parts_20261030
python -I -S experiments/call_put_stable_flow_analysis/release_parts.py verify --manifest research_evidence/hepta_stable_flow_20261029/releases/recovery_parts_20261030/PARTS.json
python -I -S experiments/call_put_stable_flow_analysis/release_parts.py assemble --manifest research_evidence/hepta_stable_flow_20261029/releases/recovery_parts_20261030/PARTS.json --output reconstructed_recovery.tar.gz
python -I -S research_evidence/hepta_stable_flow_20261029/recovery_20261030/recovery_archive.py verify --archive reconstructed_recovery.tar.gz
```

The generic part tool may print a hint naming the original `release.py`.
For this recovery archive, use **`recovery_archive.py verify`** as shown above;
the two manifests and completeness contracts have different meanings.

## Limited integrity fixtures

```bash
python -I -S research_evidence/hepta_stable_flow_20261029/recovery_20261030/archive_tests/test_recovery_archive.py -v
```

These are small synthetic integrity fixtures, not neural-network experiments.
They cover deterministic byte reproduction, archive/extracted-tree roundtrips,
no overwrite, payload tampering, missing/duplicate/unsafe members, incomplete
audits, missing critical bindings, changed/missing bound files, symbolic links
and recursive output paths. Their primary digest is patched only in the
test process; production code and actual scientific evidence are unchanged.
The fixture receipts and logs preserve the actual test result.
