"""E5 raw request to cohort recount, observational and never authoritative."""
import argparse,hashlib,json
from pathlib import Path
from collections import defaultdict
class Invalid(ValueError): pass
def ident(v):
 if type(v) is not str or not 1<=len(v)<=128 or any(not(c.isascii() and (c.isalnum() or c in '._:-')) for c in v):raise Invalid('bad stable ID')
 return v
def digest(v):
 if type(v) is not str or len(v)!=64 or v=='0'*64 or any(c not in '0123456789abcdef' for c in v):raise Invalid('bad SHA256')
 return v
def recount(cohort,trace):
 if type(cohort) is not dict or type(trace) is not dict or cohort.get('authority')!='DENY_ALL' or trace.get('authority')!='DENY_ALL':raise Invalid('research only')
 if cohort.get('production_promotion_permitted') is not False or trace.get('production_promotion_permitted') is not False:raise Invalid('production forbidden')
 for k in ('run_sha256','model_sha256','host_sha256','worker_sha256','plan_sha256'):
  if digest(cohort.get(k))!=digest(trace.get(k)):raise Invalid('source identity drift '+k)
 rows=trace.get('requests')
 if type(rows) is not list or not 1<=len(rows)<=100000 or type(cohort.get('requests')) is not int or cohort['requests']!=len(rows):raise Invalid('request coverage')
 seen=set();cells=set();misses={};forwards={};batches=defaultdict(set);hits=0;failed=0
 for r in rows:
  if type(r) is not dict:raise Invalid('invalid request')
  rid=ident(r.get('request_id'));cell=ident(r.get('cell_id'));scope=ident(r.get('scope'))
  input_sha=digest(r.get('input_sha256'));prep=digest(r.get('preprocessor_sha256'));fence=digest(r.get('fence_sha256'))
  forward=ident(r.get('forward_id'));batch=ident(r.get('backend_batch_id'));gen=r.get('generation')
  if rid in seen or type(gen) is not int or gen<1:raise Invalid('duplicate or stale request')
  if r.get('final_use_checked') is not True or type(r.get('cache_hit')) is not bool or type(r.get('failed')) is not bool:raise Invalid('missing per-request evidence')
  seen.add(rid);cells.add(cell);failed+=int(r['failed']);key=(scope,gen,fence,prep,input_sha)
  if r['cache_hit']:
   hits+=1
   if forward not in misses or misses[forward]!=key:raise Invalid('unearned or cross-scope hit')
  else:
   if forward in misses:raise Invalid('duplicate forward')
   misses[forward]=key
  if forward in forwards and forwards[forward]!=batch:raise Invalid('forward/batch mismatch')
  forwards[forward]=batch;batches[batch].add(forward)
 result={'active_cells':len(cells),'observed_active_cells':len(cells),'requests':len(rows),
         'cache_hits':hits,'backend_forwards':len(misses),'real_batches':len(batches),
         'failed_requests':failed,'final_use_checked_requests':len(rows)}
 for k,v in result.items():
  if cohort.get(k)!=v:raise Invalid('reported aggregate mismatch '+k)
 if cohort.get('source_distinct_inputs')!=len({k[-1] for k in misses.values()}):raise Invalid('distinct input counter mismatch')
 n=cohort.get('logical_cells')
 if type(n) is not int or n not in (64,256,1024,4096) or not 1<=len(cells)<=n:raise Invalid('invalid cohort')
 if hits+len(misses)!=len(rows):raise Invalid('request attribution incomplete')
 return {'schema':'hepta.e5-request-recount.v1','logical_cells':n,'recomputed':result,
         'source_records_structurally_checked':True,'real_worker_execution_independently_verified':False,
         'final_use_claims_authenticated':False,'production_promotion_permitted':False,'authority':'DENY_ALL'}
def _object(items):
 out={}
 for k,v in items:
  if k in out:raise Invalid('duplicate JSON key')
  out[k]=v
 return out
def read(path):
 b=Path(path).read_bytes()
 if not 0<len(b)<=32*1024*1024:raise Invalid('bad evidence size')
 return json.loads(b,object_pairs_hook=_object,parse_constant=lambda _:(_ for _ in ()).throw(Invalid('nonfinite JSON')))
def main():
 p=argparse.ArgumentParser();p.add_argument('--cohort',required=True);p.add_argument('--trace',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 result=recount(read(a.cohort),read(a.trace))
 with Path(a.output).open('x',encoding='utf8') as output:json.dump(result,output,indent=2,sort_keys=True,allow_nan=False);output.write('\n')
if __name__=='__main__':main()
