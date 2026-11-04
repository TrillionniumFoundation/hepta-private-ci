from pathlib import Path
import json, tempfile, hashlib
import torch
torch.set_num_threads(1)
from qualification.cell_meta_execution_af import physical_router_trial as t
from qualification.cell_meta_execution_af import physical_router_top1 as top
from qualification.cell_meta_execution_af import physical_router_hard_train as h
from qualification.cell_meta_execution_af import physical_router_frozen_baseline as f
from qualification.cell_meta_execution_af import physical_router_fivearm_review as five
from qualification.cell_meta_execution_af import physical_router_safe_export as safe
from qualification.cell_meta_execution_af.physical_router_safe_export_tests import SafeGraniteArtifactTests, summary, os_summary
fixture=SafeGraniteArtifactTests('test_complete_structural_case_only_never_grants_model_authority');fixture.setUp()
try:
    root=fixture.root
    soft_s=summary(False);hard_s=summary(True)
    for seed in safe.SEEDS:
        panel=t.synthetic_panel(seed=41,rule='conditional',rows=64)
        panel['source']['seed']=seed
        panel['source']['kind']='external_unverified';panel['source']['rule']='external'
        soft=t.run(panel,steps=2)
        top_report=top.create_report(panel,soft)
        hard=h.produce(panel,soft,top_report)
        frozen=f.produce(panel,soft,top_report,hard)
        fivearm=five.descriptive(panel,soft,top_report,hard,frozen)
        docs={'trial-panel':panel,'trial-report':soft,'hard-train-report':hard,'frozen-report':frozen,'fivearm-report':fivearm}
        for key,v in docs.items():
            (root/f'{seed}-{key}.json').write_bytes(t.canonical(v)+b'\n')
        for k,r in [('soft',soft),('hard',hard)]:
            rows=soft_s['arms'] if k=='soft' else hard_s['arms']
            for row in rows:
                if row['seed'] != seed:continue
                r0=next(x for x in r['results'] if x['arm']==row['arm'])
                row['split_proposed']=r0['split_proposed']
                v=r0['evaluation'] if k=='soft' else r0['retrospective_evaluation']
                row['retrospective_test_1']=v['future_1']
                row['retrospective_test_2']=v['future_2']
                m=r0['meters']
                if k=='soft':row['head_forward_rows']=m['head_forward_rows']
                else:
                    row.update({'train_head_rows':m['train_head_0_rows']+m['train_head_1_rows'],
                      'eval_head_rows':m['eval_head_0_rows']+m['eval_head_1_rows'],
                      'diagnostic_head_rows':m['diagnostic_head_rows'],
                      'train_router_rows':m['train_router_rows'],
                      'sampled_routes':m['sampled_routes']})
    (root/'descriptive-retrospective-summary.json').write_text(json.dumps(soft_s))
    (root/'hardtop1-descriptive-retrospective-summary.json').write_text(json.dumps(hard_s))
    try:
        safe.verify_descriptive_reports_against_raw(root,soft_s,hard_s)
        print('ACTUAL_TORCH_THREE_SEED_STUDY_CONTRACT_ACCEPTED')
    except Exception as e:
        print('CONTRACT_FAILED:',repr(e));raise
    print('research notes: actual Torch synthetic source only, NOT pretrained Granite')
finally:
    fixture.doCleanups()
