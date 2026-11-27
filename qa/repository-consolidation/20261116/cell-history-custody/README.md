# Cell history custody

This package preserves two reviewed research histories while keeping the maintained tree within the original 512,000-byte per-blob limit:

- `0aa2120edc45e349e8689c08c21ad010c4b5520b` — Cell state closure V4 results.
- `32b8a11ae5d55a2e7324a8b31c5057f7b911a139` — Cell field V8.

Both tips remain original second parents of ordinary merge commits. Their complete Git history, source, original assets and recorded unsuccessful results remain reachable. The maintained research workflow keeps its manual dispatch, explicit research opt-in and operator acceptance requirements.

## What is represented here

`MANIFEST.json` binds 169 original data files to exact repository paths, Git blob IDs, SHA256 digests, byte lengths, modes and original parent commits. Of these, 167 exceed the unchanged repository blob limit; two smaller files contain frozen public-corpus text whose original spelling and proper names must remain unchanged. These files total 158,124,367 bytes.

The maintained tree stores their verified history references. The whole original blobs remain in retained merge-parent history. The manifest is not an allowlist for oversized files and does not weaken the spelling or size checks.

The two gzip snapshot indexes describe complete original research subtrees. They are useful for historical byte recovery. They do not prove that a current consumer can read its inputs, and they do not replace tests of current merged source.

## Current consumers: restore inputs, then run current source

From the maintained repository root, use a full clone containing both retained original histories:

```sh
python3 qa/repository-consolidation/20261116/cell-history-custody/restore.py \
  --current-inputs \
  --restore-to /tmp/hepta-cell-current-inputs
```

The destination must be new and outside the repository. Choose another unused destination if that path already exists. On Windows, pass an unused absolute directory outside the checkout instead of the example POSIX path.

This mode restores the complete declared input set: 457 non-source files, 172,289,387 bytes, across the nine directories listed in `MANIFEST.json`. It binds every retained sibling file to the requested maintained head and every moved asset to its retained original parent. It rejects changed or unlisted input files within these declared directories. It excludes Python, shell, Rust, JavaScript and other declared source suffixes. It never copies old source into this input directory.

Continue to call entrypoints from the maintained checkout. Pass explicit input directories under the restored location. For example, the current V2 descriptive reader accepts its input directory explicitly:

```sh
python3 qa/stem-bakeoff/evidence/20261024-cell-parameter-field-v2/analyze-results.py \
  --evidence /tmp/hepta-cell-current-inputs/qa/stem-bakeoff/evidence/20261024-cell-parameter-field-v2
```

That reader writes its derived summary and figure into the supplied directory; use a separate restored directory for each analysis. It also requires its original Matplotlib dependency. Its default directory is beside its source file, so use the explicit `--evidence` argument after this representation change.

Other current readers keep their existing explicit input parameters:

| Current reader                      | Explicit input selection                                       |
| ----------------------------------- | -------------------------------------------------------------- |
| `cell_field_export_statistics.py`   | `--run`, `--data`, `--protocol`, `--evaluation`                |
| `cell_field_statistics_audit_v6.py` | `--evaluation-directory`, `--run-directory`, `--protocol-path` |
| V3 `make_figures.py`                | `--run`, `--evaluation`, `--output`                            |
| V4 closure `derive_summary.py`      | Original CLI arguments and exact recorded input digests        |

Restoration preserves archive parts as parts. Original archive concatenation, digest verification, member inspection and extraction remain separate prerequisites where a reader expects unpacked run data. The restorer does not extract archives, fetch corpora, download models, read authentication material, train models or execute research source.

Historical scripts with fixed execution-workspace paths retain those original prerequisites. Their preserved source and invocation records are historical evidence. A recovered old snapshot does not establish that their old absolute paths, external model snapshots, encryption inputs or source-checkout identities exist on a new machine.

## Verify without restoring

With no restoration mode or output directory, the command verifies the 169 original asset identities and retained ancestry:

```sh
python3 qa/repository-consolidation/20261116/cell-history-custody/restore.py
```

Use `--current-inputs` without `--restore-to` to verify the complete current input closure without writing files. An unpublished local candidate can be selected with `--head` and its full commit SHA. A shallow or partial clone missing the required history or blobs fails verification; the tool does not silently fetch different objects.

## Historical snapshots

The following restores the exact original V4 research subtree, including its original source, into a new isolated directory:

```sh
python3 qa/repository-consolidation/20261116/cell-history-custody/restore.py \
  --snapshot cell-v4 \
  --restore-to /tmp/hepta-cell-original-v4
```

Use `--snapshot cell-v8` for the V8 snapshot. V4 contains 993 files and 238,689,028 bytes. V8 contains 1,218 files and 192,916,094 bytes. The tool verifies the complete original subtree path, mode and object roster before restoring. These are inert file projections, not Git checkouts; commands that require a particular Git source identity still require a corresponding genuine checkout.

`--snapshot` and `--current-inputs` are distinct, mutually exclusive modes. Asset-only restoration is available with `--restore-to` and neither mode, but current readers should use the complete current input mode so their small sibling files are also present.

## Verification boundaries

The restorer checks regular-file metadata, canonical relative paths, declared size bounds, exact Git blob type and length, Git and SHA256 byte identities, original commit/path bindings and retained ancestry. It creates a fresh isolated directory and uses create-only file writes. It reads raw Git blobs without text conversion or checkout filters.

The custody tests exercise successful recovery after a file leaves the maintained tree, full original snapshot closure, current maintained input closure, changed current siblings, wrong source paths, wrong hashes, duplicate and escaping paths, existing destinations, repository-subdirectory output bypasses and invalid numeric metadata.

The research workflow's new contract tests and shared-feature tests use the current merged Python source. The two einsum strings in `cell_batch_runtime.py` use an equivalent batch/feature index renaming; operands, contractions and output axis order remain unchanged. The incoming `real_encoder.py` change selects eager attention only for the registered Gemma audio component and binds that selection into the feature identity. Text-only defaults and the existing local-model, permission and frozen-weight checks remain intact.

This package records custody and focused software validation. It does not turn a historical failed experiment, an incomplete run, an unqualified model or a native runtime failure into a passing qualification.
