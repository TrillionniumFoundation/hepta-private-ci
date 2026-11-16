"""Read-only frozen index, provenance and accounting checks; no resource recomputation."""
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

REPO=Path('/workspace/scratch/c385a7439f8e/hcsn-repo')
ROOT=REPO/'qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110'
OUT=Path(__file__).resolve().parent
EXPECTED_MANIFEST='0e94452d057082e028a408da8c0751fa4752a46019748215dc04b25f82395ac4'


def identity(path):
    raw=Path(path).read_bytes()
    return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def save(path,value):
    with Path(path).open('x') as stream:stream.write(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')


def values(value,path=''):
    if isinstance(value,dict):
        for key,child in value.items():yield from values(child,path+'/'+key)
    elif isinstance(value,list):
        for index,child in enumerate(value):yield from values(child,path+'/'+str(index))
    else:yield path,value


def main():
    inputs={}
    def read(path):
        path=Path(path);inputs[str(path)]=identity(path);return json.loads(path.read_bytes())
    manifest=read(ROOT/'MANIFEST.json')
    assert inputs[str(ROOT/'MANIFEST.json')]['sha256']==EXPECTED_MANIFEST
    assert len(manifest['files'])==228
    for name,item in manifest['files'].items():
        path=ROOT/name
        assert not Path(name).is_absolute() and '..' not in Path(name).parts and not path.is_symlink()
        assert identity(path)==item
    actual={str(path.relative_to(ROOT)) for path in ROOT.rglob('*') if path.is_file() and path.name!='.DS_Store'}
    assert actual==set(manifest['files'])|{'MANIFEST.json'}
    archives=[]
    for name in manifest['files']:
        if not name.endswith('.zip'):continue
        path=ROOT/name
        with ZipFile(path) as zipped:
            names=zipped.namelist()
            assert len(names)==len(set(names)) and zipped.testzip() is None
            assert all(not Path(n).is_absolute() and '..' not in Path(n).parts and '\\' not in n for n in names)
            archives.append(dict(path=name,members=len(names),**identity(path)))
    readme=(ROOT/'README.md').read_text()
    links=[]
    for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',readme):
        target=target.split()[0].strip('<>');url=urlsplit(target)
        if url.scheme or url.netloc or not url.path:continue
        path=(ROOT/unquote(url.path)).resolve()
        assert path.is_relative_to(REPO) and path.exists(),target
        item=dict(target=target,resolved=str(path),is_file=path.is_file())
        if path.is_file():item.update(identity(path));inputs[str(path)]=identity(path)
        links.append(item)
    costs,status,assets=[read(ROOT/name) for name in ['COSTS.json','STATUS.json','assets.json']]
    assert len(costs['rows'])==21 and costs['accounting_complete'] is False
    assert costs['total_elapsed_seconds'] is None and costs['total_energy_joules'] is None
    cost_bindings=[]
    for row in costs['rows']:
        path=(ROOT/row['artifact']).resolve()
        assert identity(path)==row['artifact_identity']
        raw=path.read_text()
        try:receipt=json.loads(raw)
        except json.JSONDecodeError:
            receipt=[json.loads(line) for line in raw.splitlines() if line.strip()]
        leaves=list(values(receipt));matches=[]
        for label,value in values(row['measurements']):
            if isinstance(value,(int,float)) and not isinstance(value,bool):
                candidates=[key for key,other in leaves if isinstance(other,(int,float)) and not isinstance(other,bool) and other==value]
                assert candidates,(row['id'],label,value)
                matches.append(dict(measurement=label,value=value,receipt_fields=candidates))
        cost_bindings.append(dict(id=row['id'],artifact=row['artifact'],identity=identity(path),numeric_bindings=matches,scope=row['scope']))
    prior=read(ROOT/assets['previous_index'])
    assert prior['verified_payload_count']==len(prior['verified_payloads'])==28
    pub=read(ROOT/assets['publication_receipt']['path'])
    assert identity(ROOT/assets['publication_receipt']['path'])=={k:assets['publication_receipt'][k] for k in ['bytes','sha256']}
    assert assets['new_payloads']==pub['assets'] and len(pub['assets'])==1
    assert pub['status']=='full_replay_asset_verified_draft_unchanged'
    assert len({r['asset_id'] for r in prior['verified_payloads']}|{r['asset_id'] for r in pub['assets']})==29
    assert assets['known_full_authenticated_payloads_after_this_addition']==29
    assert assets['original_model_asset_id'] in {r['asset_id'] for r in prior['verified_payloads']}
    assert all(r['authenticated_full_readback_verified'] and r['all_members_and_CRC_verified']
               and r['anonymous_asset_API']['HTTP_status']==r['anonymous_asset_browser']['HTTP_status']=='404' for r in pub['assets'])
    assert pub['final_draft_identity_verified']['draft'] is True
    failed=read(ROOT/assets['publication_failed_attempt'])
    assert not failed['assets'] and not any(r['label']=='upload-once' for r in failed['commands'])
    full_d=read(ROOT/'full-d-replay/SUMMARY.json')
    assert len(full_d['fits'])==status['full_D_replay']['passed']==status['full_D_replay']['fits']==6
    assert full_d['max_metric_absolute_difference']==status['full_D_replay']['max_metric_absolute_difference']
    assert all(r['training_adequacy'] is False and r['original_training_status']=='budget_exhausted'
               and r['metrics']['events']==31952 for r in full_d['fits'])
    labels=read(ROOT/'trace-coverage/independent-review-v1/RESULT.json')
    assert labels['examined_retained_record_labels']==status['original_trace_coverage']['retained_record_slots']==2066
    assert labels['examined_retained_valid_sample_states']==status['original_trace_coverage']['valid_sample_position_layer_states']==16492
    assert all(r['post_update_retained_records']==0 and r['all_retained_before_first_update'] for r in labels['fits'])
    original_plan=read(ROOT/'../p0p5-followup-20261110/original42/terminal-small/campaign-v2-plan.json')
    assert original_plan['equal_resource_process_elapsed_seconds']==original_plan['equal_resource_process_cpu_seconds']==[300,900,1800]
    assert original_plan['quality_threshold']==.3
    assert status['resource_analysis']['plan_was_post_terminal'] is True
    resource_review=read(ROOT/'independent-resource-review-v1/RESULT.json')
    # Deliberately do not reexecute its calculation; its exact bytes match the earlier independent result.
    assert identity(ROOT/'independent-resource-review-v1/RESULT.json')['sha256']=='b498c2d0dd72dff9d0243b749ccccd6c95caaddca932b8644a428910aa2d05b4'
    assert status['scientific_benefit']==status['whole_training_numerical_qualification']=='HOLD'
    assert status['original42_adequate']==26 and status['baseline_after_separate_C1_adequate']==33
    assert status['original_HCSN_adequate']==0 and status['confirmation_E_access'] is False
    ci=assets['hosted_science_artifact'];path=ROOT/ci['local_path']
    assert identity(path)=={k:ci['archive'][k] for k in ['bytes','sha256']}
    hosted=[]
    with ZipFile(path) as zipped:
        obj={name:json.loads(zipped.read(name)) for name in ['identity.json','outcome.json','qualification.json','error-budget.json','qvi-oracle.json','evidence-integrity.json']}
        ident=obj['identity.json'];outcome=obj['outcome.json']
        assert ident['source_head']==ci['source_head']==status['current_hosted_science']['source_head']
        assert ident['tested_commit']==ci['tested_merge'] and ident['source_tree']==ident['tested_tree']==ci['common_tree']
        assert ident['trees_equal'] and ident['run_id']==str(ci['run_id']) and ident['run_attempt']=='1'
        assert outcome['science_status']=='PASSED_DECLARED_FIXTURES' and all(v=='success' for v in outcome['steps'].values())
        qualification=obj['qualification.json'];budget=obj['error-budget.json'];integrity=obj['evidence-integrity.json']
        assert qualification['tests_run']==92 and qualification['source_unchanged'] is True
        assert len(budget['fixtures'])==4 and budget['source_unchanged'] is True
        assert len(integrity['verified_files'])==785 and integrity['passed'] is True
        for name,measurements,scope in [
            ('qualification.json',{'wall_seconds':qualification['wall_seconds'],'process_cpu_seconds':qualification['process_cpu_seconds'],
                'peak_rss_native':qualification['peak_rss_native'],'peak_rss_native_unit':qualification['peak_rss_native_unit']},
                'Producer main qualification interval, after imports. Reported process CPU is its sampled interval; RSS is process high-water mark. Not whole hosted job, billing, or artifact-download cost.'),
            ('error-budget.json',{'wall_seconds':budget['wall_seconds']},
                'Producer historical error-budget fixture interval; no complete process exit CPU or hosted job total is inferred.'),
            ('qvi-oracle.json',{'total_wall_seconds':obj['qvi-oracle.json']['total_wall_seconds']},
                'Small independent QVI fixture report timer; not neural free-boundary task gain or a full hosted job duration.'),
            ('qvi-tests.log',{'unittest_reported_seconds':.119,'tests':3},
                'Unittest internal elapsed time, excludes startup/import/teardown outside its runner; distinct from the oracle report, both nested in the hosted job.'),
            ('memory-controls-tests.log',{'unittest_reported_seconds':.003,'tests':3},
                'Unittest internal elapsed time, not complete process or actual memory-task training.')]:
            raw=zipped.read(name)
            if name.endswith('.log'):
                text=raw.decode();m=re.search(r'Ran (\d+) tests in ([0-9.]+)s',text)
                assert m and int(m.group(1))==3 and float(m.group(2))==measurements['unittest_reported_seconds']
            hosted.append(dict(member=name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),measurements=measurements,scope=scope))
    save(OUT/'HOSTED-FIXTURE-COST-ADDENDUM.json',dict(schema='exact-hosted-artifact-local-timing-addendum-v1',
        archive=identity(path),run_id=ci['run_id'],attempt=1,artifact_id=ci['artifact_id'],members=hosted,
        complete_hosted_job_CPU_seconds=None,complete_hosted_job_wall_seconds=None,billed_currency=None,energy_joules=None,
        additive_total=None,scope='Extracted existing artifact fields only. All fixture timers are nested within the hosted job and separate from archive download/collection. No CI or oracle rerun.',
        disposition='Known local fixture timings were retained in the artifact but not individually indexed by the frozen21-row ledger. This separate addendum indexes them without changing the frozen snapshot or claiming complete costs.'))
    for name,item in manifest['files'].items():assert identity(ROOT/name)==item
    assert identity(ROOT/'MANIFEST.json')['sha256']==EXPECTED_MANIFEST
    assert all(identity(Path(name))==item for name,item in inputs.items())
    result=dict(schema='independent-resource-replay-index-review-v1',status='passed_frozen_index_with_nonblocking_cost_index_addendum',
        reviewed_root=str(ROOT),manifest=identity(ROOT/'MANIFEST.json'),verified_files=228,
        zip_archives=archives,relative_links=links,cost_rows=cost_bindings,input_identities=inputs,
        sources_and_inputs_unchanged=True,blocking_findings=[],
        nonblocking_findings=[dict(id='INDEX-COST-01',status='closed_by_separate_addendum_not_by_mutating_snapshot',
            description='Hosted science local fixture timers are retained in the exact artifact but not separately indexed in the frozen top cost ledger.',
            closure_artifact='HOSTED-FIXTURE-COST-ADDENDUM.json')],
        manual_scope_review=['Post-terminal descriptive analysis with original prospective cuts; D tuning and SD are not E confirmation.',
            'C1 is an adaptive extra phase; original42 and continued views are explicit; all LR/seed costs preserved.',
            'Six successful quality replays retain original HCSN budget exhaustion and inadequacy.',
            'Original zero post-update retained training coverage is distinct from supplemental final-checkpoint numerical export.',
            'Bootstrap/controller/per-fit and publication nested timers are not additive; failed publication and unknown transport remain retained.',
            'Hosted science92 and declared budgets/QVI/controls do not establish all repository CI.',
            '29 is a retained-full-readback union, not a new full release inventory; preliminary/starter limitations remain.',
            'C2 and numerical audit are not claimed completed by this snapshot.'],
        execution_limits=dict(model_reads=0,forwards=0,optimizer_steps=0,numerical_oracles=0,resource_algorithm_recomputations=0),
        limitation='Filesystem/source-chain/index check of the frozen working snapshot only; a future Git commit/tree or external mutation needs its own receipt.')
    save(OUT/'RESULT.json',result)
    print(json.dumps(dict(status=result['status'],files=228,zips=len(archives),relative_links=len(links),cost_rows=len(cost_bindings),blocking_findings=0)))


if __name__=='__main__':main()
