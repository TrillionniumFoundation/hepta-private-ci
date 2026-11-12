"""Prepare one create-only formatter request. Root is the only dispatcher."""
import ast
import base64
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import re

OUT=Path(__file__).resolve().parent
WORKSPACE=OUT.parent
SOURCE='a96d1b821d10ed3d9e99dd06c5141f9f242ae318'
TREE='f96bebefbc1e7d8187efadb62f88d524cdd18451'
RECORDS='/home/qian-qi/hepta-learn-037c-evidence/format-central-merged-lib-v1'
KEY='learn-037c-format-central-merged-lib-v1'
PATH='codex-rs/hepta-agentd/src/lib.rs'
INPUT=WORKSPACE/'candidate-central-assembly-a96-v1/actual-layers-v3/work'/PATH
STAGED=WORKSPACE/'candidate-central-assembly-a96-v1/actual-layers-v3/STAGED_FILES.json'
EXPECTED={'bytes':72278,'sha256':'9e37aad01df37d27a279581f9fe5535d392bbc267eed99ef8c07703bc9c4b69e','blob':'52877e53e769277a0bdf2bafd33054629ac97218'}

def meta(b):
 return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def jb(v):return (json.dumps(v,indent=2,ensure_ascii=False)+'\n').encode()
def save(name,b):
 p=OUT/name
 if p.exists():assert p.read_bytes()==b,'differing canonical: '+name
 else:p.write_bytes(b)

before=INPUT.read_bytes();assert meta(before)==EXPECTED
staged_bytes=STAGED.read_bytes();staged=json.loads(staged_bytes)
row=next(r for r in staged if r['path']==PATH);assert row['after']==EXPECTED
source_binding={
 'commit':SOURCE,'tree':TREE,
 'description':'Ancestor a96 plus the verified actual cohort component merges. This request formats only the single central merged lib.rs byte string in a fresh isolated record directory. It does not snapshot or access any current Git checkout, target cache, Cargo build or native test.',
 'input_path':str(INPUT),'merged_input':EXPECTED,
 'original_a96_file':row['base'],'merge_layers':row['layers'],
 'assembly_staged_manifest':{'path':str(STAGED),**meta(staged_bytes)},
 'not_raw_version_component':True,
 'current_git_source_snapshot':'OMITTED: this operation has no checkout or target access; exact ancestor and assembled input provenance are carried in the payload',
 'only_write_root':RECORDS,
}
origin={'base_kind':'verified central merged lib.rs; base equals formatter input, not bare a96','source_binding':source_binding}
files=[{'path':PATH,'base_exists':True,'base':EXPECTED,'before':EXPECTED,'base_utf8':before.decode(),'before_utf8':before.decode(),'origin':origin}]
input_manifest={'state':'NOT_SUBMITTED','first_start_owner':'/root','source_binding':source_binding,'files':[{k:v for k,v in r.items() if k not in {'base_utf8','before_utf8'}} for r in files],'counts':{'files':1,'production':1,'tests':0},'native':'UNRUN','ordinary_qualification':0}
template_path=WORKSPACE/'root-progress-postread-format-v3/format-driver.py'
template=template_path.read_bytes();assert meta(template)['sha256']=='d119f7392fba426f8a616c233007bf68fafc6ff46f34101f172fb7bded2eacca'
provenance={'original_driver_path':str(template_path),'original_driver':meta(template),'allowed_changes':['fresh record and artifact/qualification labels','one exact path and count','input payload hashes and per-file source binding'],'unchanged':['single argv-chunk launch','create-only records','Rust toolchain 1.96.0','rustfmt binary SHA 342c3d56e8958da0b108108a39e37ceac64ebdd42e6eefafa237d219e5b7eb0c','edition=2024, imports_granularity=Item, skip_children=true','no Git checkout/target/Cargo/native access'],'state':'NOT_SUBMITTED','first_start_owner':'/root'}
payload={'source_commit':SOURCE,'source_tree':TREE,'source_binding':source_binding,'files':files,'input_manifest':input_manifest,'format_method_provenance':provenance}
payload_bytes=jb(payload);compressed=gzip.compress(payload_bytes,mtime=0);encoded=base64.b64encode(compressed).decode()
driver=template.decode()
changes={
 'format-root-progress-postread-v3':'format-central-merged-lib-v1',
 'root-progress-postread-v3-prefmt.patch':'central-merged-lib-v1-prefmt.patch',
 'combined-root-progress-postread-v3.patch':'combined-central-merged-lib-v1.patch',
 'isolated Root progress/postread V3 formatting only; no native or ordinary qualification':'isolated central merged lib formatting only; no native or ordinary qualification',
 'assert len(payload["files"]) == 3':'assert len(payload["files"]) == 1',
}
for a,b in changes.items():assert a in driver;driver=driver.replace(a,b)
for name,value in [('INPUT_GZIP_SHA256',meta(compressed)['sha256']),('INPUT_JSON_SHA256',meta(payload_bytes)['sha256'])]:
 driver,n=re.subn('^'+name+r' = .*?$',name+' = '+repr(value),driver,count=1,flags=re.M);assert n==1
