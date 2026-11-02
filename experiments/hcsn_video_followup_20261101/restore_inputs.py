"""Restore only hash-bound development caches; never confirmation inputs."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASELINE = 'a793d55c23a7742378b081b162252da428a9fdb2'


def source_bytes(relative):
    path = ROOT / relative
    if path.exists():
        return path.read_bytes()
    return subprocess.check_output(['git', '-C', str(ROOT), 'show', BASELINE + ':' + relative])
HERE = Path(__file__).resolve().parent


class Parts(io.RawIOBase):
    def __init__(self, parts):
        self.parts = iter(parts)
        self.current = io.BytesIO()
        self.digest = hashlib.sha256()
        self.total = 0

    def readable(self):
        return True

    def readinto(self, buffer):
        while True:
            data = self.current.read(len(buffer))
            if data:
                buffer[:len(data)] = data
                return len(data)
            try:
                row = next(self.parts)
            except StopIteration:
                return 0
            data = source_bytes(row['path'])
            assert len(data) == row['bytes']
            assert hashlib.sha256(data).hexdigest() == row['sha256']
            self.digest.update(data)
            self.total += len(data)
            self.current = io.BytesIO(data)


def restore(manifest_path, parts_path, select, destination):
    manifest = json.loads(source_bytes(manifest_path))
    part_manifest = json.loads(source_bytes(parts_path))
    expected = {r['path']: r for r in manifest['files']}
    selected = {k: r for k, r in expected.items() if select(k)}
    stream = Parts(part_manifest['parts'])
    done = []
    with tarfile.open(fileobj=io.BufferedReader(stream), mode='r|gz') as archive:
        for member in archive:
            if member.name not in selected:
                continue
            row = selected[member.name]
            assert member.isfile() and member.size == row['bytes']
            data = archive.extractfile(member).read()
            assert hashlib.sha256(data).hexdigest() == row['sha256']
            target = HERE / 'inputs' / destination(member.name)
            assert target.resolve().is_relative_to((HERE / 'inputs').resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                assert target.read_bytes() == data
            else:
                with target.open('xb') as output:
                    output.write(data)
            done.append(dict(original=member.name, path=str(target.relative_to(HERE)), bytes=row['bytes'], sha256=row['sha256']))
    # All parts were validated as read. Drain bytes after tar EOF too.
    while stream.read(1024 * 1024):
        pass
    if 'archive_sha256' in part_manifest:
        assert stream.digest.hexdigest() == part_manifest['archive_sha256']
        assert stream.total == part_manifest['bytes']
    assert len(done) == len(selected)
    return done


def main():
    baseline = 'experiments/hcsn_four_stage_flow_20261031/artifacts/'
    addressed = 'experiments/hcsn_addressed_flow_20261101/artifacts/'
    records = restore(baseline + 'EVIDENCE_MANIFEST.json', baseline + 'PARTS.json',
        lambda p: p.endswith(('/results/avt_data/train.npz', '/results/avt_data/validation.npz')),
        lambda p: 'data/' + Path(p).name)
    records += restore(addressed + 'COMPLETE_EVIDENCE_MANIFEST.json', addressed + 'COMPLETE_EVIDENCE_MANIFEST.json',
        lambda p: '/results/av_features/' in p or '/results/av_mouth_features/' in p,
        lambda p: p.split('/results/', 1)[1])
    (HERE / 'INPUT_IDENTITY.json').write_text(json.dumps(dict(files=records,
        baseline_commit='a793d55c23a7742378b081b162252da428a9fdb2',
        scope='Only original train/validation arrays and fixed-prefix caches; no test, cross-cohort, or 1019 data restored'), indent=2) + '\n')
    print(json.dumps(dict(files=len(records), bytes=sum(r['bytes'] for r in records))))


if __name__ == '__main__':
    main()
