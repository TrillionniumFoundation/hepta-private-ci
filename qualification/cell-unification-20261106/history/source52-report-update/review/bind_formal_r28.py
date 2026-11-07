#!/usr/bin/env python3
"""Bind report candidates to the frozen r28 formal group, without changing the group or main reports."""
import gzip,hashlib,json,shutil
from pathlib import Path
B=Path('/workspace/scratch/08f5efd48967')
P=B/'source52-report-update-preparation'
R=B/'hepta-cell/qualification/cell-unification-20261106'
N=P/'new-files'
G=R/'native-evidence/r28-project-checkpoint'
D=N/'history/source52-r28-complete-checkpoint'
def pin(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def enc(o):return (json.dumps(o,ensure_ascii=False,indent=2)+'\n').encode()
def load(p):return json.loads(p.read_bytes())
def ref(p):return {'path':str(p.relative_to(R)),**pin(p.read_bytes())}
def keep(p,b):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():assert p.read_bytes()==b,p
 else:p.write_bytes(b)
for name in ['README.md','STATUS.json','SOURCE_IDENTITY.json']:
 assert (R/name).read_bytes()==(P/'references'/name).read_bytes(),name
assert pin((G/'CLOSURE.json').read_bytes())['sha256']=='4b0deafe8f0b6b6d405716eae380de0e5253efbc4677b9eafdab1b768b5a3465'
assert pin((G/'INDEPENDENT-READBACK.json').read_bytes())['sha256']=='c4144ca3679596fbfdd3beede12fffc269ec3eee4f56b0376ea92363657bba8c'
assert pin((G/'ATTACHMENT-MANIFEST.json').read_bytes())['sha256']=='f29e9590918445ba779631f801394cea6a734e369678e49922c4c26685bc0899'
closed=load(G/'CLOSURE.json')
assert closed['source_commit']=='1e0910becc37383e6d17ecf861ea844fd07d8862'
assert closed['source_tree']=='211f15baff19095e8c98bcea2b0ed99ca2270ade'
assert closed['original_outer_exit']==0 and set(closed['original_phase_exits'].values())=={0}
assert closed['counts']=={'unique':1564,'PASS':1564,'FAIL':0,'TIMEOUT':0,'reported_skipped':3}
facts=load(P/'FACTS.candidate.json')
old=facts['r28']
saved=P/'references/superseded-r28-direct-copies'
saved.mkdir(parents=True,exist_ok=True)
keep(saved/'FACTS-before-formal.json',(P/'FACTS.candidate.json').read_bytes())
keep(saved/'MANIFEST-before-formal.json',(D/'MANIFEST.json').read_bytes())
index=[]
for p in sorted(G.rglob('*')):
 if not p.is_file():continue
 assert not p.is_symlink(),p
 raw=p.read_bytes()
 index.append((p,pin(raw),None))
 if p.suffix=='.gz':
  try:decoded=gzip.decompress(raw)
  except (OSError,EOFError):continue
  index.append((p,pin(decoded),pin(raw)))
mapping={}
for name,oldref in old['closed_originals'].items():
 target={k:oldref[k] for k in ['bytes','sha256','git_blob']}
 matches=[item for item in index if item[1]==target]
 assert matches,(name,target)
 base=Path(oldref['path']).name
 matches.sort(key=lambda item:(item[0].name not in {base,base+'.gz'},item[2] is not None,len(item[0].parts),str(item[0])))
 path,original,stored=matches[0]
 linked={'path':str(path.relative_to(R)),**(stored or original)}
 if stored:linked.update(compression='gzip',original_uncompressed=original)
 mapping[name]=linked
 source=N/oldref['path']
 assert source.is_file() and pin(source.read_bytes())==target,source
 keep(saved/source.name,source.read_bytes())
 source.unlink()
facts['r28']['closed_originals']=mapping
facts['r28']['complete_snapshot']=ref(G/'CLOSURE.json')
facts['r28']['formal_attachment_manifest']=ref(G/'ATTACHMENT-MANIFEST.json')
facts['r28']['independent_readback']=ref(G/'INDEPENDENT-READBACK.json')
facts['r28']['binding_independent_readback']=old['independent_readback']
facts['r28']['formal_original_mapping_verified_by_exact_bytes']=True
facts['source52_formal_group_expected_but_not_assumed_present']='native-evidence/source52-repair-apply-checkpoint'
manifest={
 'schema':'hepta.source52-r28-formal-report-reference.v1',
 'classification':'FORMAL_ORIGINAL_PROJECT_GATE_REFERENCES_NO_DUPLICATE_LARGE_LOGS',
 'source_commit':closed['source_commit'],'source_tree':closed['source_tree'],
 'job_id':closed['original_gate_job'],'original_outer_exit_code':0,
 'formal_closure':ref(G/'CLOSURE.json'),'formal_independent_readback':ref(G/'INDEPENDENT-READBACK.json'),
 'formal_attachment_manifest':ref(G/'ATTACHMENT-MANIFEST.json'),
 'complete_originals':mapping,
 'independent_binding_and_closed_gate_readback':old['independent_readback'],
 'raw_log_and_test_rows_exactly_mapped_to_formal_gzip':True,
 'prior_candidate_duplicate_bytes_preserved_outside_publication_overlay':True,
 'whole_workspace_qualification':None,'fix_fmt_executed':False,
}
(D/'MANIFEST.json').write_bytes(enc(manifest))
(P/'FACTS.candidate.json').write_bytes(enc(facts))
readme=P/'build_readme_candidate.py'
text=readme.read_text()
for a,b in [
('[r28]: history/source52-r28-complete-checkpoint/MANIFEST.json','[r28]: native-evidence/r28-project-checkpoint/CLOSURE.json'),
('[r28-facts]: history/source52-r28-complete-checkpoint/INDEPENDENT-BINDING-AND-CLOSED-GATE-READBACK.json','[r28-facts]: native-evidence/r28-project-checkpoint/INDEPENDENT-READBACK.json')]:
 assert text.count(a)==1,a
 text=text.replace(a,b)
readme.write_text(text)
report={'schema':'hepta.source52-report-formal-r28-binding.v1','result':'CLEAR',
 'formal_closure':ref(G/'CLOSURE.json'),'formal_attachment_manifest':ref(G/'ATTACHMENT-MANIFEST.json'),
 'originals_verified':len(mapping),'mapping':mapping,
 'raw_originals_in_publication_overlay':0,'canonical_reports_unchanged':True,
 'existing_formal_group_unchanged':True,
 'r29_full_workspace_result':None,'gate_execution_by_editor':False}
(P/'FORMAL-R28-BINDING-READBACK.json').write_bytes(enc(report))
print(json.dumps({'result':'CLEAR','originals':len(mapping),'facts':pin((P/'FACTS.candidate.json').read_bytes()),
 'readback':pin((P/'FORMAL-R28-BINDING-READBACK.json').read_bytes())}))

