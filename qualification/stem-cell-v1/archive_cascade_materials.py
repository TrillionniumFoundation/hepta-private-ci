"""Original-artifact owner: create exact historical source-bound, heldout-label-separated snapshots.

This uses archived *already executed* pretrained model predictions, NOT new
model forwards; public source labels are handled by a separate material owner.
"""
from __future__ import annotations
import argparse, hashlib, json, zipfile
from pathlib import Path

ORIGINAL_ZIP_SHA = 'e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d'
PHYSICAL_ZIP_SHA = 'd8e2af397d7ea862245fae0337588ab491dd70e8a8a9a42879e4a7f2d4be3afa'
SOURCE_PANEL_SHA = '8090d3b006364f3da780cea7f1bb91827e8024776e175aa99f5636597bfa644a'
SOURCE_INPUT_SHA = '8227fe173a759c42bfc75c56b877ba08a655de621df491c0851df1b2e7534e49'
MODELS = {'granite97': ('ibm-granite/granite-embedding-97m-multilingual-r2', '835ad14087e140460703cf0fae09f97d469d65c2', '6098b3e5141694fbf841f092631ef7f00abee606eca12a6c82d6249211ee4e57'),
          'mmbert_small': ('jhu-clsp/mmBERT-small','0eb3d056ec1d6333cf4e19b0966dfde342a41a3a','d5382f28e60627c0b4e35446b7bef84e9dc5ffb00cd76e4c1ab1b2a99f1cb2ac')}
DATA_SCHEMA = 'hepta.real-archive.stem-cascade-input.v1'
OWNER_SCHEMA='hepta.real-archive.stem-cascade-owner-label.v1'
SPLIT_SALT='hepta-20261015-granite97-mmbert-retrospective-fold-v1'


def raw_sha(x):return hashlib.sha256(x).hexdigest()
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')
def sha(x):return raw_sha(canonical(x))
def unique(pairs):
    obj={}
    for k,v in pairs:
        if k in obj:raise ValueError('duplicate JSON object key')
        obj[k]=v
    return obj

def checked_json(data):return json.loads(data,object_pairs_hook=unique,
  parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))

def checked_zip(path,expected,members):
    path=Path(path)
    if not path.is_file() or not 1000<=path.stat().st_size<5_000_000 or raw_sha(path.read_bytes())!=expected:
        raise ValueError('missing or changed original physical ZIP bytes')
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or any(v.startswith('/') or '..' in Path(v).parts for v in names):
            raise ValueError('unsafe duplicate or traversal archive member')
        result={}
        for member in members:
            if member not in names or z.getinfo(member).file_size>800000:
                raise ValueError('missing / oversized original archive member')
            result[member]=checked_json(z.read(member))
        return result


def assemble_archive(original_zip,physical_zip):
    h=checked_zip(original_zip,ORIGINAL_ZIP_SHA,['stem-agnews-new-source-panel.json','stem-agnews-source.json'])
    phys=checked_zip(physical_zip,PHYSICAL_ZIP_SHA,['granite97.report.json','mmbert_small.report.json','independent-scores.json','original-panel-receipt.json'])
    src=h['stem-agnews-new-source-panel.json'];score=phys['independent-scores.json']
    if (sha(src)!=SOURCE_PANEL_SHA or src.get('case_count')!=128
        or src.get('schema')!='hepta.stem.agnews-fresh-cross-sectional-cohort.v1'
        or src.get('same_public_source_family') is not True or src.get('chronological_future_claim') is not False
        or src.get('new_source_rows_disjoint_from_previous_study') is not True
        or src.get('selection_uses_model_predictions') is not False
        or src.get('source_signer_independently_authenticated') is not False
        or src.get('production_promotion')!='DENY_ALL'
        or score.get('authority')!='DENY_ALL' or score.get('source_digest')!=SOURCE_INPUT_SHA
        or score.get('labels_digest')!='27c2603e2c5019e82e6064ba6ed4e8553c7c4075ff58c80d5d6569ada8a8bad8'
        or phys['original-panel-receipt.json'].get('panel_digest')!=src.get('original_panel_digest')):
        raise ValueError('changed source cohort or scorer identity')
    src_rows={}
    for c in src['cases']:
        if (set(c)!={'case_id','group_id','joint_input','joint_input_digest','label','label_name','source_digest','split'}
          or c.get('split')!='new_holdout' or type(c.get('label')) is not int or c['label'] not in (0,1)
          or c.get('label_name')!=('world' if c['label']==0 else 'sports')
          or sha(c['joint_input'])!=c['joint_input_digest']
          or c['source_digest']!=c['group_id'] or c['source_digest'][:24]!=c['case_id']
          or c['case_id'] in src_rows):raise ValueError('new source row identity mismatch')
        src_rows[c['case_id']]=c
    if len(src_rows)!=128 or len({v['group_id'] for v in src_rows.values()})!=128:
        raise ValueError('independent source group census changed')
    model_rows={}
    for m,(repo,rev,expected_sha) in MODELS.items():
        data=phys[m+'.report.json']
        if (sha(data)!=expected_sha or data.get('schema')!='hepta.p0.compact.physical-trial.v1'
          or data.get('model_id')!=m or data.get('model_repository')!=repo or data.get('revision')!=rev
          or data.get('model_weights_executed_locally') is not True or data.get('actual_encoder_forward_count')!=352
          or data.get('q24_feature_dimension')!=384 or data.get('source_sha256')!=SOURCE_INPUT_SHA
          or data.get('authority')!='DENY_ALL' or data.get('production_accepted') is not False
          or data.get('matched_full_lifecycle_cost') is not False):
            raise ValueError('real pretrained original report identity drift')
        if score['report_sha256'][m]!=expected_sha:raise ValueError('original independent scoring seal drift')
        rows={}
        if len(data['future_predictions'])!=192:raise ValueError('incomplete original model prediction denominator')
        for p in data['future_predictions']:
            if p['split']!='new_holdout':continue
            if (p['case_id'] in rows or p['case_id'] not in src_rows or
                p['group_id']!=src_rows[p['case_id']]['group_id'] or
                p['joint_input_digest']!=src_rows[p['case_id']]['joint_input_digest'] or
                type(p['encoder_forward_ns']) is not int or p['encoder_forward_ns']<=0 or
                type(p['head_ns']['learned_gate']) is not int or p['head_ns']['learned_gate']<=0 or
                type(p['input_tokens']) is not int or not 1<=p['input_tokens']<=512 or
                type(p['probs']['learned_gate']) not in (float,int) or
                not 0<p['probs']['learned_gate']<1):
                raise ValueError('real pretrained original prediction/cost mismatch')
            rows[p['case_id']]=p
        if set(rows)!=set(src_rows):raise ValueError('missing original model predictions')
        correct=sum(int((r['probs']['learned_gate']>=.5)==bool(src_rows[cid]['label'])) for cid,r in rows.items())
        if correct!=score['models'][m]['quality']['new_holdout']['learned_gate']['correct']:
            raise ValueError('source labels do not independently replay original model accuracy')
        model_rows[m]=rows
    return src_rows,model_rows