expected='EXPECTED_PATHS = {\n    '+repr(PATH)+',\n}'
driver,n=re.subn(r'^EXPECTED_PATHS = \{.*?^\}',expected,driver,count=1,flags=re.M|re.S);assert n==1

def normalized(source):
 class Normalize(ast.NodeTransformer):
  def visit_Assign(self,node):
   if len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id in {'INPUT_GZIP_SHA256','INPUT_JSON_SHA256','RECORDS','EXPECTED_PATHS'}:node.value=ast.Constant('PER_REQUEST:'+node.targets[0].id)
   return self.generic_visit(node)
  def visit_Assert(self,node):
   if ast.unparse(node.test) in {"len(payload['files']) == 3","len(payload['files']) == 1"}:node.test=ast.Constant('EXACT_FILE_COUNT')
   return self.generic_visit(node)
  def visit_Constant(self,node):
   aliases={
    'root-progress-postread-v3-prefmt.patch':'PREFMT_PATCH','central-merged-lib-v1-prefmt.patch':'PREFMT_PATCH',
    'combined-root-progress-postread-v3.patch':'COMBINED_PATCH','combined-central-merged-lib-v1.patch':'COMBINED_PATCH',
    'isolated Root progress/postread V3 formatting only; no native or ordinary qualification':'FORMAT_ONLY','isolated central merged lib formatting only; no native or ordinary qualification':'FORMAT_ONLY',
   }
   if isinstance(node.value,str) and node.value in aliases:node.value=aliases[node.value]
   return node
 return ast.dump(Normalize().visit(copy.deepcopy(ast.parse(source))),include_attributes=False)
normal=normalized(driver);assert normal==normalized(template.decode())
chunks=[encoded[i:i+32768] for i in range(0,len(encoded),32768)]
request={'host':'desktop','executable':'/usr/bin/python3','args':['-u','-c',driver,*chunks],'cwd':'/home/qian-qi/hepta-learn-037c-evidence','idempotency_key':KEY}
assert gzip.decompress(base64.b64decode(''.join(request['args'][3:]),validate=True))==payload_bytes
sizes=[len(request['executable'].encode()),*[len(s.encode()) for s in request['args']]];assert max(sizes)<=32768
arg_total=sum(n+1 for n in sizes);arg_max=os.sysconf('SC_ARG_MAX');assert arg_total+65536<arg_max
request_bytes=jb(request)
review={'state':'NOT_SUBMITTED','first_start_owner':'/root','stable_key':KEY,'records':RECORDS,'request':meta(request_bytes),'driver':meta(driver.encode()),'payload':meta(payload_bytes),'compressed':meta(compressed),'input':EXPECTED,'files':1,'base_equals_before':True,'source_binding':source_binding,'normalized_ast_equal_to_approved_driver':True,'normalized_ast_sha256':hashlib.sha256(normal.encode()).hexdigest(),'argument_sizes':sizes,'argument_total_bytes_with_nuls':arg_total,'local_SC_ARG_MAX':arg_max,'reserved_environment_and_pointer_bytes':65536,'remote_ARG_MAX':'not probed','create_only_records':True,'checkout_access':False,'target_access':False,'cargo_or_native_tests':False,'after_hash':'UNOBSERVED; requires actual formatter result','expected_bounds':{'only_rust_path':PATH,'original_input_bytes':72278,'base_before_postimage_copies':3,'required_source_paths':1,'max_argument_bytes':32768,'write_root':RECORDS,'rustfmt_config':'imports_granularity=Item,skip_children=true','rustfmt_edition':'2024','rustc_toolchain':'1.96.0','rustfmt_sha256':'342c3d56e8958da0b108108a39e37ceac64ebdd42e6eefafa237d219e5b7eb0c','rustfmt_after_bytes':'not pre-assumed; must verify actual manifest and patch','no_current_git_snapshot':True},'ordinary_qualification':0}
for name,b in {'format-driver.py':driver.encode(),'input-payload.json':payload_bytes,'input-payload.json.gz':compressed,'input-manifest.json':jb(input_manifest),'format-method-provenance.json':jb(provenance),'h-pty-start-request.json':request_bytes,'REQUEST_REVIEW.json':jb(review)}.items():save(name,b)
print(json.dumps({k:review[k] for k in ['state','stable_key','records','request','driver','payload','compressed','input','files','argument_sizes','argument_total_bytes_with_nuls','normalized_ast_equal_to_approved_driver']},indent=2))
