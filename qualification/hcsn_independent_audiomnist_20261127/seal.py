"""Record every candidate and code identity before test access."""
import argparse
import json
from pathlib import Path
from fit import ARMS, BUDGETS, SEEDS, dump, sha


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('models',type=Path);parser.add_argument('data',type=Path)
    parser.add_argument('table',type=Path);parser.add_argument('seal',type=Path)
    a=parser.parse_args()
    if a.seal.exists():raise FileExistsError(a.seal)
    here=Path(__file__).resolve().parent
    paths=[a.models/'law_check.json']
    for seed in SEEDS:
        paths.extend(a.models/f'parent_{seed}.{ext}' for ext in ('npz','json'))
        for arm in ARMS:
            for t in BUDGETS:
                paths.extend(a.models/f'{arm}_{seed}_{t}.{ext}' for ext in ('npy','json'))
    records={p.name:sha(p) for p in paths}
    code={p:sha(here/p) for p in ('PROTOCOL.md','data.py','receiver.py','fit.py','check_law.py','seal.py','cold.py','verify.py')}
    dump(a.seal,{'fits':records,'code':code,'data_manifest':sha(a.data/'data.json'),'table':sha(a.table),'primary_budget_cpu_seconds':45,'new_test_access':'pending; no fitting process opened the test NPZ files'})
    print('sealed',len(records),'files',sha(a.seal))
