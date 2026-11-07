#!/usr/bin/env python3
"""Freeze the byte-verified R31 formal group; local files only."""
import hashlib
import json
import os
from pathlib import Path

PREP = Path(__file__).resolve().parent
B = PREP.parent


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def new(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    assert path.read_bytes() == raw
    return pin(raw)


def main():
    plan = json.loads((PREP / 'COPY-PLAN.json').read_bytes())
    target = B / plan['target']
    for row in plan['files']:
        assert pin((target / row['path']).read_bytes()) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}
    readback_raw = (target / 'ATTACHMENT-BYTE-READBACK.json').read_bytes()
    readback = json.loads(readback_raw)
    assert readback['result'] == 'PASS' and readback['payload_files_verified'] == plan['file_count']
    assert readback['copy_plan'] == pin((PREP / 'COPY-PLAN.json').read_bytes())
    files = []
    for path in sorted(target.rglob('*')):
        if path.is_file():
            assert not path.is_symlink()
            files.append({'path': str(path.relative_to(target)), **pin(path.read_bytes())})
    assert {row['path'] for row in files} == {row['path'] for row in plan['files']} | {'ATTACHMENT-BYTE-READBACK.json'}
    manifest = {'schema': 'hepta.r31-formal-attachment-manifest.v1', 'state': 'FROZEN',
        'root': plan['target'], 'files': files, 'listed_files': len(files),
        'listed_bytes': sum(row['bytes'] for row in files), 'count_including_this_manifest': len(files) + 1,
        'all_original_member_and_support_mapping_rows': plan['source_mapping_rows'],
        'original_archive_source_files_not_duplicated': 197,
        'complete_original_workspace_gate': 'PASS', 'original_tests': {'PASS': 20228, 'FAIL': 0, 'TIMEOUT': 0, 'reported_skip': 130},
        'diagnostic_only': True, 'behavior_repair_claimed': False,
        'fix_fmt_authorization_or_results_included': False, 'science': 'HOLD', 'authority': 'DENY_ALL',
        'root_upload_and_registration_owner': True, 'Git_upload_performed_by_this_script': False}
    manifest_pin = new(target / 'ATTACHMENT-MANIFEST.json', manifest)
    binary = json.loads((target / 'BINARY-PLAN.json').read_bytes())
    handoff = {'schema': 'hepta.r31-formal-handoff.v1', 'formal_root': plan['target'],
        'state': 'FROZEN', 'files': len(files) + 1, 'bytes': manifest['listed_bytes'] + manifest_pin['bytes'],
        'attachment_manifest': {'path': 'ATTACHMENT-MANIFEST.json', **manifest_pin},
        'closure': {'path': 'CLOSURE.json', **pin((target / 'CLOSURE.json').read_bytes())},
        'independent_original_gate_readback': {'path': 'INDEPENDENT-READBACK.json', **pin((target / 'INDEPENDENT-READBACK.json').read_bytes())},
        'attachment_byte_readback': {'path': 'ATTACHMENT-BYTE-READBACK.json', **pin(readback_raw)},
        'source_destination_mapping': {'path': 'SOURCE-DESTINATION-MAPPING.json', **pin((target / 'SOURCE-DESTINATION-MAPPING.json').read_bytes())},
        'binary_plan': {'path': 'BINARY-PLAN.json', **pin((target / 'BINARY-PLAN.json').read_bytes())},
        'binary_files': len(binary['files']),
        'known_archive_blob_already_created_and_registered': '693da6d9414f88c1620516a28958c518ac924978',
        'duplicate_base64_transfer_chunks_not_copied': True,
        'root_docs_INDEX_ledger_native_source_unchanged_by_assembler': True,
        'science': 'HOLD', 'authority': 'DENY_ALL', 'formatter_results_or_authorization_included': False}
    handoff_pin = new(PREP / 'HANDOFF-MANIFEST.json', handoff)
    print(json.dumps({**handoff, 'handoff': handoff_pin}))


if __name__ == '__main__':
    main()
