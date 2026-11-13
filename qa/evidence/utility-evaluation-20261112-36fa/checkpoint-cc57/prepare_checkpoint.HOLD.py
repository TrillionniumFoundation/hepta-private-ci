"""Prepare an append-only checkpoint from the actual published 2841-file tree.

This is offline preparation only. Root supplies a frozen complete file map,
the separate newly verified metadata entries and a dated README after observing
the current main job; this file performs no Git API or native operations.
"""
import hashlib
import importlib.util
import json
import re
from pathlib import Path

OUT=Path('/tmp/hepta-36fa-cc57-evidence-publication-v1')
BASE=Path('/tmp/hepta-36fa-after2793-20261112')
HELPER=Path('/tmp/hepta-36fa-checkpoint-after-canonical-20261112/prepare_checkpoint.py')
REPO='TrillionniumFoundation/hepta-private-ci'
spec=importlib.util.spec_from_file_location('verified_prior_merkle_helpers',HELPER)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def main():
    anchors=json.loads((BASE/'PUBLISHED_2841_ANCHORS.json').read_bytes())
    base=json.loads((BASE/'PUBLISH_PLAN.json').read_bytes())['files']
    remote=json.loads(json.loads((BASE/'leaf.READ.response.json').read_bytes())['content'])
    assert len(base)==2841 and remote['truncated'] is False
    assert {r['path']:r['sha'] for r in remote['tree'] if r['type']=='blob'}==base
    assert module.merkle(base)[0]==anchors['evidence_leaf']==remote['sha']
    package=json.loads((OUT/'FROZEN_INPUT_FILEMAP.json').read_bytes())
    assert isinstance(package,dict) and set(base)<=set(package)
    assert all(package[p]==v for p,v in base.items())
    files=dict(package)
    for row in json.loads((OUT/'ROOT_VERIFIED_INCREMENTAL_ENTRIES.json').read_bytes()):
        raw=Path(row['local']).read_bytes()
        assert row['full_readback_equal'] is True
        assert module.oid('blob',raw)==row['sha']
        assert len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256']
        assert len(raw)<500000
        module.add(files,row['path'],row['sha'])
    archive='checkpoints/README_2841FILES_BEFORE_CC57_SOURCE_REQUALIFICATION.md'
    module.add(files,archive,base['README.md'])
    module.add(files,'checkpoint-cc57/prepare_checkpoint.HOLD.py',module.oid('blob',Path(__file__).read_bytes()))
    text=(OUT/'README.TEMPLATE.md').read_text()
    assert text.count('__FINAL_EVIDENCE_COUNT__')==1
    text=text.replace('__FINAL_EVIDENCE_COUNT__',f'{len(files):,}')
    raw=text.encode()
    files['README.md']=module.oid('blob',raw)
    assert [p for p in base if files[p]!=base[p]]==['README.md']
    for link in re.findall(r'\]\(([^)]+)\)',text):
        if '://' in link or link.startswith('#'):continue
        target=link.split('#')[0].rstrip('/')
        assert target in files or any(p.startswith(target+'/') for p in files),link
    (OUT/'README.PUBLISH.md').write_bytes(raw)
    leaf,directories=module.merkle(files)
    changed={p:sha for p,sha in files.items() if base.get(p)!=sha}
    requests=[{'kind':'leaf','expected_sha':leaf,'request':{
        'repository_full_name':REPO,'base_tree_sha':anchors['evidence_leaf'],
        'tree_elements':[{'path':p,'mode':'100644','type':'blob','sha':sha} for p,sha in sorted(changed.items())]}}]
    old_child,new_child=anchors['evidence_leaf'],leaf
    for kind,name in [('parent-evidence','utility-evaluation-20261112-36fa'),('parent-qa','evidence'),('parent-root','qa')]:
        old=json.loads(json.loads((BASE/(kind+'.READ.response.json')).read_bytes())['content'])
        assert module.tree_sha(old['tree'])==old['sha']==anchors['evidence_parent_trees'][kind]
        entries=[{k:r[k] for k in ('path','mode','type','sha')} for r in old['tree']]
        selected=[r for r in entries if r['path']==name]
        assert len(selected)==1 and selected[0]['mode']=='040000' and selected[0]['sha']==old_child
        selected[0]['sha']=new_child
        parent=module.tree_sha(entries)
        requests.append({'kind':kind,'expected_sha':parent,'request':{'repository_full_name':REPO,'base_tree_sha':old['sha'],'tree_elements':selected}})
        old_child,new_child=old['sha'],parent
    state=json.loads((OUT/'OBSERVED_STATE_THROUGH_VERIFY_START.json').read_bytes())
    assert state['source']=='cc57c7198db6293ccca562253c42fffbe2a04633'
    assert state['tree']=='b7b357c07b5539769a068c6b9b009629f5612d1e'
    plan={'format':'hepta-cc57-source-requalification-evidence-checkpoint-v1',
          'base_head':anchors['evidence_head'],'base_leaf':anchors['evidence_leaf'],
          'leaf_sha':leaf,'root_tree':new_child,'file_count':len(files),
          'unchanged_old_non_readme_paths':2840,'old_readme_archive':archive,
          'new_paths':len(files)-len(base),'tree_count':len(directories),
          'changed_old_paths':['README.md'],'tree_requests':requests,'files':files,
          'readme':{'bytes':len(raw),'sha':files['README.md'],'sha256':hashlib.sha256(raw).hexdigest()},
          'observed_state':state,'real_qualified_task_chain_outcomes':0}
    (OUT/'PUBLISH_PLAN.json').write_text(json.dumps(plan,sort_keys=True,indent=2)+'\n')
    print(json.dumps({k:v for k,v in plan.items() if k not in ('files','tree_requests')},sort_keys=True,indent=2))

if __name__=='__main__':main()
