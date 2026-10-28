"""Create the deterministic, training-only portable seed for the registered pilot."""
import argparse
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

from .registration import digest, load_registration

HERE = Path(__file__).parent
REPO = HERE.parents[3]


def build(assets, registration_path):
    registration = load_registration(registration_path, assets)
    if registration['mechanism_events'] != 43 or len(registration['mechanism_source_ids']) != 8:
        raise ValueError('Unexpected fixed mechanism budget')
    destination = HERE / 'ci'
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'seed').mkdir()
    (destination / 'REGISTRATION.json').write_bytes(registration_path.read_bytes())
    files = {'SOURCE_PROTOCOL.json': assets / 'SOURCE_PROTOCOL.json'}
    for sid in registration['mechanism_source_ids']:
        for name in ['RECEIPT.json', 'FEATURES.npz']:
            relative = 'prepared/observer_train/' + sid + '/' + name
            files[relative] = assets / relative
    for name in ['ACQUISITION.json', 'TSM_ACQUISITION.json', 'pann_LICENSE.MIT', 'tsm_LICENSE',
                 'torchvision_LICENSE', 'perception_README.md', 'sthv2_label_map.txt']:
        files['pretrained/' + name] = assets / 'pretrained' / name
    members = []
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', compresslevel=9, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as archive:
            for name, path in sorted(files.items()):
                data = path.read_bytes()
                member = tarfile.TarInfo(name)
                member.size = len(data)
                member.mode = 0o644
                member.mtime = 0
                archive.addfile(member, io.BytesIO(data))
                members.append({'path': name, 'bytes': len(data), 'sha256': digest(data)})
    payload = buffer.getvalue()
    encoded = base64.b64encode(payload).decode('ascii')
    parts = []
    for offset in range(0, len(encoded), 38000):
        number = len(parts) + 1
        name = f'seed/part-{number:03d}.jsonl'
        data = (json.dumps({'part': number, 'base64': encoded[offset:offset+38000]},
                           separators=(',', ':')) + '\n').encode()
        (destination / name).write_bytes(data)
        parts.append({'part': number, 'path': 'ci/' + name, 'bytes': len(data), 'sha256': digest(data)})
    acquisitions = [json.loads((assets / 'pretrained' / name).read_text())
                    for name in ('ACQUISITION.json', 'TSM_ACQUISITION.json')]
    weights = [row for record in acquisitions for row in record['receipts'] if row['name'].endswith('.pth')]
    names = ['.github/workflows/ndu-natural-observer-v4.yml']
    prefix = 'experiments/multimodal_output_portfolio/closure_20261028/'
    names += [prefix + 'semantic_top1_v4/' + name for name in ('ci_pilot.py', 'ci_tests.py', 'seed_pack.py', 'ci_runtime.py', 'ci_runtime_tests.py', 'ci_mechanism.py')]
    names += [prefix + 'semantic_LICENSES.md', prefix + 'data_source_usage_register.json']
    for name in registration['implementation_sha256']:
        names.append(str((HERE.parent / name).resolve().relative_to(REPO)))
    pins = {name: digest((REPO / name).read_bytes()) for name in sorted(set(names))}
    pip = ['{python}', '-m', 'pip', 'install', '--disable-pip-version-check', '--only-binary=:all:']
    manifest = {
        'schema': 'hepta.closure.top1-v4-portable-ci-pilot.v1',
        'registration_sha256': registration['registration_sha256'],
        'registration_file_sha256': digest(registration_path.read_bytes()),
        'source_ids': registration['mechanism_source_ids'], 'maximum_sources': 8, 'maximum_events': 43,
        'training_updates': 0, 'holdout_sources': 0, 'fit_or_select_models': False,
        'maximum_wall_seconds': 1800,
        'wall_budget_limits': 'External socket and process cleanup can overrun a nominal timeout; retain failures and actual cost. No physical-CPU tail bound is claimed.',
        'initial_headroom_minimum_bytes': registration['specification']['budget']['initial_process_headroom_minimum_bytes'],
        'initial_free_disk_minimum_bytes': 3000000000,
        'dependency_commands': [
            ['install-numeric', pip + ['--report', '{output}/install-numeric-report.json',
                'numpy==2.3.5', 'scipy==1.17.0', 'Pillow==12.3.0']],
            ['install-torch', pip + ['--index-url', 'https://download.pytorch.org/whl/cpu',
                '--report', '{output}/install-torch-report.json', 'torch==2.8.0+cpu', 'torchvision==0.23.0+cpu']],
        ],
        'weights': weights, 'weight_bytes': sum(row['bytes'] for row in weights),
        'seed': {'format': 'Deterministic gzip of regular tar members, carried as ordered JSON Lines base64 records to keep each reviewed Git object below40000bytes.',
                 'bytes': len(payload), 'sha256': digest(payload), 'parts': parts, 'members': members,
                 'unpacked_bytes': sum(row['bytes'] for row in members),
                 'maximum_member_bytes': max(row['bytes'] for row in members)},
        'implementation_sha256': pins,
        'evidence': 'Preserve all43 actual four-file bundles and reopened features, original source hashes, partial failure evidence, resource observations, and self+children CPU. Input seed and official weights are exactly recoverable and excluded from the result artifact.',
        'claim': 'Training-source feature/codec/resource mechanism only. A pass does not establish observer accuracy, generator quality, fresh adequacy, policy value or qualification.',
    }
    manifest['pilot_sha256'] = digest(manifest)
    with (destination / 'PILOT.json').open('x') as stream:
        stream.write(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets', required=True, type=Path)
    parser.add_argument('--registration', required=True, type=Path)
    args = parser.parse_args()
    value = build(args.assets, args.registration)
    print(json.dumps({'pilot_sha256': value['pilot_sha256'], 'seed_bytes': value['seed']['bytes'],
                      'seed_parts': len(value['seed']['parts']), 'seed_members': len(value['seed']['members'])}))
