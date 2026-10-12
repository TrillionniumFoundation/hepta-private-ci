"""Fixed-work CPU replay of a saved acquisition attempt; never a policy retry.

Each runtime configuration gets a fresh interpreter. Rejected observations remain
rejected, all scheduled diagnostic attempts are retained, and no outcomes scored.
"""
import argparse
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

from four_gate_common import canonical, digest, require, strict_loads, write_once
from fbsde_acquisition_observe import AttemptJournal, observe_view, ViewBudgetExceeded

PROFILES = ('historical_2', 'bounded_1', 'bounded_2', 'passive_2')
SOURCE_FILES = ('plan.json', 'physical.json', 'input-inventory.json', 'candidate-head.pt')


def read_bytes(root, name, limit=16*1024*1024):
    path = root/name
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit,
            'bounded regular replay input')
    return path.read_bytes()


def select_attempt(root):
    """Select first rejection, otherwise first attempt; never inspect a label."""
    first = None
    for split in ('validation', 'test'):
        if not (root/f'{split}-view-attempts.jsonl').exists():
            continue
        raw = read_bytes(root, f'{split}-view-attempts.jsonl', 64*1024*1024)
        require(not raw or raw.endswith(b'\n'), 'partial attempt journal')
        previous = None
        for sequence, line in enumerate(raw.splitlines()):
            row = strict_loads(line); identity = row.pop('attempt_sha256')
            require(identity == digest(row) and row['previous_sha256'] == previous and
                    row['sequence'] == sequence and row['split'] == split, 'attempt chain mismatch')
            previous = identity
            row['attempt_sha256'] = identity
            if first is None: first = row
            if row['status'] != 'returned': return row
    require(first is not None, 'no attempted view to replay')
    return first


class PhaseClock:
    """Parallel clock readings do not replace the original PROCESS CPU budget.

    Endpoints are sequential snapshots, not simultaneous. Signed process-minus-
    thread differences can be negative at small scale; never clamp them to zero.
    """
    def __init__(self): self.samples = []

    def __call__(self):
        cpu = time.process_time_ns(); thread = time.thread_time_ns(); wall = time.perf_counter_ns()
        usage = resource.getrusage(resource.RUSAGE_SELF)
        self.samples.append({'process_cpu_ns': cpu, 'thread_cpu_ns': thread, 'wall_ns': wall,
            'voluntary_switches': usage.ru_nvcsw, 'involuntary_switches': usage.ru_nivcsw,
            'minor_faults': usage.ru_minflt,
            'gc_collections': sum(g['collections'] for g in gc.get_stats())})
        return cpu

    def report(self):
        deltas = [{k: b[k]-a[k] for k in a} for a,b in zip(self.samples,self.samples[1:])]
        for row in deltas: row['process_minus_caller_thread_cpu_ns'] = row['process_cpu_ns']-row['thread_cpu_ns']
        return {'samples': self.samples, 'intervals': deltas, 'simultaneous_endpoints': False}


