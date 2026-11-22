"""Independent hard-policy reader; never trusts recorded PASS or utilities."""
from pathlib import Path
import argparse
import json
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor'))
from data_contract import read, save, pin, verify, canonical, digest, serializable, head, exact_radius
from study_io import admit, checked, context
import value_graph


def independent_policy(graph, scores):
    mask = np.asarray(graph['masks'], dtype=bool)
    payoff = np.asarray(graph['terminal'])
    order = sorted(range(len(scores)), key=lambda i: graph['states'][i]['tick'])
    actions = np.array([max(np.flatnonzero(mask[i]), key=lambda a: (scores[i, a], -a))
                        for i in range(len(scores))], dtype=np.int64)
    value = np.zeros(len(scores))
    optimum = np.zeros(len(scores))
    qstar = payoff.copy()
    for i in reversed(order):
        for a in (1, 2, 3):
            if mask[i, a]:
                qstar[i, a] = sum(float(p) * (float(optimum[j])-float(fee))
                                  for p, j, fee in graph['edges'][i][a-1] if p)
        optimum[i] = max(qstar[i, a] for a in np.flatnonzero(mask[i]))
        a = actions[i]
        value[i] = (payoff[i, a] if a in (0, 4, 5) else
                    sum(float(p) * (float(value[j])-float(fee)) for p, j, fee in graph['edges'][i][a-1] if p))
    occupation = np.zeros(len(scores))
    occupation[graph['initial']] = 1
    reward = cost = continuation_gap = terminal_gap = terminal_mass = 0.
    raw_gap = optimum - qstar[np.arange(len(scores)), actions]
    for i in order:
        a = actions[i]
        mass = float(occupation[i])
        if a in (0, 4, 5):
            reward += mass * float(payoff[i, a])
            terminal_gap += mass * float(raw_gap[i])
            terminal_mass += mass
        else:
            continuation_gap += mass * float(raw_gap[i])
            for p, j, fee in graph['edges'][i][a-1]:
                if p:
                    occupation[j] += mass * float(p)
                    cost += mass * float(p) * float(fee)
    initial = graph['initial']
    residual = float(optimum[initial] - value[initial] - terminal_gap - continuation_gap)
    assert abs(residual) < 2e-10 and abs(value[initial] - reward + cost) < 2e-10
    assert abs(terminal_mass-1) < 2e-10 and raw_gap.min() > -2e-12
    metrics = dict(utility=float(value[initial]), optimal_utility=float(optimum[initial]),
        optimal_regret=float(optimum[initial]-value[initial]), expected_terminal_reward=reward,
        expected_expense=cost, terminal_gap_contribution=terminal_gap,
        continuation_gap_contribution=continuation_gap, PDI_residual=residual)
    return metrics, dict(scores=scores, actions=actions, values=value, occupancy=occupation, raw_gap=raw_gap)


