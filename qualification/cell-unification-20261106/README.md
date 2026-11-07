# Preserved Cell qualification evidence

This directory now stores all **4,087 original Git files** from
[`a6f3aa12ba187448c35449c7da0a9798ae4ca987`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/a6f3aa12ba187448c35449c7da0a9798ae4ca987/qualification/cell-unification-20261106)
as a bounded archive. All **116,240,752 original bytes**, original paths,
and Git file modes are preserved. Historical failures, unknown outcomes, budgets,
and qualification statements retain their original meaning.

The previous layout contained 47 files above the repository's
512,000-byte blob limit and 37 paths above 190 UTF-16 units.
The original [Windows job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42302804112/job/128184561094)
failed during checkout with six long file paths; its product test steps were skipped.
Its complete decoded job log is retained in [the compressed log](failures/windows-checkout.log.gz),
with the original step outcomes in [the failure record](failures/windows-checkout.json).

## Archive and integrity

[`MIGRATION.json`](MIGRATION.json) records the migration checks and retained logs.
[`archive/index.json`](archive/index.json) binds the immutable original source,
143 payload parts and 3 compressed member manifests. Each archive file
is at most **480,000 bytes**. Payload parts concatenate into a gzip stream;
the decompressed bytes follow manifest order. Each member records its path, Git
mode, byte count, SHA-256, and original Git blob ID.

The verifier bounds compressed parts, individual and cumulative decoded manifests,
member counts, paths, and total payload bytes. It checks the complete source roster,
whole payload and every member without creating the original long paths. Hashes
establish byte integrity; they do not create a new independent qualification or
grant execution authority.

From the repository root:

```sh
python -B scripts/hepta_evidence_archive.py verify \
  qualification/cell-unification-20261106/archive \
  --expected-source a6f3aa12ba187448c35449c7da0a9798ae4ca987 \
  --expected-listing c1e6d2104a3b33f7a37b600efd8468e2a169e7a5e624682ac6fe78a674ea6669
```

Add `--repo .` when the original commit's Git tree is locally available to compare
the archived roster directly with `git ls-tree`. The pinned listing digest above
also checks the complete original roster on a shallow checkout.

## Restore the original layout

Use a new, short destination outside the current checkout. On Windows, choose a
short root such as `C:\e` so the restored historical paths fit the host's path limits.

```sh
python -B scripts/hepta_evidence_archive.py restore \
  qualification/cell-unification-20261106/archive \
  --expected-source a6f3aa12ba187448c35449c7da0a9798ae4ca987 \
  --expected-listing c1e6d2104a3b33f7a37b600efd8468e2a169e7a5e624682ac6fe78a674ea6669 \
  --destination /tmp/hepta-original
```

Restoration verifies the archive before creating the destination and refuses an
existing destination. It restores the original repository-relative layout beneath
that root. A write failure leaves a partial new destination; the archive remains
unchanged. The original reports, manifests, scripts, and nested archives can then
be read at their original relative paths.

## Observed archive validation and product-test boundary

The final archive passed complete roster, payload, and member verification. A real
restore of all 4,087 files matched the original bytes, Git blob IDs, and Git modes.
The 14 archive regression tests passed, including corruption, omission, traversal,
truncation, existing destinations, cumulative manifest limits, and separate path
and blob limits. The first development fixture failure and the preceding test log
are retained under `failures/`; the final test receipt binds the tested sources.

The dedicated `Hepta evidence archive` workflow is configured to verify the archive
on Linux and Windows. For source `4ce8808d8b48624a17d247fdf47c7fbdaaab80a4`,
Windows job `128279386114` and Ubuntu job `128279386486` both completed checkout,
all 14 archive regression tests, complete archive verification, and the path/blob
budget checks successfully. The [Windows receipt](../cell-architecture-20261106/ci/4ce-windows-archive.json)
and [Ubuntu receipt](../cell-architecture-20261106/ci/4ce-linux-archive.json)
preserve the original job logs and hashes.

Those archive jobs did not run Rust product tests. Their results are scoped to the
recorded source revision and do not qualify later revisions. The original Windows
checkout failure remains part of the evidence, and its skipped product tests
remain unexecuted for that original run.
