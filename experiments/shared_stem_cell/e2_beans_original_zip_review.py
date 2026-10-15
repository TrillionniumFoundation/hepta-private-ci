"""Strictly read-only original four-artifact verifier for Beans E2 (research).

Archives and every ZIP SHA are supplied by a separate operator; no GitHub API,
model loader, source author, training process or original scorer is imported.
No token, checkpoint or production capability is accepted or generated.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import stat
import zipfile

SCHEMA = 'hepta.e2.beans-natural-retrospective.v1'
MODEL_REVISIONS = {
    'dino': '150c8e7bb7cef2d30ec31b13a517af14840ee3f7',
    'granite': '835ad14087e140460703cf0fae09f97d469d65c2',
}
DINO_WEIGHT_SHA = 'ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1'
DATA_REV = '27aa014ce09b193e1a6f58112d4a66e0eddb69c5'
DATA_TRAIN = '7f905a7323966a58e89b8e839ed656bb869fc82d16a3fadc7dce40972a5f8b19'
DATA_TEST = '534a6b0648f585d69b7ec0ad7a7540720d60c8db8106dc6d0508296316f6cb27'
SRC_FILES = {'train_images.jsonl','future_images.jsonl','train_anchors.jsonl','train_class.jsonl'}
TGT_FILES = {'future_caption_targets.jsonl','future_class_targets.jsonl'}
CLASSES = ('angular_leaf_spot','bean_rust','healthy')
ARMS = ('fitted','rotated_target_control','unaligned_identity','vision_prototype')
HEX = set('0123456789abcdef')

class Reject(ValueError):
    pass

def require(test, message):
    if not test: raise Reject(message)

def digest(raw): return hashlib.sha256(raw).hexdigest()

def is_sha(value):
    return type(value) is str and len(value)==64 and not set(value).difference(HEX)

def canon(data):
    return (json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                       allow_nan=False)+'\n').encode()

def json_object(raw):
    def pairs(items):
        out={}
        for key,value in items:
            require(key not in out, 'duplicate JSON field')
            out[key]=value
        return out
    data=json.loads(raw, object_pairs_hook=pairs,
                    parse_constant=lambda _: (_ for _ in ()).throw(Reject('nonfinite JSON')))
    require(raw==canon(data), 'noncanonical JSON bytes')
    return data

def json_lines(raw):
    require(raw and raw.endswith(b'\n'), 'empty/truncated JSONL')
    return [json_object(line+b'\n') for line in raw.splitlines()]

def original_zip(path, expected_sha):
    """Return a strict member dictionary after hashing complete ZIP bytes."""
    require(is_sha(expected_sha), 'operator ZIP sha pin missing')
    path=Path(path)
    require(path.is_file() and not path.is_symlink() and
            0<path.stat().st_size<=70_000_000, 'unsafe or oversized original ZIP')
    blob=path.read_bytes()
    require(digest(blob)==expected_sha, 'original ZIP pin mismatch')
    out={}
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            info=zf.infolist()
            require(0<len(info)<=512, 'invalid ZIP member census')
            total=0
            for member in info:
                key=member.filename
                require(type(key) is str and not key.startswith('/') and not key.startswith('\\')
                        and '\\' not in key and not any(p in ('.','..','') for p in key.strip('/').split('/'))
                        and not (member.flag_bits & 1)
                        and not stat.S_ISLNK(member.external_attr >> 16)
                        and member.file_size<=12_000_000, 'unsafe ZIP member')
                if member.is_dir(): continue
                require(key not in out, 'duplicate ZIP member')
                total+=member.file_size
                require(total<=110_000_000, 'unbounded ZIP extraction')
                out[key]=zf.read(member)
    except (zipfile.BadZipFile, RuntimeError, EOFError) as exc:
        raise Reject('invalid ZIP encoding') from exc
    return out

def member(items, suffix):
    """Allow the original GH artifact's root prefix but reject ambiguous names."""
    candidates=[value for key,value in items.items()
                if key==suffix or key.endswith('/'+suffix)]
    require(len(candidates)==1, 'missing or ambiguous original member: '+suffix)
    return candidates[0]

def receipt(items, suffix):
    return json_object(member(items,suffix))

