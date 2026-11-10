"""Independent seed/manifest reconstruction of retained training-trace labels; JSON only."""
import hashlib
import json
from pathlib import Path
import random
from zipfile import ZipFile

BASE=Path('/workspace/scratch/c385a7439f8e')
LABELS=BASE/'final-retained-trace-labels-archive-v1'
ORIGINAL=BASE/'fresh42-terminal-small-v1'
OUT=Path(__file__).resolve().parent


def identity(path):
    raw=Path(path).read_bytes()
    return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def load(path):return json.loads(Path(path).read_bytes())


def save(path,value):
    with Path(path).open('x') as stream:stream.write(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')


def main():
    inputs={}
    def read(path):
        inputs[str(path)]=identity(path)
        return load(path)
    zip_path=BASE/'final-retained-trace-labels-20261110-v1.zip'
    assert identity(zip_path)==dict(bytes=39664,sha256='46a74ada1d695fd15e2d09303d41674ee61eeaa765cf34205d5a37c355630be2')
    with ZipFile(zip_path) as zipped:
        assert zipped.testzip() is None and len(zipped.namelist())==len(set(zipped.namelist()))
        for name in zipped.namelist():assert zipped.read(name)==(LABELS/name).read_bytes()
    package=read(LABELS/'MANIFEST.json')
    for name,item in package['files'].items():
        assert identity(LABELS/name)=={key:item[key] for key in ['bytes','sha256']}
    manifest_path=BASE/'uci-cloud-prepared-v1/data-manifest.json'
    manifest=read(manifest_path)
    assert identity(manifest_path)['sha256']=='0eb233da8d0b766c35356ba450d0572f1e6a87a47f1d8a17cd32c2ae6f25a1cb'
    assert not manifest['confirmation_access'] and manifest['mode']=='all-development'
    episodes=[e for e in manifest['episodes'] if e['partition']=='train']
    ids=[e['id'] for e in episodes]; sizes={e['id']:e['events'] for e in episodes}
    assert len(ids)==356 and sum(sizes.values())==89216
    archive_summary=read(ORIGINAL/'fresh42-terminal-archives-v1/SUMMARY.json')
    archive_rows={row['name']:row for row in archive_summary['rows']}
    aggregate=read(LABELS/'originals/RESULT.json')
    assert identity(LABELS/'originals/source.py')['sha256']==aggregate['source_sha256']
    names=[f'hcsn-s{s}-lr{lr}' for s in [101,211,307] for lr in ['0.001','0.003']]
    assert [row['name'] for row in aggregate['fits']]==names
    checked=[]
    for name in names:
        item=read(LABELS/'originals'/(name+'.json'))
        report_path=ORIGINAL/'campaign-v2'/name/'result.json'
        report,plan=read(report_path),read(report_path.with_name('plan.json'))
        archived=archive_rows[name];trace=archived['trace_files']['training-domain.jsonl']
        assert item['trace_sha256']==trace['sha256'] and item['trace_bytes']==trace['bytes']
        assert item['footer']==trace['last_json_record']
        assert item['epoch_ledger_sha256']==report['events_sha256']
        assert report['plan_sha256']==identity(report_path.with_name('plan.json'))['sha256']
        assert archived['result']['sha256']==identity(report_path)['sha256']
        assert item['data_manifest_sha256']==identity(manifest_path)['sha256']
        for native,digest in item['producer_sources'].items():
            relative=native.split('/run-source-v8/',1)[1]
            source=BASE/'v8-local-validation/source'/relative
            assert identity(source)['sha256']==digest==report['source_before'][native]
            inputs[str(source)]=identity(source)
        assert plan['batch_size']==32 and plan['micro_batch_size']==8
        target=item['footer']['captures']
        assert target==report['main_micro_forward_attempts']
        rng=random.Random(plan['seed'])
        captures=[];epoch=0
        while len(captures)<target:
            epoch+=1;order=list(range(len(ids)));rng.shuffle(order)
            for batch_no,offset in enumerate(range(0,len(ids),32)):
                whole=[ids[i] for i in order[offset:offset+32]]
                padded=max(sizes[e] for e in whole)
                for micro_start in range(0,len(whole),8):
                    group=whole[micro_start:micro_start+8]
                    captures.append(dict(epoch=epoch,update=(epoch-1)*12+batch_no,ids=group,
                        sizes=[sizes[e] for e in group],padded=padded))
                    if len(captures)==target:break
                if len(captures)==target:break
        seen_slots=sum(max(c['sizes']) for c in captures)
        valid_seen=sum(sum(c['sizes']) for c in captures)
        excluded=sum(len(c['sizes'])*c['padded']-sum(c['sizes']) for c in captures)
        assert seen_slots==item['seen_record_slots']==item['footer']['seen_records']
        assert valid_seen==item['reconstructed_seen_valid_sample_position_layer_states']
        assert excluded==item['footer']['padded_states_excluded']
        expected=[]
        for capture_no,c in enumerate(captures):
            for pos in range(max(c['sizes'])):
                expected.append(dict(index=len(expected),capture=capture_no,position=pos,layer=0,
                    update_index=c['update'],batch_indices=[i for i,n in enumerate(c['sizes']) if pos<n],
                    episode_id='+'.join(c['ids']),derived_epoch=c['epoch'],derived_phase='main'))
                if len(expected)==item['retained_record_slots']:break
            if len(expected)==item['retained_record_slots']:break
        labels=item['record_labels']
        assert len(labels)==len(expected)==item['footer']['retained_records']
        for actual,wanted in zip(labels,expected):
            assert all(actual[key]==value for key,value in wanted.items())
            assert actual['valid_sample_position_layer_states']==len(wanted['batch_indices'])
            assert actual['literal_epoch_field'] is None and actual['literal_phase_field'] is None
        valid_retained=sum(len(row['batch_indices']) for row in labels)
        assert valid_retained==item['retained_valid_sample_position_layer_states']
        assert all(row['update_index']==0 and row['derived_epoch']==1 for row in labels)
        assert item['post_update_retained_record_slots']==item['post_update_retained_valid_sample_states']==0
        assert item['footer']['drop_reason']=='byte_budget' and item['footer']['truncated'] is True
        assert item['footer']['dropped_records']==seen_slots-len(labels)
        assert item['retained_sample_state_fraction_of_reconstructed_seen']==valid_retained/valid_seen
        match=next(row for row in aggregate['fits'] if row['name']==name)
        assert all(item[key]==value for key,value in match.items())
        checked.append(dict(name=name,retained_record_slots=len(labels),retained_valid_sample_states=valid_retained,
            reconstructed_seen_valid_sample_states=valid_seen,seen_record_slots=seen_slots,excluded_padding=excluded,
            retained_fraction=valid_retained/valid_seen,captures=target,all_retained_before_first_update=True,
            post_update_retained_records=0,derived_epochs=[1],derived_phases=['main'],
            trace_sha256=item['trace_sha256'],original_report_sha256=identity(report_path)['sha256']))
    assert all(identity(Path(path))==item for path,item in inputs.items())
    result=dict(schema='independent-retained-trace-labels-JSON-review-v1',status='all_six_labels_and_count_reconstructions_agree',
        fits=checked,source_inputs=inputs,inputs_unchanged=True,source_package=identity(zip_path),
        examined_retained_record_labels=sum(row['retained_record_slots'] for row in checked),
        examined_retained_valid_sample_states=sum(row['retained_valid_sample_states'] for row in checked),
        execution_scope='Pure JSON and seeded-order reconstruction; no Torch import, model, forward, optimizer or numerical oracle.',
        provenance_scope='Label scan source/output commitments, original archive summary trace SHA/footer, original result/plan identities and exact local v8 source are bound. Large raw probability-trace bytes were not reread independently here.',
        denominator_scope='Full seen-valid-state denominator reconstructed from seeded epoch order, effective batch32 padding, microbatch8, manifest lengths and observed capture count; dropped probability states themselves are not available.',
        scientific_admission='HOLD',whole_training_numerical_admission='HOLD',model_reads=0)
    save(OUT/'RESULT.json',result)
    print(json.dumps(dict(status=result['status'],record_labels=result['examined_retained_record_labels'],valid_sample_states=result['examined_retained_valid_sample_states'],fits=checked)))


if __name__=='__main__':main()
