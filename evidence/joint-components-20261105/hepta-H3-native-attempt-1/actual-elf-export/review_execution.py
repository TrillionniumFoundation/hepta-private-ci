#!/usr/bin/env python3
"""Root verification of actual H3 archive execution and small-byte readbacks."""
from pathlib import Path
import base64
import hashlib
import json
import shutil

WORK = Path('/workspace/scratch/93bfcfe29fc8')
SOURCE = WORK / 'w1/h3-elf-export'
OUT = Path(__file__).resolve().parent / 'execution'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(name):
    return json.loads((SOURCE / name).read_bytes())


def rpc(name):
    r = load(name)
    assert r.get('isError') is not True
    return r.get('structuredContent') or json.loads(r['content'][0]['text'])


def actual_read(name, expected):
    r = rpc(name)
    assert not r.get('truncated') and len(r['files']) == 1
    f = r['files'][0]
    raw = f['text'].encode()
    assert f['eof'] and len(raw) == f['size'] and sha(raw) == f['sha256']
    assert raw == (SOURCE / expected).read_bytes()
    return json.loads(raw)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_raw = (SOURCE / 'H3-execution-delivery-manifest.json').read_bytes()
    assert sha(manifest_raw) == '001eac8329c81a0064e01601f010139b6a98b1d1239681111a5492c94d9f8c32'
    manifest = json.loads(manifest_raw)
    assert len(manifest['files']) == 66
    total = 0
    for row in manifest['files']:
        p = Path(row['path'])
        raw = p.read_bytes()
        assert len(raw) == row['bytes'] and sha(raw) == row['sha256'], str(p)
        relative = p.relative_to(SOURCE)
        dest = OUT / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            assert dest.read_bytes() == raw
        else:
            shutil.copyfile(p, dest)
        total += len(raw)
    assert total == 3503455
    (OUT / 'H3-execution-delivery-manifest.json').write_bytes(manifest_raw)
    completion = actual_read('H3-export-completion-read.raw.json', 'H3-export-completion.json')
    assert completion['status'] == 'COMPLETE' and completion['phase'] == 'H3'
    assert completion['archive_sha256'] == '5365fcf900781044108e9642ae02a110e4ac8d031d9ee516c4f0b0e471e1e773'
    assert completion['archive_bytes'] == 283427280
    assert completion['source_commit'] == '6db78eca53a5acdda0d96873d3f4cd65863426f0'
    assert completion['source_tree'] == 'e91f5994017fc5d2cfe58d405a20ee6ad9376772'
    assert completion['plan_sha256'] == sha((SOURCE / 'H3-export-plan.json').read_bytes())
    assert completion['exporter_sha256'] == sha((SOURCE / 'export_h3_retained_images.py').read_bytes())
    assert not completion['native_reexecution'] and not completion['binary_rebuilt'] and not completion['capture_gaps_filled']
    terminal = rpc('H3-export-terminal.raw.json')
    launch = rpc('H3-export-launch.raw.json')
    assert terminal['job_id'] == launch['job']['id'] == '1a1add12f68-fc05-5aec'
    assert launch['job']['idempotency_key'] == '93bfc-hepta-h3-actual-retained-images-export-01'
    assert terminal['state'] == 'succeeded' and terminal['exit_code'] == 0 and not terminal['timed_out'] and not terminal['automatic_retry']
    assert terminal['output_complete'] and terminal['output_durable'] and terminal['terminal_publication_confirmed']
    outer = (terminal['at_unix_ms'] - launch['job']['created_unix_ms']) / 1000
    assert outer == 263.109 and completion['elapsed_seconds'] <= outer <= 900
    streams = [rpc('H3-export-streams-first.raw.json'), rpc('H3-export-streams-last.raw.json')]
    for stream in ['stdout', 'stderr']:
        chunks = sorted([r[stream] for r in streams], key=lambda r: r['offset'])
        data = b''
        for chunk in chunks:
            raw = bytes.fromhex(chunk['bytes_hex'])
            assert raw == chunk['text'].encode() and chunk['next_offset'] == chunk['offset'] + len(raw)
            if chunk['offset'] == 0 and not raw and not data:
                continue
            assert chunk['offset'] == len(data)
            data += raw
        assert data == (SOURCE / ('H3-export.' + stream)).read_bytes()
        assert len(data) == terminal['log_bytes'][stream]['seen'] == terminal['log_bytes'][stream]['stored']
        assert terminal['log_synced'][stream] and not terminal['log_truncated'][stream]
    stdout = (SOURCE / 'H3-export.stdout').read_bytes()
    assert json.loads(stdout) == completion
    assert stdout != (SOURCE / 'H3-export-completion.json').read_bytes()
    parts = completion['parts']
    assert len(parts) == 68
    offset = 0
    for number, part in enumerate(parts):
        assert part['index'] == number and part['offset'] == offset and 0 < part['bytes'] <= 4194304
        assert part['name'] == f'H3-actual-retained-elfs.tar.xz.part-{number:04d}'
        offset += part['bytes']
    assert offset == completion['archive_bytes']
    data = b''
    version = None
    range_names = ['H3-index-first-range.raw.json'] + [f'H3-index-range-{n}.raw.json' for n in [65536, 131072, 196608, 262144]]
    for number, name in enumerate(range_names):
        r = rpc(name)
        raw = base64.b64decode(r['data_base64'], validate=True)
        assert sha(raw) == r['chunk_sha256'] and r['offset'] == len(data)
        assert r['next_offset'] == len(data) + len(raw) and r['size'] == 294654
        assert r['eof'] is (number == 4)
        if version is None:
            version = r['version']
        assert r['version'] == version
        data += raw
    assert data == (SOURCE / 'H3-actual-export-index.json').read_bytes()
    assert sha(data) == completion['archive_index_sha256'] == 'b023aca6ab2dccf4324dccab2e5319a00ef9b32773e0dc73127efc9af3caa002'
    index = json.loads(data)
    plan = load('H3-export-plan.json')
    assert index['original_run_outcome'] == plan['original_run_outcome'] == completion['original_run_outcome']
    assert len(index['files']) == len(plan['files']) == 11
    for actual, original in zip(index['files'], plan['files']):
        assert {k: actual[k] for k in original} == original
        assert actual['first_read_metadata'] == actual['second_read_metadata']
        assert actual['second_read_sha256'] == actual['sha256']
        assert actual['other_aliases_reopened_by_this_export'] is False
    assert sum(r['bytes'] for r in index['files']) == 1674575368
    assert sum(len(r['aliases']) for r in index['files']) == 30
    assert sum(len(r['original_observations']) for r in index['files']) == 279
    readback = actual_read('H3-index-readback-read.raw.json', 'H3-index-readback.json')
    expected_members = {r['name']: {'bytes': r['bytes'], 'sha256': r['sha256']} for r in index['files']}
    expected_members.update(index['embedded_metadata_files'])
    expected_members['export-index.json'] = {'bytes': len(data), 'sha256': sha(data)}
    assert readback['actual_members'] == expected_members and len(expected_members) == 16
    assert readback['archive_sha256'] == completion['archive_sha256'] and readback['archive_bytes'] == completion['archive_bytes']
    read_terminal = rpc('H3-index-read-terminal.raw.json')
    read_launch = rpc('H3-index-read-launch.raw.json')
    assert read_terminal['job_id'] == read_launch['job']['id'] == '1a1adda0573-fc05-5b28'
    assert read_terminal['state'] == 'succeeded' and read_terminal['exit_code'] == 0 and not read_terminal['timed_out']
    read_outer = (read_terminal['at_unix_ms'] - read_launch['job']['created_unix_ms']) / 1000
    assert read_outer == 33.874 and readback['elapsed_seconds'] < read_outer < 60
    releases = []
    for label, owned in [('archive', terminal), ('index', read_terminal)]:
        prefix = 'H3-' + label + '-release'
        target = 'H3-archive-owned-release-proof.json' if label == 'archive' else 'H3-index-read-owned-release-proof.json'
        proof = actual_read(prefix + '-proof-read.raw.json', target)
        released = rpc(prefix + '-terminal.raw.json')
        assert released['state'] == 'succeeded' and released['exit_code'] == 0 and not released['timed_out']
        assert proof['job_id'] == owned['job_id'] and proof['owned_processes_clear'] and not proof['failures']
        assert all(not r['exists'] and not r['owned_pids'] for r in proof['exact_cgroups'])
        assert all(not r['present'] for r in proof['original_root_processes'])
        assert proof['original_authoritative_terminal']['at_unix_ms'] == owned['at_unix_ms']
        releases.append({'job_id': proof['job_id'], 'probe_job_id': released['job_id'], 'proof_sha256': sha((SOURCE / target).read_bytes())})
    report = {
        'schema': 'root-h3-actual-archive-execution-review-v1', 'result': 'PASS small-byte execution readback',
        'delivery_files': 66, 'delivery_bytes': total, 'delivery_manifest_sha256': sha(manifest_raw),
        'archive_job_id': terminal['job_id'], 'archive_terminal': terminal,
        'actual_outer_seconds': outer, 'original_budget_seconds': 900,
        'actual_exporter_seconds': completion['elapsed_seconds'],
        'archive_bytes': completion['archive_bytes'], 'archive_sha256': completion['archive_sha256'],
        'archive_parts': len(parts), 'parts_contiguous': True,
        'actual_index_bytes': len(data), 'actual_index_sha256': sha(data), 'index_rpc_ranges': 5, 'index_version': version,
        'actual_images': 11, 'actual_image_bytes': 1674575368, 'aliases': 30, 'observations': 279,
        'all_original_inventory_fields_preserved': True, 'recorded_first_second_source_metadata_equal': True,
        'separate_readback_job': read_terminal['job_id'], 'separate_readback_outer_seconds': read_outer,
        'separate_readback_members': len(expected_members), 'separate_readback_budget_seconds': 60,
        'stdout_completion_json_equal': True, 'stdout_completion_bytes_equal': False,
        'stdout_bytes': len(stdout), 'completion_bytes': len((SOURCE / 'H3-export-completion.json').read_bytes()),
        'owned_releases': releases,
        'archive_bulk_locally_verified': False,
        'original_native_result': 'FAILED', 'unmatched_h3_pid_attributed': False,
        'new_native_or_learning_trial': False,
        'limits': ['The root has checked actual small RPC bytes, not the remote 283427280 archive bytes.',
                   'Complete lossless download and local full archive/part/member verification remain required.',
                   'Remote archive success does not qualify H3 or replace any missing native gate.']
    }
    p = OUT / 'root-review.json'
    p.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'result': report['result'], 'files': 66, 'bytes': total, 'review_sha256': sha(p.read_bytes()), 'bulk_pending': True}))


if __name__ == '__main__':
    main()
