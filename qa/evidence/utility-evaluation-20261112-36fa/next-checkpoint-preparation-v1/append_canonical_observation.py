#!/usr/bin/env python3
"""Append already-observed Root objects to an independent evidence map only."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

OUT = Path('/tmp/hepta-36fa-next-evidence-preparation-v1')
ROOT = Path('/tmp/hepta-36fa-after2268-20261112')

def raw_identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def stable_read(path):
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    return raw

def save_new(name, raw):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, name
    else:
        with path.open('xb') as handle:
            handle.write(raw)
    return raw_identity(raw)

def jwrite(name, value):
    return save_new(name, (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode())

def main():
    base = json.loads((OUT / 'BASE_2268_FILEMAP.json').read_bytes())
    initial = json.loads((OUT / 'FULL_FILEMAP_BEFORE_README_REPLACEMENT.json').read_bytes())
    result = dict(initial)
    raw = stable_read(ROOT / 'ROOT_UPLOADS.jsonl')
    rows = [json.loads(line) for line in raw.splitlines() if line]
    prior = json.loads((OUT / 'INPUT_SNAPSHOT_INDEX.json').read_bytes())
    prior_uploads = next(x for x in prior if x['source'] == str(ROOT / 'ROOT_UPLOADS.jsonl'))
    prior_bytes = Path(prior_uploads['snapshot']).read_bytes()
    assert raw.startswith(prior_bytes), 'Root upload ledger changed instead of append-only growth'
    assert len(rows) >= 208
    source_pin = save_new('canonical-actual-addendum/ROOT_UPLOADS_' + str(len(rows)) + '_ROWS.' + hashlib.sha256(raw).hexdigest()[:16] + '.original.jsonl', raw)
    added = []
    revisions = []
    for row in rows:
        assert row['full_readback_equal'] is True
        name, sha = row['path'], row['sha']
        assert not name.startswith('/') and '..' not in Path(name).parts
        if name in result:
            assert result[name] == sha, ('Do not replace an existing path', name, result[name], sha)
            continue
        local = Path(row['local_path'])
        content = stable_read(local)
        pin = raw_identity(content)
        assert pin == {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': sha}
        snap = 'canonical-actual-addendum/' + local.name
        save_new(snap, content)
        result[name] = sha
        added.append({'path': name, **pin, 'full_readback_equal': True,
                      'proof_kind': 'Root existing create-and-full-readback ledger plus independent local-byte identity',
                      'local_snapshot': str(OUT / snap), 'ledger': source_pin})
    assert len(base) == 2268 and all(result[k] == v for k, v in base.items())
    assert result['checkpoints/README_2268FILES_BEFORE_FINAL_NONRUST.md'] == base['README.md'] == '3e8b17601e82f5f7be49d172784bc2c4a452a080'
    jwrite('CANONICAL_OBSERVATION_ADDENDUM.json', {
        'format': 'hepta-independent-canonical-observation-addendum-v1',
        'observed_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_ledger_snapshot': source_pin, 'source_ledger_rows': len(rows),
        'initial_files': len(initial), 'added': added, 'revisions': revisions,
        'combined_files': len(result), 'all_original_2268_same_sha': True,
        'canonical_status': 'actual clean alignment independently observed by Root; full qualification gates not observed started',
        'source_ref_publication': 'pending Root actual CAS and independent readback evidence',
        'commit_ref_PR_H_source_writes_by_this_script': False,
    })
    jwrite('INCREMENTAL_FILEMAP_WITH_CANONICAL_OBSERVATION.json', {k: v for k, v in result.items() if k not in base})
    jwrite('FULL_FILEMAP_WITH_CANONICAL_OBSERVATION_BEFORE_README.json', result)
    print(json.dumps({'added': len(added), 'increment': len(result)-len(base), 'combined': len(result)}))

if __name__ == '__main__':
    main()
