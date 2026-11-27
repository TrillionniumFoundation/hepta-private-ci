# Reconstruct the audit archives

The two archives are stored as ordered binary parts so that each repository blob
remains below the existing 512,000 byte limit. The part size is at most 491,520
bytes. This changes only how the archive bytes are stored in the repository.

The original archives published at commit
`b9fb18785fb74e968b5e0bf304679515bfa93a2b` are preserved exactly:

| Archive | Bytes | Parts | SHA-256 | Git blob |
| --- | ---: | ---: | --- | --- |
| `complete-known-parent-graph-7812.tsv.gz` | 3,796,298 | 8 | `4faa440281f85412a8d3c5463cac94842ec14dde8429eb6737d05201ec827bfb` | `72fcbf78c81216213f02426968ea22b753bdbf08` |
| `native-evidence-PUBLIC.zip` | 1,605,908 | 4 | `1fe917ebc21b0e4e9ddae589623d6bdab2327c62897a07920e658336cd8141b0` | `d06c664be3e073f8b1c96029d0f97e5d233e9d5b` |

## Usage

Use Python 3.9 or later with the standard library. From the repository root, run:

```sh
python3 qa/repository-consolidation/20261121/rust-c1a0-audit/reconstruct_archives.py --output-dir /tmp/hepta-audit-archives
```

Replace the output directory with a directory you choose. Keep reconstructed
archives outside the tracked evidence directory to avoid adding the large
original files to a later commit. The script has no implicit output directory.

The manifest, script and `archive-parts` directory must remain together. The
script reads the archives and parts in the order recorded in
[ARCHIVE-PARTS.json](ARCHIVE-PARTS.json). It verifies each part's size, SHA-256 and
Git blob identity, then checks the same three values for each complete archive.
It validates all inputs before publishing either output archive.

Existing files with the exact recorded content are accepted without changes.
Existing different files, missing parts, altered parts, symbolic links in part
paths or output files, and invalid part ordering cause an error. No existing
different file is overwritten.
New output files are published through a temporary file and a hard link in the
chosen output directory, so that directory must support hard links.

The script does not download anything, extract either archive, or execute archive
contents. The reconstructed gzip and ZIP bytes match the original containers;
the evidence, failed command records and test results inside them are unchanged.
The original archive identities in the evidence manifest remain valid for the
reconstructed files. The ordered part identities are recorded separately in
`ARCHIVE-PARTS.json`.
