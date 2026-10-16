"""SHA-pinned historical human/Reader inputs; no fresh Encoder or label guessing."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import time
import zipfile
from pathlib import Path

LOCKS = {
 'reader': (11946621518, '1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17'),
 'labels0': (11949305579, 'cb303e78cbbb1c9db400591e8a372609766a91213ddbdd323acd119ae1afb976'),
 'labels1': (11949100961, 'd17c501eb02709ede687c72e7f5c6d6a32e776d365e7f1bbd01ec4587048d4f5'),
 'human_score': (11953241456, '8f8ac3c4ed99b4859b9d0258d19c2afdaca1ac194a806130196b3d9980aa91a4'),
}
READERS = ('conditioned', 'mean_pool_query_fused', 'no_evidence', 'no_query')
LABEL_SOURCE = '5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada'


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(x):
    return hashlib.sha256(x).hexdigest()


def strict_loads(raw):
    def pairs(items):
        out = {}
        for k,v in items:
            if k in out: raise ValueError('duplicate JSON key')
            out[k] = v
        return out
    def bad(x): raise ValueError('nonfinite JSON: '+x)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


def write_new(path, data):
    with Path(path).open('xb') as f: f.write(canonical(data))


def member(path, role, name):
    raw = Path(path).read_bytes()
    if sha(raw) != LOCKS[role][1]: raise ValueError('original archive SHA mismatch: '+role)
    with zipfile.ZipFile(Path(path)) as z:
        if len(z.namelist()) != len(set(z.namelist())): raise ValueError('duplicate ZIP name')
        info = z.getinfo(name)
        if info.file_size > 1_000_000: raise ValueError('oversized source member')
        return strict_loads(z.read(name))


def load_sources(paths):
    observed = member(paths['reader'], 'reader', 'multirc-native-candidate-audit/audit.json')
    old_score = member(paths['human_score'], 'human_score', 'original-human-e16-centered-result.json')
    if old_score['original_validation_source_sha256'] != LABEL_SOURCE: raise ValueError('label lineage')
    raw_rows = observed['rows']
    ids = [r['task_id'] for r in raw_rows]
    if len(ids) != 33 or len(set(ids)) != 33: raise ValueError('candidate census')
    lookup = {r['task_id']: r for r in raw_rows}
    groups = sorted({r['source_group'] for r in raw_rows})
    if len(groups) != 4: raise ValueError('passage census')
    labels = {}
    for fold in (0,1):
        data = member(paths['labels'+str(fold)], 'labels'+str(fold), f'training-fold-{fold}.json')
        if (data['original_validation_human_label_source_sha256'] != LABEL_SOURCE
            or data['original_observation_id'] != observed['observation_id']
            or data['slate_id'] != observed['slate_id']
            or data['source_archive_sha256'] != LOCKS['reader'][1]
            or data['held_labels_exposed'] is not False): raise ValueError('fold source binding')
        these = data['training_label_rows']
        if len({r['task_id'] for r in these}) != len(these): raise ValueError('duplicate label')
        expected = {i for i in ids if lookup[i]['source_group'] != data['held_group']}
        if {r['task_id'] for r in these} != expected: raise ValueError('label fold completeness')
        for r in these:
            i,y = r['task_id'],r['label']
            if type(y) is not int or y not in (0,1): raise ValueError('invalid human label')
            if i in labels and labels[i] != y: raise ValueError('contradictory archived human label')
            labels[i] = y
    if set(labels) != set(ids): raise ValueError('incomplete genuine labels')
    predictions = {}
    for reader in READERS:
        rr = observed['predictions'][reader]
        if len(rr) != len(ids) or {r['task_id'] for r in rr} != set(ids): raise ValueError('Reader census')
        weights = {r['weights_sha256'] for r in rr}
        if len(weights) != 1: raise ValueError('Reader weight drift')
        predictions[reader] = {r['task_id']: r for r in rr}
    rows=[]
    for i in sorted(ids):
        rr=lookup[i]; margins=[]
        for reader in READERS:
            p=predictions[reader][i]
            if any(p[k] != rr[k] for k in ('source_group','question_slot')): raise ValueError('Reader row drift')
            logits=p['logits']
            if len(logits)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in logits):
                raise ValueError('invalid original logits')
            margins.append(logits[1]-logits[0])
        rows.append({'id':i,'group':rr['source_group'],'question':rr['question_slot'],
                     'base':margins[1], 'margins':margins})
    # No labels in within-question centering. Complete native slates are required.
    for r in rows:
        siblings=[s for s in rows if (s['group'],s['question'])==(r['group'],r['question'])]
        r['x']=[r['margins'][j]-sum(s['margins'][j] for s in siblings)/len(siblings) for j in range(4)]
    for r in rows:
        del r['margins']
    if len({(r['group'],r['question']) for r in rows})!=8: raise ValueError('question census')
    # Compare archived original-human aggregate, not labels inferred from scores.
    correct=sum(int((r['base']>0)==labels[r['id']]) for r in rows)
    if correct!=old_score['results']['mean_pool_query_fused']['correct']: raise ValueError('human-score mismatch')
    provenance={'artifacts':{k:{'id':v[0],'sha256':v[1]} for k,v in LOCKS.items()},
                'label_source_sha256':LABEL_SOURCE,'observation_id':observed['observation_id'],
                'model_snapshot_sha256':observed['model_snapshot_sha256'],
                'cached_reader_weights':{k:next(iter({r['weights_sha256'] for r in observed['predictions'][k]})) for k in READERS},
                'historical_reader_work':observed['additional_work_observation'],
                'fresh_encoder_forwards':0, 'fresh_original_reader_forwards':0,
                'label_source':'two original human training-fold archives, reconciled union',
                'new_download_of_original_parquet':False, 'independent_human_signature':False}
    return rows, labels, provenance


def prepare(paths, output):
    c,w=time.process_time_ns(),time.perf_counter_ns()
    output=Path(output); output.mkdir(parents=True,exist_ok=False)
    rows, labels, provenance=load_sources(paths)
    groups=sorted({r['group'] for r in rows})
    for j,g in enumerate(groups):
        train=[dict(r,label=labels[r['id']]) for r in rows if r['group']!=g]
        held=[r for r in rows if r['group']==g]
        write_new(output/f'fold-{j}.json',{'schema':'hepta.merton.real-head.fold.v1',
                  'fold':j,'held_group':g,'train':train,'held_inputs':held,'provenance':provenance})
    write_new(output/'scorer-labels.json',{'labels':labels,'rows':rows,'provenance':provenance})
    write_new(output/'prepare-receipt.json',{'cpu_ns':time.process_time_ns()-c,
              'wall_ns':time.perf_counter_ns()-w,'candidate_count':len(rows),'passage_count':4,
              'provenance':provenance,'input_files':{f'fold-{i}.json':sha((output/f'fold-{i}.json').read_bytes()) for i in range(4)}})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for role in LOCKS: p.add_argument('--'+role.replace('_','-'),required=True,type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); prepare({r:getattr(a,r) for r in LOCKS},a.output)
