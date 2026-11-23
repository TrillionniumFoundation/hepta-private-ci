"""Restore the fresh transfer study's original inputs from the committed evidence and publisher media."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ARTIFACTS = {
    'hcsn_intervention_value/evidence/records-04.zip': '2a95a37926871bec001a744e1e96caa549bf9faadcbcaea67e904c6919f6247c',
    'hcsn_intervention_value/evidence/records-07.zip': '183732c6893d929ec186e33992e9f62d15f95fc82e84c833c8672cdd1fc569b5',
    'hcsn_blocker_followup/evidence/locked_heads.zip': '3efff8e987a255d7f28de547bb7d488fcaf1e063539891f355ac4cb48c567fd0',
    'hcsn_blocker_followup/media/source_replay.zip': '4358f818d748ce69fc180ebcc8b228e55d0024ba8eb6432d224a2a52a3d428ce',
}
CAMERA_URL = 'https://download.pytorch.org/models/resnet18-f37072fd.pth'
PROTOCOL = '6936fe0348ba15653ee758d4aa0737d99557becee6b98fddcdbcb793c701f98f'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_hash(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def checked(path, expected):
    require(path.is_file() and file_hash(path) == expected, f'Missing or mismatched SHA-256: {path}')


def link_to(path, source):
    source = source.resolve(strict=True)
    if path.exists() or path.is_symlink():
        require(path.resolve(strict=True) == source, f'Existing path has another target: {path}')
    else:
        path.symlink_to(source, target_is_directory=source.is_dir())


def materialize(path, value, expected):
    require(hashlib.sha256(value).hexdigest() == expected, f'Archive member SHA-256 mismatch: {path.name}')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        checked(path, expected)
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        try:
            f.write(value)
            f.close()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def restore(work, protocol):
    q = REPO / 'qualification'
    for name, sha in ARTIFACTS.items():
        checked(q / name, sha)
    pins = protocol['frozen_sha256']
    checked(HERE / 'cohort.json', protocol['cohort_sha256'])
    plan = {
        'audio_gallery': ('hcsn_intervention_value/evidence/records-04.zip', 'primary/discovery/front_weights.json', 'discovery/front_weights.json'),
        'old_source_svd': ('hcsn_blocker_followup/evidence/locked_heads.zip', 'fit.json', 'selector/fit.json'),
        'old_bounded_edits': ('hcsn_blocker_followup/evidence/locked_heads.zip', 'edit_seal.json', 'selector/edit_seal.json'),
    }
    for name, digest in pins.items():
        if name.startswith('policies/'):
            plan[name] = ('hcsn_intervention_value/evidence/records-07.zip', 'primary/' + name, name)
        elif name.startswith('qualification/'):
            checked(REPO / name, digest)
    archives = sorted({entry[0] for entry in plan.values()})
    for archive in archives:
        with ZipFile(q / archive) as packaged:
            for name, (which, member, dest) in plan.items():
                if which == archive:
                    materialize(work / dest, packaged.read(member), pins[name])
    six = HERE.parent / 'purchase-attainability-20261123/train_only_seal.json'
    materialize(work / 'selector/train_only_six.json', six.read_bytes(), pins['train_only_six'])
    restored = set(plan) | {'train_only_six', 'camera'} | {key for key in pins if key.startswith('qualification/')}
    require(restored == set(pins), 'Unmapped frozen input in the protocol')
    print(f'Verified {len(plan)+1} frozen parameter or seal files and {len(ARTIFACTS)} source archives.')
    return pins['camera']


def originals(work, folders, fetch):
    sys.path.insert(0, str(REPO))
    from qualification.hcsn_intervention_value.media.acquire import acquire, digests
    cohort = json.loads((HERE / 'cohort.json').read_text())
    by_id = {r['pageid']: r for r in cohort['sources']}
    cache = work / 'media-cache'
    cache.mkdir(exist_ok=True)
    for pid in cohort['qualified_ids']:
        row = by_id[pid]
        name = str(pid) + Path(row['title']).suffix
        dest = cache / name
        if not dest.is_file():
            previous = next((folder / name for folder in folders if (folder / name).is_file()), None)
            if previous is not None:
                link_to(dest, previous)
            elif fetch:
                acquire(dict(row, split='test'), work, work / 'acquisition.jsonl')
            else:
                raise FileNotFoundError(f'Missing original {name}. Supply --originals or --fetch.')
        require(dest.stat().st_size == row['size'] and
                digests(dest) == [row['sha1'], row['source_sha256']], f'Publisher bytes mismatch: {dest}')
    print(f'Verified {len(cohort["qualified_ids"])} originals, {cohort["qualified_original_bytes"]:,} bytes.')


def camera(work, weights, expected, fetch):
    dest = work / 'resnet18.pth'
    if weights is not None:
        checked(weights, expected)
        link_to(dest, weights)
    elif not dest.exists() and fetch:
        with urlopen(CAMERA_URL, timeout=120) as response:
            materialize(dest, response.read(), expected)
    checked(dest, expected)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--work', type=Path, required=True, help='Replay directory outside the checkout')
    cli.add_argument('--originals', nargs='+', type=Path, default=[], help='Existing original media directories')
    cli.add_argument('--weights', type=Path, help='Local torchvision ImageNet-1K V1 ResNet-18 checkpoint')
    cli.add_argument('--fetch', action='store_true', help='Fetch missing originals and checkpoint from publishers')
    cli.add_argument('--parameters-only', action='store_true', help='Restore archived parameters and verify pinned code only')
    args = cli.parse_args()
    checked(HERE / 'protocol.json', PROTOCOL)
    protocol = json.loads((HERE / 'protocol.json').read_text())
    work = args.work.resolve()
    require(not work.is_relative_to(REPO), 'Pick a replay directory outside the checkout')
    work.mkdir(parents=True, exist_ok=True)
    link_to(work / 'trial', REPO)
    (work / 'scratch').mkdir(exist_ok=True)
    expected = restore(work, protocol)
    if not args.parameters_only:
        originals(work, args.originals, args.fetch)
        camera(work, args.weights, expected, args.fetch)
        print(f'Verified official ImageNet weights in {work}. Run the replay from this directory.')


if __name__ == '__main__':
    main()
