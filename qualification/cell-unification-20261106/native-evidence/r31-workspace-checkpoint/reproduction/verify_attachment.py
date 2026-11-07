#!/usr/bin/env python3
"""Separate local byte verifier for the new R31 attachment draft."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import tarfile

PREP = Path(__file__).resolve().parent
B = PREP.parent


def require(value, message):
    if not value:
        raise AssertionError(message)


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def main():
    plan_raw = (PREP / 'COPY-PLAN.json').read_bytes()
    plan = json.loads(plan_raw)
    target = B / plan['target']
    expected = {row['path']: row for row in plan['files']}
    actual = {str(path.relative_to(target)) for path in target.rglob('*') if path.is_file()}
    require(len(expected) == len(plan['files']) and set(expected) == actual, 'payload path set differs')
    contents = {}
    for name, row in expected.items():
        path = target / name
        require(not path.is_symlink(), 'attachment symlink')
        data = path.read_bytes()
        require(pin(data) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}, 'payload raw pin differs: ' + name)
        contents[name] = data
    archive = contents['archive/checkpoint-r31-closed.tar.gz']
    require(pin(archive) == {'bytes': 4484123, 'sha256': '87afd6c49a3c753b90c8e53b3b70988f2964352fcf2daf0ed85c536ac6f77563',
                             'git_blob': '693da6d9414f88c1620516a28958c518ac924978'}, 'archive pin differs')
    members = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tf:
        for member in tf.getmembers():
            p = PurePosixPath(member.name)
            require(member.isfile() and not member.issym() and not member.islnk() and not p.is_absolute()
                    and '..' not in p.parts and member.name not in members, 'archive member unsafe')
            members[member.name] = tf.extractfile(member).read()
    require(len(members) == 353, 'archive member count differs')
    mapping_raw = contents['SOURCE-DESTINATION-MAPPING.json']
    mapping = json.loads(mapping_raw)
    transformations, exact, archive_only, aliases = 0, 0, 0, 0
    archive_member_paths = set()
    source_file_paths = set()
    for row in mapping['rows']:
        origin = row['origin']
        if origin['kind'] == 'archive_member':
            raw = members[origin['member']]
            archive_member_paths.add(origin['member'])
        elif origin['kind'] == 'local_original':
            path = B / origin['path']
            require(path.is_file() and not path.is_symlink(), 'original file unavailable during attachment readback')
            raw = path.read_bytes()
            source_file_paths.add(origin['path'])
        else:
            raise AssertionError('unknown source mapping origin')
        require(pin(raw) == row['raw'], 'mapped original raw bytes differ')
        stored = contents[row['destination']]
        if row['storage'] == 'original_archive_member_only':
            require(row['origin']['kind'] == 'archive_member' and origin['member'].startswith('source/'), 'archive-only mapping is not source')
            require(row['destination'] == 'archive/checkpoint-r31-closed.tar.gz'
                    and row['archive_member'] == origin['member'] and pin(stored) == row['stored_archive'],
                    'archive-only source locator differs')
            archive_only += 1
        else:
            require(pin(stored) == row['stored'], 'mapped stored pin differs')
            if row['storage'] == 'deterministic_gzip':
                require(stored[:2] == b'\x1f\x8b' and int.from_bytes(stored[4:8], 'little') == 0,
                        'gzip header or mtime differs')
                require(row['gzip_mtime'] == 0 and gzip.decompress(stored) == raw, 'gzip original bytes differ')
                transformations += 1
            else:
                require(row['storage'] == 'exact_bytes' and stored == raw, 'exact copy differs')
                exact += 1
            aliases += int(row['deduplicated'])
    require(archive_member_paths == set(members) and archive_only == 197, 'archive coverage incomplete')
    require(not any(name.startswith('original/source/') for name in contents), '197 source files unnecessarily duplicated')
    member_map = json.loads(contents['ORIGINAL-MEMBER-MAPPING.json'])
    require(member_map['members'] == [row for row in mapping['rows'] if row['origin']['kind'] == 'archive_member'],
            'archive member map differs from complete mapping')
    binary = json.loads(contents['BINARY-PLAN.json'])
    require({row['path'] for row in binary['files']} == {name for name in contents if name.endswith('.gz')}, 'binary plan path set differs')
    for row in binary['files']:
        require(pin(contents[row['path']]) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}, 'binary plan pin differs')
    root = json.loads(contents['reviews/ROOT-ARCHIVE-READBACK.json'])
    independent = json.loads(contents['INDEPENDENT-READBACK.json'])
    closure = json.loads(contents['CLOSURE.json'])
    require(closure['engineering_gate'] == 'PASS' and root['result'] == 'ORIGINAL_SOURCE53_R31_PASS'
            and independent['classification'] == 'CLOSED_DEFAULT_WORKSPACE_PASS', 'qualification differs')
    require(closure['counts'] == root['counts'] == independent['execution']['terminal_counts']
            == {'PASS': 20228, 'FAIL': 0, 'TIMEOUT': 0}, 'independent result counts differ')
    require(closure['reported_skipped'] == root['reported_skipped'] == independent['execution']['reported_skipped'] == 130,
            'reported skips differ')
    require(closure['raw_exit'] == closure['effective_exit'] == closure['outer_exit'] == 0, 'original exits differ')
    require(closure['diagnostic_only'] is True and closure['behavior_repair_claimed'] is False
            and closure['science'] == 'HOLD' and closure['authority'] == 'DENY_ALL'
            and closure['formatter_or_fix_results_included'] is False
            and closure['post_fix_fmt_qualification_claimed'] is False, 'evidence boundary differs')
    require(closure['archive_publication_response'] in contents and closure['archive_registration_snapshot'] in contents,
            'archive publication evidence missing')
    response = json.loads(contents[closure['archive_publication_response']])
    require(response['structuredContent']['sha'] == pin(archive)['git_blob'] and response['isError'] is False,
            'archive actual publication proof differs')
    report = {'schema': 'hepta.r31-formal-independent-attachment-byte-readback.v1', 'result': 'PASS',
        'scope': 'LOCAL_ATTACHMENT_BYTES_AND_ORIGINAL_MAPPINGS_ONLY_NO_NEW_GATE',
        'copy_plan': pin(plan_raw), 'payload_files_verified': len(contents),
        'payload_bytes_verified': sum(len(raw) for raw in contents.values()),
        'mapping_rows_verified': len(mapping['rows']), 'original_local_file_paths_verified': len(source_file_paths),
        'archive_members_verified': len(members), 'source_members_only_in_archive': archive_only,
        'exact_copy_mapping_rows': exact, 'deterministic_gzip_mapping_rows': transformations,
        'deduplicated_mapping_rows': aliases, 'all_gzip_raw_roundtrips_exact': True,
        'source_destination_mapping': pin(mapping_raw), 'actual_archive': pin(archive),
        'all_binary_plan_pins_verified': True,
        'current_PASS_and_historical_failed_pending_snapshot_boundaries_preserved': True,
        'root_and_independent_original_gate_readbacks_agree': True,
        'full_native_repo_tree_reconstruction_claimed': False,
        'formatter_inventory_or_finalizer_evidence_not_mixed_into_gate': True,
        'native_Rust_metadata_Git_upload_fix_or_fmt_executed': False,
        'closure_artifacts_generated_after_this_report_are_final_manifest_only': True}
    raw = (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode()
    path = target / 'ATTACHMENT-BYTE-READBACK.json'
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    require(path.read_bytes() == raw, 'readback report write differs')
    print(json.dumps({'report': pin(raw), 'payload_files': len(contents), 'mapping_rows': len(mapping['rows']), 'result': 'PASS'}))


if __name__ == '__main__':
    main()
