"""Independent clock/output arithmetic; imports neither Torch nor the replay worker."""
from pathlib import Path
import math

from four_gate_common import digest, require, strict_loads
from fbsde_acquisition_budget_audit import summarize_attempts


def read(root, name):
    path = root/name
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 64*1024*1024,
            'bounded regular clock observation')
    return strict_loads(path.read_bytes())


def verify_clocks(probe, attempt):
    samples = probe['samples']; intervals = probe['intervals']
    require(probe['sequence'] == attempt['sequence'] and probe['status'] == attempt['status'], 'clock attempt mismatch')
    require(len(samples) == 5 and len(intervals) == 4, 'all original phase endpoints required')
    for i,(a,b) in enumerate(zip(samples,samples[1:])):
        require(set(a)==set(b) and all(type(v) is int and v>=0 for v in (*a.values(),*b.values())), 'clock fields')
        delta = {k:b[k]-a[k] for k in a}
        require(all(v>=0 for v in delta.values()), 'nonmonotone diagnostic endpoint')
        delta['process_minus_caller_thread_cpu_ns'] = delta['process_cpu_ns']-delta['thread_cpu_ns']
        require(delta==intervals[i], 'clock interval arithmetic drift')
        name = ('text','encoder','head','receipt')[i]+'_cpu_ns'
        require(delta['process_cpu_ns']==attempt['phase_cpu_ns'][name], 'phase CPU drift')
    require(samples[-1]['process_cpu_ns']-samples[0]['process_cpu_ns']==attempt['cpu_ns'], 'view CPU drift')


def audit(directory):
    root = Path(directory); plan = read(root,'replay-plan.json'); processes = read(root,'processes.json')
    profiles = ['historical_2','bounded_1','bounded_2','passive_2']
    require(plan['profiles']==profiles and [r['profile'] for r in processes]==profiles, 'runtime comparison inventory')
    require(all(r['returncode']==0 and r['timeout'] is False for r in processes), 'child process failed')
    results = {}; bindings = []; returned_by_profile = {}; pids = []
    for profile in profiles:
        child = root/profile; binding = read(child,'binding.json'); summary = read(child,'summary.json')
        probes = read(child,'parallel-clocks.json'); predictions = read(child,'returned-predictions.json')
        require(binding['profile']==profile and binding['original_attempt']==plan['selected_attempt'], 'selected source drift')
        require(binding['repeats']==plan['repeats']==len(probes)==summary['attempts'] and
                summary['completed_fixed_work'] and summary['fatal_error'] is None, 'incomplete fixed-work protocol')
        require(binding['intra_threads']==(1 if profile=='bounded_1' else 2), 'thread configuration drift')
        if profile!='historical_2': require(binding['interop_threads']==1, 'inter-op drift')
        if profile=='passive_2': require(binding['environment']['OMP_WAIT_POLICY']=='PASSIVE', 'passive setting drift')
        bindings.append((binding['source_files_sha256'],binding['head_identity'],binding['backend']))
        pids.append(binding['pid'])
        budget = summarize_attempts(child)
        attempts = [strict_loads(line) for line in (child/'test-view-attempts.jsonl').read_bytes().splitlines()]
        require(len(attempts)==len(probes), 'missing attempted work')
        for probe,attempt in zip(probes,attempts): verify_clocks(probe,attempt)
        valid = {a['sequence'] for a in attempts if a['status']=='returned'}
        require(len(predictions)==len(valid)==summary['returned'] and
                summary['budget_rejected']==len(attempts)-len(valid) and
                {p['sequence'] for p in predictions}==valid, 'failed observation returned or missing')
        for row in predictions:
            p = row['probabilities']
            require(len(p)==8 and all(type(v) is float and math.isfinite(v) and 0<=v<=1 for v in p)
                    and abs(sum(p)-1)<1e-5 and row['symbol']==max(range(8),key=p.__getitem__), 'invalid replay output')
        returned_by_profile[profile] = {p['sequence']:p for p in predictions}
        results[profile] = {'budget':budget,'process_cpu_ns':sum(p['samples'][-1]['process_cpu_ns']-p['samples'][0]['process_cpu_ns'] for p in probes),
            'caller_thread_cpu_ns':sum(p['samples'][-1]['thread_cpu_ns']-p['samples'][0]['thread_cpu_ns'] for p in probes),
            'voluntary_switches':sum(p['samples'][-1]['voluntary_switches']-p['samples'][0]['voluntary_switches'] for p in probes),
            'involuntary_switches':sum(p['samples'][-1]['involuntary_switches']-p['samples'][0]['involuntary_switches'] for p in probes),
            'gc_collections':sum(p['samples'][-1]['gc_collections']-p['samples'][0]['gc_collections'] for p in probes),
            'whole_child_wall_ns':next(r['whole_child_wall_ns'] for r in processes if r['profile']==profile),
            'whole_child_cpu_ns':next(r['whole_child_cpu_ns'] for r in processes if r['profile']==profile)}
    require(all(b==bindings[0] for b in bindings), 'different frozen data/model across runtime arms')
    require(len(pids)==len(set(pids)), 'worker PID repeated; fresh process identity unresolved')
    common = set.intersection(*(set(v) for v in returned_by_profile.values()))
    differences = []; symbols = True; vectors = True
    for sequence in sorted(common):
        rows = [returned_by_profile[p][sequence] for p in profiles]
        symbols &= len({r['symbol'] for r in rows})==1
        vectors &= len({r['vector_sha256'] for r in rows})==1
        differences.extend(abs(a-b) for r in rows[1:] for a,b in zip(rows[0]['probabilities'],r['probabilities']))
    return {'schema':'hepta.cpu-tail-replay.audit.v1','profiles':results,
        'common_returned_attempts':len(common),'max_output_probability_difference':max(differences) if differences else None,
        'symbols_match_on_common_returns':symbols if common else None,
        'vector_hashes_match_on_common_returns':vectors if common else None,
        'all_attempts_in_cost_statistics':True,'process_budget_replaced_by_thread_budget':False,
        'diagnostic_sampling_is_not_simultaneous':True,'runtime_cause_established':False,
        'selected_runtime_for_production':None,'policy_or_learning_improvement_claimed':False,
        'physical_execution_authenticated':False,'production_promotion_permitted':False}


