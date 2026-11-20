#!/usr/bin/env python3
"""Freeze a local-only dbd6 archive plan v2; never create an archive."""
from __future__ import annotations

import argparse
import ast
import json
from datetime import datetime,timezone
from pathlib import Path

from archive_common import ROOT,MAX_ORIGINAL_BYTES,content_role,excluded_name,git_blob,is_elf_header,json_bytes,metadata,safe_member,sha256,stable_read

from host_capture_closure_v2 import validate_closure

HERE=Path(__file__).resolve().parent
SOURCE='dbd6a00992b60f4b33e8f10c2defda031d123bcb'
TREE='fe037f5b6617fb647d416e0523685fa4ce08ef2f'
INPUT_ROOTS=[
 'e6_owner_work/initial_observation_diagnostic_candidate/rev1',
 'e6_owner_work/initial_observation_noupdate12_failure',
 'e6_initial_observation_runner_review_1',
 'e6_diagnostic_freeze_source_stage_peer_1',
 'e6_observation_control_review_1',
 'e6_initial_a_unavailable_diagnostic_candidate_2',
 'e6_initial_a_unavailable_diagnostic_candidate_3',
 'e6_noupdate12_c_drain_review',
]
EXTRA_FILES=[
 'e6_owner_work/deploy_initial_observation_diagnostic_pipeline1.py',
 'e6_owner_work/diagnostic_noupdate12_c_physical1_payload.json',
 'e6_owner_work/diagnostic_noupdate12_childlogs1_payload.json',
 'e6_owner_work/freeze_initial_observation_diagnostic_source1.py',
 'e6_owner_work/initial_observation_diagnostic_compile1_launcher.py',
 'e6_owner_work/initial_observation_diagnostic_compile1_meta.json',
 'e6_owner_work/initial_observation_diagnostic_compile1_payload.json',
 'e6_owner_work/initial_observation_diagnostic_freeze1_meta.json',
 'e6_owner_work/initial_observation_diagnostic_freeze1_payload.json',
 'e6_owner_work/initial_observation_diagnostic_gate1_launcher.py',
 'e6_owner_work/initial_observation_diagnostic_gate1_meta.json',
 'e6_owner_work/initial_observation_diagnostic_gate1_payload.json',
 'e6_owner_work/initial_observation_diagnostic_pipeline1_meta.json',
 'e6_owner_work/initial_observation_diagnostic_pipeline1_payload.json',
 'e6_owner_work/read_diagnostic_noupdate12_c_physical1.py',
 'e6_owner_work/read_diagnostic_noupdate12_childlogs1.py',
 'e6_owner_work/run_initial_observation_diagnostic_compile1.py',
 'e6_owner_work/run_initial_observation_diagnostic_gate1.py',
 'metrics_integration/final_evidence_publication_work/FROZEN_217_FILES.json',
 'metrics_integration/final_evidence_publication_work/FROZEN_257_FILES.json',
 'metrics_integration/execution-readout-intake-diagnostic-2/ROOT_GITHUB_BLOB_READBACK.json',
 'metrics_integration/final_evidence_publication_work/FROZEN_273_FILES.json',
 'metrics_integration/execution-readout-intake-diagnostic-3/ROOT_GITHUB_BLOB_READBACK.json',
]
OUT_OF_SCOPE=[
 'e6_noupdate12_c_drain_candidate_1',
 'e6_noupdate12_c_drain_candidate_2',
 'e6_c_drain_budget_owner_review_1',
 'metrics_integration/EXECUTION_READOUT_20261120.md',
 'metrics_integration/execution-readout-publication',
 'metrics_integration/execution-readout-intake-diagnostic-1',
 'metrics_integration/execution-readout-intake-diagnostic-2',
 'metrics_integration/execution-readout-intake-diagnostic-3',
 'e6_archive_readback_1',
 'e6_observation_diagnostic_review_publication_1',
]
REQUIRED_PINS={
 'e6_owner_work/initial_observation_diagnostic_candidate/rev1/RESULT.json':'b1d4e2126e75e62a20213a07a14e150f6fd83f4ffef98c19d8e288c4ab100649',
 'e6_owner_work/initial_observation_diagnostic_candidate/rev1/SOURCE_GATE_RESULT.json':'fc850c12616f1a1a51f35675457c80c63aff191eb8b86bdc4d5d6da0ca362050',
 'e6_owner_work/initial_observation_diagnostic_candidate/rev1/SOURCE_FREEZE_RESULT.json':'af4665cd2704b8c25a9ab44d963d79f11b83bfc307e69bb49be5741e7094dfca',
 'e6_owner_work/initial_observation_noupdate12_failure/PIPELINE_RESULT.json':'68ab50844539231700fee1c6ff700cce7ec904dd4bbb1dc64a941cc642e0e3a6',
 'e6_owner_work/initial_observation_noupdate12_failure/WRAPPER_RESULT.json':'98aff6cb4739c04a2e6b4bfb4fdc60d72003f1d6df78ac43df91ec4286255ef0',
 'e6_owner_work/initial_observation_noupdate12_failure/ordinary-post-a-no-update.xml':'65318b60bb71cacfe5961445de2d5092bd8be20a5ecb9f982c5f460df79226bc',
 'e6_owner_work/initial_observation_noupdate12_failure/ROOT_C_DRAIN_DIAGNOSIS_REVIEW.json':'4ac0ba2ff2c20b0d631743b59ded97d12fbad84e0b517aee67072c0a69aa47b2',
 'e6_owner_work/initial_observation_noupdate12_failure/C_LAYOUT_READOUT.json':'081db551d0cc1eb2e879883f92b7d78af86e8b2e702994e9eb624d917f01942c',
 'e6_noupdate12_c_drain_review/PHYSICAL_LAYOUT_READOUT.json':'e744b3f970ef98fb9a5c25191f0f089c5dbaa4073e2d06b50e2d3ce2b82e733c',
 'metrics_integration/final_evidence_publication_work/FROZEN_217_FILES.json':'5f03561e3cd81fedc499e323515f76f2f0adc2b6904a13543469f77d726c3315',
 'metrics_integration/final_evidence_publication_work/FROZEN_257_FILES.json':'d763647e01ebd4a04cbae8af0fe3c62b541e6ddc910b972efdac80027f3ae9bd',
 'metrics_integration/execution-readout-intake-diagnostic-2/ROOT_GITHUB_BLOB_READBACK.json':'d0dcb62ed931f6b12e27a026d947ebddae1529f9b185d906f068378d8bf13029',
 'metrics_integration/final_evidence_publication_work/FROZEN_273_FILES.json':'156f448802a8fa9253cf6e7cba0e8546131c6e9be5e0e9f4a526615bdf59a756',
 'metrics_integration/execution-readout-intake-diagnostic-3/ROOT_GITHUB_BLOB_READBACK.json':'14586ecfd3516e47d96363776f3b1dde1e5d7f6b424391c4c44ede765428b91a',
}


