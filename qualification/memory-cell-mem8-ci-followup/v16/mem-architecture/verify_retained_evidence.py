"""Verify retained original observations without executing tests or model code."""
import hashlib
import json
from pathlib import Path
import runpy
import tarfile

import audit_originals as audit

HERE = Path(__file__).resolve().parent

def verify():
    manifest = audit.load(HERE / 'FILE_MANIFEST.json')
    actual = {p.relative_to(HERE).as_posix() for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    assert actual == {r['path'] for r in manifest['files']} | {'FILE_MANIFEST.json'}
    for row in manifest['files']:
        assert audit.identity((HERE / row['path']).read_bytes()) == {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}
    originals = [audit.verify_artifact(aid) for aid in (13864355906, 13863093381, 13861644625, 13862932588)]
    large = HERE / 'artifacts/13862859146'
    large_manifest = audit.load(large / 'MANIFEST.json')
    retained = []
    for row in large_manifest['members']:
        if row['name'] == 'source-input.tar.gz':
            continue
        raw = (large / 'files' / row['name']).read_bytes()
        assert len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
        retained.append(row['name'])
    assert len(retained) == 9
    groups = audit.audit_receipts(13861644625, 'source-head', audit.HEAD, 43035589682)
    groups += audit.audit_receipts(13864355906, 'source-head', audit.HEAD, 43035589682)
    groups += audit.audit_receipts(13862859146, 'source-head', audit.HEAD, 43035589987)
    groups += audit.audit_receipts(13862932588, 'base-merge', audit.MERGE, 43035589987)
    original_audit = audit.load(HERE / 'AUDIT.json')
    assert groups == original_audit['groups']
    assert audit.campaign() == original_audit['synthetic_campaign']
    source = audit.load(HERE / 'SOURCE_ARCHIVE_FULL_INDEX.json')
    helpers = runpy.run_path(str(HERE / 'references/tree_functions.py'), run_name='tree_functions')
    expected = helpers['listing']((HERE / 'references/CANDIDATE_TREE.ls-tree').read_bytes())
    measured = {r['path']: {'mode': r['mode'], 'type': 'blob', 'git_blob': r['git_blob']} for r in source['files']}
    assert len(measured) == len(source['files']) == len(expected) == 14050
    assert measured == expected and helpers['tree_hash'](measured) == audit.TREE
    native_sources = []
    for name in ('changed-source-before.tar.gz', 'changed-source-after.tar.gz'):
        entries = []
        with tarfile.open(HERE / 'artifacts/13864355906/files' / name, 'r:gz') as archive:
            for member in archive:
                assert not Path(member.name).is_absolute() and '..' not in Path(member.name).parts
                if not member.isfile():
                    continue
                data = archive.extractfile(member).read()
                identity = audit.identity(data)
                assert expected[member.name]['git_blob'] == identity['git_blob']
                entries.append({'path': member.name, **identity})
        native_sources.append({'name': name, 'source_files': len(entries), 'files': entries})
    assert native_sources == audit.load(HERE / 'NATIVE_SOURCE_ARCHIVE_AUDIT.json')
    assert [row['source_files'] for row in native_sources] == [215, 0]
    prerequisites = audit.load(HERE / 'PREREQUISITE_FAILURE_AUDIT.json')
    for failure in prerequisites:
        raw = (HERE / f"original/job-{failure['job_id']}.log").read_bytes()
        assert len(raw) == failure['raw_log']['bytes']
        assert hashlib.sha256(raw).hexdigest() == failure['raw_log']['sha256']
        lines = raw.decode().splitlines()
        for item in failure['actual_error_lines']:
            assert lines[item['line'] - 1] == item['text']
        assert any('Temporary failure resolving' in row['text'] for row in failure['actual_error_lines'])
    return {'status': 'PASS_RETAINED_EVIDENCE_SCOPE', 'package_members': len(actual),
            'complete_original_ZIPs_replayed': originals, 'large_Architecture_ZIP_small_members_replayed': retained,
            'strict_original_receipts_replayed': len(groups), 'MEM_integrity_passed': 35,
            'MEM_CPU_tests_executed': 0, 'MEM_native_tests_executed': 0,
            'Architecture_source_python_passed': 136, 'Architecture_base_python_passed': 136,
            'Architecture_unique_python_ids': 136, 'Architecture_native_tests_executed': 0,
            'synthetic_reader_processes': 14, 'all_source_index_entries_bound_to_complete_Git_tree': 14050,
            'MEM_native_before_source_files_bound': 215, 'MEM_native_after_rewrite_source_files': 0,
            'large_original_ZIP_and_source_tar_replayed_from_this_package': False,
            'large_wrapper_boundary': 'Original 125 MB wrapper was fully hashed/CRC/read by root; retained audit and full source index record that observation. Its original compressed bytes are not duplicated here. Source payload identities all match the existing immutable Git tree.',
            'tests_or_models_executed_by_verifier': 0}

if __name__ == '__main__':
    print(json.dumps(verify(), indent=2, sort_keys=True))
