# Source archive integrity

Add the two files in `scripts/` beside the existing
`scripts/hepta_cell_joint_config.py`. This stage reuses that module's clean
checkout, descriptor-relative no-follow reads and immutable byte-pin checks.
It adds no dependencies and is explicitly POSIX-only.

The binding describes independent identities:

```json
{
  "schema": "hepta.source-archive-binding.v1",
  "tested_source": {"commit": "<40 lowercase hex>", "tree": "<40 lowercase hex>"},
  "archive": {"path": "source.tar.gz", "sha256": "<64 lowercase hex>", "bytes": 12345},
  "archive_prefix": "source",
  "runtime_configuration": {"path": "runtime.json", "sha256": "<64 lowercase hex>", "bytes": 123},
  "release_source": {"commit": "<40 lowercase hex>", "tree": "<40 lowercase hex>"}
}
```

Only `schema`, `tested_source` and `archive` are mandatory. Omit
`archive_prefix` for a tar whose members begin at the Git tree root. A prefix
is a directory envelope: every source member must remain within it. No source
exclusions or implicit first-directory stripping are supported. Runtime
configuration is an optional independent raw byte pin, not proof of use.
The optional release commit/tree is checked against local Git objects and
reported separately; it need not equal the intended tested source.

```sh
python3 -B scripts/hepta_source_archive.py \
  --binding /evidence/archive-binding.json \
  --source-root /work/clean-tested-source \
  --artifact-root /evidence \
  --output /evidence/archive-integrity.json
```

Output creation is exclusive. Keep reports and artifacts outside the source
checkout. Exit 0 means integrity verified; exit 1 emits a failure report.

The verifier compares every tracked file's raw bytes, Git executable
classification and symlink target without extraction. It retains SHA-256,
Git blob identity and original tar permission bits for each file. Git does not
record arbitrary read/write permission bits; those bits are reported, not
claimed equal to a filesystem mode. Special permission bits, hard links,
sparse files, devices, duplicate members, missing files, extra files or
directories, noncanonical paths and root-escaping symlinks are refused.
Submodules and nonportable path syntax are also refused explicitly.

Tar and gzip-compressed tar are supported. Decompressed input is bounded by
the complete Git tree plus a finite metadata allowance. Both tar end markers
and the entire trailing stream are checked, including concatenated gzip
members. `git archive` output changed by `export-ignore` or `export-subst`
fails rather than silently equating a subset with the complete Git tree.

All reports are integrity-only. They cannot authenticate prior test execution,
CI, publication, actual runtime configuration use, learning benefit, production
qualification or owner authority. Those claims remain false even when the
archive matches the intended tested source and the release tree also matches.

Behavior tests use real Git commits and tar/gzip archives:

```sh
PYTHONPATH=scripts python3 -B -m unittest test_hepta_source_archive -v
```
