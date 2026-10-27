"""Archive completed evidence and verify every member by actual disk restore."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile


WORK = Path('/workspace/scratch/95988d8d3ab1')
ROOT = WORK/'ndu-evidence-v2'
AREA = Path(__file__).parent
ARCHIVE = WORK/'ndu_evidence_closure_v2_20261027.tar.gz'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    if ARCHIVE.exists():
        raise FileExistsError('Do not replace an existing raw evidence archive')
    reports = AREA/'results'
    shutil.copyfile(ROOT/'decision-development-001/INDEPENDENT_AUDIT.json', reports/'DEPLOYMENT_INDEPENDENT_AUDIT.json')
    shutil.copyfile(WORK/'ndu-evidence-v2-download.log', ROOT/'download.log')
    code = ROOT/'current_repository_source'
    code.mkdir(exist_ok=False)
    for path in AREA.iterdir():
        if path.is_file() and path.suffix in ('.py', '.md', '.json'):
            shutil.copyfile(path, code/path.name)
    shutil.copytree(reports, ROOT/'repository_results')
    description = {
        'scope': 'New2400AudioMNISTWAV, exact frozen observer, fitted observation laws and priors, immutable qualification and actual transcripts, historical protected-selector development, independent audits and executed source versions.',
        'historical_observer_input_dependency': {
            'archive': 'ndu_evidence_sources_20261027.tar.gz',
            'sha256': 'f765a8e6d28c1b95c9f03f9edb5d8790447037515c45c27e4755d726571f2f27',
            'library_file_id': 'libfile_32a94b74d9e48191b154cab8603fbea7',
            'note': 'Exact historical fit/validation observer JSON is copied into this archive. Reencoding the old4000WAV corpus depends on the separately preserved original archive.'},
        'joint_probe_raw_dependency': 'Probe media lives in ndu-direct-gradient-v2/probe-audit-001 and belongs in the separate joint-training archive; this evidence archive contains its source and summary receipt only.',
        'path_note': 'Executed research scripts retain the original workspace paths; frozen records can be inspected independently. Do not overwrite their original run directories when reproducing.',
        'qualification_reuse': 'The negative qualification21-32 is never reclassified as new validation or rescored under the protected selector.',
        'post_archive_receipts': 'Archive verification and upload receipts are generated afterward and bound separately in Git.'}
    (ROOT/'PACKAGE_README.json').write_text(json.dumps(description, indent=2, sort_keys=True)+'\n')
    files = sorted(path for path in ROOT.rglob('*') if path.is_file())
    if any(path.is_symlink() for path in ROOT.rglob('*')):
        raise ValueError('Raw evidence contains an unexpected symlink')
    inventory = [{'path': str(path.relative_to(ROOT)), 'bytes': path.stat().st_size, 'sha256': digest(path)} for path in files]
    manifest = ROOT/'PACKAGE_MANIFEST.json'
    manifest.write_text(json.dumps({'files': inventory, 'original_bytes': sum(row['bytes'] for row in inventory)},
                                   indent=2, sort_keys=True)+'\n')
    files.append(manifest)
    with tarfile.open(ARCHIVE, 'x:gz', compresslevel=6) as stream:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            info = tarfile.TarInfo('ndu-evidence-v2/'+relative)
            info.size, info.mode, info.mtime = path.stat().st_size, 0o644, 0
            with path.open('rb') as payload:
                stream.addfile(info, payload)
    expected = {row['path']: row for row in inventory}
    expected['PACKAGE_MANIFEST.json'] = {'bytes': manifest.stat().st_size, 'sha256': digest(manifest)}
    checked, restored_bytes = set(), 0
    with tempfile.TemporaryDirectory(prefix='ndu-evidence-v2-restore-', dir=WORK) as temporary:
        with tarfile.open(ARCHIVE, 'r:gz') as stream:
            for member in stream:
                path = PurePosixPath(member.name)
                if not member.isfile() or path.is_absolute() or '..' in path.parts or path.parts[0] != 'ndu-evidence-v2':
                    raise ValueError('Unexpected archive member')
                relative = '/'.join(path.parts[1:])
                if relative not in expected or relative in checked:
                    raise ValueError('Archive member census differs')
                target = Path(temporary)/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with stream.extractfile(member) as source, target.open('xb') as restored:
                    shutil.copyfileobj(source, restored)
                record = expected[relative]
                if target.stat().st_size != record['bytes'] or digest(target) != record['sha256']:
                    raise ValueError('Restored evidence bytes differ')
                restored_bytes += target.stat().st_size
                checked.add(relative)
                target.unlink()
    if checked != set(expected):
        raise ValueError('Archive omitted required evidence')
    receipt = {'schema': 'hepta.ndu.evidence-closure-archive.v2', 'archive_path': str(ARCHIVE),
               'archive_bytes': ARCHIVE.stat().st_size, 'archive_sha256': digest(ARCHIVE),
               'members': len(checked), 'restored_bytes': restored_bytes,
               'manifest_sha256': digest(manifest), 'every_member_written_reopened_hashed': True,
               'verification_storage': 'Each member was restored to its relative path, reopened and hashed, then the verified temporary duplicate was removed to bound disk use.',
               'upload_completed': False}
    (ROOT/'ARCHIVE_VALIDATION.json').write_text(json.dumps(receipt, indent=2, sort_keys=True)+'\n')
    (reports/'RAW_ARCHIVE.json').write_text(json.dumps(receipt, indent=2, sort_keys=True)+'\n')
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    main()
