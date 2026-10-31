"""Independent row-level recheck; no training, model calls or study mutations."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import numpy as np

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
RUN = args.run
result = json.loads((RUN / 'RESULT.json').read_text())
rows = [json.loads(line) for line in (RUN / 'rows.jsonl').open()]
seeds = [17, 29, 43]
conditions = {'test': ['clean', 'occlusion', 'missing', 'heavy_noise'], 'retention': ['clean']}
counts = {'test':128, 'retention':96}
arms = ['A_frozen_fixed','B_ordinary_fixed','C_field_fixed','D_frozen_native','E_field_native','F_field_history','G_ordinary_native','H_frozen_history','I_field_reset','J_generic_fixed','K_richer_fixed']
expected = {(s,a,seed,p,c) for s in counts for a in arms for seed in seeds for p in range(counts[s]) for c in conditions[s]}
lookup = {(r['split'],r['arm'],r['seed'],r['pair'],r['corruption']):r for r in rows}
assert len(rows) == len(lookup) == len(expected) == 20064
assert set(lookup) == expected
identities = {}
for row in rows:
    key = row['split'],row['pair']
    value = tuple(row['source_ids'])
    assert identities.setdefault(key,value) == value
    assert row['refinement_count'] == 1+(row['action'] != 0)
assert len({x for pair in identities.values() for x in pair}) == 448

values = {(s,o,a):np.array([[[lookup[(s,a,seed,p,c)][o]['utility']-.002*lookup[(s,a,seed,p,c)]['refinement_count'] for c in conditions[s]] for p in range(counts[s])] for seed in seeds]) for s in counts for o in ['reward','audit'] for a in arms}
indices = {s:np.random.default_rng(271027+i).integers(counts[s], size=(4000,counts[s])) for i,s in enumerate(counts)}
errors = {'mean':[], 'per_seed':[], 'interval':[], 'pooled_ce':[]}
checks = []
for split, entries, tail in [('test',result['primary_contrasts'],.05/(2*6)),('retention',result['retention_vs_frozen'],.05/(2*9))]:
    for entry in entries:
        a,b = entry['candidate'],entry['control']
        for observer in ['reward','audit']:
            difference = values[(split,observer,a)] - values[(split,observer,b)]
            by_pair = difference.mean(axis=(0,2))
            interval = np.quantile(by_pair[indices[split]].mean(axis=1),[tail,1-tail])
            saved = entry['observers'][observer]
            errors['mean'].append(abs(difference.mean()-saved['mean_net_return_difference']))
            errors['per_seed'].extend(abs(difference.mean(axis=(1,2))-np.array([x['difference'] for x in saved['per_seed_mean_differences']])).tolist())
            errors['interval'].extend(abs(interval-np.array(saved['paired_cluster_interval'])).tolist())
            gain = bool(interval[0]>0 and np.all(difference.mean(axis=(1,2))>0))
            assert gain == saved['gain_supported']
            if split=='retention':
                assert bool(interval[0]>=-.01) == saved['noninferiority_supported']
            checks.append({'split':split,'candidate':a,'control':b,'observer':observer,'mean':float(difference.mean()),'ci':interval.tolist(),'gain':gain})
for key,v in values.items():
    split,observer,arm = key
    ce = -.5*np.log(np.exp(-2*v).mean())
    errors['pooled_ce'].append(abs(ce-result['summaries'][split+'/'+arm]['observers'][observer]['pooled_ce']))
for observer in ['reward','audit']:
    v = values[('test',observer,'E_field_native')]-values[('test',observer,'C_field_fixed')]-values[('test',observer,'D_frozen_native')]+values[('test',observer,'A_frozen_fixed')]
    ci = np.quantile(v.mean(axis=(0,2))[indices['test']].mean(axis=1),[.025,.975])
    saved=result['interaction_descriptive']['observers'][observer]
    errors['mean'].append(abs(v.mean()-saved['mean_net_return_interaction']))
    errors['interval'].extend(abs(ci-np.array(saved['descriptive_95_interval'])).tolist())
max_errors = {k:max(v,default=0) for k,v in errors.items()}
assert max(max_errors.values()) < 1e-12
assert not any(c['accepted_with_retention'] for c in result['primary_contrasts'])
output = {'scope':'Independent arithmetic on the completed rows; does not refit, call models, or re-score media. Media/native verification is the separate audit.', 'rows':len(rows),'unique_source_pairs':len(identities),'unique_source_ids':448,'complete_grid':True,'all_primary_acceptances_false':True,'maximum_numeric_discrepancy':max_errors,'rows_sha256':hashlib.sha256((RUN/'rows.jsonl').read_bytes()).hexdigest(),'result_sha256':hashlib.sha256((RUN/'RESULT.json').read_bytes()).hexdigest(),'checks':checks}
args.out.write_text(json.dumps(output,indent=2)+'\n')
print(json.dumps({k:v for k,v in output.items() if k!='checks'},indent=2))