def prepare(original_zip,physical_zip):
    src,models=assemble_archive(original_zip,physical_zip)
    ids=sorted(src,key=lambda key:(raw_sha((SPLIT_SALT+':'+key).encode()),key))
    cal=set(ids[:64]);ev=set(ids[64:]);assert len(cal)==len(ev)==64
    groups={'calibration':[],'evaluation':[]};labels={}
    for cid in sorted(src):
        x=src[cid];item=dict(case_id=cid,source_group=x['group_id'],joint_input_digest=x['joint_input_digest'],
            granite_probability=float(models['granite97'][cid]['probs']['learned_gate']),
            mmbert_probability=float(models['mmbert_small'][cid]['probs']['learned_gate']),
            granite_encoder_ns=models['granite97'][cid]['encoder_forward_ns'],
            mmbert_encoder_ns=models['mmbert_small'][cid]['encoder_forward_ns'],
            granite_head_ns=models['granite97'][cid]['head_ns']['learned_gate'],
            mmbert_head_ns=models['mmbert_small'][cid]['head_ns']['learned_gate'])
        if cid in cal:
            groups['calibration'].append(dict(**item,label=x['label']))
        else:
            groups['evaluation'].append(item);labels[cid]=x['label']
    common=dict(archive_original_sha256=ORIGINAL_ZIP_SHA,archive_physical_sha256=PHYSICAL_ZIP_SHA,
                original_model_prediction_sha256={k:v[2] for k,v in MODELS.items()},source_panel_sha256=SOURCE_PANEL_SHA,
                source_split_salt=SPLIT_SALT,model_forward_newly_executed=False,
                true_future_window=False,external_source_signer_verified=False,production_authorized=False,authority='DENY_ALL')
    material={key:dict(schema=DATA_SCHEMA,partition=key,rows=rows,**common) for key,rows in groups.items()}
    for v in material.values():v['material_id']=sha(v)
    owner=dict(schema=OWNER_SCHEMA,evaluation_material_id=material['evaluation']['material_id'],
        labels=labels,source_panel_sha256=SOURCE_PANEL_SHA,production_authorized=False,authority='DENY_ALL')
    owner['owner_id']=sha(owner)
    return material['calibration'],material['evaluation'],owner


def write_new(path,obj):
    with open(path,'x',encoding='utf8') as out:out.write(canonical(obj).decode()+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--historical-source-zip',required=True);p.add_argument('--real-physical-zip',required=True)
    p.add_argument('--output-dir',required=True);a=p.parse_args();path=Path(a.output_dir);path.mkdir(exist_ok=False,parents=True)
    try:
        c,e,o=prepare(a.historical_source_zip,a.real_physical_zip)
        for name,obj in (('calibration.json',c),('evaluation-blind.json',e),('evaluation-owner-labels.json',o)):
            write_new(path/name,obj)
        write_new(path/'SEALED.json',dict(schema='hepta.real-archive.material-seal.v1',
            files={n:raw_sha((path/n).read_bytes()) for n in ('calibration.json','evaluation-blind.json','evaluation-owner-labels.json')},
            evaluation_labels_not_for_policy_fit=True,real_pretrained_new_forward_claim=False,authority='DENY_ALL'))
    except Exception as error:
        write_new(path/'FAILED.json',dict(error_type=type(error).__name__,authority='DENY_ALL'))
        raise

if __name__=='__main__':main()
