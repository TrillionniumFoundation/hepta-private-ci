"""V19 exact physical archived-data admission; audit only, no original text output.

The archive is a historical source candidate, NOT an independent publisher
signature, task correctness label, live model authority or proof of new inference.
Never put private raw source, old model tensors or unredacted answers in Git.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import stat
import tarfile
import zipfile

SCHEMA = 'hepta.stem.v19.original-source-archive-byte-admission.shadow.v1'
ARTIFACT_ID = 11586991191
ARTIFACT_SHA256 = '07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af'
PAYLOAD = 'memory-inputs.tar.gz'
MAX_ZIP_BYTES = 420_000_000
MAX_MEMBER_BYTES = 330_000_000
MAX_EXPANDED_BYTES = 850_000_000
MAX_MEMBERS = 100
READ_SIZE = 1024 * 1024
EXPECTED = {
    'memory-inputs/reader/model.safetensors': ('5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c', 269060552),
    'memory-inputs/reader/config.json': ('8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a', 861),
    'memory-inputs/reader/tokenizer.json': ('9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c', 2104556),
    'memory-inputs/locomo.json': ('79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4', 2805274),
}


def sha_file(path: Path) -> str:
    h = sha256()
    with path.open('rb') as inp:
        for block in iter(lambda: inp.read(READ_SIZE), b''):
            h.update(block)
    return h.hexdigest()


def safe_path(name: str) -> bool:
    if name == 'memory-inputs':
        return True  # one inert root directory in the original tar
    if type(name) is not str or not name.startswith('memory-inputs/'):
        return False
    p = PurePosixPath(name)
    return (not p.is_absolute() and '\\' not in name and '\x00' not in name
            and all(segment not in ('', '.', '..') for segment in name.rstrip('/').split('/')))


def audit_archive(path, expected_zip_sha=ARTIFACT_SHA256, expected_files=EXPECTED):
    """Stream every original tar member; never extract, execute, or emit raw bytes."""
    p = Path(path)
    if (p.is_symlink() or not p.is_file() or not stat.S_ISREG(p.stat().st_mode)
        or not 0 < p.stat().st_size <= MAX_ZIP_BYTES):
        raise ValueError('original archive missing, symbolic or unbounded')
    zip_digest = sha_file(p)
    if zip_digest != expected_zip_sha:
        raise ValueError('frozen original GitHub artifact bytes changed')
    files = {}
    seen = set()
    count = total = 0
    with zipfile.ZipFile(p, 'r') as z:
        entries = z.infolist()
        if len(entries) != 1 or entries[0].filename != PAYLOAD or entries[0].is_dir():
            raise ValueError('unsupported outer source archive layout')
        if not 0 < entries[0].file_size <= MAX_ZIP_BYTES:
            raise ValueError('unsupported source tar payload size')
        with z.open(entries[0], 'r') as binary:
            with tarfile.open(fileobj=binary, mode='r|gz') as t:
                for member in t:
                    if not safe_path(member.name) or member.name in seen:
                        raise ValueError('duplicate, traversing or unrecognized member')
                    seen.add(member.name)
                    count += 1
                    if count > MAX_MEMBERS:
                        raise ValueError('unbounded inner tar member count')
                    if member.isdir():
                        if member.size != 0:
                            raise ValueError('nonempty tar directory')
                        continue
                    if not member.isfile() or not 0 < member.size <= MAX_MEMBER_BYTES:
                        # 0-byte lock files in the original archive are explicitly
                        # allowed only as regular files with zero size.
                        if not member.isfile() or member.size != 0:
                            raise ValueError('unsafe original tar member type/size')
                    total += member.size
                    if total > MAX_EXPANDED_BYTES:
                        raise ValueError('original archive expansion ceiling reached')
                    stream = t.extractfile(member)
                    if stream is None:
                        raise ValueError('original tar member absent')
                    h = sha256()
                    actual_bytes = 0
                    while chunk := stream.read(READ_SIZE):
                        actual_bytes += len(chunk)
                        if actual_bytes > member.size:
                            raise ValueError('original tar size mismatch')
                        if member.name in expected_files:
                            h.update(chunk)
                    if actual_bytes != member.size:
                        raise ValueError('original member unexpectedly truncated')
                    if member.name in expected_files:
                        want_sha, want_len = expected_files[member.name]
                        if member.size != want_len or h.hexdigest() != want_sha:
                            raise ValueError('pinned original source/model differs: ' + member.name)
                        files[member.name] = {'sha256': want_sha, 'bytes': want_len}
    if set(files) != set(expected_files):
        raise ValueError('incomplete original source/model identity inventory')
    return {'schema': SCHEMA,
            'original_github_artifact_id': ARTIFACT_ID,
            'original_zip_sha256': zip_digest,
            'checked_files': {x: files[x] for x in sorted(files)},
            'tar_member_count': count,
            'tar_total_expanded_bytes': total,
            'private_text_or_model_weights_exported': False,
            'new_model_forward_executed': False,
            'independently_human_verified': False,
            'stronger_reference_reader_executed': False,
            'cell_split_authorized': False,
            'production_authorized': False,
            'decision': 'ARCHIVED_PHYSICAL_SOURCE_BYTES_ONLY_HOLD_NO_GO'}


def verify_sanitized_result(report):
    """Fail closed on any published ability/authority or altered archive census.

    This verifies a *descriptive receipt* against the pinned archived profile;
    it does not independently reread the ZIP on the hosted source-only CI.
    """
    expected = {'schema', 'original_github_artifact_id', 'original_zip_sha256',
                'checked_files', 'tar_member_count', 'tar_total_expanded_bytes',
                'private_text_or_model_weights_exported', 'new_model_forward_executed',
                'independently_human_verified', 'stronger_reference_reader_executed',
                'cell_split_authorized', 'production_authorized', 'decision'}
    if type(report) is not dict or set(report) != expected:
        raise ValueError('archive receipt unsupported fields')
    if (report['schema'] != SCHEMA or report['original_github_artifact_id'] != ARTIFACT_ID
        or report['original_zip_sha256'] != ARTIFACT_SHA256
        or report['tar_member_count'] != 56
        or report['tar_total_expanded_bytes'] != 644195777
        or report['decision'] != 'ARCHIVED_PHYSICAL_SOURCE_BYTES_ONLY_HOLD_NO_GO'):
        raise ValueError('original archived byte census or posture changed')
    filelist = {name: {'sha256': sh, 'bytes': size}
                for name, (sh, size) in EXPECTED.items()}
    if report['checked_files'] != filelist:
        raise ValueError('original pinned file census changed')
    flags = ('private_text_or_model_weights_exported', 'new_model_forward_executed',
             'independently_human_verified', 'stronger_reference_reader_executed',
             'cell_split_authorized', 'production_authorized')
    if any(report[k] is not False for k in flags):
        raise ValueError('fabricated inference, independent review or authority')
    return {'status':'PHYSICAL_ARCHIVE_DIGEST_REPORT_CONSISTENT_NO_GO',
            'archived_model_forward_reexecuted_by_this_test':False,
            'production_authorized':False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--original-zip')
    parser.add_argument('--public-receipt')
    parser.add_argument('--out', help='Create-only local digest-only result; never writes corpus content')
    a = parser.parse_args()
    if bool(a.original_zip) == bool(a.public_receipt):
        raise ValueError('choose exactly one: physical archive or sanitized receipt')
    if a.public_receipt:
        result = json.loads(Path(a.public_receipt).read_text())
        print(json.dumps(verify_sanitized_result(result), sort_keys=True))
        return
    result = audit_archive(a.original_zip)
    if a.out:
        from v17_reference_reader_physical import write_private
        write_private(a.out, result)
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))

if __name__ == '__main__':
    main()