def reader_scores(rows, H):
    logits = np.column_stack([np.sum(H * row, axis=1) for row in rows])
    probability = 1/(1+np.exp(-np.clip(logits[:, 3], -700, 700)))
    result = np.zeros((len(H), 6))
    result[:, 1:4] = logits[:, :3]
    result[:, 4], result[:, 5] = 1-2*probability, 2*probability-1
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, wall = time.process_time(), time.monotonic()
    protocol = admit(args.protocol, args.inputs)
    protocol_sha = pin(args.protocol)['sha256']
    ctx = context(protocol)
    input_by_hash = {x['sha256']: checked(args.inputs, x) for x in protocol['input_pins']}
    counts = dict(world_records=0, policy_records=0, alias_records=0, independently_rebuilt_new_worlds=0,
                  independent_policy_DPs=0, oracle_policy_DPs=0, maximum_PDI_residual=0.,
                  maximum_array_error=0., source_hashes_checked=len(protocol['input_pins']))
    def budget():
        if time.process_time()-started > protocol['limits']['verification']['cpu_soft_seconds']:
            raise TimeoutError('independent reader frozen CPU cap')
    values = {}
    for phase in ('generation', 'selection', 'confirmation'):
        directory = args.run_root / f'{phase}_attempt001' / 'output'
        result = read(directory/'RESULTS.json')
        process = read(directory.parent/'PROCESS.json')
        assert result['status']=='COMPLETED' and process['status']=='COMPLETED'
        assert result['protocol_sha256']==protocol_sha and process['protocol_unchanged']
        assert process['result_pin']['sha256']==pin(directory/'RESULTS.json')['sha256']
        original_root = Path(result['original_run_root'])
        def resolve(spec):
            old = Path(spec['path'])
            if old.is_relative_to(original_root):
                actual = dict(spec, path=str(args.run_root/old.relative_to(original_root)))
                verify(actual)
                return actual
            actual = input_by_hash[spec['sha256']]
            assert actual['bytes']==spec['bytes']
            return actual
        for fit in protocol['fit_ids']:
            budget()
            row = result['fits'][str(fit)]
            base = read(checked(args.inputs, protocol['fits'][str(fit)]['model'])['path'])
            anchor = head(base)
            models = {}
            for name, entry in row['models'].items():
                model = read(resolve(entry['model_pin'])['path'])
                protected = json.loads(canonical(model))
                for key in ('w2', 'b2'):
                    protected['network'][key]=base['network'][key]
                assert protected==base and exact_radius(anchor, head(model))['within_shared_ball']
                assert digest(canonical(model).encode())==entry['canonical_model_sha256']
                models[name]=head(model)
            records = {'gen': row['GEN_record_pin']} if phase=='generation' else row['records']
            values.setdefault(phase, {})[str(fit)]={}
            if phase=='generation':
                with np.load(checked(args.inputs, protocol['fits'][str(fit)]['hidden'])['path'], allow_pickle=False) as a:
                    old_hidden=a['H']
                cached={x['world_index']:x for x in protocol['fits'][str(fit)]['graphs']}
            for domain, record_pin in records.items():
                record=read(resolve(record_pin)['path'])
                assert record['protocol_sha256']==protocol_sha
                metrics_by_arm={a:[] for a in record['arm_order']}
                with np.load(resolve(record['arrays_pin'])['path'], allow_pickle=False) as saved:
                    for world in record['worlds']:
                        budget()
                        graph=read(resolve(world['graph_pin'])['path'])
                        if phase=='generation':
                            bounds=cached[world['world_index']]
                            H=old_hidden[bounds['row_start']:bounds['row_end']]
                        else:
                            rebuilt=value_graph.build(ctx,graph['public'],base,protocol['state_cap'],budget)
                            assert canonical(serializable(rebuilt))==canonical(graph)
                            X,_=value_graph.semantic_inputs(ctx,graph['public'],ctx.NumpyPolicy(base),rebuilt['states'],budget)
                            H=value_graph.strict_hidden(base,X)
                            with np.load(resolve(world['features_pin'])['path'],allow_pickle=False) as features:
                                assert np.array_equal(X,features['X']) and np.array_equal(H,features['H'])
                            counts['independently_rebuilt_new_worlds']+=1
                        computed={}
                        for name in record['arm_order']:
                            observed=world['arms'][name]
                            counts['policy_records']+=1
                            alias=observed['alias_of']
                            if alias is not None:
                                assert np.array_equal(models[name],models[alias])
                                assert observed['metrics']==world['arms'][alias]['metrics']
                                metric, arrays=computed[alias]
                                counts['alias_records']+=1
                            else:
                                scores=reader_scores(models[name],H)
                                metric,arrays=independent_policy(graph,scores)
                                counts['independent_policy_DPs']+=1
                            for key,value in metric.items():
                                assert abs(value-observed['metrics'][key])<2e-10,(phase,fit,name,key)
                            for key,array in arrays.items():
                                old=saved[observed['array_prefix']+'__'+key]
                                if key=='actions':assert np.array_equal(array,old),(phase,fit,name,'actions')
                                else:
                                    error=float(np.max(np.abs(array-old)))
                                    counts['maximum_array_error']=max(counts['maximum_array_error'],error)
                                    assert error<2e-10,(phase,fit,name,key,error)
                            counts['maximum_PDI_residual']=max(counts['maximum_PDI_residual'],abs(metric['PDI_residual']))
                            computed[name]=(metric,arrays)
                            metrics_by_arm[name].append(metric)
                        counts['world_records']+=1
                means={a:float(np.mean([x['utility'] for x in m])) for a,m in metrics_by_arm.items()}
                for name,mean in means.items():assert abs(mean-record['means'][name]['utility'])<2e-12
                values[phase][str(fit)][domain]=means
                if phase=='selection':
                    for family in ('DIRECT','BP'):
                        deltas=np.array([x['utility'] for x in metrics_by_arm[family]])-np.array([x['utility'] for x in metrics_by_arm['KEEP']])
                        choice=family if deltas.mean()>protocol['mean_improvement_threshold'] and deltas.min()>=-protocol['maximum_selection_world_loss'] else 'KEEP'
                        assert row['choices'][family]==choice
            if phase=='generation':
                oracle=read(resolve(row['oracle_pin'])['path'])
                for world in oracle['worlds']:
                    graph=read(resolve(world['graph_pin'])['path'])
                    bounds=cached[world['world_index']]
                    H=old_hidden[bounds['row_start']:bounds['row_end']]
                    for name in ('KEEP','Q_ORACLE','B_ORACLE','BOTH_ORACLE'):
                        scores=reader_scores(anchor,H)
                        if name in ('Q_ORACLE','BOTH_ORACLE'):scores[:,1:4]=np.asarray(graph['qstar'])[:,1:4]
                        if name in ('B_ORACLE','BOTH_ORACLE'):scores[:,4:6]=np.asarray(graph['terminal'])[:,4:6]
                        metric,_=independent_policy(graph,scores)
                        for key,value in metric.items():assert abs(value-world['arms'][name][key])<2e-10
                        counts['oracle_policy_DPs']+=1
    output=dict(status='PASS',protocol_sha256=protocol_sha,counts=counts,values=values,
        scope='Independent hard-policy value, occupancy, raw gaps, exact input/model hashes, new graphs/features and selection; not a new candidate search',
        CPU_seconds_from_entry=time.process_time()-started,wall_seconds=time.monotonic()-wall)
    save(args.output/'RESULTS.json',output)
    print(json.dumps({k:v for k,v in output.items() if k!='values'}))


if __name__=='__main__':main()