def _validate_source_images(source, manifest):
    require(type(manifest) is dict and manifest.get('schema')==SCHEMA+'.source-plan'
            and manifest.get('dataset_repo')=='AI-Lab-Makerere/beans'
            and manifest.get('dataset_revision')==DATA_REV
            and manifest.get('train_parquet_sha256')==DATA_TRAIN
            and manifest.get('phase_time_is_not_original_timestamp') is True
            and manifest.get('train_cases')==36 and manifest.get('test_cases')==24
            and manifest.get('natural_images') is True
            and manifest.get('stem_selected') is False
            and manifest.get('production_accepted') is False
            and manifest.get('authority')=='DENY_ALL'
            and type(manifest.get('file_sha256s')) is dict
            and set(manifest['file_sha256s'])==SRC_FILES,
            'unapproved natural original source manifest')
    rows={}
    for filename in SRC_FILES:
        data=member(source,'source/'+filename)
        require(is_sha(manifest['file_sha256s'][filename]) and
                digest(data)==manifest['file_sha256s'][filename], 'source file altered: '+filename)
        rows[filename]=json_lines(data)
    train=rows['train_images.jsonl'];future=rows['future_images.jsonl']
    require(len(train)==36 and len(future)==24 and len(rows['train_class.jsonl'])==36
            and len(rows['train_anchors.jsonl'])==36, 'train/future count mismatch')
    groups=set();images=set();cases=set()
    train_max=0;future_min=2**63
    for phase,items in (('train',train),('future',future)):
        for row in items:
            require(type(row) is dict and set(row)=={
                'case_id','group_id','scope','observed_at','split','condition',
                'image_path','image_sha256','question','source_sha256'}, 'unexpected case metadata')
            require(row['split']==phase and row['condition']=='vision_required'
                    and row['scope']==manifest['scope']
                    and type(row['observed_at']) is int and 0<=row['observed_at']<2**63
                    and type(row['question']) is str and row['question'], 'invalid case phase/scope')
            key=row['case_id'];grp=row['group_id'];img=row['image_sha256'];filename=row['image_path']
            require(type(key) is str and key and key not in cases and
                    type(grp) is str and grp not in groups and
                    is_sha(img) and img not in images and
                    type(filename) is str and '/' not in filename and '\\' not in filename and
                    '..' not in filename and filename.startswith(key+'.'), 'case overlap or unsafe name')
            cases.add(key);groups.add(grp);images.add(img)
            image=member(source,'source/images/'+filename)
            require(50<len(image)<=3_000_000 and digest(image)==img, 'original photograph bytes differ')
            bound=digest(canon(['hepta.e2.image-case.v1',key,grp,row['scope'],
                                row['observed_at'],row['condition'],img,row['question']]))
            require(bound==row['source_sha256'], 'image/question source binding mismatch')
            if phase=='train':train_max=max(train_max,row['observed_at'])
            else:future_min=min(future_min,row['observed_at'])
    require(train_max<future_min, 'recorded ordinal phase conflict')
    train_by={r['case_id']:r for r in train}
    train_counts={c:0 for c in CLASSES};class_seen=set();anchor_seen=set()
    for cl in rows['train_class.jsonl']:
        require(type(cl) is dict and set(cl)=={'case_id','class_label'} and
                cl['case_id'] in train_by and cl['case_id'] not in class_seen and
                cl['class_label'] in CLASSES, 'train class label census corrupted')
        class_seen.add(cl['case_id']);train_counts[cl['class_label']]+=1
    for anchor in rows['train_anchors.jsonl']:
        require(type(anchor) is dict and set(anchor)=={
                'case_id','group_id','scope','observed_at','source_sha256','target_text'} and
                anchor['case_id'] in train_by and anchor['case_id'] not in anchor_seen and
                type(anchor['target_text']) is str and anchor['target_text'],
                'train text-anchor fields missing')
        anchor_seen.add(anchor['case_id'])
        require(all(anchor[k]==train_by[anchor['case_id']][k]
                    for k in ('case_id','group_id','scope','observed_at','source_sha256')),
                'train text-anchor case identity drift')
    require(train_counts=={c:12 for c in CLASSES} and
            class_seen==anchor_seen==set(train_by),'train paired label quotas mismatch')
    return rows

