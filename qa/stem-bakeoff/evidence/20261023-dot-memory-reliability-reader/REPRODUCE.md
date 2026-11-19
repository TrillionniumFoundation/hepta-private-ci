# Inspect without rerunning models

From this directory, Python standard library alone verifies the archived bytes:

```sh
python3 - <<'PY'
import hashlib, json, zipfile
from pathlib import Path
index = json.loads(Path('evidence-index.json').read_text())
archive = Path(index['archive'])
assert archive.stat().st_size == index['bytes']
assert hashlib.sha256(archive.read_bytes()).hexdigest() == index['sha256']
with zipfile.ZipFile(archive) as z:
    manifest = json.loads(z.read('SHA256-MANIFEST.json'))
    assert manifest == index['manifest']
    assert set(z.namelist()) == set(manifest) | {'SHA256-MANIFEST.json'}
    for name, spec in manifest.items():
        data = z.read(name)
        assert len(data) == spec['bytes']
        assert hashlib.sha256(data).hexdigest() == spec['sha256']
    result = json.loads(z.read('reader-feasibility-001/result.json'))
    assert result['development_reader_patch_pass'] is False
    assert result['candidate_applied'] is False
    assert result['candidate_code_executed'] is False
    for name in ['domain_data.py', 'test_domain_data.py']:
        suffix = 'scripts/memory_cell_domain/' + name
        assert z.read('reader-feasibility-001/baseline/' + suffix) == z.read('reader-feasibility-001/candidate/' + suffix)
print('All scoped bytes verified; Reader failure preserved; no model executed.')
PY
```

Review the raw `reader-feasibility-001/generation.txt`, `output-validation.json`,
`protocol.json`, `acquisition.json`, `messages.json` and cost receipts. The messages
file is the actual code-repair model input; evaluator test source is separate.
Do not fix the output fence or nonexistent edit target and relabel it as this run.

The archive's launch scripts preserve the original absolute development paths and
exclusive-create behavior. They are provenance, not an instruction to execute a
second attempt. A new trial needs a new isolated directory, reviewed path changes,
new protocol, explicit budget and a separate result. Never run from historical
state directories. Official weights are external and not silently downloaded by
any verification command here.

## Optional mechanism reproduction in a fresh checkout

Use this branch's published commit, not the newer d61 stack. Preserve existing
results rather than rerunning in their directories. Prepare the dependencies from
`scripts/memory_cell/requirements.txt`; the original CPU environment versions are
in archived `runtime.json` (PyTorch 2.5.1+cpu from its official index). Then from
repository root:

```sh
MEMORY_SYSTEM_PYTHON=/absolute/path/to/reviewed-venv/bin/python \
  bash scripts/memory_cell_system/run_tests.sh
```

This discovers 26 service, 20 domain and 5 TCP methods and uses tiny fixture
models. It is not the separate 800-update pretrained lifecycle. The original logs
and independent final-source manifest are sufficient to inspect the recorded run
without repeating it. The two source-stage trees are given in README.md; this
publication's evidence commit changes only this evidence directory.

`local-changes.patch` can alternatively be applied, after `git apply --check`, to
a new pinned a26 checkout. `patch-reproduction-receipt.json` records that all 13
files byte-matched the tested result. The three-arm development executor scripts,
protocol, import identities and failure/pass logs are also included. Their gold
patches are self-test controls, not Reader outputs or formal evaluation answers.
