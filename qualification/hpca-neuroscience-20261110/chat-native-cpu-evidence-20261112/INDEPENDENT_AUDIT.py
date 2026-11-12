import hashlib,json,pathlib,re,subprocess,sys
e=pathlib.Path('/home/qq/work/hpca-chat-native-run-20261112-t7/execution')
src=pathlib.Path('/home/qq/work/hpca-public-chat-wrapper-diagnostic-20261112-t5')
root=src/'qualification/hpca-neuroscience-20261110'
model=pathlib.Path('/home/qq/work/hpca-base-output-e901-20261112-evidence/execution/model')
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p): return json.loads(p.read_text())
res=load(e/'RESULT.json');pre=load(e/'PREEXECUTION.json');plans=load(root/'HPCA_V2_OOD_PLAN.json')['tasks'];bp=load(root/'BASE_OUTPUT_PLAN.json')
assert res['schema']=='HPCA-CHAT-WRAPPER-PUBLIC-RESULT-1'
assert res['authority']==pre['authority']=='DENY_ALL_HOLD_NO_GO'
assert res['head']==pre['head']=='4669280bd92804e6b5357ec0d8a27197858a5b6a'
assert res['tree']==pre['tree']==subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=src,text=True).strip()
assert res['head']==subprocess.check_output(['git','rev-parse','HEAD'],cwd=src,text=True).strip()
assert not subprocess.check_output(['git','status','--porcelain'],cwd=src,text=True).strip()
assert res['preexecution_sha256']==sha(e/'PREEXECUTION.json')
assert res['journal_sha256']==sha(e/'ROWS.jsonl')
assert pre['weight_updates']==0 and pre['independent_future']==0
for name,hash0 in pre['sources'].items(): assert sha(root/name)==hash0,(name,'source drift')
for name,ident in pre['model'].items():
    p=model/name;assert p.is_file() and not p.is_symlink()
    assert p.stat().st_size==ident['bytes'] and sha(p)==ident['sha256'],name
for name,expected in bp['expected_existing_identities'].items(): assert pre['model'][name]['sha256']==expected,name
rows=res['rows'];assert len(rows)==len(plans)==len(pre['prompts'])==24
assert len({r['id'] for r in rows})==24
assert [p['id'] for p in plans]==[r['id'] for r in rows]==[p['id'] for p in pre['prompts']]
assert all(r['truth']==p['truth'] and r['family']==p['family'] for r,p in zip(rows,plans))
seen=[];began=[];end=0;journal=[]
for index,line in enumerate((e/'ROWS.jsonl').read_text().splitlines()):
    item=json.loads(line);journal.append(item);assert item['sequence']==index
    if item['kind']=='attempt_started': began.append(item['task_id'])
    elif item['kind']=='row_completed': seen.append(item['row'])
    elif item['kind']=='all_rows_complete': end+=1;assert item['n']==24
    else: raise AssertionError(('unknown journal kind',item['kind']))
assert len(journal)==49 and len(began)==len(seen)==24 and end==1
assert began==[r['id'] for r in rows] and seen==rows
for r in rows:
    tokens=r['tokens'];assert 1<=len(tokens)<=8
    assert r['first_eos']==(tokens[0]==2)
    m=re.match(r'^\s*(yes|no)(?!\w)',r['text'],flags=re.I)
    parsed=m.group(1).lower() if m else None
    assert parsed==r['parsed']
    assert r['valid']==(parsed is not None)
    assert r['correct']==(parsed==r['truth'])
    assert r['inference_wall_seconds']>=0
summary={'n':len(rows),'valid':sum(x['valid'] for x in rows),
         'correct':sum(x['correct'] for x in rows),
         'first_eos':sum(x['first_eos'] for x in rows),
         'independent_future':0}
assert summary==res['summary']
by_family={f:{'n':len([r for r in rows if r['family']==f]),
              'valid':sum(r['valid'] for r in rows if r['family']==f),
              'correct':sum(r['correct'] for r in rows if r['family']==f)} for f in sorted({r['family'] for r in rows})}
report={'schema':'hpca-chat-audit-v1','status':'independent_arithmetic_and_custody_pass',
        'scope':'same 24 public tasks, not independent future benefit',
        'origin_git_head':res['head'],'origin_git_tree':res['tree'],
        'result_sha256':sha(e/'RESULT.json'),'preexecution_sha256':sha(e/'PREEXECUTION.json'),
        'journal_sha256':sha(e/'ROWS.jsonl'),'model_weight_sha256':pre['model']['model.safetensors']['sha256'],
        'summary_recomputed':summary,'by_family':by_family,
        'journal_events':len(journal),'source_files_verified':len(pre['sources']),
        'model_assets_verified':len(pre['model']),
        'selected_adopt':False,'native_owner_qualified':False,'production_qualified':False}
output=e.parent/'INDEPENDENT_AUDIT.json'
output.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
print(json.dumps(report,sort_keys=True))
