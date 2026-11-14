"""Package reproducible research, excluding rebuildable toolchains/caches."""
from __future__ import annotations
from pathlib import Path
import argparse
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parent
WORKSPACE=ROOT.parent
EXCLUDED_PARTS={'__pycache__','.git','toolchain','toolchain_downloads','cargo_cache','target'}

def selected_files(checkpoint=False):
    selected=[]
    for folder in ['rrsnn_v2','rrsnn_experiments']:
        for path in (WORKSPACE/folder).rglob('*'):
            if not path.is_file() or path.is_symlink(): continue
            rel=path.relative_to(WORKSPACE)
            if EXCLUDED_PARTS.intersection(rel.parts): continue
            if path.suffix in ('.pyc','.zip') or path.name in ('file_manifest.json','package_status.json'): continue
            if checkpoint and folder=='rrsnn_v2':
                if path.name in ('progress.json','run.log') or 'coupled' in rel.parts: continue
                if 'results' in rel.parts and any(p.startswith('seed_') for p in rel.parts):
                    run_dir=path.parent
                    while run_dir!=ROOT and not run_dir.name.startswith('seed_'): run_dir=run_dir.parent
                    if run_dir==ROOT or not (run_dir/'training.json').exists(): continue
            selected.append(path)
    r0=WORKSPACE/'rollover_snn_research'
    for relative in ['analytic_neuron.py','results/validation_results.json']:
        if (r0/relative).exists(): selected.append(r0/relative)
    complete=WORKSPACE/'RR_SNN_V2_Complete_Results.json'
    if not checkpoint and complete.exists(): selected.append(complete)
    return sorted(set(selected))

def main(checkpoint=False):
    paths=selected_files(checkpoint)
    completed=len(list((ROOT/'results').glob('*/seed_*/training.json')))
    milestones=len(list((ROOT/'coupled/results').glob('*/seed_*/training.json')))
    if not checkpoint:
        required=['results/aggregate.json','coupled/results/aggregate.json',
                  'audit/strict_initial_counterfactual/aggregate.json',
                  'benchmark_results/scaling_results.json','coupled/benchmark_results/scaling_results.json',
                  'closure_ledger.json','RR_SNN_V2_Report.ipynb']
        if completed!=70 or milestones!=10 or any(not (ROOT/name).exists() for name in required):
            raise ValueError('Refusing to label an incomplete package as final')
        if not (WORKSPACE/'RR_SNN_V2_Complete_Results.json').exists():
            raise ValueError('Complete combined result export is absent')
        if not json.loads((ROOT/'closure_ledger.json').read_text())['local_declared_experiments_complete']:
            raise ValueError('Final evidence ledger is not complete')
    status={'schema':'rrsnn.v2.package-status.v1','in_progress_checkpoint':checkpoint,
            'planned_main_training_runs':70,'completed_main_training_runs':completed,
            'completed_supplementary_checkpoint_milestones':milestones,
            'main_results_complete':(ROOT/'results/aggregate.json').exists(),
            'supplementary_results_complete':(ROOT/'coupled/results/aggregate.json').exists(),
            'all_external_or_production_gates_closed':False,
            'production_activation_allowed':False,
            'scope':'Reproducible research, original v0 evidence plus v2 repairs and experiments; external production gates remain separately identified',
            'excluded_rebuildable_directories':sorted(EXCLUDED_PARTS)}
    manifest=[]
    destination=WORKSPACE/'RR_SNN_V2_Research_Package.zip'
    temporary=destination.with_suffix('.inprogress.zip')
    with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in paths:
            data=path.read_bytes();relative=str(path.relative_to(WORKSPACE))
            archive.writestr(relative,data)
            manifest.append({'path':relative,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        archive.writestr('rrsnn_v2/package_status.json',json.dumps(status,indent=2)+'\n')
        archive.writestr('rrsnn_v2/file_manifest.json',json.dumps(manifest,indent=2)+'\n')
    with zipfile.ZipFile(temporary) as archive:
        bad=archive.testzip()
        if bad is not None: raise ValueError(f'Archive checksum failed: {bad}')
    temporary.replace(destination)
    (ROOT/'package_status.json').write_text(json.dumps(status,indent=2)+'\n')
    (ROOT/'file_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'path':str(destination),'files':len(manifest)+2,'bytes':destination.stat().st_size,
                      'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),**status}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--checkpoint',action='store_true')
    main(parser.parse_args().checkpoint)