def run_worker(evidence, output, profile, repeats, model_dir=None):
    require(profile in PROFILES and type(repeats) is int and 1 <= repeats <= 1024,
            'registered bounded runtime experiment')
    require(sys.platform.startswith('linux'), 'Linux CPU accounting profile required')
    output.mkdir(parents=True, exist_ok=False)
    envelope = time.process_time_ns()
    import torch
    from fbsde_acquisition_data import text_view, hashed_reference
    from fbsde_acquisition_study import make_head
    from four_gate_capture import tensor_digest

    # Called before constructing any tensor/model; inter-op is set only once.
    torch.set_num_threads(1 if profile == 'bounded_1' else 2)
    if profile != 'historical_2': torch.set_num_interop_threads(1)
    original = select_attempt(evidence)
    hashes = {n: hashlib.sha256(read_bytes(evidence,n)).hexdigest() for n in SOURCE_FILES}
    plan = strict_loads(read_bytes(evidence,'plan.json'))
    physical = strict_loads(read_bytes(evidence,'physical.json'))
    require(hashes['candidate-head.pt'] == physical['candidate_head_file_sha256'], 'Head file drift')
    inventory = strict_loads(read_bytes(evidence,'input-inventory.json'))
    matches = [r for r in inventory[original['split']] if r['id'] == original['id']]
    require(len(matches) == 1, 'replay source not unique')
    row = matches[0]; text = row['text']; view = original['view']
    require(digest(text) == row['text_sha256'] == original['source_input_sha256'] and
            digest(text_view(text,view)) == original['text_sha256'], 'original view text drift')
    bundle = torch.load(evidence/'candidate-head.pt', map_location='cpu', weights_only=True)
    head = make_head(torch).eval().requires_grad_(False); head.load_state_dict(bundle['state'], strict=True)
    head_id = digest({k: tensor_digest(v) for k,v in head.state_dict().items()})
    require(head_id == original['head_sha256'] == physical['candidate_head_identity'], 'Head tensor drift')
    mean, scale = bundle['mean'], bundle['scale']
    require(mean.shape == scale.shape == (384,) and torch.isfinite(mean).all().item() and
            torch.isfinite(scale).all().item() and (scale > 0).all().item(), 'normalizer contract')
    normalize = lambda v: ((v-mean)/scale).clamp(-8,8)
    backend = plan['backend']
    if backend == 'mmbert':
        require(model_dir is not None, 'physical replay requires actual model cache')
        from four_gate_pretrained import load_pinned, MODEL, REVISION
        model, tokenizer, files, _ = load_pinned(model_dir)
        require(plan['model'] == MODEL and plan['revision'] == REVISION and
                files == physical['physical_files'], 'physical Encoder drift')
        def encode(texts):
            tokens = tokenizer(texts, padding=True, truncation=False, return_tensors='pt')
            require(tokens['input_ids'].shape[1] <= 256, 'no replay truncation')
            with torch.inference_mode():
                h = model(**tokens).last_hidden_state.float(); m = tokens['attention_mask'].unsqueeze(-1)
                return (h*m).sum(1)/m.sum(1)
    else:
        require(backend == 'hashing_reference_v1', 'no backend substitution')
        def encode(texts): return hashed_reference(texts,torch)
    write_once(output/'binding.json', {'schema':'hepta.cpu-tail-replay.binding.v1',
        'original_attempt':original,'source_files_sha256':hashes,'profile':profile,'backend':backend,
        'repeats':repeats,'head_identity':head_id,'pid':os.getpid(),
        'torch_version':torch.__version__,'python_version':sys.version,
        'parallel_runtime':torch.__config__.parallel_info(),
        'intra_threads':torch.get_num_threads(),'interop_threads':torch.get_num_interop_threads(),
        'environment':{k:os.environ.get(k) for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OMP_WAIT_POLICY')},
        'affinity':sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None,
        'first_call_is_included':True,'warmup_excluded':False,'policy_results_available':False})
    journal = AttemptJournal(output/'test-view-attempts.jsonl')
    probes = []; returned = []; rejected = 0; fatal = None
    try:
        for i in range(repeats):
            clock = PhaseClock(); status = 'returned'
            try:
                symbol, receipt = observe_view(view, lambda v:text_view(text,v),encode,normalize,head,
                    torch,head_id,journal,{'split':'test','id':f'replay:{i}','arm':profile,
                    'source_input_sha256':row['text_sha256']},cpu_clock=clock)
                returned.append({'sequence':i,'symbol':symbol,'vector_sha256':receipt['vector_sha256'],
                                 'probabilities':receipt['probabilities']})
            except ViewBudgetExceeded:
                rejected += 1; status = 'budget_exceeded'  # Never returned to any policy.
            except Exception as error:
                fatal = type(error).__name__; status = 'execution_error'
            probes.append({'sequence':i,'status':status,**clock.report()})
            if fatal is not None: break
    finally:
        journal.close()
    require(head_id == digest({k:tensor_digest(v) for k,v in head.state_dict().items()}), 'frozen Head mutated')
    write_once(output/'parallel-clocks.json',probes)
    write_once(output/'returned-predictions.json',returned)
    write_once(output/'summary.json',{'scheduled_attempts':repeats,'attempts':len(probes),
        'returned':len(returned),'budget_rejected':rejected,'fatal_error':fatal,
        'completed_fixed_work':len(probes)==repeats and fatal is None,
        'process_cpu_envelope_ns':time.process_time_ns()-envelope,
        'view_limit_ns':100_000_000,'stability_established':False,
        'production_promotion_permitted':False})
    if fatal: raise RuntimeError('replay aborted; original and diagnostic failures retained')


def run(output, *, evidence_dir, repeats=64, model_dir=None):
    """Run each fixed configuration once, not retry-until-green. No shell strings."""
    require(type(repeats) is int and 1 <= repeats <= 1024, 'bounded repeat schedule')
    output = Path(output); evidence_dir = Path(evidence_dir)
    output.mkdir(parents=True, exist_ok=False)
    plan = {'profiles':PROFILES,'repeats':repeats,'selected_attempt':select_attempt(evidence_dir),
            'clock_is_process_not_thread':True,'no_effectiveness_or_risk_selection':True,
            'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    plan['sources_sha256'] = {name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ('fbsde_cpu_replay.py','fbsde_cpu_replay_audit.py','fbsde_acquisition_study.py',
                     'fbsde_acquisition_observe.py','four_gate_common.py','four_gate_capture.py')}
    write_once(output/'replay-plan.json',plan)
    if (evidence_dir/'validation-parallel-clocks.jsonl').exists():
        from fbsde_cpu_replay_audit import audit_live
        write_once(output/'original-clock-audit.json',audit_live(evidence_dir))
    statuses = []
    for profile in PROFILES:
        env = os.environ.copy()
        if profile != 'historical_2':
            env.update(OMP_NUM_THREADS='1' if profile=='bounded_1' else '2',
                       MKL_NUM_THREADS='1' if profile=='bounded_1' else '2')
        if profile == 'passive_2': env['OMP_WAIT_POLICY'] = 'PASSIVE'
        args = [sys.executable,str(Path(__file__).resolve()),'--worker','--evidence-dir',str(evidence_dir.resolve()),
                '--output',str((output/profile).resolve()),'--runtime-profile',profile,'--repeats',str(repeats)]
        if model_dir is not None: args += ['--model-dir',str(Path(model_dir).resolve())]
        started = time.perf_counter_ns()
        used = resource.getrusage(resource.RUSAGE_CHILDREN)
        child_cpu_start = used.ru_utime+used.ru_stime
        with (output/f'{profile}.log').open('xb') as log:
            try:
                proc = subprocess.run(args,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=240,check=False)
                status = {'profile':profile,'returncode':proc.returncode,'timeout':False}
            except subprocess.TimeoutExpired:
                status = {'profile':profile,'returncode':None,'timeout':True}
        used = resource.getrusage(resource.RUSAGE_CHILDREN)
        statuses.append({**status,'whole_child_wall_ns':time.perf_counter_ns()-started,
                         'whole_child_cpu_ns':round(1e9*(used.ru_utime+used.ru_stime-child_cpu_start))})
    write_once(output/'processes.json',statuses)
    require(all(r['returncode']==0 for r in statuses), 'some replay children failed; see retained logs')
    from fbsde_cpu_replay_audit import audit
    write_once(output/'arithmetic-audit.json',audit(output))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--worker',action='store_true');p.add_argument('--evidence-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--model-dir',type=Path)
    p.add_argument('--runtime-profile',choices=PROFILES);p.add_argument('--repeats',type=int,default=64)
    a = p.parse_args()
    if a.worker: run_worker(a.evidence_dir,a.output,a.runtime_profile,a.repeats,a.model_dir)
    else: run(a.output,evidence_dir=a.evidence_dir,repeats=a.repeats,model_dir=a.model_dir)
