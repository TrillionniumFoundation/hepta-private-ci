"""Cross-check real database prefixes, external floors, exit codes and source calls.

The semantic checkpoint replay is shared with restart validation. SQL/anchor and
private simulator effects are independently reconstructed here. This does not
turn a self-contained record into independent execution or native authority.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import sys
import unittest
import copy
import tempfile
import shutil
from four_gate_common import digest, require, strict_loads
from fbsde_checkpoint_audit import validate_rows
from fbsde_transfer_reference import STATES, source_effect

EVENTS=('retire','verification_intent','recovery_request','recovery_receipt','reactivate','finish','restart_quarantine')


def audit(root):
    root=Path(root)
    def read(path):
        path=root/path
        require(path.is_file() and not path.is_symlink() and path.stat().st_size<16*1024*1024,'bounded original evidence')
        return strict_loads(path.read_bytes())
    def database(path, floor, expected):
        uri=(root/path).resolve().as_uri()+'?mode=ro'
        with closing(sqlite3.connect(uri,uri=True)) as db:
            require(db.execute('PRAGMA quick_check').fetchall()==[('ok',)],'database integrity')
            schema,dbid=db.execute('SELECT schema,database_id FROM meta').fetchone()
            require(schema=='hepta.rule-checkpoint.v1' and dbid==floor['database_id'],'anchor lineage')
            rows=[];previous=None
            for seq,prev,event,snapshot,identity in db.execute('SELECT * FROM checkpoint ORDER BY seq'):
                e,s=strict_loads(event),strict_loads(snapshot)
                require(seq==len(rows) and prev==previous and identity==digest([schema,dbid,seq,prev,e,s]),'SQL checkpoint chain')
                rows.append(dict(event=e,snapshot=s,digest=identity));previous=identity
        require(rows==expected and rows[floor['sequence']]['digest']==floor['digest'],'database/evidence/floor mismatch')
        validate_rows(rows)
    def costs(rows):
        require(type(rows) is list and all(type(r) is dict and set(r)=={'event','cpu_ns','wall_ns','bytes'}
            and all(type(r[k]) is int and r[k]>=0 for k in ('cpu_ns','wall_ns','bytes'))
            and 0<r['bytes']<=131072 for r in rows), 'invalid measured persistence work')
    plan=read(Path('plan.json'));result=read(Path('results.json'))
    cases=[(e,p) for e in EVENTS for p in ('before_commit','after_commit')]+[('source_verification','inside_source'),('source_recovery','inside_source')]
    require(plan['cases']==[list(x) for x in cases] and result['abrupt_exits']==16 and
        result['native_owner_integrated'] is False and result['power_loss_guarantee'] is False and
        result['production_promotion_permitted'] is False and len(result['crashes'])==16,'registered complete crash design')
    for index,(event,phase) in enumerate(cases):
        directory=Path(f'crash-{index:02}');row=read(directory/'recovery.json');exit=read(directory/'exit.json')
        code=73 if phase=='before_commit' else 74 if phase=='after_commit' else 75
        require(exit==dict(expected=code,returncode=code) and row['exit']==code and row['restart_blocked'] is True,'false abrupt exit or old-rule admission')
        require(row['owner_anchor']==read(directory/'control/anchor.json') and row['current_context']==read(directory/'control/current-context.json'),'owner inputs changed')
        marker=read(directory/'control/crash-marker.json')
        require(marker['stage']==phase and marker['event']==event and type(marker['pid']) is int and marker['pid']>0,
                'different crash point or absent process marker')
        before,after=row['checkpoint_before'],row['checkpoint_after']
        if phase=='after_commit':require(before[-1]['event']['event']==event,'committed crash event absent')
        elif phase=='before_commit':require(before[-1]['event']['event']!=event,'uncommitted event survived rollback')
        entered_path=root/directory/'control/source-entered.jsonl'
        entered=[]
        if entered_path.exists():
            raw=entered_path.read_bytes();require(len(raw)<65536 and raw.endswith(b'\n'),'partial source-entry trace')
            entered=[strict_loads(line)['request'] for line in raw.splitlines()]
        intents=[r['event']['request'] for r in before if r['event']['event'] in ('recovery_request','verification_intent')]
        expected_entries=0 if event in ('retire','restart_quarantine','verification_intent','recovery_request') else 3 if event=='reactivate' else 1
        require(len(entered)==expected_entries and entered==intents[:expected_entries], 'unpaid or unrecorded child source work')
        costs(row['costs'])
        require(after[:len(before)]==before and after[len(before)]['event']['event']=='restart_quarantine','history erased or restart omitted')
        require(after[len(before)]['snapshot']['state']!='active' and after[len(before)]['snapshot']['attempts']==before[-1]['snapshot']['attempts'],'restart restored table or quota')
        database(directory/'store/rule.sqlite3',row['owner_anchor'],after)
        newrule=7 if row['current_context']['generation']==2 else 1
        requests=[r['event']['request'] for r in after[len(before)+1:] if r['event']['event']=='recovery_request']
        require(requests==[r['request'] for r in row['recovery_calls']],'actual callback inventory')
        for call in row['recovery_calls']:
            req,receipt=call['request'],call['receipt']
            require(receipt==dict(request_sha256=digest(req),effect=list(source_effect(newrule,tuple(req['state'])))),'recovery source receipt')
        require(after[-1]['snapshot']['attempts']<=5 and bool(row['outputs'])==row['reactivated'],'unbounded or fabricated activation')
        summary=dict(index=index,event=event,phase=phase,reactivated=row['reactivated'],
            attempts_before=before[-1]['snapshot']['attempts'],attempts_after=after[-1]['snapshot']['attempts'],
            new_calls=len(row['recovery_calls']))
        require(result['crashes'][index]==summary,'fabricated crash summary or attempts')
        if row['reactivated']:
            require(row['outputs']==[[s[j] for j in source_effect(newrule,s)] for s in STATES],'recovered output')
    total_initial=total_recovery=0
    require(len(result['stable'])==33,'all source rules required')
    for rule in range(33):
        directory=Path(f'rule-{rule:02}');e=read(directory/'evidence.json');database(directory/'rule.sqlite3',e['anchor'],e['rows'])
        require(e['rule']==rule and e['outputs']==[[s[j] for j in source_effect(rule,s)] for s in STATES],'stable restored semantics')
        for call in e['calls']:
            req=call['request'];require(call['receipt']==dict(request_sha256=digest(req),effect=list(source_effect(rule,tuple(req['state'])))),'actual stable source')
        require(type(e['initial_calls']) is int and 0<=e['initial_calls']<=5, 'initial source boundary')
        requests=[x['event']['request'] for x in e['rows'] if x['event']['event']=='recovery_request']
        require(requests==[x['request'] for x in e['calls'][e['initial_calls']:]], 'stable source attempts lost')
        costs(e['costs'])
        summary=dict(rule=rule,initial_calls=e['initial_calls'],recovery_calls=len(e['calls'])-e['initial_calls'],outputs=len(e['outputs']))
        require(result['stable'][rule]==summary,'fabricated stable summary')
        total_initial+=e['initial_calls'];total_recovery+=len(e['calls'])-e['initial_calls']
    require(total_initial==result['initial_source_calls']==112 and total_recovery==result['recovery_source_calls']==112 and
        result['stable_outputs']==198,'fictitious source savings or denominator')
    return dict(abrupt_exit_cases=16,restored_rule_cases=33,stable_outputs=198,
        sqlite_prefixes_verified=True,shared_restart_validator=True,native_owner_integrated=False)


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'study';shutil.copytree(SOURCE,self.root)
    def tearDown(self):self.tmp.cleanup()
    def change(self,path,fn):
        p=self.root/path;value=json.loads(p.read_text());fn(value);p.write_text(json.dumps(value))
    def test_original(self):self.assertEqual(audit(self.root)['stable_outputs'],198)
    def test_fake_native_pass(self):
        self.change('results.json',lambda x:x.update(native_owner_integrated=True))
        with self.assertRaises(ValueError):audit(self.root)
    def test_restart_active(self):
        self.change('crash-00/recovery.json',lambda x:x['checkpoint_after'][len(x['checkpoint_before'])]['snapshot'].update(state='active'))
        with self.assertRaises(ValueError):audit(self.root)
    def test_erased_source_attempt(self):
        self.change('crash-05/recovery.json',lambda x:x['recovery_calls'].pop())
        with self.assertRaises(ValueError):audit(self.root)
    def test_fake_process_exit(self):
        self.change('crash-07/exit.json',lambda x:x.update(returncode=0))
        with self.assertRaises(ValueError):audit(self.root)
    def test_missing_case(self):
        self.change('results.json',lambda x:x['crashes'].pop())
        with self.assertRaises(ValueError):audit(self.root)
    def test_fake_available_recovery(self):
        self.change('results.json',lambda x:x['crashes'][9].update(reactivated=True))
        with self.assertRaises(ValueError):audit(self.root)
    def test_erased_child_source_entry(self):
        (self.root/'crash-06/control/source-entered.jsonl').write_bytes(b'')
        with self.assertRaises(ValueError):audit(self.root)
    def test_negative_io_cost(self):
        self.change('crash-00/recovery.json',lambda x:x['costs'][0].update(cpu_ns=-1))
        with self.assertRaises(ValueError):audit(self.root)
    def test_anchor_rollback(self):
        self.change('crash-04/control/anchor.json',lambda x:x.update(sequence=0,digest='a'*64))
        with self.assertRaises(ValueError):audit(self.root)


if __name__=='__main__':
    SOURCE=Path(sys.argv.pop())
    unittest.main()
