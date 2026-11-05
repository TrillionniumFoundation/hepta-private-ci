"""Cloud-only packaging. Never contacts Git, a desktop, or an authority service."""
from pathlib import Path, PurePosixPath
import argparse
import base64
import hashlib
import io
import json
import lzma
import shutil
import subprocess
import sys
import tarfile


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def info(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': sha(raw)}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def main(source):
    delivery = source / 'delivery'
    delivery.mkdir(exist_ok=False)
    stage = delivery / 'package-members'
    stage.mkdir()
    for folder in ('inputs', 'proof', 'rpc-prefix-suffix', 'scripts'):
        (stage / folder).mkdir()
    report = json.loads((source / 'verification.json').read_text())
    source_digests = {}
    for name in ('probe-plan.json', 'verification.json'):
        source_digests[name] = sha((source / name).read_bytes())
        shutil.copyfile(source / name, stage / 'proof' / name)
    for name in ('verify_transport_package.py', 'build_probe_delivery.py'):
        source_digests[name] = sha((source / name).read_bytes())
        shutil.copyfile(source / name, stage / 'scripts' / name)
    recipe = {'schema': 'exact-github-rpc-reconstruction-v1',
              'format': 'Original JSON prefix + exact JSON string token + original suffix, including final newline',
              'cases': []}
    for i, result in enumerate(report['results']):
        rpc_path = Path(result['rpc_file'])
        input_path = Path(result['readback_file'])
        assert rpc_path.parent == input_path.parent == source
        rpc = rpc_path.read_bytes()
        data = input_path.read_bytes()
        assert len(rpc) == result['rpc_bytes'] and sha(rpc) == result['rpc_sha256']
        assert len(data) == result['decoded_bytes'] and sha(data) == result['sha256']
        source_digests[rpc_path.name] = sha(rpc)
        source_digests[input_path.name] = sha(data)
        value = json.loads(rpc)['structuredContent']['content']
        token = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        assert rpc.count(token) == 1
        start = rpc.index(token)
        prefix, suffix = rpc[:start], rpc[start + len(token):]
        assert prefix + token + suffix == rpc
        name = result['case']
        prefix_name = 'rpc-prefix-suffix/' + name + '.prefix.bin'
        suffix_name = 'rpc-prefix-suffix/' + name + '.suffix.bin'
        (stage / prefix_name).write_bytes(prefix)
        (stage / suffix_name).write_bytes(suffix)
        input_name = 'inputs/' + input_path.name
        (stage / input_name).write_bytes(data)
        item = {'case': name, 'input_member': input_name, 'input_bytes': len(data),
                'input_sha256': sha(data), 'prefix_member': prefix_name,
                'suffix_member': suffix_name, 'original_rpc_name': rpc_path.name,
                'original_rpc_bytes': len(rpc), 'original_rpc_sha256': sha(rpc),
                'returned_content_characters': len(value)}
        if i == 0:
            encoded = base64.b64encode(data).decode('ascii')
            reproduced = '\n'.join(encoded[j:j + 60] for j in range(0, len(encoded), 60)) + '\n'
            assert reproduced == value
            item.update(transform='base64-wrapped', wrap_columns=60,
                        newline='\n', trailing_newline=True)
        else:
            assert data.decode('utf-8') == value
            item['transform'] = 'utf-8'
        recipe['cases'].append(item)
    write_json(stage / 'rpc-reconstruction.json', recipe)
    (stage / 'README.txt').write_text(
        'READ-ONLY GIT BYTE TRANSPORT PROBE\n\n'
        'Exact repository: TrillionniumFoundation/hepta-private-ci\n'
        'Exact evidence head: 571c3da959bcbcca6639a5882d49aebadd00bff2\n'
        'Actual successes: binary 1,044,516 bytes via fetch_file encoding=base64;\n'
        'UTF-8 2,812,928 bytes via fetch_blob. Both match size, SHA256, and Git blob SHA.\n'
        'No 5.6 MiB text was tested. These two successes are not a maximum API limit.\n'
        'No desktop request, Git object creation, push, ref/PR mutation, or authentication change.\n\n'
        'The original RPC files remain intact at the source. This archive stores each actual\n'
        'readback once plus byte-exact RPC prefixes/suffixes and a validated payload codec.\n'
        'Run: python3 -B scripts/verify_transport_package.py --root . --reconstruct-dir ../rpc-restored\n'
        'Every member and both reconstructed RPCs are checked before success.\n'
    )
    members = [{'path': str(p.relative_to(stage)), 'bytes': p.stat().st_size,
                'sha256': sha(p.read_bytes())} for p in sorted(stage.rglob('*')) if p.is_file()]
    manifest = {'schema': 'git-transport-probe-member-manifest-v1', 'members': members,
                'manifest_self_hash': 'Bound externally by the delivery manifest/archive digest.'}
    write_json(stage / 'MANIFEST.json', manifest)
    archive = delivery / 'git-transport-probe-571c.tar.xz'
    with lzma.open(archive, 'xb', preset=6) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.USTAR_FORMAT) as tar:
            for path in sorted(stage.rglob('*')):
                if not path.is_file():
                    continue
                raw = path.read_bytes()
                entry = tarfile.TarInfo(str(path.relative_to(stage)))
                entry.size = len(raw)
                entry.mode = 0o644
                entry.mtime = 0
                entry.uid = entry.gid = 0
                entry.uname = entry.gname = ''
                tar.addfile(entry, io.BytesIO(raw))
    extracted = delivery / 'roundtrip-extracted'
    extracted.mkdir()
    extracted_members = []
    with tarfile.open(archive, 'r:xz') as tar:
        seen = set()
        for entry in tar:
            relative = PurePosixPath(entry.name)
            assert entry.isfile() and not relative.is_absolute() and '..' not in relative.parts
            assert entry.name not in seen
            seen.add(entry.name)
            raw = tar.extractfile(entry).read()
            assert len(raw) == entry.size
            expected = stage.joinpath(*relative.parts).read_bytes()
            assert raw == expected
            path = extracted.joinpath(*relative.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(raw)
            extracted_members.append({'path': entry.name, 'bytes': len(raw), 'sha256': sha(raw)})
    assert seen == {m['path'] for m in members} | {'MANIFEST.json'}
    verify = subprocess.run([sys.executable, '-B', str(extracted / 'scripts/verify_transport_package.py'),
                             '--root', str(extracted), '--reconstruct-dir', str(delivery / 'reconstructed-rpcs')],
                            capture_output=True, check=False, timeout=30)
    (delivery / 'verify.stdout.log').write_bytes(verify.stdout)
    (delivery / 'verify.stderr.log').write_bytes(verify.stderr)
    assert verify.returncode == 0, verify.stderr.decode(errors='replace')
    verified = json.loads(verify.stdout)
    for result in report['results']:
        original = Path(result['rpc_file'])
        rebuilt = delivery / 'reconstructed-rpcs' / original.name
        assert original.read_bytes() == rebuilt.read_bytes()
    for name, before in source_digests.items():
        assert sha((source / name).read_bytes()) == before
    roundtrip = {'status': 'PASS', 'archive': info(archive),
                 'all_tar_members_exactly_equal_before_and_after': True,
                 'members': extracted_members, 'verifier': verified,
                 'reconstructed_rpcs_byte_for_byte_equal_originals': True,
                 'original_files_unchanged': source_digests,
                 'scope': 'Cloud-only packaging/reconstruction, not a new Git transport test.'}
    write_json(delivery / 'roundtrip-report.json', roundtrip)
    chunks = []
    parts = delivery / 'transport-parts'
    parts.mkdir()
    with archive.open('rb') as stream:
        offset = 0
        while True:
            raw = stream.read(1000000)
            if not raw:
                break
            path = parts / ('git-transport-probe-571c.tar.xz.part-' + str(len(chunks)).zfill(4))
            path.write_bytes(raw)
            chunks.append({'path': str(path), 'offset': offset, 'bytes': len(raw),
                           'sha256': sha(raw),
                           'git_blob_sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()})
            offset += len(raw)
    assert b''.join(Path(c['path']).read_bytes() for c in chunks) == archive.read_bytes()
    delivery_manifest = {
        'schema': 'git-transport-probe-small-artifact-delivery-v1', 'status': 'VERIFIED_CLOUD_PACKAGE',
        'archive': info(archive), 'archive_member_manifest': info(stage / 'MANIFEST.json'),
        'roundtrip_report': info(delivery / 'roundtrip-report.json'),
        'verify_stdout': info(delivery / 'verify.stdout.log'), 'verify_stderr': info(delivery / 'verify.stderr.log'),
        'tar_member_count': len(extracted_members), 'transport_chunks': chunks,
        'transport_chunk_target_bytes': 1000000,
        'transport_chunk_scope': 'Local transport preparation only; these newly made chunks have not been uploaded/read back from Git.',
        'actual_git_probe_successes': {'binary_bytes': 1044516, 'utf8_bytes': 2812928},
        'no_5_6_mib_text_test': True, 'raw_originals_deleted': False,
        'git_writes': 0, 'desktop_requests': 0, 'push_authorization': False,
    }
    write_json(delivery / 'delivery-manifest.json', delivery_manifest)
    print(json.dumps({'delivery': info(delivery / 'delivery-manifest.json'),
                      'archive': info(archive), 'members': len(extracted_members),
                      'roundtrip': 'PASS', 'transport_chunks': chunks}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, required=True)
    args = parser.parse_args()
    main(args.source_root.resolve())