def audit_live(directory):
    """Bind contemporaneous thread clocks to original accepted AND failed attempts."""
    root = Path(directory); budget = summarize_attempts(root); checked = 0; errors = 0
    for split in ('validation','test'):
        source = root/f'{split}-view-attempts.jsonl'
        if not source.exists(): continue
        path = root/f'{split}-parallel-clocks.jsonl'
        require(path.is_file() and not path.is_symlink() and path.stat().st_size<=64*1024*1024, 'missing bounded live clocks')
        raw = path.read_bytes(); require(not raw or raw.endswith(b'\n'), 'partial live clock line')
        originals = [strict_loads(line) for line in source.read_bytes().splitlines()]
        supplemental = [strict_loads(line) for line in raw.splitlines()]
        require(len(originals)==len(supplemental), 'live clock coverage differs')
        previous = None
        for sequence,(attempt,probe) in enumerate(zip(originals,supplemental)):
            identity = probe.pop('attempt_sha256')
            require(identity==digest(probe) and probe['previous_sha256']==previous and
                    probe['sequence']==probe['source_sequence']==sequence and
                    probe['source_attempt_sha256']==attempt['attempt_sha256'], 'live clock binding drift')
            require(all(probe[k]==attempt[k] for k in ('split','id','arm','view','status')), 'live context drift')
            if attempt['status']=='execution_error': errors += 1
            else: verify_clocks(probe,attempt)
            previous = identity; checked += 1
    return {'schema':'hepta.cpu-live-clocks.audit.v1','matched_attempts':checked,
        'execution_errors_without_full_clock_check':errors,'budget':budget,
        'original_failure_preserved':bool(budget['failures']),
        'clock_overhead_is_measured':True,'runtime_cause_established':False,
        'production_promotion_permitted':False}
