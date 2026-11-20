"""Independently verify dbd6 cloud archive and both lossless publication maps."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import tarfile

ROOT = Path(__file__).resolve().parent.parent
HOST = ROOT / 'e6_diagnostic_host_archive_readback_1/publication-1'
CLOUD = ROOT / 'e6_diagnostic_cloud_archive_1/pack-2-actual-host-closure'
OUT = ROOT / 'metrics_integration/dbd6-archive-intake-1'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def oid(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def read_json(path):
    return json.loads(path.read_bytes())


def safe(name):
    p = PurePosixPath(name)
    return not p.is_absolute() and '..' not in p.parts and '\x00' not in name


def verified_file(row, bounded=True):
    assert safe(row['path']) and row['mode'] == '100644'
    p = Path(row['local_path'])
    assert p.is_file() and not p.is_symlink()
    data = p.read_bytes()
    assert len(data) == row['bytes'] and sha(data) == row['sha256'] and oid(data) == row['git_blob']
    if bounded:
        assert len(data) <= 480000
    return data


def restore(rep, visited):
    if rep['encoding'] == 'identity':
        row = rep['file']
        visited[row['path']] = row
        return verified_file(row)
    assert rep['encoding'] == 'exact-byte-parts'
    descriptor = json.loads(restore(rep['descriptor'], visited))
    assert descriptor['schema'] == 'hepta.exact-byte-parts.v2' and descriptor['max_part_bytes'] == 480000
    original = rep['original']
    for key, value in descriptor['original'].items():
        assert original[key] == value
    parts = descriptor['parts']
    assert len({p['file']['path'] for p in parts}) == len(parts)
    combined = bytearray()
    for i, part in enumerate(parts):
        assert part['ordinal'] == i and part['offset'] == len(combined)
        row = part['file']
        combined.extend(verified_file(row))
        visited[row['path']] = row
    assert bytes(combined) == verified_file(original, bounded=False)
    return bytes(combined)


def main():
    assert not OUT.exists()
    OUT.mkdir()
    host_map_bytes = (HOST / 'PUBLICATION_FILES.json').read_bytes()
    cloud_map_bytes = (CLOUD / 'PUBLICATION_FILES.json').read_bytes()
    assert sha(host_map_bytes) == '419139ea01abe7cf73e1b8c5412b35b853c7284ff43e6432abae78d18227f88c'
    assert sha(cloud_map_bytes) == '1168606a166f416d98ee80239eb81e239fffbcad9e3e0dea422691ee72bfe184'
    host_map = json.loads(host_map_bytes)
    cloud_map = json.loads(cloud_map_bytes)
    result_bytes = (CLOUD / 'RESULT.json').read_bytes()
    assert sha(result_bytes) == '8f9e347a136d2f9cba0e26c0a35fa3dca41392b421acdb19c781189cb294acbe'
    result = json.loads(result_bytes)
    assert result['successful'] and result['status'] == 'ARCHIVE_AND_PUBLICATION_PREPARATION_FULLY_VERIFIED'
    assert verified_file(cloud_map['required_result']) == result_bytes
    plan_bytes = (CLOUD / 'PLAN.json').read_bytes()
    assert sha(plan_bytes) == result['plan_sha256'] == 'ee4bcbbab7d0879baa7bb1a0737c2db29389d10dd210cff938099b0855f6be14'
    plan = json.loads(plan_bytes)
    manifest_bytes = (CLOUD / 'MANIFEST.json').read_bytes()
    assert sha(manifest_bytes) == result['manifest_sha256']
    manifest = json.loads(manifest_bytes)
    parts = read_json(CLOUD / 'archive-parts.json')
    combined = bytearray()
    for i, part in enumerate(parts['parts']):
        assert part['name'] == f'cloud-dbd6-originals.tar.xz.part-{i:03d}' and part['offset'] == len(combined)
        data = (CLOUD / part['name']).read_bytes()
        assert len(data) == part['bytes'] <= 480000 and sha(data) == part['sha256']
        combined.extend(data)
    assert len(parts['parts']) == result['part_count'] == 13
    assert len(combined) == result['archive_bytes'] == 6030300
    assert sha(combined) == result['archive_sha256'] == '6b1d709e94e6ac725e0311fa718ebb00f1cab9e82eaed0ac8f5b6656c3213ab8'
    archive_path = CLOUD / parts['archive_name']
    assert archive_path.read_bytes() == combined
    expected = {r['member']: r for r in plan['included']}
    assert len(expected) == 1221 and sum(r['bytes'] for r in expected.values()) == 37093020
    rpc = {r['member'] for r in plan['rpc_index']}
    assert len(rpc) == 169 and rpc <= set(expected)
    originals_checked = 0
    with tarfile.open(archive_path, 'r:xz') as archive:
        members = archive.getmembers()
        assert len(members) == len({m.name for m in members}) == 1225
        assert all(m.isfile() and safe(m.name) for m in members)
        assert {m.name for m in members} == set(expected) | {'MANIFEST.json', 'PLAN.json', 'RPC_INDEX.json', 'EXCLUDED_METADATA.json'}
        for member in members:
            with archive.extractfile(member) as stream:
                data = stream.read()
            assert len(data) == member.size
            if member.name in expected:
                row = expected[member.name]
                assert len(data) == row['bytes'] and sha(data) == row['sha256'] and oid(data) == row['git_blob_oid']
                assert data == Path(row['original_path']).read_bytes()
                originals_checked += 1
            else:
                assert data == (CLOUD / member.name).read_bytes()
    assert originals_checked == result['original_members'] == 1221
    assert {(r['member'], r['bytes'], r['sha256']) for r in manifest['originals']} == {
        (r['member'], r['bytes'], r['sha256']) for r in expected.values()}
    rows = []
    for mapping, count, total in [(host_map, 96, 10825262), (cloud_map, 34, 8481669)]:
        assert mapping['file_count'] == len(mapping['files']) == count
        assert sum(r['bytes'] for r in mapping['files']) == mapping['total_bytes'] == total
        for row in mapping['files']:
            verified_file(row)
            rows.append(row)
    host_visited = {}
    host_reps = read_json(HOST / 'REPRESENTATIONS.json')
    for rep in host_reps['representations']:
        restore(rep, host_visited)
    restore(host_map['representation_index'], host_visited)
    assert set(host_visited) <= {r['path'] for r in host_map['files']}
    cloud_visited = {}
    metadata_index = json.loads(restore(cloud_map['metadata_reassembly_index'], cloud_visited))
    for item in metadata_index['split_originals']:
        assert restore(item['representation'], cloud_visited) == verified_file(item['original'], bounded=False)
    assert set(cloud_visited) <= {r['path'] for r in cloud_map['files']}
    # Include both externally stored file maps and their bounded entry pointers.
    for directory, prefix, key, original_map in [
        (HOST, 'host', 'representation', host_map_bytes),
        (CLOUD, 'cloud', 'file_map_representation', cloud_map_bytes),
    ]:
        pointer_path = directory / 'PUBLICATION_MAP_STORAGE.json'
        pointer = read_json(pointer_path)
        controls = {}
        assert restore(pointer[key], controls) == original_map
        rows.extend(controls.values())
        data = pointer_path.read_bytes()
        assert len(data) <= 480000
        rows.append({'path': f'evidence/e6-observation-diagnostic-runtime-20261120/{prefix}/publication-control/PUBLICATION_MAP_STORAGE.json',
                     'local_path': str(pointer_path), 'bytes': len(data), 'sha256': sha(data),
                     'git_blob': oid(data), 'mode': '100644'})
    assert len(rows) == len({r['path'] for r in rows}) == 134
    baseline = read_json(ROOT / 'metrics_integration/final_evidence_publication_work/FROZEN_273_FILES.json')
    assert not {r['path'] for r in rows} & {r['path'] for r in baseline}
    result = {'status': 'ROOT_INDEPENDENT_CLOUD_TAR_AND_BOTH_PUBLICATION_MAPS_PASS',
              'cloud_actual_result_sha256': sha(result_bytes), 'cloud_archive_sha256': sha(combined),
              'cloud_archive_bytes': len(combined), 'cloud_parts': 13, 'cloud_tar_members': 1225,
              'cloud_originals': 1221, 'cloud_original_bytes': 37093020, 'complete_RPC_originals_byte_equal': 169,
              'host_map_sha256': sha(host_map_bytes), 'cloud_map_sha256': sha(cloud_map_bytes),
              'host_map_files': 96, 'cloud_map_files': 34, 'additional_external_control_files': 4,
              'total_new_publication_paths': len(rows), 'max_file_bytes': max(r['bytes'] for r in rows),
              'all_Git_blob_OIDs_independently_computed': True,
              'all_metadata_descriptors_and_parts_restore_literal_original_bytes': True,
              'no_frozen273_path_collision': True, 'final_head_git_gate_executed': False,
              'native_model_or_host_runs': 0, 'experiment_qualification_granted': False}
    (OUT / 'ROOT_READBACK.json').write_text(json.dumps(result, indent=2) + '\n')
    (OUT / 'PUBLICATION_FILES_134.json').write_text(json.dumps(sorted(rows, key=lambda r: r['path']), indent=2) + '\n')
    print(json.dumps(result, indent=2))
    print('root_readback_sha256=' + sha((OUT / 'ROOT_READBACK.json').read_bytes()))
    print('publication_files_sha256=' + sha((OUT / 'PUBLICATION_FILES_134.json').read_bytes()))


if __name__ == '__main__':
    main()
