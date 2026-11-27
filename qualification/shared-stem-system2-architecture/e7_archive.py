"""Pinned real GitHub ZIP reader, shared STRICT parsing but no decision/scoring."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import zipfile

HISTORICAL_SHA = 'e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d'
PHYSICAL_SHA = 'd8e2af397d7ea862245fae0337588ab491dd70e8a8a9a42879e4a7f2d4be3afa'
PANEL_SHA = '8090d3b006364f3da780cea7f1bb91827e8024776e175aa99f5636597bfa644a'
REVISIONS = {'granite97':('835ad14087e140460703cf0fae09f97d469d65c2','cls_l2'),
             'mmbert_small':('0eb3d056ec1d6333cf4e19b0966dfde342a41a3a','masked_mean_l2')}
HEADS = ('frozen_gate','learned_gate','trained_linear')
ARMS = ('granite_only','mmbert_only','gate_conf_075','gate_conf_090','gate_conf_098')
THRESHOLDS = {'gate_conf_075':.75,'gate_conf_090':.9,'gate_conf_098':.98}
ROW_FIELDS = {'case_id','group_id','split','joint_input_digest','probs',
              'encoder_forward_ns','head_ns','input_tokens'}


def require(ok,msg):
    if not ok:
        raise ValueError(msg)


def digest(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()


def canonical(item)->bytes:
    return json.dumps(item,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')


def decode(b:bytes):
    def no_duplicates(items):
        out={}
        for k,v in items:
            if k in out:
                raise ValueError('duplicate object key')
            out[k]=v
        return out
    return json.loads(b,object_pairs_hook=no_duplicates,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def read_zip(path,sha256):
    path=Path(path)
    require(type(sha256) is str and sha256 in (HISTORICAL_SHA,PHYSICAL_SHA),
            'only registered real model evidence archives admitted')
    require(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=20_000_000,
            'bounded original ZIP missing')
    raw=path.read_bytes()
    require(digest(raw)==sha256,'registered Actions ZIP hash mismatch')
    with zipfile.ZipFile(path) as z:
        infos=z.infolist()
        require(0<len(infos)<=100 and len({x.filename for x in infos})==len(infos),
                'duplicate or excessive ZIP members')
        require(all(not x.is_dir() and not PurePosixPath(x.filename).is_absolute()
                    and '..' not in PurePosixPath(x.filename).parts and x.file_size<=2_000_000
                    and x.compress_size<=2_000_000
                    and (x.external_attr>>16 & 0o170000)!=0o120000
                    for x in infos),'unsafe ZIP member')
        require(sum(x.file_size for x in infos)<=10_000_000,'ZIP expansion budget')
        return {x.filename:z.read(x.filename) for x in infos}


def physical_rows(archive:dict[str,bytes]):
    """No historical labels or scorer imported; check actual presealed outputs."""
    require(type(archive) is dict,'physical archive map required')
    require('pre-score-seals.sha256' in archive and 'current-source.sha' in archive,
            'missing physical model evidence seals')
    checkout=archive['current-source.sha'].decode('ascii').strip()
    require(len(checkout)==40 and all(c in '0123456789abcdef' for c in checkout),
            'unbound physical source revision')
    seals=archive['pre-score-seals.sha256'].decode('utf-8')
    results={}
    identity=None
    for model,(revision,pooling) in REVISIONS.items():
        blob=archive[model+'.report.json']
        require(digest(blob) in seals,'model report absent from original evidence seal')
        log=decode(archive[model+'.stdout.log'])
        require(log.get('report_sha256')==digest(blob),'model stdout report SHA drift')
        report=decode(blob)
        require(report.get('schema')=='hepta.p0.compact.physical-trial.v1'
                and report.get('model_id')==model and report.get('revision')==revision
                and report.get('pooling')==pooling and report.get('authority')=='DENY_ALL'
                and report.get('production_accepted') is False
                and report.get('p0_accepted') is False and report.get('p1_accepted') is False
                and report.get('model_weights_executed_locally') is True
                and report.get('chronological_future_verified') is False
                and report.get('matched_full_lifecycle_cost') is False
                and report.get('authenticity_independently_verified') is False,
                'unadmitted physical report identity or claim')
        require(type(report.get('actual_encoder_forward_count')) is int
                and report['actual_encoder_forward_count']==352
                and report.get('q24_feature_dimension')==384,
                'unmatched reported model computation')
        original_identity=(report.get('source_sha256'),report.get('source_only_future_sha256'))
        if identity is None:
            identity=original_identity
        require(identity==original_identity,'same source required')
        rows=report.get('future_predictions')
        require(type(rows) is list and len(rows)==192
                and Counter(x.get('split') for x in rows)=={'test':64,'new_holdout':128},
                'missing original physical case coverage')
        selected={}
        for row in rows:
            require(type(row) is dict and set(row)==ROW_FIELDS,'physical raw row inventory changed')
            if row['split']!='new_holdout':
                continue
            cid=row['case_id']
            require(type(cid) is str and 1<=len(cid)<=128 and cid not in selected
                    and type(row['group_id']) is str and len(row['group_id'])==64
                    and type(row['joint_input_digest']) is str and len(row['joint_input_digest'])==64,
                    'missing or duplicated physical source identity')
            require(type(row['probs']) is dict and set(row['probs'])==set(HEADS)
                    and type(row['head_ns']) is dict and set(row['head_ns'])==set(HEADS),
                    'missing Head prediction/cost arms')
            for head in HEADS:
                p=row['probs'][head]
                require(type(p) in (int,float) and math.isfinite(p) and 0<=p<=1,
                        'invalid original model probability')
                require(type(row['head_ns'][head]) is int and row['head_ns'][head]>0,
                        'invalid original Head runtime')
            require(type(row['encoder_forward_ns']) is int and row['encoder_forward_ns']>0
                    and type(row['input_tokens']) is int and 0<row['input_tokens']<=512,
                    'invalid recorded Encoder time/tokens')
            selected[cid]=row
        require(len(selected)==128,'missing heldout model prediction rows')
        results[model]=selected
    require(set(results['granite97'])==set(results['mmbert_small']),
            'physical model case groups differ')
    for cid,gr in results['granite97'].items():
        mm=results['mmbert_small'][cid]
        require((gr['group_id'],gr['joint_input_digest'])==(mm['group_id'],mm['joint_input_digest']),
                'model input source misalignment')
    return results