def _validate_withheld(withheld, source_hash, manifest, rows):
    target=receipt(withheld,'target-manifest.json')
    require(type(target) is dict and set(target)=={
        'schema','source_manifest_sha256','original_test_parquet_sha256',
        'file_sha256s','production_accepted','authority'},'invalid target manifest shape')
    require(target['schema']==SCHEMA+'.withheld-target-plan' and
            target['source_manifest_sha256']==source_hash and
            target['original_test_parquet_sha256']==DATA_TEST and
            type(target['file_sha256s']) is dict and set(target['file_sha256s'])==TGT_FILES and
            target['production_accepted'] is False and target['authority']=='DENY_ALL',
            'source/test manifest binding missing')
    clean={}
    for filename in TGT_FILES:
        data=member(withheld,filename)
        require(is_sha(target['file_sha256s'][filename]) and
                digest(data)==target['file_sha256s'][filename], 'future target changed: '+filename)
        clean[filename]=json_lines(data)
    target_rows=clean['future_class_targets.jsonl']
    require(len(target_rows)==24 and len(clean['future_caption_targets.jsonl'])==24,
            'future original label coverage missing')
    target_by={r['case_id']:r for r in target_rows}
    future={r['case_id']:r for r in rows['future_images.jsonl']}
    require(len(target_by)==24 and len(future)==24 and set(target_by)==set(future),
            'target/source case group mismatch')
    count={k:0 for k in CLASSES}
    for case,truth in target_by.items():
        row=future[case]
        require(type(truth) is dict and set(truth)=={
            'case_id','group_id','scope','observed_at','source_sha256','source_input_sha256','class_label'}
            and truth['class_label'] in CLASSES and
            all(truth[k]==row[k] for k in ('case_id','group_id','scope','observed_at','source_sha256'))
            and truth['source_input_sha256']==row['image_sha256'], 'future target/source drift')
        count[truth['class_label']]+=1
    require(count=={k:8 for k in CLASSES}, 'unbalanced or swapped natural class cohort')
    captions=clean['future_caption_targets.jsonl'];seen_captions=set()
    for cap in captions:
        require(type(cap) is dict and set(cap)=={
                'case_id','group_id','scope','observed_at','split','source_input_sha256','target_text'}
                and cap['split']=='future' and type(cap['target_text']) is str
                and cap['target_text'] and cap['case_id'] in future
                and cap['case_id'] not in seen_captions,
                'future Granite geometry targets invalid')
        seen_captions.add(cap['case_id'])
        original=future[cap['case_id']]
        require(all(cap[k]==original[k] for k in ('case_id','group_id','scope','observed_at'))
                and cap['source_input_sha256']==original['image_sha256'],
                'future geometry target source drift')
    require(seen_captions==set(future), 'withheld caption coverage mismatch')
    return clean, target

