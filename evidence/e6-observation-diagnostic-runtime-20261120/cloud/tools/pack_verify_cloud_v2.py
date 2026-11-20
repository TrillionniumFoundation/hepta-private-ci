#!/usr/bin/env python3
"""Execute an explicitly reviewed cloud-only archive plan v2, then full readback.

No network, host tools, git, subprocesses, model calls, or source execution.
Output is a new directory. Failures and any partial archive remain retained.
"""
from __future__ import annotations

import argparse
import io
import json
import lzma
import os
import tarfile
import time
import traceback
from pathlib import Path

from archive_common import ROOT,MAX_PART_BYTES,git_blob,json_bytes,safe_member,sha256,stable_read
from host_capture_closure_v2 import validate_closure
from publication_parts_v2 import Publication,identity

HERE=Path(__file__).resolve().parent


def put_new(path: Path,data: bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream:stream.write(data)


def read_current(record):
    path=Path(record['original_path']);data,meta=stable_read(path)
    assert len(data)==record['bytes'] and sha256(data)==record['sha256'],record['member']
    assert git_blob(data)==record['git_blob_oid']
    assert meta==record['source_metadata'],('source metadata changed after plan freeze',record['member'])
    return data


def current_paths(plan):
    found=set()
    for relative in plan['input_roots']:
        for path in (ROOT/relative).rglob('*'):
            if path.is_symlink() or path.is_file():found.add(str(path.relative_to(ROOT)))
    found.update(plan['extra_files'])
    return found


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--plan-sha256',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--execute-reviewed-plan',action='store_true',required=True)
    args=parser.parse_args()
    plan_path=args.plan.resolve();plan_data=plan_path.read_bytes()
    assert sha256(plan_data)==args.plan_sha256
    plan=json.loads(plan_data)
    assert plan['schema']=='hepta.e6.dbd6.cloud-original-archive-plan.v2'
    assert plan['source']=='dbd6a00992b60f4b33e8f10c2defda031d123bcb'
    assert plan['tree']=='fe037f5b6617fb647d416e0523685fa4ce08ef2f'
    assert plan['source_inventory_sha256']=='20fe46de4b63f5a2bcce469113ebe27b7514f942c7f960a71e4dabaa4f643d0f'
    assert plan['max_part_bytes']==MAX_PART_BYTES==480000
    assert plan['max_published_file_bytes']==MAX_PART_BYTES
    assert plan['host_metadata_inventory_pending'] is False,'Actual finite host capture must first be frozen into a new reviewed plan.'
    assert plan['reviewed_runtime_capture_set_closed'] is True
    closure=plan['host_capture_closure']
    checked_closure,closure_paths=validate_closure(Path(closure['closure_path']),closure['closure_sha256'])
    assert checked_closure==closure
    assert set(closure_paths)<=set(plan['extra_files'])
    assert {Path(r['path']).name for r in plan['controller_pins']}=={
        'archive_common.py','prepare_archive_plan_v2.py','pack_verify_cloud_v2.py',
        'publication_parts_v2.py','host_capture_closure_v2.py'}
    for rec in plan['controller_pins']:
        path=Path(rec['path']);data=path.read_bytes()
        assert len(data)==rec['bytes'] and sha256(data)==rec['sha256']
    expected_paths={r['workspace_relative_path'] for r in plan['included']}
    expected_paths.update(r['workspace_relative_path'] for r in plan['excluded_metadata'])
    assert current_paths(plan)==expected_paths,'Input roots changed after plan freeze; prepare a new plan.'
    out=args.output.resolve();assert out.parent==HERE and not out.exists()
    out.mkdir();started=time.monotonic();phase='archive_preflight';archive_verified=False
    try:
        # Preflight before creating an archive; all later reads verify again.
        for record in plan['included']:read_current(record)
        auxiliary={
            'PLAN.json':plan_data,
            'RPC_INDEX.json':json_bytes(plan['rpc_index']),
            'EXCLUDED_METADATA.json':json_bytes({'excluded':plan['excluded_metadata'],'out_of_scope_roots':plan['out_of_scope_roots']}),
        }
        original_records=[{'member':r['member'],'bytes':r['bytes'],'sha256':r['sha256']} for r in plan['included']]
        metadata_records=[{'member':name,'bytes':len(data),'sha256':sha256(data)} for name,data in auxiliary.items()]
        manifest={'schema':'hepta.e6.cloud-original-archive.v2','source':plan['source'],'tree':plan['tree'],
                  'plan_sha256':sha256(plan_data),'original_members':len(original_records),
                  'original_bytes':sum(r['bytes'] for r in original_records),
                  'originals':original_records,'metadata_members':metadata_records,
                  'manifest_self_digest_external_in_RESULT':True,'private_key_bodies_excluded':True,
                  'new_repair_candidate_excluded':True,'rpc_envelopes_verbatim':plan['rpc_count'],
                  'host_capture_closure_sha256':closure['closure_sha256'],
                  'whole_host_filesystem_claimed':False}
        manifest_data=json_bytes(manifest)
        auxiliary['MANIFEST.json']=manifest_data
        for name,data in auxiliary.items():put_new(out/name,data)
        partial=out/'cloud-dbd6-originals.tar.xz.partial'
        with lzma.open(partial,'xb',preset=6) as compressed:
            with tarfile.open(fileobj=compressed,mode='w|',format=tarfile.PAX_FORMAT) as tar:
                for record in plan['included']:
                    data=read_current(record)
                    info=tarfile.TarInfo(record['member']);info.size=len(data)
                    info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0
                    info.mode=record['source_metadata']['mode']&0o777
                    tar.addfile(info,io.BytesIO(data))
                for name,data in sorted(auxiliary.items()):
                    info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644
                    info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0
                    tar.addfile(info,io.BytesIO(data))
        archive=out/'cloud-dbd6-originals.tar.xz';partial.rename(archive)
        expected={r['member']:r for r in original_records+metadata_records}
        expected['MANIFEST.json']={'bytes':len(manifest_data),'sha256':sha256(manifest_data)}
        original_by_member={r['member']:r for r in plan['included']}
        rpc_members={r['member'] for r in plan['rpc_index']}
        seen=set();member_checks=[];rpc_checks=[]
        with tarfile.open(archive,'r|xz') as tar:
            for member in tar:
                assert member.isfile() and safe_member(member.name) and member.name not in seen
                seen.add(member.name);assert member.name in expected,member.name
                info=expected[member.name];assert member.size==info['bytes']
                stream=tar.extractfile(member);assert stream is not None
                data=stream.read();assert len(data)==info['bytes'] and sha256(data)==info['sha256']
                if member.name in original_by_member:
                    assert data==read_current(original_by_member[member.name])
                member_checks.append({'member':member.name,'bytes':len(data),'sha256':sha256(data),'match':True,
                                      'byte_equal_to_original':member.name in original_by_member})
                if member.name in rpc_members:
                    assert data==read_current(original_by_member[member.name])
                    rpc_checks.append({'member':member.name,'bytes':len(data),'sha256':sha256(data),
                                       'byte_identical_to_original_rpc':True,'removed_fields':0,'transformations':0})
        assert seen==set(expected)
        assert len(rpc_checks)==plan['rpc_count']
        archive_bytes=archive.read_bytes();archive_sha=sha256(archive_bytes)
        parts=[]
        for ordinal,offset in enumerate(range(0,len(archive_bytes),MAX_PART_BYTES)):
            data=archive_bytes[offset:offset+MAX_PART_BYTES]
            path=out/f'cloud-dbd6-originals.tar.xz.part-{ordinal:03d}'
            put_new(path,data)
            parts.append({'path':str(path),'name':path.name,'offset':offset,'bytes':len(data),'sha256':sha256(data)})
        rebuilt=b''.join(Path(p['path']).read_bytes() for p in parts)
        assert rebuilt==archive_bytes and sha256(rebuilt)==archive_sha
        # Full original bytes are rechecked after packaging, including mutable
        # progress snapshots; future files cannot be silently folded in.
        assert current_paths(plan)==expected_paths
        for record in plan['included']:read_current(record)
        parts_record={'archive_name':archive.name,'archive_bytes':len(archive_bytes),'archive_sha256':archive_sha,
                      'part_count':len(parts),'max_part_bytes':MAX_PART_BYTES,'parts':parts,'all_parts_reassemble_byte_exactly':True}
        put_new(out/'archive-parts.json',json_bytes(parts_record))
        put_new(out/'MEMBER_READBACK.json',json_bytes({'status':'PASS','members':member_checks,'member_count':len(member_checks),'no_filesystem_tar_extraction':True}))
        put_new(out/'RPC_RESTORE_READBACK.json',json_bytes({'status':'PASS','rpc_count':len(rpc_checks),'records':rpc_checks,
                   'mode':'Verbatim original RPC envelopes round-tripped through archive; no optional template encoding used.'}))
        verify={'status':'PASS','original_members':len(original_records),'total_tar_members':len(member_checks),
                'original_bytes':manifest['original_bytes'],'all_member_names_safe_unique_regular':True,
                'all_member_sizes_and_sha_match':True,'all_original_members_byte_equal':True,'all_rpc_original_bytes_equal':True,
                'parts_reassemble_byte_exactly':True,'original_inputs_unchanged':True,
                'source':plan['source'],'plan_sha256':sha256(plan_data),'archive_sha256':archive_sha,
                'verification_is_not_native_model_or_learning_qualification':True}
        put_new(out/'VERIFY_RESULT.json',json_bytes(verify))
        archive_verified=True
        archive_result={
            'status':'ARCHIVE_ONLY_VERIFIED_PUBLICATION_PENDING',
            'archive_verified':True,'overall_success_not_claimed':True,
            'source':plan['source'],'tree':plan['tree'],
            'plan_sha256':sha256(plan_data),'manifest_sha256':sha256(manifest_data),
            'archive_bytes':len(archive_bytes),'archive_sha256':archive_sha,
            'original_members':len(original_records),'original_bytes':manifest['original_bytes'],
            'part_count':len(parts),'rpc_verbatim_count':len(rpc_checks),
            'wall_seconds_through_archive_verification':time.monotonic()-started,
        }
        put_new(out/'ARCHIVE_RESULT.json',json_bytes(archive_result))
        phase='publication_components'
        prefix=plan['proposed_repository_prefix'];assert safe_member(prefix)
        publication=Publication(out,prefix)
        publish=[Path(p['path']) for p in parts]
        publish += [out/name for name in [
            'PLAN.json','MANIFEST.json','RPC_INDEX.json','EXCLUDED_METADATA.json',
            'archive-parts.json','MEMBER_READBACK.json','RPC_RESTORE_READBACK.json',
            'VERIFY_RESULT.json','ARCHIVE_RESULT.json']]
        publish += [Path(r['path']) for r in plan['controller_pins']]
        for path in publish:
            target=prefix+('/tools/' if path.parent==HERE else '/')+path.name
            publication.stage(path,target)

        # This index describes the preceding representations and is deliberately
        # not self-containing. Its own representation is in the external map.
        restoration_index={
            'schema':'hepta.publication-metadata-restoration.v2',
            'scope':'Preceding archive sidecars and controller source files',
            'max_component_bytes':MAX_PART_BYTES,
            'split_originals':list(publication.restorations),
            'original_bytes_not_reserialized':True,
            'this_index_if_oversized_is_also_split':True,
            'overall_success_not_claimed':True,
        }
        put_new(out/'METADATA_REASSEMBLY.json',json_bytes(restoration_index))
        restoration_representation=publication.stage(
            out/'METADATA_REASSEMBLY.json',prefix+'/METADATA_REASSEMBLY.json')
        component_readback=publication.verify_all()
        component_readback['status']='COMPONENT_BYTES_VERIFIED_FINAL_RESULT_PENDING'
        component_readback['metadata_reassembly_index']=restoration_representation
        put_new(out/'PUBLICATION_VALIDATION.json',json_bytes(component_readback))
        publication.stage(out/'PUBLICATION_VALIDATION.json',prefix+'/PUBLICATION_VALIDATION.json')
        publication.verify_all()

        # Prepare, but do not write, the final successful RESULT. The external
        # file map can bind these bytes without a circular hash: RESULT does not
        # contain the file-map hash, and the map is not a member of itself.
        phase='publication_map_and_final_input_validation'
        result={
            'status':'ARCHIVE_AND_PUBLICATION_PREPARATION_FULLY_VERIFIED',
            'successful':True,'source':plan['source'],'tree':plan['tree'],
            'plan_sha256':sha256(plan_data),'manifest_sha256':sha256(manifest_data),
            'archive_bytes':len(archive_bytes),'archive_sha256':archive_sha,
            'original_members':len(original_records),'original_bytes':manifest['original_bytes'],
            'part_count':len(parts),'rpc_verbatim_count':len(rpc_checks),
            'publication_files_including_result':len(publication.files)+1,
            'all_published_files_max_bytes':MAX_PART_BYTES,
            'metadata_split_reassembly_literal_bytes_verified':True,
            'host_capture_closure_sha256':closure['closure_sha256'],
            'whole_host_filesystem_claimed':False,
            'wall_seconds_before_final_map_and_input_validation':time.monotonic()-started,
            'timing_does_not_include_final_map_and_commit_of_RESULT':True,
            'host_calls':0,'native_model_training_or_Git_actions':0,
            'final_head_gate_not_executed':True,
            'scope':'Cloud dbd6 archive and publication preparation only; no repair execution or experiment promotion.',
            'file_map_is_external_sidecar_not_its_own_member':True,
        }
        result_data=json_bytes(result)
        assert len(result_data)<=MAX_PART_BYTES
        result_row=identity(out/'RESULT.json',prefix+'/RESULT.json',result_data)
        assert result_row['path'] not in publication.files
        file_rows=sorted(list(publication.files.values())+[result_row],key=lambda row:row['path'])
        assert len({row['path'] for row in file_rows})==len(file_rows)
        file_map={
            'status':'FILE_MAP_REQUIRES_MATCHING_FINAL_SUCCESSFUL_RESULT',
            'files':file_rows,'file_count':len(file_rows),
            'total_bytes':sum(row['bytes'] for row in file_rows),
            'max_file_bytes':max(row['bytes'] for row in file_rows),
            'whole_tar_not_added_to_git':True,
            'final_head_gate_receipt_must_remain_external':True,
            'this_file_is_external_and_not_in_its_own_files_array':True,
            'metadata_reassembly_index':restoration_representation,
            'required_result':result_row,
        }
        file_map_data=json_bytes(file_map)
        put_new(out/'PUBLICATION_FILES.json',file_map_data)
        # The orchestration map is also preserved/split if oversized. Its storage
        # files stay in this external control list, outside its own evidence map.
        map_publication=Publication(out/'external-map-storage',prefix+'/publication-control')
        map_representation=map_publication.stage(
            out/'PUBLICATION_FILES.json',prefix+'/publication-control/PUBLICATION_FILES.json')
        assert map_publication.restore(map_representation)==file_map_data
        map_publication.verify_all()
        map_storage={
            'status':'EXTERNAL_CONTROL_FILES_FINAL_RESULT_REQUIRED',
            'file_map_representation':map_representation,
            'control_file_count':len(map_publication.files),
            'control_file_enumeration':'Follow the representation recursively; each descriptor retains the complete part file identity including its local path.',
            'not_members_of_their_own_evidence_file_map':True,
            'file_map_byte_identical':True,'required_result':result_row,
        }
        # This small root pointer contains recursive descriptor identities, not
        # an unbounded list of evidence or part rows. Descriptors carry the rows.
        map_storage_data=json_bytes(map_storage)
        assert len(map_storage_data)<=MAX_PART_BYTES
        put_new(out/'PUBLICATION_MAP_STORAGE.json',map_storage_data)
        assert (out/'PUBLICATION_MAP_STORAGE.json').read_bytes()==map_storage_data
        assert max(row['bytes'] for row in file_rows)<=MAX_PART_BYTES
        assert publication.verify_all()['all_split_originals_byte_identical']
        assert map_publication.restore(map_representation)==file_map_data
        assert current_paths(plan)==expected_paths
        for record in plan['included']:read_current(record)
        final_closure,unused=validate_closure(Path(closure['closure_path']),closure['closure_sha256'])
        assert final_closure==closure
        for pin in plan['controller_pins']:
            data,unused=stable_read(Path(pin['path']))
            assert len(data)==pin['bytes'] and sha256(data)==pin['sha256']
        # The candidate bytes are checked under a clearly non-final filename.
        # Only then does an atomic create-only hard link make RESULT visible.
        # There is no remaining validation or publication write after this commit.
        phase='commit_final_result'
        pending_result=out/'RESULT.prepared-bytes.json'
        put_new(pending_result,result_data)
        actual_result,unused=stable_read(pending_result)
        assert actual_result==result_data
        assert identity(out/'RESULT.json',result_row['path'],actual_result)==result_row
        os.link(pending_result,out/'RESULT.json')
        return result
    except BaseException as exc:
        failure={
            'status':'FAILED_PRESERVED','successful':False,'phase':phase,
            'error':repr(exc),'wall_seconds':time.monotonic()-started,
            'archive_only_verified':archive_verified,
            'publication_file_map_not_usable':True,
            'host_calls':0,'native_model_training_or_Git_actions':0,
            'partial_outputs_not_deleted':True,
        }
        # No failed invocation may retain an overall successful RESULT. If the
        # final file had been written, keep it under an explicitly invalid name.
        result_path=out/'RESULT.json'
        if result_path.exists():
            result_path.rename(out/'RESULT.invalid-candidate.json')
        put_new(result_path,json_bytes(failure))
        put_new(out/'FAILURE.json',json_bytes(failure))
        put_new(out/'exception.txt',traceback.format_exc().encode())
        raise



if __name__=='__main__':
    print(json.dumps(main(),ensure_ascii=False,indent=2))
