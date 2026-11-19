# MemoryCell / NDU Library — source-only snapshot (2026-11-03)

This snapshot preserves **180 original Library source records representing 159 unique byte strings**. Duplicates were omitted from the ZIP files and mapped to their canonical contents in `SOURCE_SHA256_MANIFEST.json`. Includes Python, shell, workflow YAML, historical `.patch` and other **source-only** files. No original data sets, model weights, checkpoints, experiment traces or raw execution archives were included.

**Source authority:** ChatGPT Library root snapshots; this is not an executable production source tree. Current upstream `hepta-private-ci` and its branches may already supersede these historical files. **Do not apply old patches, activate workflows, or merge these into an active CI path as-is.** The snapshot uses an isolated `library-recovery/` prefix and was built from the exact Library byte copies.

## Reproduce integrity validation (Python 3 standard library)

```bash
python3 - <<'PY'
import hashlib, json, zipfile, pathlib
here=pathlib.Path('.')
manifest=json.loads((here/'SOURCE_SHA256_MANIFEST.json').read_text())
assert manifest['original_records']==180 and manifest['unique_files']==159
expected={x['canonical_name']:x['sha256'] for x in manifest['files']}
observed={}
for package in manifest['packages']:
    blob=(here/package['filename']).read_bytes()
    assert len(blob)==package['bytes']
    assert hashlib.sha256(blob).hexdigest()==package['sha256']
    with zipfile.ZipFile(here/package['filename']) as archive:
        for member in archive.namelist():
            assert member.startswith('source/') and '..' not in pathlib.PurePosixPath(member).parts
            name=member[len('source/'):]
            data=archive.read(member)
            digest=hashlib.sha256(data).hexdigest()
            assert expected[name]==digest, name
            assert name not in observed, name
            observed[name]=digest
assert len(observed)==159
for item in manifest['files']:
    assert observed[item['canonical_name']]==item['sha256']
print('PASS: 5 ZIPs, 159 canonical source files, 180 original records')
PY
```

Every source entry also has its original full Git Blob SHA-1 in the manifest. ZIP packages carry separate SHA-256 and byte sizes. The ZIPs use deterministic 2026-11-03 archive timestamps and deflate compression; they are code transport only and do not contain raw experiment evidence.

## Validation boundaries

- Python AST parse was checked for readable root `.py` source snapshots; no root Python syntax errors were found in this selected set.
- A conservative regex scan of selected original bytes found no obvious private-key, GitHub PAT, AWS access-key, or hard-coded API-key/password assignment patterns. This is **not** a complete secrets/PII assurance; unreviewed historical code is retained in the isolated branch and never installed.
- No claim is made that historical workflows can run against the current branch or that associated model/data dependencies are present.
- Reproducibility here means **byte-for-byte source verification**, not replaying complete experiments. Each actual experiment must pin its corresponding historical toolchain, dataset permissions, source commit and evaluation profile.
- Do not clear ChatGPT Library until all remaining source candidates and the original dot-host Git worktrees have been audited and the destination GitHub commits verified.

## Source identity / public history

Base public code commit at snapshot capture: `732e934ba496d90fbe042b8d41d479ef901643e5`. Recovery deliberately adds only this archival directory; it does not modify `main` or any active CI workflow.