def _validate_producer(producer, source_manifest_hash, source, rows):
    required_forbidden=('future_caption_targets.jsonl','future_class_targets.jsonl','target-manifest.json')
    require(not any(key.endswith(x) for key in producer for x in required_forbidden),
            'withheld future labels appeared in encoder/producer ZIP')
    p=receipt(producer,'producer_receipt.json')
    require(p.get('schema')==SCHEMA+'.producer-receipt' and p.get('natural_images') is True
            and p.get('dataset_revision')==DATA_REV and p.get('dataset_train_sha256')==DATA_TRAIN
            and p.get('dino_revision')==MODEL_REVISIONS['dino']
            and p.get('granite_revision')==MODEL_REVISIONS['granite']
            and p.get('dino_weights_sha256')==DINO_WEIGHT_SHA
            and p.get('dino_train_forwards')==36 and p.get('dino_future_forwards')==24
            and type(p.get('granite_train_forwards')) is int and p['granite_train_forwards']>0
            and p.get('source_manifest_sha256')==source_manifest_hash
            and p.get('test_labels_seen') is False
            and p.get('model_origin_independently_attested') is False
            and p.get('production_accepted') is False and p.get('stem_selected') is False
            and p.get('authority')=='DENY_ALL', 'original paired model receipt invalid')
    linked={'fit_sha256':'bridge_fit.json',
            'sealed_geometry_sha256':'sealed_geometry_predictions.json',
            'sealed_class_sha256':'sealed_class_predictions.json',
            'granite_train_encoded_sha256':'granite_train/encoded.jsonl'}
    for name,path in linked.items():
        require(is_sha(p.get(name)) and digest(member(producer,path))==p[name],
                'producer artifact not byte-bound: '+path)
    for name,expected in (('vision_train/receipt.json',36),('vision_future/receipt.json',24)):
        img=receipt(producer,name)
        phase='train' if expected==36 else 'future'
        original_rows=rows['train_images.jsonl'] if phase=='train' else rows['future_images.jsonl']
        original_source_digest=digest(member(source,'source/'+phase+'_images.jsonl'))
        require(img.get('phase')==phase and img.get('source_sha256')==original_source_digest,
                'DINO physical input was not original source image JSONL')
        feature_rows=json_lines(member(producer,name.replace('receipt.json','features.jsonl')))
        require(len(feature_rows)==expected, 'vision physical feature census missing')
        source_cases={x['case_id']:x for x in original_rows};seen_feat=set()
        for entry in feature_rows:
            require(type(entry) is dict and entry.get('case_id') in source_cases
                    and entry['case_id'] not in seen_feat,'duplicate or extra original vision feature')
            seen_feat.add(entry['case_id']);raw=source_cases[entry['case_id']]
            require(all(entry.get(k)==raw[k] for k in ('case_id','group_id','scope',
                    'observed_at','condition','question','source_sha256'))
                    and entry.get('image_sha256')==raw['image_sha256'],
                    'original DINO feature source identity mismatch')
            f=entry.get('source')
            require(type(f) is dict and f.get('modality')=='image' and
                    f.get('input_sha256')==raw['image_sha256'] and
                    type(f.get('values')) is list and len(f['values'])==384 and
                    all(type(v) in (float,int) and math.isfinite(v) for v in f['values']),
                    'invalid original 384D frozen vision feature')
            norm=math.sqrt(math.fsum(v*v for v in f['values']))
            require(0.999<=norm<=1.001, 'frozen vision feature not unit normalized')
        img=receipt(producer,name)
        require(img.get('image_count')==expected and img.get('actual_model_forwards')==expected
                and img.get('checkpoint_locally_byte_verified') is True
                and img.get('publisher_authenticated') is False
                and img.get('labels_seen') is False
                and img.get('production_accepted') is False
                and img.get('authority')=='DENY_ALL'
                and img.get('encoder_revision')==MODEL_REVISIONS['dino']
                and img.get('snapshot_file_sha256s',{}).get('model.safetensors')==DINO_WEIGHT_SHA
                and img.get('output_sha256')==digest(member(producer,name.replace('receipt.json','features.jsonl'))),
                'vision original receipt/feature identity failure')
    text=receipt(producer,'granite_train/receipt.json')
    require(text.get('phase')=='train' and text.get('model_revision')==MODEL_REVISIONS['granite']
            and text.get('model_checkpoint_locally_verified') is True
            and text.get('physical_forwards')==p['granite_train_forwards']
            and text.get('encoded_sha256')==p['granite_train_encoded_sha256']
            and text.get('production_accepted') is False, 'Granite source/model-forwards not coupled')
    fit=receipt(producer,'bridge_fit.json')
    require(fit.get('train_examples')==36 and fit.get('production_accepted') is False
            and set(fit.get('bridges',{}))=={'fitted','rotated_target_control','unaligned_identity'},
            'incomplete trained + negative-control bridge')
    pred=receipt(producer,'sealed_class_predictions.json')
    require(pred.get('schema')==SCHEMA+'.class-predictions' and
            pred.get('arms')==list(ARMS) and pred.get('future_labels_seen') is False and
            pred.get('production_accepted') is False and pred.get('stem_selected') is False and
            pred.get('authority')=='DENY_ALL' and len(pred.get('rows',[]))==24,
            'future original class predictions absent')
    return pred,p

def _validate_evaluator(evaluator, source_hash, class_prediction_hash):
    score=receipt(evaluator,'independent_class_readout.json')
    require(score.get('schema')==SCHEMA+'.independent-class-readout' and
            score.get('source_manifest_sha256')==source_hash and
            score.get('predictions_sha256')==class_prediction_hash and
            score.get('total_cases')==24 and score.get('natural_original_images') is True
            and score.get('chronological_future_test') is False and
            score.get('independent_ground_truth_owner') is False and
            score.get('production_accepted') is False and score.get('authority')=='DENY_ALL',
            'independent original natural task score invalid')
    geometry=receipt(evaluator,'independent_geometry_readout.json')
    require(geometry.get('physical_future_granite_batched_forwards',0)>=1 and
            geometry.get('true_prospective_window') is False and
            geometry.get('production_accepted') is False, 'future real text model geometry missing')
    return score,geometry