def enumerate_paths(extra_files):
    found={}
    for relative in INPUT_ROOTS:
        base=ROOT/relative
        assert base.is_dir(),relative
        for path in sorted(base.rglob('*')):
            if path.is_symlink() or path.is_file():
                found[str(path.relative_to(ROOT))]=path
    for relative in extra_files:
        assert safe_member(relative),relative
        p=ROOT/relative
        assert p.exists(),relative
        found[relative]=p
    return found


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--provisional-host-inventory',action='store_true',
                      help='Prepare a non-executable provisional plan; capture is not complete.')
    mode.add_argument('--host-capture-closure',type=Path,
                      help='Separately reviewed actual finite inventory/capture closure JSON.')
    parser.add_argument('--host-capture-closure-sha256')
    args=parser.parse_args()
    output=args.output.resolve()
    assert output.parent==HERE and not output.exists()
    closure_summary=None;closure_extras=[]
    if args.host_capture_closure is not None:
        assert args.host_capture_closure_sha256
        closure_summary,closure_extras=validate_closure(
            args.host_capture_closure.resolve(),args.host_capture_closure_sha256)
    else:
        assert args.host_capture_closure_sha256 is None
    extra_files=sorted(set(EXTRA_FILES+closure_extras))
    exact_receipt_exceptions={
        'metrics_integration/execution-readout-intake-diagnostic-2/ROOT_GITHUB_BLOB_READBACK.json',
        'metrics_integration/execution-readout-intake-diagnostic-3/ROOT_GITHUB_BLOB_READBACK.json',
    }
    for relative in extra_files:
        assert relative in exact_receipt_exceptions or not any(
            relative==blocked or relative.startswith(blocked+'/') for blocked in OUT_OF_SCOPE),relative
    inputs=enumerate_paths(extra_files);included=[];excluded=[]
    for relative,path in sorted(inputs.items()):
        meta=metadata(path);reason=excluded_name(path)
        if meta['symlink'] or not meta['regular']:
            reason='non-regular or symlink; body not followed'
        if reason:
            excluded.append({'workspace_relative_path':relative,'metadata':meta,'reason':reason,'body_opened':False})
            continue
        if is_elf_header(path):
            excluded.append({'workspace_relative_path':relative,'metadata':meta,
                             'reason':'ELF artifact; no body retained in archive','body_retained':False,
                             'type_probe_bytes_only':4})
            continue
        assert meta['bytes']<=MAX_ORIGINAL_BYTES,('Large non-ELF original must not be silently excluded; prepare a separately reviewed streaming reader.',relative)
        data,meta=stable_read(path)
        member='originals/'+relative;assert safe_member(member)
        rec={'member':member,'workspace_relative_path':relative,'original_path':str(path),
             'bytes':len(data),'sha256':sha256(data),'git_blob_oid':git_blob(data),
             'content_role':content_role(path,data),'source_metadata':meta}
        included.append(rec)
    by_name={r['workspace_relative_path']:r for r in included}
    assert len(by_name)==len(included)
    for relative,expected in REQUIRED_PINS.items():assert by_name[relative]['sha256']==expected,relative
    # Bind all five actual C inputs without opening any key file or host path.
    capture=ROOT/'e6_owner_work/initial_observation_noupdate12_failure/c-physical/CAPTURED_INPUTS.json'
    captured=json.loads(capture.read_text());assert len(captured)==5
    physical=[]
    for record in captured:
        local=capture.parent/Path(record['captured_path']).name
        rec=by_name[str(local.relative_to(ROOT))]
        assert rec['bytes']==record['bytes'] and rec['sha256']==record['sha256']
        physical.append({'member':rec['member'],'actual_remote_path':record['path'],'bytes':rec['bytes'],'sha256':rec['sha256']})
    child_logs=[r for r in included if '/childlogs/' in r['workspace_relative_path'] and r['workspace_relative_path'].endswith('.log')]
    assert len(child_logs)==12
    # The 273 upload receipts are a baseline, never an archive replacement.
    frozen_path=ROOT/'metrics_integration/final_evidence_publication_work/FROZEN_273_FILES.json'
    frozen=json.loads(frozen_path.read_text());assert len(frozen)==273
    for item in frozen:
        data,unused=stable_read(Path(item['local_path']))
        assert len(data)==item['bytes'] and sha256(data)==item['sha256']
        assert git_blob(data)==item['git_blob']==item['server_sha']
    controller_pins=[]
    for name in ['archive_common.py','prepare_archive_plan_v2.py','pack_verify_cloud_v2.py',
                 'publication_parts_v2.py','host_capture_closure_v2.py']:
        p=HERE/name;data=p.read_bytes();ast.parse(data,filename=str(p))
        controller_pins.append({'path':str(p),'bytes':len(data),'sha256':sha256(data)})
    rpc=[{'member':r['member'],'bytes':r['bytes'],'sha256':r['sha256'],'representation':'full original JSON bytes, no field removal or text reserialization'} for r in included if r['content_role']=='original_rpc_envelope_verbatim']
    plan={'schema':'hepta.e6.dbd6.cloud-original-archive-plan.v2',
          'status':'PREPARED_FOR_REVIEW_NOT_PACKAGED','prepared_at_utc':datetime.now(timezone.utc).isoformat(),
          'source':SOURCE,'tree':TREE,'source_inventory_sha256':'20fe46de4b63f5a2bcce469113ebe27b7514f942c7f960a71e4dabaa4f643d0f',
          'workspace_root':str(ROOT),'input_roots':INPUT_ROOTS,'extra_files':extra_files,
          'included_count':len(included),'included_bytes':sum(r['bytes'] for r in included),
          'included':included,'excluded_metadata':excluded,'out_of_scope_roots':OUT_OF_SCOPE,
          'out_of_scope_exception':'Only the exact named ROOT_GITHUB_BLOB_READBACK.json in prior intakes 2 and 3 are included as upload receipts; no report draft or C-repair implementation/design snapshot is included.',
          'rpc_count':len(rpc),'rpc_index':rpc,'rpc_transformations':0,
          'rpc_roundtrip_policy':'Restore every original envelope verbatim from archive and compare bytes to its source; hex/base64/text and every other field remain intact.',
          'actual_c_inputs':physical,'actual_child_stdio_count':12,
          'full_host_physical_inputs_claimed':False,
          'host_metadata_inventory_pending':closure_summary is None,
          'reviewed_runtime_capture_set_closed':closure_summary is not None,
          'host_capture_closure':closure_summary,
          'known_17_captured_raw_files_are_not_all_physical_material':True,
          'future_additions_require_a_new_plan_and_sha':'Do not silently extend this frozen input list. Later repair candidate/compile/runtime belongs to a separate snapshot.',
          'controller_pins':controller_pins,'frozen_upload_baseline':{'paths':273,'sha256':REQUIRED_PINS[str(frozen_path.relative_to(ROOT))]},
          'max_part_bytes':480000,'max_published_file_bytes':480000,
          'proposed_repository_prefix':'evidence/e6-observation-diagnostic-runtime-20261120/cloud',
          'sidecars_outside_tar':['ARCHIVE_RESULT.json','RESULT.json','archive-parts.json',
              'MEMBER_READBACK.json','RPC_RESTORE_READBACK.json','VERIFY_RESULT.json',
              'METADATA_REASSEMBLY.json','PUBLICATION_VALIDATION.json','PUBLICATION_FILES.json',
              'PUBLICATION_MAP_STORAGE.json'],
          'metadata_publication_policy':'Every oversized metadata file keeps its original bytes locally and is represented by exact <=480000-byte parts, recursively sized descriptors, and literal restoration checks.',
          'overall_success_policy':'RESULT successful=true may be written only after archive, all publication representations, publication map and unchanged inputs are verified. The external file map is not its own member.',
          'key_and_ELF_policy':'No key body is opened by filename-admitted collection; large artifacts and ELF bodies are excluded and only metadata retained. Existing RESULT/ELF metadata is preserved. This is not a universal secret scan.',
          'archive_executions':0,'archive_verifications':0,'host_calls':0,'native_model_training_or_Git_actions':0}
    output.mkdir()
    (output/'PLAN.json').write_bytes(json_bytes(plan))
    (output/'RPC_INDEX.json').write_bytes(json_bytes(rpc))
    (output/'EXCLUDED_METADATA.json').write_bytes(json_bytes({'excluded':excluded,'out_of_scope_roots':OUT_OF_SCOPE,'key_material_not_downloaded_by_this_task':True,'full_host_key_inventory_not_claimed':True}))
    result={'status':'INPUT_PLAN_ONLY_NO_ARCHIVE_EXECUTION','plan_path':str(output/'PLAN.json'),
            'plan_bytes':(output/'PLAN.json').stat().st_size,'plan_sha256':sha256((output/'PLAN.json').read_bytes()),
            'included_count':len(included),'included_bytes':sum(r['bytes'] for r in included),'rpc_count':len(rpc),
            'excluded_count':len(excluded),'verified_frozen_upload_receipts':273,
            'reviewed_runtime_capture_pending':closure_summary is None,
            'whole_host_filesystem_claimed':False,'source_repairs_excluded':True,
            'controller_syntax_only':True,'archive_pack_or_restore_executions':0}
    (output/'PREPARATION_RESULT.json').write_bytes(json_bytes(result))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
