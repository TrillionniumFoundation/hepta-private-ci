"""New capture identities and pinned AudioMNIST qualification sources."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import uuid

from .blocks import Capture


ROOT = Path('/workspace/scratch/95988d8d3ab1/ndu-evidence-v2')
SOURCE = ROOT / 'source'
REVISION = '630d7dab4c040882834de6fa21baf9a60372accd'
SOURCE_ID = 'https://github.com/soerenab/AudioMNIST@' + REVISION
SPEAKERS = tuple(f'{number:02}' for number in range(21, 33))
CHECKPOINT = Path('/workspace/scratch/95988d8d3ab1/ndu-continuation-evidence/observer.pt')
CHECKPOINT_SHA = '6c5391e2ea0ee6102977992cb14ebcee857e393a7c9c66b8b534c78951356e86'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def download():
    SOURCE.mkdir(parents=True, exist_ok=True)
    names = ['README.md', 'LICENSE'] + [f'data/{speaker}/{digit}_{speaker}_{index}.wav'
        for speaker in SPEAKERS for digit in range(10) for index in range(20)]
    failure_path = ROOT / 'DOWNLOAD_ATTEMPTS.jsonl'

    def one(name):
        path = SOURCE/name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            for attempt in range(5):
                try:
                    url = f'https://raw.githubusercontent.com/soerenab/AudioMNIST/{REVISION}/{name}'
                    with urllib.request.urlopen(url, timeout=45) as response:
                        payload = response.read()
                    if name.endswith('.wav') and payload[:4] != b'RIFF':
                        raise ValueError('Expected real RIFF audio')
                    temporary = path.with_suffix(path.suffix+'.partial')
                    temporary.write_bytes(payload)
                    temporary.replace(path)
                    break
                except Exception as error:
                    with failure_path.open('a') as stream:
                        stream.write(json.dumps({'path': name, 'attempt': attempt,
                                                'error': repr(error), 'time_ns': time.time_ns()})+'\n')
                    if attempt == 4:
                        raise
                    time.sleep(min(attempt+1, 4))
        return {'path': name, 'bytes': path.stat().st_size, 'sha256': digest(path)}

    rows = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for row in pool.map(one, names):
            rows.append(row)
            if len(rows) % 400 == 0:
                print(json.dumps({'files': len(rows), 'bytes': sum(r['bytes'] for r in rows)}), flush=True)
    wavs = [row for row in rows if row['path'].endswith('.wav')]
    old = json.loads(Path('/workspace/scratch/95988d8d3ab1/ndu-continuation-evidence/source/SOURCE_MANIFEST.json').read_text())
    old_hashes = {row['sha256'] for row in old['files']}
    if len({r['sha256'] for r in wavs}) != len(wavs) or old_hashes & {r['sha256'] for r in wavs}:
        raise ValueError('Qualification sources collide with each other or prior sources')
    manifest = {'source_id': SOURCE_ID, 'roles': {'test': list(SPEAKERS)}, 'files': rows,
                'prior_source_manifest_sha256': digest('/workspace/scratch/95988d8d3ab1/ndu-continuation-evidence/source/SOURCE_MANIFEST.json'),
                'old_source_hash_overlap': 0, 'model_features_computed': False,
                'created_ns': time.time_ns(), 'bytes': sum(row['bytes'] for row in rows)}
    write(SOURCE/'SOURCE_MANIFEST.json', manifest)
    return manifest


def observe():
    import numpy as np
    import torch
    from .encoder import DigitObserver, features

    if digest(CHECKPOINT) != CHECKPOINT_SHA:
        raise ValueError('Frozen observer identity mismatch')
    manifest = json.loads((SOURCE/'SOURCE_MANIFEST.json').read_text())
    inventory = {row['path']: row for row in manifest['files']}
    registry = json.loads((SOURCE/'CAPTURE_REGISTRY.json').read_text())
    torch.set_num_threads(1)
    model = DigitObserver().eval().requires_grad_(False)
    model.load_state_dict(torch.load(CHECKPOINT, map_location='cpu', weights_only=True))
    rows = []
    with torch.inference_mode():
        for speaker in SPEAKERS:
            names = [f'data/{speaker}/{digit}_{speaker}_{index}.wav' for digit in range(10) for index in range(20)]
            tensor = torch.stack([features(SOURCE/name) for name in names])
            probabilities = torch.cat([model(chunk).softmax(-1) for chunk in tensor.split(64)]).double().numpy()
            for name, probability in zip(names, probabilities):
                content = digest(SOURCE/name)
                if content != inventory[name]['sha256']:
                    raise ValueError('Source content changed after custody')
                capture = Capture(SOURCE_ID, registry[name]['opaque_acquisition'], content)
                if capture.event_id != registry[name]['event_id']:
                    raise ValueError('Acquisition registry changed')
                digit, _, index = Path(name).stem.split('_')
                views = np.argsort(-probability, kind='stable')[:2].tolist()
                rows.append({'source_path': name, 'speaker': speaker, 'target': int(digit),
                             'index': int(index), 'capture': vars(capture), 'event_id': capture.event_id,
                             'content_sha256': content, 'observation': views[0], 'rank_views': views,
                             'probabilities': probability.tolist()})
    return rows


def make_capture_registry():
    path = SOURCE/'CAPTURE_REGISTRY.json'
    manifest = json.loads((SOURCE/'SOURCE_MANIFEST.json').read_text())
    if not path.exists():
        records = {}
        for row in manifest['files']:
            if row['path'].endswith('.wav'):
                acquisition = uuid.uuid4().hex
                record = Capture(SOURCE_ID, acquisition, row['sha256'])
                records[row['path']] = {'opaque_acquisition': acquisition, 'event_id': record.event_id,
                                        'content_sha256': row['sha256']}
        write(path, records)
    return path


if __name__ == '__main__':
    result = download()
    print(json.dumps({'complete': True, 'files': len(result['files']), 'bytes': result['bytes']}))