def review_archives(paths, pins):
    require(set(paths)=={'source','withheld','producer','independent'} and
            set(pins)==set(paths), 'all four independent GitHub ZIP artifacts required')
    archives={k:original_zip(paths[k],pins[k]) for k in paths}
    source=archives['source'];withheld=archives['withheld'];producer=archives['producer']
    for collection in (source,producer):
        require(not any(name.endswith(x) for name in collection for x in
                    ('future_caption_targets.jsonl','future_class_targets.jsonl','target-manifest.json')),
                'withheld target material leaked into encoder-visible ZIP')
    source_manifest_bytes=member(source,'source-manifest.json')
    source_hash=digest(source_manifest_bytes)
    manifest=json_object(source_manifest_bytes)
    source_rows=_validate_source_images(source,manifest)
    targets,target_manifest=_validate_withheld(withheld,source_hash,manifest,source_rows)
    prediction,producer_receipt=_validate_producer(producer,source_hash,source,source_rows)
    scorer,geometry=_validate_evaluator(archives['independent'],source_hash,
                                        producer_receipt['sealed_class_sha256'])
    # Independently implement outcome recomputation: no original scorer/model imported.
    expected={r['case_id']:r for r in targets['future_class_targets.jsonl']}
    raw_correct={a:0 for a in ARMS};paired={a:{'rescued':0,'harmed':0,'both_correct':0,'both_wrong':0}
            for a in ARMS if a!='vision_prototype'}
    seen=set()
    for row in prediction['rows']:
        cid=row['case_id'];require(cid not in seen and cid in expected,'duplicate/extra predictions')
        seen.add(cid);label=expected[cid]['class_label']
        require(set(row.get('predicted_labels',{}))==set(ARMS) and
                all(row['predicted_labels'][a] in CLASSES for a in ARMS), 'unknown arm or class')
        source_row=next(r for r in source_rows['future_images.jsonl'] if r['case_id']==cid)
        require(all(row[k]==source_row[k] for k in ('case_id','group_id','scope','observed_at'))
                and row['source_input_sha256']==source_row['image_sha256'],
                'original future prediction source drift')
        correct={arm:row['predicted_labels'][arm]==label for arm in ARMS}
        for arm in ARMS:raw_correct[arm]+=int(correct[arm])
        for arm in paired:
            current,baseline=correct[arm],correct['vision_prototype']
            key='rescued' if current and not baseline else 'harmed' if baseline and not current else 'both_correct' if current else 'both_wrong'
            paired[arm][key]+=1
    require(len(seen)==24 and set(seen)==set(expected), 'original score row census mismatch')
    require(scorer['accuracy']=={a:{'correct':raw_correct[a],'total':24} for a in ARMS},
            'independent task results disagree with originals')
    require(scorer['paired_vs_frozen_vision_prototype']==paired,
            'original per-case paired correctness was misreported')
    return {'schema':'hepta.e2.beans-four-original-archives-review.v1',
            'input_zip_sha256s':pins,'original_source_manifest_sha256':source_hash,
            'original_withheld_target_manifest_sha256':digest(member(withheld,'target-manifest.json')),
            'cases':24,'real_original_model_receipts_consistent':True,
            'original_prediction_labels_recomputed':True,
            'correct_per_arm':raw_correct,'paired_vs_frozen_vision_prototype':paired,
            'source_dataset':'AI-Lab-Makerere/beans',
            'retrospective_public_test_only':True,
            'independent_training_or_model_execution_attestation':False,
            'independent_ground_truth_owner':False,
            'natural_future1_future2_future3_verified':False,
            'matched_compute_cost_verified':False,
            'five_arm_text_ocr_native_complete':False,
            'stem_selected':False,'production_accepted':False,'authority':'DENY_ALL'}

def main():
    p=argparse.ArgumentParser()
    for key in ('source','withheld','producer','independent'):
        p.add_argument('--'+key+'-zip',required=True)
        p.add_argument('--'+key+'-sha256',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    paths={k:getattr(args,k+'_zip') for k in ('source','withheld','producer','independent')}
    pins={k:getattr(args,k+'_sha256') for k in paths}
    result=review_archives(paths,pins)
    out=Path(args.output)
    require(not out.exists() and out.parent.is_dir() and not out.is_symlink(),
            'write-once output required')
    out.write_bytes(canon(result))
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
