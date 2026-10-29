import ast,copy,hashlib,importlib.util,json,sys,types
from pathlib import Path
ROOT=Path(__file__).resolve().parent
OLD=ROOT/'reference'
sys.path.insert(0,str(ROOT))
import support

def load(name,p):
 spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
old=load('old_accounting',OLD/'accounting.py');new=load('new_accounting',ROOT/'accounting.py')
# Literal receipt validator exercises invocation and tamper propagation only;
# local real-metadata qualification was performed separately; private inputs are not published.
fake=types.ModuleType('evidence');calls={'validate':0,'carry':0};bad=False

def validate(row,rows):
 calls['validate']+=1
 if row['receipt']!={'literal':'valid'}:raise ValueError('literal receipt rejected')
def carry(rows):calls['carry']+=1
fake.validate=validate;fake.require_carry=carry;fake.exact_shared_failed_T=lambda row:False
sys.modules['evidence']=fake
cells=support.CELLS;ids=[support.cell_id(c) for c in cells];passed=[]

def row(i,cat,amount,beneficiaries=None,deps=None):
 v={k:'0' for k in old.CATEGORIES};v[cat]=str(amount)
 return {'id':str(i),'dependencies':deps or [],'physical_scope_ids':['scope-'+str(i)],'actual_cpu_seconds':str(amount),'measured_categories':dict(v),'charge_categories':dict(v),'basis':'MEASURED_PARTITION','beneficiaries':ids if beneficiaries is None else beneficiaries,'success':True,'receipt':{'literal':'valid'},'proof':{'kind':'LITERAL'}}
def outcome(fn):
 try:return ('value',fn())
 except Exception as e:return ('error',type(e).__name__,str(e))
def compare(name,rows,p='0',m='0'):
 a=outcome(lambda:{support.cell_id(c):old.standalone(rows,c,parent_p=p,parent_m=m) for c in cells})
 b=outcome(lambda:new.standalone_all(rows,parent_p=p,parent_m=m))
 assert a==b,(name,a,b)
 for c in cells:assert outcome(lambda:old.standalone(rows,c,parent_p=p,parent_m=m))==outcome(lambda:new.standalone(rows,c,parent_p=p,parent_m=m))
 passed.append(name)
compare('empty',[])
rows=[row('P','P','2'),row('S','S','3'),row('M','M','4')]
for j,cid in enumerate(ids):rows.extend([row('T'+str(j),'T',str(10+j),[cid]),row('O'+str(j),'O','1',[cid])])
compare('mixed_shared_and_own',rows,'0.25','0.75')
for cat,limit in [('P',40),('O',180),('S',60),('M',120)]:
 for amount in (str(limit),str(limit)+'.000001'):
  compare(cat+amount,[row(cat,cat,amount,[ids[0]] if cat=='O' else None)])
for m in ['0','19.999999','20','20.000001','120','120.000001']:compare('parent_M_'+m,[],m=m)
for p in ['40','40.000001']:compare('parent_P_'+p,[],p=p)
for t in ['780','780.000001']:compare('total_cap_'+t,[row('T','T',t,[ids[0]])])
variants=[]
x=copy.deepcopy(rows);x.append(copy.deepcopy(x[0]));variants.append(('duplicate_id',x))
x=copy.deepcopy(rows);x[1]['physical_scope_ids']=x[0]['physical_scope_ids'];variants.append(('scope_overlap',x))
x=copy.deepcopy(rows);x[0]['dependencies']=['missing'];variants.append(('missing_dependency',x))
x=copy.deepcopy(rows);x[0]['dependencies']=[x[1]['id']];x[1]['dependencies']=[x[0]['id']];variants.append(('cycle',x))
x=copy.deepcopy(rows);x[0]['beneficiaries']=[ids[0]];variants.append(('shared_debit_omitted',x))
x=copy.deepcopy(rows);x[3]['beneficiaries']=ids;variants.append(('own_T_shared',x))
x=copy.deepcopy(rows);x[0]['receipt']={'literal':'tampered'};variants.append(('bad_receipt',x))
x=copy.deepcopy(rows);x[0]['actual_cpu_seconds']='3';variants.append(('undercharge',x))
x=copy.deepcopy(rows);x[0]['basis']='UNKNOWN';variants.append(('unknown_basis',x))
x=copy.deepcopy(rows);x[0]['charge_categories']['P']='NaN';variants.append(('nonfinite',x))
for name,x in variants:compare(name,x)
# Validation is 12 passes versus exactly one, with equal outputs.
calls.update(validate=0,carry=0);a={support.cell_id(c):old.standalone(rows,c) for c in cells};a_calls=dict(calls)
calls.update(validate=0,carry=0);b=new.standalone_all(rows);b_calls=dict(calls)
assert a==b and a_calls['validate']==12*len(rows) and b_calls['validate']==len(rows) and a_calls['carry']==12 and b_calls['carry']==1
passed.append('full_validation_once_per_batch')
# No cross-call reuse: a later changed receipt must be rejected.
x=copy.deepcopy(rows);new.standalone_all(x);x[0]['receipt']={'literal':'tampered'}
assert outcome(lambda:new.standalone_all(x))[0]=='error';passed.append('no_cross_call_cache')
# Snapshot is detached even if a live clock callback mutates the caller list.
x=[row('P','P','1')];count=0

def clock():
 global count
 count+=1;x[0]['charge_categories']['P']='999';return '1'
b=new.standalone_all(x,parent_m_clock=clock)
assert count==13 and all(v['categories']['P']=='1' and v['categories']['M']=='1' for v in b.values())
passed.append('local_detached_snapshot_and_clock_count')
values=iter(['119.99']*12+['120.01'])
assert outcome(lambda:new.standalone_all([],parent_m_clock=lambda:next(values)))==('error','ValueError','category ceiling')
passed.append('final_shared_clock_overshoot_rejected')
values=iter([str(i) for i in range(13)])
b=new.standalone_all([],parent_m_clock=lambda:next(values));assert all(v['categories']['M']=='12' for v in b.values());passed.append('final_shared_clock_applies_all_cells')
assert outcome(lambda:new.standalone_all([],verify_receipts=False))[0]=='error';passed.append('no_public_unverified_batch')
# Exact original arithmetic statements remain AST-identical in the private helper.
a=next(n for n in ast.parse((OLD/'accounting.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='standalone')
b=next(n for n in ast.parse((ROOT/'accounting.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='_standalone_verified')
assert ast.dump(ast.Module(body=a.body[2:],type_ignores=[]))==ast.dump(ast.Module(body=b.body[1:],type_ignores=[]));passed.append('exact_original_formula_AST')
compile((ROOT/'eval_controller.py').read_text(),str(ROOT/'eval_controller.py'),'exec');passed.append('eval_controller_syntax')
print(json.dumps({'status':'PASS_FINITE_SYNTHETIC_ONLY','test_count':len(passed),'tests':passed,'validation_counts':{'old':a_calls,'batch':b_calls},'model_or_dataset_reads':False},sort_keys=True))
