import hashlib,json,os,subprocess,tempfile,zipfile
from pathlib import Path
archive=Path('/home/qian-qi/hepta-hcsn-independent-audit-20261111-3b200f7/original-c2-selected-state.zip')
expected='a1f624d88b3e240b3e583987210a1422c47cbab92ecd59beee5a1c6b28b2d92b'
data=archive.read_bytes()
if hashlib.sha256(data).hexdigest()!=expected: raise ValueError('original selected archive differs')
base='4ed61beacd9e8cf08cd1f7f8c938b75d747149e4'
branch='codex/hcsn-recovery-raw-evidence-20261111-3b20'
repo=Path(tempfile.mkdtemp(prefix='hepta-hcsn-raw-evidence-20261111-3b20-',dir='/tmp'))/'repo'
repo.mkdir()
def run(args,capture=False):
 result=subprocess.run(['git','-C',str(repo),*args],check=True,text=True,stdout=subprocess.PIPE if capture else None)
 return result.stdout.strip() if capture else None
run(['init'])
run(['remote','add','origin','https://github.com/TrillionniumFoundation/hepta-private-ci.git'])
run(['fetch','--depth=1','--filter=blob:none','origin',base])
if run(['rev-parse','FETCH_HEAD'],True)!=base: raise ValueError('fetched source differs')
run(['read-tree',base])
run(['symbolic-ref','HEAD','refs/heads/'+branch])
run(['update-ref','refs/heads/'+branch,base])
prefix='qualification/hcsn_differentiable/evidence/p2-c2-independent-recovery-20261111/original-selected-state'
out=repo/prefix
out.mkdir(parents=True)
parts=[]
for index,offset in enumerate(range(0,len(data),450000)):
 payload=data[offset:offset+450000]
 name=f'original-c2-selected-state.zip.part-{index:02d}'
 (out/name).write_bytes(payload)
 parts.append({'path':name,'offset':offset,'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()})
with zipfile.ZipFile(archive) as z:
 if z.testzip() is not None: raise ValueError('ZIP integrity failed')
 original=json.loads(z.read('MANIFEST.json'))
 for name,item in original['files'].items():
  payload=z.read(name)
  if len(payload)!=item['bytes'] or hashlib.sha256(payload).hexdigest()!=item['sha256']:
   raise ValueError('original member differs: '+name)
 (out/'ORIGINAL-SOURCE-MANIFEST.json').write_bytes(z.read('MANIFEST.json'))
manifest={'schema':'hcsn-original-c2-selected-archive-parts-v1','source_head':base,'original_archive_name':'original-c2-selected-state.zip','archive_bytes':len(data),'archive_sha256':expected,'part_size_limit_bytes':450000,'part_order':'Ascending offset, as listed in parts.','parts':parts,'original_source_file_count':len(original['files']),'original_source_uncompressed_bytes':sum(v['bytes'] for v in original['files'].values()),'qualification':'HOLD_NO_GO','original_controller_terminal':'unknown','selected_weights':'Four terminal best checkpoints and two incomplete last checkpoints.','scope':'Original selected-state bytes only; no training or adoption.'}
(out/'ARCHIVE-PARTS.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
readme='# Original selected C2 state bytes\n\nJoin the ten original-c2-selected-state.zip.part-* files in ascending\noffset order from ARCHIVE-PARTS.json, then verify the complete SHA-256 before\nopening the ZIP. Each part is at most 450,000 bytes; no blob policy is relaxed.\n\nThe ZIP preserves 368 original files, including four completed fit best\ncheckpoints, two incomplete fit last checkpoints, all 289 small immutable epoch\ncommit records, original torn journals and zero-byte interrupted artifacts.\nOriginal intermediate checkpoint bytes, nonempty full-development logit\npayloads and the complete prepared dataset are intentionally outside this\nselected archive. Their source identities remain in the original records.\n\nBoth original incomplete fit terminals and the controller terminal remain\nunknown. There is no new training, replay of training, automatic resume or\nadoption. Qualification remains HOLD_NO_GO.\n'
(out/'README.md').write_text(readme)
run(['add','--',prefix])
changed=run(['diff','--cached','--name-only',base],True).splitlines()
if len(changed)!=13 or not all(n.startswith(prefix+'/') for n in changed): raise ValueError('unexpected index changes: '+repr(changed))
run(['diff','--cached','--check'])
for p in out.iterdir():
 if p.stat().st_size>450000: raise ValueError('blob too large: '+str(p))
run(['-c','user.name=ChatGPT','-c','user.email=noreply@openai.com','commit','--signoff','-m','evidence(hcsn): preserve selected original C2 state bytes'])
commit=run(['rev-parse','HEAD'],True); tree=run(['rev-parse','HEAD^{tree}'],True)
run(['-c','credential.helper=','-c','credential.helper=!gh auth git-credential','push','origin','HEAD:refs/heads/'+branch])
remote=run(['ls-remote','origin','refs/heads/'+branch],True).split()[0]
if remote!=commit: raise ValueError('remote ref mismatch')
print(json.dumps({'repository':'TrillionniumFoundation/hepta-private-ci','branch':branch,'base':base,'commit':commit,'tree':tree,'files':changed,'archive_parts':manifest,'remote_ref_readback_equal':True,'workspace':str(repo)},sort_keys=True))
