#!/usr/bin/env python3
"""Archive only the frozen 68-file DATA review; do not run its parsers or tests.

No host, network, Git, database, model, credential, or native API is used.
RESULT.json is a create-only last commit after all publication validation.
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import time

sys.dont_write_bytecode = True

from archive_common import ROOT, MAX_PART_BYTES, content_role, git_blob, json_bytes, safe_member, sha256, stable_read
from publication_parts_v2 import Publication, identity, put_new

FROZEN_MANIFEST_SHA = 'd21f91f9668243dbed3e367dd69cc3b1e0cefe6486f576bac41ce324f58c3bd4'
FROZEN_SOURCE = 'dbd6a00992b60f4b33e8f10c2defda031d123bcb'
WORK = ROOT / 'e6_training_business_archive_1'
SOURCE_ROOT = ROOT / 'e6_noupdate12_training_business_physical_review_1'
PREFIX = 'evidence/e6-observation-diagnostic-runtime-20261120/training-business-data'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    started = time.monotonic()
    output = Path(args.output).absolute()
    assert output.is_relative_to(WORK) and output.name.startswith('pack-')
    assert not output.exists(), 'A fresh output directory is required; no automatic rerun.'
    output.mkdir(parents=True, exist_ok=False)
    committed = False
    try:
        plan_path = Path(args.plan).absolute()
        plan_bytes, plan_stat = stable_read(plan_path)
        assert sha256(plan_bytes) == args.plan_sha256
        plan = json.loads(plan_bytes)
        assert plan['schema'] == 'hepta.training-business-archive-plan.v1'
        assert plan['source_manifest_sha256'] == FROZEN_MANIFEST_SHA
        assert plan['actual_source'] == FROZEN_SOURCE
        assert plan['review_files'] == 68 and plan['review_bytes'] == 1507304
        assert plan['archive_input_files'] == 69 and plan['archive_input_bytes'] == 1536982
        assert plan['max_publication_file_bytes'] == MAX_PART_BYTES == 480000
        assert plan['repository_prefix'] == PREFIX
        assert plan['physical_owner_seconds_limit'] == 60
        assert plan['original_runtime_outcome'] == 'NoUpdate12 FAIL at C Generation drain'

        def budget():
            assert time.monotonic() - started <= 60, 'Archive preparation exceeded its 60-second local window.'

        controllers = plan['controllers']
        assert {r['path'] for r in controllers} == {
            str(Path(__file__).resolve()), str(Path(__file__).with_name('archive_common.py').resolve()),
            str(Path(__file__).with_name('publication_parts_v2.py').resolve()),
        }
        for row in controllers:
            data, stat = stable_read(Path(row['path']))
            assert (len(data), sha256(data), git_blob(data)) == (row['bytes'], row['sha256'], row['git_blob'])
            assert stat == row['stat']
            put_new(output / 'controller' / Path(row['path']).name, data)
        put_new(output / 'PLAN.json', plan_bytes)
        source_manifest_bytes, source_manifest_stat = stable_read(SOURCE_ROOT / 'READOUT_MANIFEST.json')
        assert sha256(source_manifest_bytes) == FROZEN_MANIFEST_SHA
        original_manifest = json.loads(source_manifest_bytes)
        assert original_manifest['files_count'] == 68
        assert original_manifest['actual_source'] == FROZEN_SOURCE
        assert original_manifest['source_inventory_canonical_sha256'] == '20fe46de4b63f5a2bcce469113ebe27b7514f942c7f960a71e4dabaa4f643d0f'
        expected = {r['path']: r for r in original_manifest['files']}
        assert len(expected) == 68
        entries = plan['inputs']
        assert len(entries) == 69
        assert {r['member'] for r in entries} == set(expected) | {'READOUT_MANIFEST.json'}
        retained = {}
        for row in entries:
            budget()
            name = row['member']
            assert safe_member(name) and name not in retained
            path = SOURCE_ROOT / name
            assert path.resolve() == path and row['source_path'] == str(path)
            data, stat = stable_read(path)
            assert stat == row['stat']
            assert (len(data), sha256(data), git_blob(data)) == (row['bytes'], row['sha256'], row['git_blob'])
            if name == 'READOUT_MANIFEST.json':
                assert data == source_manifest_bytes
            else:
                old = expected[name]
                assert old['local_absolute'] == str(path)
                assert (len(data), sha256(data), git_blob(data)) == (old['bytes'], old['sha256'], old['git_blob'])
            retained[name] = data
        assert sum(len(x) for x in retained.values()) == 1536982

        archive = output / 'training-business-data.tar.xz'
        with tarfile.open(archive, 'x:xz', format=tarfile.PAX_FORMAT, preset=6) as tar:
            for name in sorted(retained):
                budget()
                data = retained[name]
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o644
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ''
                tar.addfile(info, io.BytesIO(data))
        archive_data, archive_stat = stable_read(archive)
        readback = []
        seen = set()
        with tarfile.open(archive, 'r:xz') as tar:
            for member in tar:
                budget()
                assert member.isfile() and safe_member(member.name) and member.name not in seen
                assert member.name in retained
                seen.add(member.name)
                stream = tar.extractfile(member)
                assert stream is not None
                data = stream.read()
                assert data == retained[member.name] and len(data) == member.size
                readback.append({'member': member.name, 'bytes': len(data), 'sha256': sha256(data), 'git_blob': git_blob(data), 'literal_equal_to_original': True, 'role': content_role(SOURCE_ROOT / member.name, data)})
        assert seen == set(retained)
        assert archive.read_bytes() == archive_data
        put_new(output / 'MEMBER_READBACK.json', json_bytes({'members': readback, 'members_count': len(readback), 'original_review_files': 68, 'original_review_manifest_additional': 1, 'all_original_bytes_equal': True, 'archive_verified_only_not_overall_publication_status': True}))
        put_new(output / 'ORIGINAL_READOUT_MANIFEST.json', source_manifest_bytes)
        put_new(output / 'READOUT.md', retained['READOUT.md'])
        part_rows = []
        for ordinal, offset in enumerate(range(0, len(archive_data), MAX_PART_BYTES)):
            budget()
            chunk = archive_data[offset:offset + MAX_PART_BYTES]
            name = f'training-business-data.tar.xz.part-{ordinal:03d}'
            path = output / name
            put_new(path, chunk)
            part_rows.append({'ordinal': ordinal, 'offset': offset, 'file': name, 'bytes': len(chunk), 'sha256': sha256(chunk), 'git_blob': git_blob(chunk)})
        assert b''.join((output / r['file']).read_bytes() for r in part_rows) == archive_data
        put_new(output / 'archive-parts.json', json_bytes({'archive': archive.name, 'bytes': len(archive_data), 'sha256': sha256(archive_data), 'parts': part_rows, 'max_part_bytes': MAX_PART_BYTES, 'ordered_concatenation_literal_equal': True}))
        manifest = {'schema': 'hepta.training-business-archive.v1', 'source_manifest_sha256': FROZEN_MANIFEST_SHA, 'actual_source': FROZEN_SOURCE, 'original_review_files': 68, 'original_review_bytes': 1507304, 'additional_original_manifest_files': 1, 'archive_members': 69, 'archive_input_bytes': 1536982, 'archive_bytes': len(archive_data), 'archive_sha256': sha256(archive_data), 'original_files': entries, 'excluded_from_this_archive': ['Existing host/cloud archives are dependencies and unchanged; their full content is not duplicated.', 'FinalUse attribution addendum is a separate layer.', 'Later C-drain candidate and ordinary Adopt source reviews are outside the frozen 68-file manifest.'], 'original_runtime_outcome': plan['original_runtime_outcome'], 'new_model_native_host_signature_or_database_operations': 0}
        put_new(output / 'MANIFEST.json', json_bytes(manifest))

        publication = Publication(output / 'publication-parts', PREFIX)
        logical = ['PLAN.json', 'MANIFEST.json', 'ORIGINAL_READOUT_MANIFEST.json', 'MEMBER_READBACK.json', 'archive-parts.json', 'READOUT.md']
        logical += ['controller/' + Path(row['path']).name for row in controllers]
        logical += [r['file'] for r in part_rows]
        for name in logical:
            budget()
            publication.stage(output / name, PREFIX + '/' + name)
        put_new(output / 'METADATA_REASSEMBLY.json', json_bytes(publication.restorations))
        publication.stage(output / 'METADATA_REASSEMBLY.json', PREFIX + '/METADATA_REASSEMBLY.json')
        verified = publication.verify_all()
        put_new(output / 'PUBLICATION_VALIDATION.json', json_bytes(verified))
        publication.stage(output / 'PUBLICATION_VALIDATION.json', PREFIX + '/PUBLICATION_VALIDATION.json')
        # RESULT has no digest of its containing map; the map is an external sidecar.
        final_result = {'status': 'COMPLETE_ORIGINAL_REVIEW_ARCHIVE_AND_PUBLICATION_RESTORATION_PASS', 'successful': True, 'source_manifest_sha256': FROZEN_MANIFEST_SHA, 'actual_source': FROZEN_SOURCE, 'review_files': 68, 'archive_members_including_original_manifest': 69, 'archive_sha256': sha256(archive_data), 'archive_bytes': len(archive_data), 'archive_parts': len(part_rows), 'literal_original_members_verified': True, 'all_complete_RPC_envelopes_kept_verbatim': True, 'physical_seconds_before_final_map_and_revalidation': time.monotonic() - started, 'original_whole_parent': 'FAIL', 'learning_or_FinalUse_qualification_granted': False, 'new_host_model_native_optimizer_signature_database_or_Git_operations': 0, 'final_result_committed_only_after_publication_and_source_revalidation': True}
        final_bytes = json_bytes(final_result)
        assert len(final_bytes) <= MAX_PART_BYTES
        prepared_result = output / 'RESULT.prepared-bytes.json'
        put_new(prepared_result, final_bytes)
        assert prepared_result.read_bytes() == final_bytes
        final_path = output / 'RESULT.json'
        final_row = identity(final_path, PREFIX + '/RESULT.json', final_bytes)
        assert final_row['path'] not in publication.files
        public_rows = sorted([*publication.files.values(), final_row], key=lambda r: r['path'])
        old_paths = {r['path'] for r in plan['existing_publication_paths']}
        assert not ({r['path'] for r in public_rows} & old_paths)
        map_bytes = json_bytes(public_rows)
        # This bounded 69-member recipe produces a small map; never truncate a map.
        assert len(map_bytes) <= MAX_PART_BYTES
        map_path = output / 'PUBLICATION_FILES.json'
        put_new(map_path, map_bytes)
        map_storage = {'schema': 'hepta.external-publication-map.v1', 'map': identity(map_path, PREFIX + '/PUBLICATION_FILES.json', map_bytes), 'self_reference_excluded': True, 'include_map_and_this_control_separately_when_building_the_final_Git_manifest': True}
        map_storage_bytes = json_bytes(map_storage)
        assert len(map_storage_bytes) <= MAX_PART_BYTES
        put_new(output / 'PUBLICATION_MAP_STORAGE.json', map_storage_bytes)
        assert json.loads(map_path.read_bytes()) == public_rows
        assert (output / 'PUBLICATION_MAP_STORAGE.json').read_bytes() == map_storage_bytes
        publication.verify_all()
        assert prepared_result.read_bytes() == final_bytes
        for row in entries:
            data, stat = stable_read(Path(row['source_path']))
            assert stat == row['stat'] and data == retained[row['member']]
        for row in controllers:
            data, stat = stable_read(Path(row['path']))
            assert stat == row['stat'] and sha256(data) == row['sha256']
        assert stable_read(plan_path) == (plan_bytes, plan_stat)
        assert stable_read(SOURCE_ROOT / 'READOUT_MANIFEST.json') == (source_manifest_bytes, source_manifest_stat)
        budget()
        # Last filesystem operation on the success path. The exact inode was read above.
        os.link(prepared_result, final_path)
        committed = True
        print(json.dumps({'status': 'PASS', 'result': str(final_path), 'archive_sha256': sha256(archive_data), 'publication_components': len(public_rows)}, ensure_ascii=False))
    except BaseException as exc:
        if not committed and not (output / 'RESULT.json').exists():
            failure = {'status': 'FAILED_INCOMPLETE_PUBLICATION', 'successful': False, 'error_type': type(exc).__name__, 'error': str(exc), 'prior_partial_files_retained': True, 'seconds': time.monotonic() - started}
            put_new(output / 'FAILURE.json', json_bytes(failure))
        raise


if __name__ == '__main__':
    main()
