"""Describe the already verified disabled candidate, without future P4 identities."""
from pathlib import Path
import hashlib
import json

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'v6-candidate'
BASE=ROOT.parent/'cli-duplicate-flag-v5'/'v5-candidate'
def iden(path):
    data=path.read_bytes()
    return {'path':str(path),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
            'blob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()}
source=json.loads((ROOT/'source-map-v6.json').read_bytes())
verify=json.loads((ROOT/'cloud-verification-v1'/'verification.json').read_bytes())
assert all((OUT/row['path']).read_bytes() and iden(OUT/row['path'])['sha256']==row['sha256'] for row in source['files'])
assert len(source['files'])==28 and len(verify['reconstructed_files'])==28
for row in verify['reconstructed_files']:
    assert iden(OUT/row['path'])['sha256']==row['sha256'],row['path']
manifest={
 'schema':'hepta-b16-v6-build-only-current-host-review-v1',
 'status':'SOURCE_ONLY_DISABLED_NO_ACTUAL_P4_BASELINE',
 'scope':'Add one explicit current-host build-only cache provenance branch; no native source, test, ref, launch, budget or historical result change.',
 'authority':{'parent_task':'/root authorized the V6 source-only branch and four necessary provenance guard counterexamples.',
              'bootstrap_plan_blob':'80e01271a43a894e35818715c70d55579c382eac',
              'bootstrap_plan':iden(Path('ci-audit/recovered-20261105/b16-alternative-host-readiness-v1/b16-ai395-bootstrap-plan-v1.json').resolve()),
              'execution_authorized':False},
 'base':{'runtime_directory':str(BASE),'integrity':iden(BASE/'runner-integrity.json'),'v5_preserved':True},
 'candidate':{'directory':str(OUT),'files':source['files'],'changed_files':source['changed_files'],
              'patch':iden(ROOT/'v5-to-v6.delta.patch'),'integrity':iden(OUT/'runner-integrity.json'),
              'disabled_template':iden(OUT/'foundation-build-only-binding-UNBOUND.json')},
 'known_source_context_not_a_future_baseline':{
    'new_host_alias':'ai395','code_commit':'20fd174ded4e5ce01bda34e4f6d1d74803301f49',
    'code_tree':'4a3374e22e16ce5c764288ad018cd9affadf94ea',
    'published_A_head':'0e139b599f0fe451f80fb7db4b2913bb9c679dce',
    'published_A_tree':'091e659e0da6602299fd14cfa93889191405edd8',
    'historic_tested_A_tree':'fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff',
    'historic_A_artifact_sha256':'48dcb2b104793c7dac9699803e4746d6d8145bcc66701de167de57cbf6bd3c6c',
    'last_tested_A_to_final_A_review':'40bd8b7030931cae6573ec126f4afc13a1140d33',
    'actual_P4_baseline':None,
    'limit':'CI confirmed P3 supply preparation is incomplete and P4 does not yet exist. These are known source references, not constructed future metadata or artifact hashes.'},
 'mode_contract':{
    'existing_mode':'reuse_final_A','new_mode':'BUILD_ONLY_CURRENT_HOST',
    'new_input_field':'current_host_build_only_baseline',
    'input_schema':'hepta-b16-current-host-build-only-baseline-v1',
    'required_boolean_values':{'tests_executed':False,'test_qualification':False},
    'actual_context_fields':['host(alias,uname,uid,euid)','cache_owner','source_directory','target_directory','source_commit','source_tree','ordinary_index','locks','tools','recipe_sources','cargo_profile','environment'],
    'required_actual_record_arrays':{'commands':3,'source_guards':6,'normal_helpers_before_catalog':6,'normal_helpers_after_catalog':6,'programs_after_catalog':363,'helpers_after_catalog':33},
    'metadata_and_catalog':'Complete original stdout pins; metadata193 members/1501 nodes, current source/target and foundation metadata equality; unfiltered full catalog; all program roles and helper roster checked.',
    'source_guard_format':'Use the actual bootstrap head/head_tree/working_tree/ordinary_index/guarded_files/untracked format, not fabricated renamed raw records.',
    'identity_extra_fields':'Original mode/dev/inode/git_blob/version fields remain in evidence. Locks/index compare their actual bytes+SHA; tool bindings compare name/path/bytes/SHA; recipes compare relative path/bytes/SHA. Existing SourceGuard and tool checks remain unchanged.',
    'new_host_environment_binding':'The final binding must copy the actual controlled P4 environment including new-host CARGO_HOME/RUSTUP_HOME and real tool/V8/cache paths. Null or omitted future values in the disabled template are not evidence.',
    'historical_evidence':'The exact historical artifact file can be copied as archival evidence. Its internal ROG program/helper paths and fb9 source remain unchanged. A build-only object cannot replace its tested-artifact role.',
    'family_derivation':'The immutable original family is retained. New current-host metadata/catalog/helper paths derive a separate BUILD_ONLY family with source_tree4a and explicit historical_roster_reference; it has no last_tested_A_tree label.',
    'future_epoch_continuity':'Same current-host pin/mode/host/owner plus every existing prior qualification/source/index/lock/graph guard. Immutable P4 is build provenance; original per-phase current builds/identities remain authoritative.',
    'rehash_scope':'All current 363+33 files are rehashed at foundation entry before source mutation. Subsequent epochs do not require rebuilt files to equal P4 hashes.',
    'internal_compatibility_names':'The loader privately maps after-catalog rows into existing capacity-arithmetic keys ending before_just. These aliases are not exported as an actual P4 just invocation; the original P4 receipt and published cache receipt explicitly retain BUILD_ONLY and tests_executed=false.'},
 'preservation':iden(ROOT/'preservation-verification.json'),
 'whole_legacy_branch_comparison':iden(ROOT/'legacy-branch-equivalence.json'),
 'unchanged_components':['b16_native.py including V5 single original no-fail-fast path','b16_oracles.py and all physical marker/panic/101 predicates','b16_locks.py and real two-lock generation gates','5 epoch manifests and all payload objects','SourceGuard class','negative_with_finally','execute_scopes','export_evidence','original foundation-output-family.json','original guard test bodies'],
 'budget':{'foundation_required_bytes':22000000000,'other_cargo_growth_bytes':12000000000,'evidence_growth_bytes':2000000000,'per_command_reserve_bytes':8000000000,'other_epoch_budget_rules_unchanged':True,'fresh_free_required':True,'peak_proven':False,'cache_cleanup_authorized':False},
 'validation':{'cloud_only':True,'receipt':iden(ROOT/'cloud-verification-v1'/'verification.json'),
               'four_guard_cases':[line.split(' ... ')[0] for line in (ROOT/'cloud-verification-v1'/'four-provenance-guard-controls.stderr').read_text().splitlines() if ' ... ok' in line],
               'guard_exit_code':verify['commands'][0]['exit_code'],'isolated_git_reconstruction_files':28,
               'native_started':False,'actual_P4_consumed':False,'B16_cases_executed':0,'A_test_qualification_granted':False},
 'necessary_next_gates':['Root and independent static review of V6 delta/integrity.','Complete actual P3/P4 original receipts, exact source/host/environment/tool/lock/artifact and command binding.','Create separate reviewed bound input and launcher only after actual P4 validation; keep old ROG evidence untouched.','Fresh approved free-space and unchanged source/ordinary index/HEAD guards before authorized foundation.','Run original foundation before driver adoption; all later epochs and their original real lock gates remain separately authorized.'],
 'internal_stage_ids_are_not_original_blocker_ids':True,
 'readme':iden(ROOT/'README.md'),
}
(ROOT/'review-manifest-v6.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(iden(ROOT/'review-manifest-v6.json'),indent=2))
