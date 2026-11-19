"""Read only the completed collector's metadata and bind publication inputs."""
import hashlib
import json
from pathlib import Path
import resource
import time
from datetime import datetime, timezone

STARTED, CPU = time.monotonic(), time.process_time()
BASE = Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training')
COLLECTION = BASE / 'numerics-terminal-postmortem-v1'
LAUNCH = BASE / 'numerics-terminal-postmortem-launch-v1'
OUT = BASE / 'terminal-numerics-draft-input-inventory-v1'
EXPECTED = {
    COLLECTION.with_suffix('.zip'): (34050599, 'e96030a4c1a29031e56c406d7cc72cee9d141a0edb4701e3a83d60b5d5e32c52'),
    COLLECTION / 'COLLECTION-RECEIPT.json': (8567, '8461128602a2ca104d71401e4d42f59510aac37a96d79942a6c8e2344a409804'),
    COLLECTION / 'SUMMARY.json': (194004, 'c50b137cb66f9dc29217f919098cb592285a5395cbf60f6381681b264d531812'),
    COLLECTION / 'RESULT.json': (750901, '56a33e26617f8abcdae1b4cf8dab59520753782407d0cee130124831df6fa374'),
    LAUNCH / 'receipt.json': (2939, '43d0581a893ac2ec1e478082f7897ac73c53e62673ad01ded885001694ef02d9'),
}


def require(value, message):
    if not value:
        raise ValueError(message)


def identity(path):
    require(path.is_file() and not path.is_symlink(), 'nonregular metadata path')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return {'bytes': path.stat().st_size, 'sha256': h.hexdigest()}


def main():
    OUT.mkdir(exist_ok=False)
    source = Path(__file__).read_bytes()
    (OUT / 'source.py').write_bytes(source)
    checked = {}
    for path, (size, digest) in EXPECTED.items():
        observed = identity(path)
        require(observed == {'bytes': size, 'sha256': digest}, 'known terminal input differs: ' + str(path))
        checked[str(path)] = observed
    collection = json.loads((COLLECTION / 'COLLECTION-RECEIPT.json').read_bytes())
    bootstrap = json.loads((LAUNCH / 'receipt.json').read_bytes())
    require(collection['metadata_collection_status'] == 'completed', 'collector incomplete')
    require(bootstrap['status'] == 'completed_metadata_collection', 'bootstrap incomplete')
    rows = []
    paths = [(p, 'collector-launch/' + str(p.relative_to(LAUNCH))) for p in sorted(LAUNCH.rglob('*')) if p.is_file()]
    paths += [(COLLECTION / name, 'postmortem/' + name) for name in
              ('COLLECTION-RECEIPT.json', 'SUMMARY.json', 'RESULT.json', 'ORIGINAL-MANIFEST.json')]
    paths += [(p, 'collector-source/' + p.name) for p in sorted(COLLECTION.glob('*.py'))]
    require(len(paths) == len({str(p) for p, _ in paths}) and len(paths) <= 24, 'metadata roster bound')
    for path, member in paths:
        item = identity(path)
        require(item['bytes'] <= 16777216, 'metadata file too large')
        rows.append({'path': str(path), 'member': member, **item})
    require(sum(row['bytes'] for row in rows) <= 67108864, 'metadata byte bound')
    require(all(identity(Path(row['path'])) == {k: row[k] for k in ('bytes', 'sha256')} for row in rows),
            'metadata changed during inventory')
    require(Path(__file__).read_bytes() == source, 'inventory source changed')
    result = {'schema': 'terminal-numerics-publication-input-inventory-v1', 'status': 'completed_read_only_inventory',
              'completed_utc': datetime.now(timezone.utc).isoformat(), 'receipt_inputs': rows,
              'known_input_identities': checked,
              'original_archive': {'path': str(COLLECTION.with_suffix('.zip')), **checked[str(COLLECTION.with_suffix('.zip'))]},
              'collection_receipt': str(COLLECTION / 'COLLECTION-RECEIPT.json'),
              'bootstrap_receipt': str(LAUNCH / 'receipt.json'),
              'source_identity': {'bytes': len(source), 'sha256': hashlib.sha256(source).hexdigest()},
              'wall_prefix_seconds': time.monotonic() - STARTED, 'CPU_prefix_seconds': time.process_time() - CPU,
              'peak_RSS_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
              'cost_scope': 'Metadata-only input hash and inventory. Outer GNU includes interpreter/imports; no original audit or collector CPU included.',
              'model_or_probability_array_deserializations': 0, 'original_files_modified': False,
              'original_audit_program_and_launch_retained_in_main_archive': ['program/', 'launch/', 'bootstrap/']}
    raw = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    (OUT / 'RESULT.json').write_bytes(raw)
    print(json.dumps({'result_path': str(OUT / 'RESULT.json'), 'result': {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()},
                      'inventory': result}), flush=True)


if __name__ == '__main__':
    main()
