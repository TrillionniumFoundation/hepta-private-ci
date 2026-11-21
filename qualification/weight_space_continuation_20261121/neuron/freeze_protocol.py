"""Metadata-only preflight followed by a single create-only protocol freeze."""
import ast
import datetime
import inspect
import os
from pathlib import Path
import platform
import sys
import time
import numpy as np
import scipy
import experiment as e
from compile_core import ROOT,BASE,OLD,FT,CAUSAL,planning,read,save,sha,canonical,identity

started=time.process_time()
if (ROOT/'attempt001').exists() or (ROOT/'PROTOCOL_FROZEN.json').exists():
    raise ValueError('attempt/protocol already exists')
paths=set()
for folder in (OLD/'vendor',OLD/'inputs/history',OLD/'attempt001/worlds',FT/'attempt001/worlds',
               CAUSAL/'attempt001/worlds',CAUSAL/'v2/attempt001/worlds'):
    paths.update(p.resolve() for p in folder.rglob('*') if p.is_file() and p.suffix in ('.py','.json','.gz','.npz'))
for folder in (ROOT,):
    paths.update(p.resolve() for p in folder.glob('*.py'))
for name in ('CAPSULE_CONTRACT.md','DRAFT_PROTOCOL.md','PEER_STATIC_REVIEW.json'):
    paths.add((ROOT/name).resolve())
for source in (OLD/'artifact_io.py',OLD/'task_graph.py',OLD/'original_experiment.py',
    FT/'mlp_math.py',FT/'run_full_mlp_experiment.py',
    CAUSAL/'v2/causal_core.py',CAUSAL/'v2/experiment.py',CAUSAL/'v2/reuse_candidates.py'):
    paths.add(source.resolve())
rows=0;model_meta={}
for fit in e.FITS:
    model_meta[str(fit)]={}
    for arm,path in e.model_sources(fit).items():
        paths.add(path.resolve());model=read(path)
        if model['head_dimensions']!=[85,48,4] or model['family']!='renewal':
            raise ValueError('metadata architecture')
        model_meta[str(fit)][arm]=dict(path=str(path.resolve()),**identity(path))
    rec_path=FT/'attempt001'/f'fit_{fit}_CANDIDATE.json.gz';paths.add(rec_path.resolve())
    rec=read(rec_path);data_path=FT/'attempt001'/rec['dataset']['path'];paths.add(data_path.resolve())
    data=np.load(data_path)
    if set(data.files)!={'X','best','goals','pair_weights','C_belief','belief_weights','own_Q','C_scores','legal_masks','state_weights'}:
        raise ValueError('cached input keys')
    if data['X'].shape!=(rec['train_rows'],85):raise ValueError('cached input dimension')
    rows+=rec['train_rows']
    teacher_path=CAUSAL/'attempt001/TRAIN'/f'fit_{fit}_teacher.npz';paths.add(teacher_path.resolve())
    teacher=np.load(teacher_path)
    if teacher['own_optimal_targets'].shape!=(rec['train_rows'],4):raise ValueError('teacher dimensions')
if rows!=144397:raise ValueError('complete original TRAIN rows')
known,_hash,history=e.history()
full=planning.load_context(OLD/'vendor/frozen_joint')
symbols={name:str(inspect.signature(getattr(full,name))) for name in
         ('initial','legal','due_request','successor','outcomes','NumpyPolicy','Oracle','policy_value')}
for path in paths:
    if path.suffix=='.py':ast.parse(path.read_text(),filename=str(path))
files={str(path):identity(path) for path in sorted(paths)}
review=read(ROOT/'PEER_STATIC_REVIEW.json')
if review['status']!='PASS_AFTER_REVIEW_CORRECTIONS':raise ValueError('peer review missing')
preflight=dict(status='PASS_ZERO_FORWARD_PREFLIGHT',model_calls=0,gradient_updates=0,
    rows_metadata_only=rows,historical_known=len(known),source_inputs=len(files),interfaces=symbols,
    models=model_meta,CPU_seconds=time.process_time()-started,
    known_history_sha256=sha(canonical(sorted(known)).encode()),
    scope='decompression, cached shape and source/interface checks only; discovery forward separately budgeted')
save(ROOT/'PREFLIGHT.json',preflight);files[str(ROOT/'PREFLIGHT.json')]=identity(ROOT/'PREFLIGHT.json')
protocol=dict(schema='hepta-structured-own-law-continuation-compile-v1',
    status='FROZEN_BEFORE_DISCOVERY_FORWARD_AND_NEW_ENTROPY',
    created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    input_root_absolute=str(BASE),output_absolute=str(ROOT/'attempt001'),files=files,
    fits=list(e.FITS),arms=list(e.k.ARMS),model_sources=model_meta,state_cap=4096,
    independent_units=5,primary_family_size=4,primary=['J-C iid','J-C ood','J-K iid','J-K ood'],
    primary_interval='paired fit-level t df4 two-sided Bonferroni4 familywise95',utility_margin=.005,
    known_history=3456,DEV_per_fit=4,DEV_selection=False,CONF_per_fit_domain=16,
    candidate='single exact own-law DAG and closed selected-policy automaton',
    matched_training_baseline=False,gradient_updates=0,weight_edits=0,external_preregistration=False,
    resources=dict(CPU_soft_seconds=285,CPU_hard_seconds=300,wall_seconds=600,
        numeric_threads=1,affinity_CPU=7,RSS_bytes=1073741824,reader_CPU_seconds=12,
        preflight_CPU_seconds=preflight['CPU_seconds'],preflight_separate_no_model=True),
    runtime=dict(python=sys.version,numpy=np.__version__,scipy=scipy.__version__,
        machine=platform.machine(),kernel=platform.release(),available_affinity=sorted(os.sched_getaffinity(0)),
        cpu_model=next(line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),
        shared_host=True),automatic_retry=False,
    semantic_contract=dict(task='joint-current-at-due-fixed-deadline-v1',target_tick=6,
        REPAIR='sensor only',first_passage_target=False,financial_CallPut_channels=False,
        own_law='checkpoint stored transition tables and original decoder only'),
    NDU=dict(keep_original_and_stop_allowed=True,CPU_to_utility_exchange_rate=None,
        future_call_volume=None,production_eligible=False))
save(ROOT/'PROTOCOL_FROZEN.json',protocol)
print(canonical(dict(status=preflight['status'],protocol_sha256=identity(ROOT/'PROTOCOL_FROZEN.json')['sha256'],
                     pins=len(files),history=len(known),CPU_seconds=time.process_time()-started)))
