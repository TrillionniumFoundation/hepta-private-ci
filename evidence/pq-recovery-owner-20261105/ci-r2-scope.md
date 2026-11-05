# CI source audit of fixed runtime R2

Source commit: `70115620a7f540c8618a9b0d32ead20f8bc508f0`. Tree:
`ebd1437475d71252786788f67d2911f5a6e6108d`. Parent:
`9e8faef449a4392b7b9aa6a9071f260a34d95ec9`.

The original validator bytes were retained (SHA-256
`85dda7f92d774db9ea0a5709b3bcfda6a50e8dfd396d9a6bc9353a2689bd470c`).
It executed the actual workflow inline audit again on the adopted R2 checkout.
Exit code was 0; all 154 synthetic-fixture outcomes matched expectation.
The 37 selected source test names, exact filters, minimum counts, budgets,
mandatory audit and all original 24 controls remained intact. Before and after,
HEAD/tree/Git clean status and all 12 audit input Git blobs/SHA-256 values matched.
The changed product fixture is blob `d87d97f193a6095e77a60fb3cb1894f77ebc6f95`,
SHA-256 `5baaac0f3034422f28bdbd14379b2d8bb08a42eb84c8e174245aa171d3649b32`.

The outcomes consist of one accepted complete 37-test fixture, 111 rejected
individual missing/ignored/duplicate cases, 40 rejected group/receipt/log
failure cases, and two rejected obsolete selection cases. This is an execution
of the source/log audit, not execution of those 37 Rust tests.

Native tests executed by this audit: **0**.
`audit_did_not_trigger_ci`: **true**. The unchanged validator's legacy
`ci_triggered: false` field concerns its own invocation only; it makes no claim
about GitHub events from root's separate source/evidence publication. This audit
neither triggers nor inspects hosted CI, edits repository source/index, nor
launches Rust. `PYTHONDONTWRITEBYTECODE=1` and `GIT_OPTIONAL_LOCKS=0` were used.

## Retained earlier attribution

All R1/f040 source-audit receipts remain unmodified, including R1's first
workflow-materialization failure and its later successful 154-fixture audit.
R1's nine native unit passes and product compile failure (zero product bodies
executed) remain distinct from R2's independently executed native gates. The
one-line fixture error conversion does not transfer prior native execution.

The new files are `ci-selection-audit-r2-70115620.json`, its `.log`, and
`ci-selection-audit-r2-70115620-provenance.json`. Provenance records the exact
command, timing, source identity, before/after inputs and raw receipt/log hashes.
The native 9 frontier units and 4 product controls require their own exact-R2
terminal receipts. This audit's qualification is `HOLD_NO_GO`.

## Reproduce

At the fixed checkout, with these evidence files installed and Python 3/PyYAML:

```bash
PYTHONDONTWRITEBYTECODE=1 GIT_OPTIONAL_LOCKS=0 \
  python3 evidence/pq-recovery-owner-20261105/ci-validate-selection.py \
  --repository "$PWD" --output /tmp/hepta-pq-recovery-R2-new.json
```

Use a new output path; the validator refuses overwrites.
