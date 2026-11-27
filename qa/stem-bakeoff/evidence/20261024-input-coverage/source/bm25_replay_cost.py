"""Replay frozen BM25 probabilities with no feature arrays, model, or test labels.

This is a separately declared post-hoc cost attribution check. It cannot choose
new k/temperature settings or modify the completed quality study.
"""

import gc
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import resource
import shutil
import sys
import time

import numpy as np

source=Path('/home/qian-qi/workspace/hepta-cell-input-20261024/qa/stem-bakeoff')
sys.path.insert(0,str(source))
from cell_learning_baselines import retained_state_bytes
from coverage_retrieval import CoverageRetrieval

root=Path('/data/hepta-cell-input-20261024')
fitted=root/'fitted-v2'
output=root/'bm25-cost-v1'


def sha_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()


def main():
    if '__file__' not in globals():
        raise ValueError('execute the persisted analysis source file so its exact bytes can be bound')
    if not (root/'score-v2/results.json').exists():
        raise ValueError('original quality scoring must finish first')
    if 'torch' in sys.modules or 'transformers' in sys.modules:
        raise ValueError('standalone lexical replay must not import an encoder runtime')
    output.mkdir(exist_ok=False)
    plan=json.loads((fitted/'fit_manifest.json').read_text())
    manifest=json.loads((root/'cohorts-v1/manifest.json').read_text())
    if (sha_file(root/'cohorts-v1/manifest.json')!=plan['dataset_manifest_sha256']
            or sha_file(root/'cohorts-v1/predictors.json')!=manifest['files']['predictors.json']
            or sha_file(fitted/'predictions.npz')!=plan['files']['predictions.npz']):
        raise ValueError('frozen source/prediction identity changed')
    rows=json.loads((root/'cohorts-v1/predictors.json').read_text())
    evaluation=[r for r in rows if r['split']=='evaluation']
    if [r['source_id'] for r in evaluation]!=plan['evaluation_source_ids']:
        raise ValueError('frozen evaluation predictor order differs')
    texts=[r['text'] for r in evaluation]
    with np.load(fitted/'predictions.npz',allow_pickle=False) as archive:
        frozen_predictions=archive['evaluation']
    records=[]
    for case in [c for c in plan['cases'] if c['policy']=='prefix']:
        start,cpu=time.perf_counter_ns(),time.process_time_ns()
        case_root=fitted/'cases'/case['case']
        for name in ('case.json','bm25_index.json.gz','retrieval.npz'):
            relative=str((case_root/name).relative_to(fitted))
            if sha_file(case_root/name)!=plan['files'][relative]:
                raise ValueError('frozen control artifact differs: '+relative)
        with np.load(case_root/'retrieval.npz',allow_pickle=False) as archive:
            # Selective loading of labels/indices; the feature array is never read.
            labels=archive['labels'].copy()
            indices=archive['source_indices'].copy()
        with gzip.open(case_root/'bm25_index.json.gz','rt',encoding='utf-8') as stream:
            decoded=json.load(stream)
        control=CoverageRetrieval.__new__(CoverageRetrieval)
        control.y=labels
        control.postings={token:(np.asarray(values[0],dtype=np.int32),np.asarray(values[1],dtype=np.float64))
                          for token,values in decoded.items()}
        del decoded
        control.source_utf8_bytes=sum(len(rows[i]['text'].encode()) for i in indices)
        source_ids=[rows[i]['source_id'] for i in indices]
        settings=case['controls']['bm25_topk']['calibration']
        state={'labels':control.y,'postings':control.postings,'source_ids':source_ids,
               'k':settings['k'],'temperature':settings['temperature']}
        control.memory=retained_state_bytes(state)
        loading={'wall_ns':time.perf_counter_ns()-start,'cpu_ns':time.process_time_ns()-cpu}
        start,cpu=time.perf_counter_ns(),time.process_time_ns()
        similarity,_=control.similarities('bm25_topk',None,texts)
        predicted=control.predict(similarity,settings)
        verification={'wall_ns':time.perf_counter_ns()-start,'cpu_ns':time.process_time_ns()-cpu}
        for policy in ('prefix','head_tail'):
            matches=[i for i,r in enumerate(plan['records']) if
                     (r['task'],r['seed'],r['budget'],r['policy'],r['arm'])==
                     (case['task'],case['seed'],case['budget'],policy,'bm25_topk')]
            if len(matches)!=1 or not np.array_equal(predicted,frozen_predictions[matches[0]]):
                failure={'case':case['case'],'policy':policy,'status':'frozen_prediction_replay_failed',
                         'no_refitting_or_setting_change_attempted':True}
                (output/'failure.json').write_bytes(canonical(failure)+b'\n')
                raise ValueError('standalone BM25 did not reproduce frozen probabilities: '+str(failure))
        samples=[]
        for repeat in range(5):
            start,cpu=time.perf_counter_ns(),time.process_time_ns()
            similarity,_=control.similarities('bm25_topk',None,texts)
            repeated=control.predict(similarity,settings)
            duration={'wall_ns':time.perf_counter_ns()-start,'cpu_ns':time.process_time_ns()-cpu}
            if not np.array_equal(repeated,predicted):
                raise ValueError('unchanged lexical replay produced different probabilities')
            samples.append(duration)
        state_root=output/'states'/case['case']
        state_root.mkdir(parents=True)
        with (state_root/'labels.npz').open('xb') as stream:
            np.savez_compressed(stream,labels=labels)
        shutil.copy2(case_root/'bm25_index.json.gz',state_root/'index.json.gz')
        metadata={'task':case['task'],'seed':case['seed'],'budget':case['budget'],
                  'source_ids':source_ids,'k':settings['k'],'temperature':settings['temperature'],
                  'normalization':'Unicode NFKC casefold, word tokens; unchanged frozen CoverageRetrieval',
                  'index_sha256':sha_file(state_root/'index.json.gz'),
                  'labels_sha256':sha_file(state_root/'labels.npz')}
        (state_root/'metadata.json').write_bytes(canonical(metadata)+b'\n')
        record={'case':case['case'],'task':case['task'],'seed':case['seed'],'budget':case['budget'],
                'k':settings['k'],'temperature':settings['temperature'],'evaluation_queries':len(texts),
                'frozen_prediction_pairs_reproduced':2,'bitwise_equal':True,
                'prediction_sha256':hashlib.sha256(predicted.tobytes()).hexdigest(),
                'standalone_state':control.memory,'standalone_serialized_bytes':sum(p.stat().st_size for p in state_root.iterdir()),
                'state_load_cost':loading,'first_verification_pass':verification,'timed_query_passes':samples,
                'source_utf8_bytes':control.source_utf8_bytes,
                'query_utf8_bytes':sum(len(t.encode()) for t in texts),
                'encoder_calls':0,'optimizer_steps':0,'feature_arrays_loaded':0}
        records.append(record)
        print(json.dumps({'stage':'standalone_bm25','completed_states':len(records),'case':case['case'],
                          'state_bytes':control.memory['reachable_state_bytes']}),flush=True)
        del control,state,similarity,repeated,predicted
        gc.collect()
    if len(records)!=24:
        raise ValueError('all 24 fixed task/seed/budget states required; no selective reporting')
    aggregate=[]
    for budget in (32,128):
        selected=[r for r in records if r['budget']==budget]
        wall=[s['wall_ns']/1e6 for r in selected for s in r['timed_query_passes']]
        cpu=[s['cpu_ns']/1e6 for r in selected for s in r['timed_query_passes']]
        aggregate.append({'budget':budget,'states':len(selected),'queries_per_pass':len(texts),
            'timed_passes':len(wall),'batch_wall_ms_p50':float(np.median(wall)),
            'batch_wall_ms_p95':float(np.quantile(wall,.95)),'batch_cpu_ms_p50':float(np.median(cpu)),
            'state_bytes_min':min(r['standalone_state']['reachable_state_bytes'] for r in selected),
            'state_bytes_max':max(r['standalone_state']['reachable_state_bytes'] for r in selected),
            'serialized_state_bytes_min':min(r['standalone_serialized_bytes'] for r in selected),
            'serialized_state_bytes_max':max(r['standalone_serialized_bytes'] for r in selected)})
    report={'schema':'hepta.standalone-bm25-cost-replay.v1','posthoc_analysis':True,
        'fit_manifest_sha256':sha_file(fitted/'fit_manifest.json'),'quality_predictions_changed':False,
        'evaluation_labels_opened':False,'k_or_temperature_refit':False,
        'model_runtime_imported':False,'encoder_calls':0,'feature_arrays_loaded':0,
        'original_algorithm_sha256':sha_file(source/'coverage_retrieval.py'),
        'analysis_source_sha256':sha_file(Path(__file__)),'numpy_version':importlib.metadata.version('numpy'),
        'matched_frozen_policy_states':48,'records':records,'aggregate':aggregate,
        'whole_process_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        'measurement_scope':'state graph contains labels, postings, source IDs and frozen settings; process peak also includes Python, NumPy, all source texts, stored predictions and temporary query matrices',
        'not_measured':'original from-source index build time separately from combined wrapper; individual-query tail latency; energy',
        'query_timing':'five full 256-source batches after one verification warmup per frozen state'}
    (output/'report.json').write_bytes(canonical(report)+b'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='records'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
