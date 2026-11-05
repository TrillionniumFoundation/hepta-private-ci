"""Generate signed Python/SQLite traces and compare a native transition executable.

The nine-field runner protocol and fixture IDs are qualification-only. Each call
uses a new request ID; historical receipt/idempotency handling is outside this core.
Source invalidation and high counter values are direct fixture-state injections.
"""
import argparse
import hashlib
import json
import pathlib
import random
import subprocess
import sys
import tempfile
import time
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from authority import Rejected, public, sign, bundle, COMPONENTS, MAX_COUNTER
from authority_tests import authority, key

KEYS = {public(key(i)): i for i in range(2, 7)}

def digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def generate(output):
    randomizer = random.Random(150520261105)
    lines, wanted, records = [], [], []
    counts = Counter()
    for scenario in range(64):
        with tempfile.TemporaryDirectory() as work:
            a = authority(str(pathlib.Path(work)/'authority.db'))
            src = a.apply(sign(key(2), a.identity, 'source',
                dict(scope='scope', id='s', expected_revision=0, active=True, body='fixture source')))['result']
            item = bundle('scope', ['address'], [public(key(3)),public(key(4))],
                [dict(id='s', revision=src['revision'], hash=src['hash'])],
                {n:n.encode() for n in COMPONENTS})
            other = bundle('scope', ['address'], [public(key(3)),public(key(4))],
                [dict(id='s', revision=src['revision'], hash=src['hash'])],
                {n:(n+'other').encode() for n in COMPONENTS})
            a.apply(sign(key(2), a.identity, 'create', dict(cell='cell', owner=public(key(3)), bundle=item)))
            epoch = [1, MAX_COUNTER-2, MAX_COUNTER-1, MAX_COUNTER][scenario%4] if scenario >= 56 else 1
            a.db.execute('UPDATE cells SET epoch=?', (epoch,))
            lines.append(f'reset 3 {epoch} 1 4 1 1 reset cell')
            wanted.append('reset')
            for step in range(24):
                row = a.db.execute('SELECT * FROM cells').fetchone()
                pending = a.db.execute("SELECT * FROM transfers WHERE state IN ('prepared','ready')").fetchone()
                if row['state'] == 'active':
                    op = randomizer.choice(['prepare','recover_prepare'])
                    actor = 2 if op == 'recover_prepare' else KEYS[row['owner']]
                    target = randomizer.choice([i for i in (3,4,5) if i != KEYS[row['owner']]])
                    transfer = f't{step}'
                else:
                    op = randomizer.choice(['ready','commit','abort'])
                    actor = KEYS[pending['target']]
                    if op == 'abort':
                        recovery = a.db.execute('SELECT controller FROM recovery_transfers WHERE id=?',(pending['id'],)).fetchone()
                        actor = 2 if recovery else KEYS[pending['source']]
                    target, transfer = 4, pending['id']
                epoch, expected, verified, cell = row['epoch'], 1, 1, 'cell'
                fresh = 0 if scenario%8 == 0 and step >= 4 else 1
                a.db.execute('UPDATE sources SET active=?', (fresh,))
                fault = randomizer.choice(['none']*4+['actor','epoch','bundle','cell','transfer','verified','same_owner'])
                if fault == 'actor': actor = 6
                if fault == 'epoch': epoch = max(0,epoch-1)
                if fault == 'bundle': expected = 2
                if fault == 'cell': cell = 'other'
                if fault == 'transfer': transfer = 'unknown'
                if fault == 'verified': verified = 2
                if fault == 'same_owner': target = KEYS[row['owner']]
                args = dict(cell=cell, transfer=transfer, epoch=epoch, expected=item['id'] if expected==1 else other['id'])
                if op in ('prepare','recover_prepare'): args['target'] = public(key(target))
                if op == 'ready': args['bundle'] = item if verified==1 else other
                try:
                    a.apply(sign(key(actor), a.identity, op, args, f'{scenario}-{step}'))
                    result, reason = 'ok', None
                except Rejected as exc:
                    result, reason = 'rejected', str(exc)
                counts[f'{op}:{result}'] += 1
                counts[f'fault:{fault}'] += 1
                current = a.db.execute('SELECT * FROM cells').fetchone()
                phases = a.db.execute('SELECT * FROM transfers ORDER BY id').fetchall()
                tphase = next((t['state'] for t in phases if t['id']==transfer),'none')
                history=[]
                for t in phases:
                    recovery = a.db.execute('SELECT controller FROM recovery_transfers WHERE id=?',(t['id'],)).fetchone()
                    controller = KEYS[recovery[0]] if recovery else 0
                    history.append(f"{t['id']}:{KEYS[t['source']]}:{KEYS[t['target']]}:{t['epoch']}:{t['state']}:{controller}")
                line=f'{op} {actor} {epoch} {expected} {target} {verified} {fresh} {transfer} {cell}'
                expectation=f"{result} {KEYS[current['owner']]} {current['epoch']} {current['state']} {tphase} {','.join(history)}".rstrip()
                lines.append(line); wanted.append(expectation)
                records.append(dict(scenario=scenario, step=step, command=line, expected=expectation, rejection_reason=reason, fault=fault))
            a.close()
    output.mkdir(parents=True,exist_ok=True)
    (output/'commands.txt').write_text('\n'.join(lines)+'\n')
    (output/'expected.txt').write_text('\n'.join(wanted)+'\n')
    (output/'python-traces.json').write_text(json.dumps(records,indent=2)+'\n')
    report=dict(seed=150520261105, scenarios=64, operations=len(records), counts=dict(counts),
        authority_sha256=digest(HERE.parent/'authority.py'), source_files_sha256={p.name:digest(p) for p in HERE.glob('*.rs')},
        oracle='Signed V15 requests executed by Python Authority with SQLite WAL/FULL',
        scope='Migration transition outcomes and complete transfer history only; not crypto, I/O, full V15, data quality or recovery parity.')
    report['commands_sha256']=digest(output/'commands.txt');report['expected_sha256']=digest(output/'expected.txt')
    (output/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


def compare(output, actual):
    want=(output/'expected.txt').read_text().splitlines()
    got=pathlib.Path(actual).read_text().splitlines()
    differences=[dict(line=i+1,expected=a,actual=b) for i,(a,b) in enumerate(zip(want,got)) if a.rstrip()!=b.rstrip()]
    report=dict(passed=len(want)==len(got) and not differences, expected_lines=len(want), actual_lines=len(got),
                mismatches=differences, actual_sha256=digest(actual),expected_sha256=digest(output/'expected.txt'))
    (pathlib.Path(actual).with_suffix('.comparison.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2)); return 0 if report['passed'] else 1


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['generate','compare']);p.add_argument('output',type=pathlib.Path);p.add_argument('--actual')
    args=p.parse_args()
    if args.action=='generate': generate(args.output)
    else: raise SystemExit(compare(args.output,args.actual))
