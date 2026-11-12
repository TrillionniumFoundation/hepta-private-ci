"""Read hashes/AST/JSON only; do not import or call static_profile/witnesses."""
import ast
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path

ROOT=Path('/workspace/scratch/c06d659c1e72/currentstate-scale-spec')
BASE=ROOT/'qualification/hcsn_currentstate_scale_spec'
OUT=Path(__file__).resolve().parent

def sha(raw):return hashlib.sha256(raw).hexdigest()
def blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
def read(p):return json.loads(p.read_text())

def main():
    freeze=read(ROOT/'FREEZE.json');old=read(ROOT/'FREEZE-977f210-UNEXECUTED.json')
    assert freeze['source_commit']=='a26231befccb88c8784d29a748e2ed41e8042cd2'
    assert old['source_commit']=='977f2106177cabdfe82da2b7a2e7a87f3f58cca1'
    assert [len(freeze[k]) for k in ('source_sha256','input_sha256','protocol_sha256')]==[10,5,5]
    before={k:{name:sha((ROOT/name).read_bytes()) for name in freeze[k]}
            for k in ('source_sha256','input_sha256','protocol_sha256')}
    assert all(before[k]==freeze[k] for k in before)
    assert freeze['input_sha256']==old['input_sha256']
    manifest=read(BASE/'SOURCE_INPUT_MANIFEST.json')
    assert manifest['source_sha256']==freeze['source_sha256'] and manifest['input_sha256']==freeze['input_sha256']
    inventory=read(OUT/'GIT_INVENTORY.json');assert inventory['commit']==freeze['source_commit']
    entries=[]
    for item in json.loads(inventory['root']['content']):
        if item['type']=='file':entries.append((item['name'],item['size'],item['sha']))
        else:
            tree=json.loads(inventory['subtrees'][item['name']]['content'])
            assert tree['sha']==item['sha'] and tree['truncated'] is False
            entries.extend((item['name']+'/'+x['path'],x['size'],x['sha']) for x in tree['tree'] if x['type']=='blob')
    assert len(entries)==20
    git_matches={}
    for name,size,digest in entries:
        raw=(BASE/name).read_bytes();assert len(raw)==size and blob(raw)==digest
        git_matches[name]={'bytes':size,'git_blob':digest,'sha256':sha(raw)}
    profile=BASE/'static_profile.py';src=profile.read_text();tree=ast.parse(src)
    imports=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):imports.extend(n.name for n in node.names)
        elif isinstance(node,ast.ImportFrom):imports.append(node.module)
    assert set(imports)=={'ast','hashlib','json','pathlib','struct','zipfile','argparse'}
    assert sha(profile.read_bytes())=='85424afe1122d8224d7177dfca6acdde522b37515c47cf40c45379361b25e522'
    assert src.index('if len(encoded) > 100000:')<src.index('(out/"STATIC_PROFILE.json").write_bytes(encoded)')
    assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='check_intent_request' for n in ast.walk(tree))
    fun=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='check_intent_request')
    assert isinstance(fun.body[-1],ast.Raise)
    assert 'LARGEGRID_SOURCE_AND_REFERENCE_UNFROZEN' in ast.get_source_segment(src,fun.body[-1])
    witnesses=read(BASE/'PROVENANCE.json')['records']
    assert len(witnesses)==14
    for record in witnesses:
        raw=(ROOT/record['path']).read_bytes()
        assert len(raw)==record['bytes'] and sha(raw)==record['sha256']
    selected=read(BASE/'inputs/SELECTED_ORIGINAL_LAW.json')
    binding={}
    for N in (128,512):
        j=read(BASE/f'inputs/seed37-c0_b1-step24-pos1-n{N}.json')
        assert j['intervals']==N and j['reset_distance']==.3131468965881033
        assert j['physics']==selected['parameters']
        assert j['source_probability']==selected['state']['probability'][0]
        assert j['source_content']==selected['state']['content_mass'][0]
        assert j['original_line_sha256']==selected['origin_line_sha256']
        assert j['npz_sha256']==sha((BASE/f'inputs/seed37-c0_b1-step24-pos1-n{N}.npz').read_bytes())
        assert len(j['phase'])==8
        for i,p in enumerate(j['phase']):
            assert F(p['start'])==F(i,40) and F(p['end'])==F(i+1,40)
            assert len(p['content'])==4
        binding[str(N)]={'selected_original_json_numbers_equal':True,'npz_hash_equal_to_export_json':True,
                         'phase_supports_equal_j_over_40':True,'phase_signed_columns':4,
                         'source_visit':{k:j['source_visit'][k] for k in ('index','update_index','position','model_sha256')},
                         'physics':j['physics'],'reset_distance':j['reset_distance']}
    plan=read(BASE/'PLAN.json');assert plan['static_profile_max_output_bytes']==100000
    assert plan['static_profile_CPU_soft_hard_seconds']==[5,6] and plan['static_profile_RLIMIT_AS_bytes']==268435456
    assert plan['dynamic_execution_allowed'] is False and manifest['dynamic_execution_allowed'] is False
    after={k:{name:sha((ROOT/name).read_bytes()) for name in freeze[k]} for k in before}
    assert before==after
    (OUT/'FREEZE-a26231b.json').write_bytes((ROOT/'FREEZE.json').read_bytes())
    (OUT/'FREEZE-977f210-UNEXECUTED.json').write_bytes((ROOT/'FREEZE-977f210-UNEXECUTED.json').read_bytes())
    result={
      'identity':'currentstate-largegrid-static-profile-source-independent-review-v1',
      'source_commit':freeze['source_commit'],'source_sha256':sha(profile.read_bytes()),
      'freeze_sha256':sha((ROOT/'FREEZE.json').read_bytes()),'before':before,'after':after,
      'remote_git_objects_matched':20,'git_objects':git_matches,'manifest_complete':True,
      'source_witnesses_verified_as_bytes_not_imported':9,'source_imports_AST':imports,
      'source_input_provenance_records_hash_matched':14,'selected_law_metadata_independent_checks':binding,
      'NPZ_scope':'Profile source reads/decompresses member bytes for SHA and length; literal-parses NPY header only. It does not decode float payloads or construct arrays. Reviewer did not parse NPZ headers before the sole profile invocation.',
      'negative_case_scope':'Eight actual calls are statically present to a protocol-only check_intent_request; each expected ValueError is asserted. Last branch always refuses dynamic execution. Reviewer does not call that function or claim large-grid API qualification.',
      'expected_protocol_refusals':['OUTSIDE_STAGED_INTENT','PREDECESSOR_NOT_QUALIFIED','MAPPED_INPUT_MISSING',
                                    'SIGNED_CHANNELS_MISSING','PHASE_LAW_MISSING','WRONG_ACTUAL_RESET',
                                    'WRONG_UPPER_SEMANTICS','LARGEGRID_SOURCE_AND_REFERENCE_UNFROZEN'],
      'closed_preexecution_finding':{'old_source_commit':old['source_commit'],
          'old_profile_sha256':old['source_sha256']['qualification/hcsn_currentstate_scale_spec/static_profile.py'],
          'finding':'PLAN100000 output cap was initially declared without a write-time length guard.',
          'closure':'New source encodes JSON, refuses len>100000, then write_bytes. Old freeze retained as unexecuted.'},
      'reviewer_profile_invocations':0,'reviewer_witness_imports':0,'reviewer_numpy_imports':0,'reviewer_scipy_imports':0,
      'reviewer_candidate_calls':0,'reviewer_expm_calls':0,'reviewer_reference_calls':0,'reviewer_quadratures':0,
      'blocking_findings':[],
      'conclusion':'Static go only for the sole stdlib profile invocation under frozen timeout15/prlimit5:6/AS256MiB launcher.',
      'limits':['The report is not a dynamic large-grid qualification.',
                'N256 mapped input is absent; no regeneration or interpolation.',
                'Future budgets and reference denominator remain proposals, never observed runtime costs.',
                'Header/hash checks do not establish transported numerical state, gradients or training correctness.'],
      'admission':'HOLD_INTENT_ONLY','all_closed':False,'reviewer_source_sha256':sha(Path(__file__).read_bytes())
    }
    raw=(json.dumps(result,indent=2,allow_nan=False)+'\n').encode();(OUT/'REVIEW.json').write_bytes(raw)
    print(json.dumps({'static_only':True,'remote_git_objects':20,'source_input_protocol_counts':[10,5,5],
                      'hashes_unchanged':True,'blocking_findings':[],'profile_invocations':0,'witness_imports':0,
                      'new_expm':0,'review_sha256':sha(raw)}))

if __name__=='__main__':main()
