"""Deterministic, per-attempt evidence archives after both test stages finish."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile


def pack(root, target, paths):
    entries = []
    with target.open('xb') as raw:
        with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w') as archive:
                for path in sorted(set(paths)):
                    if not path.is_file() or '__pycache__' in path.parts:
                        continue
                    data = path.read_bytes()
                    name = path.relative_to(root).as_posix()
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = len(data), 0o644
                    archive.addfile(info, io.BytesIO(data))
                    entries.append({'path': name, 'bytes': len(data),
                                    'sha256': hashlib.sha256(data).hexdigest()})
    return {'file': target.name, 'bytes': target.stat().st_size,
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'entries': entries}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-root', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root, output = Path(args.run_root).resolve(), Path(args.output)
    completed = json.loads((root / 'FINAL_STAGE_RECEIPT.json').read_text())
    if len(completed['rows']) != 10 or not all(r['returncode'] == 0 for r in completed['rows']):
        raise ValueError('all ten final evaluation workers must finish before packing')
    p = json.loads((root / 'PROTOCOL_FROZEN.json').read_text())
    output.mkdir(parents=True, exist_ok=False)
    records, covered = [], set()
    for section, names in (
            ('training', [f'n{n}-{a["id"]}-s{s}' for n in p['independent_neurons']
                          for a in p['arms'] for s in p['seeds']]),
            ('adaptation', [f'n{n}-qvi_full-s{s}' for n in p['independent_neurons'] for s in p['seeds']])):
        for name in names:
            directory = root / section / name
            paths = [x for x in directory.rglob('*') if x.is_file()]
            log = root / section / (name + '.worker.log')
            if log.exists():
                paths.append(log)
            if not paths:
                raise ValueError('missing declared attempt: ' + name)
            records.append(pack(root, output / (section + '--' + name + '.tar.gz'), paths))
            covered.update(paths)
    remaining = [x for x in root.rglob('*') if x.is_file() and x not in covered
                 and '__pycache__' not in x.parts and output not in x.parents]
    records.append(pack(root, output / 'run-metadata-and-source.tar.gz', remaining))
    index = {'schema': 1, 'experiment_id': p['experiment_id'],
             'format': 'deterministic gzip/tar, relative paths rooted at the immutable run',
             'files': records, 'archive_count': len(records),
             'total_compressed_bytes': sum(r['bytes'] for r in records),
             'complete': '72 training attempts, 9 five-method adaptations, all predictions/checkpoints/logs and frozen sources'}
    with (output / 'ARCHIVE_INDEX.json').open('x') as handle:
        json.dump(index, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'archives': len(records), 'compressed_bytes': index['total_compressed_bytes'],
                      'largest_archive_bytes': max(r['bytes'] for r in records)}))


if __name__ == '__main__':
    main()
