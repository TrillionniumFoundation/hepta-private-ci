"""Resume pre-native setup with the already-frozen Hypothesis platform wheel."""
from pathlib import Path
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from setup_native_environment import ROOT, PREVIOUS, digest, write, checked_fetch

def main():
    assert sys.version_info[:2] == (3,12) and platform.machine() == 'x86_64' and sys.platform == 'linux'
    assert (ROOT/'SETUP_OWNER_LOCK.json').exists()
    assert not (ROOT/'venv').exists() and not (ROOT/'replay-1').exists() and not (ROOT/'owner-1').exists()
    write(ROOT/'SETUP_RECOVERY_OWNER_LOCK.json',{'pid':os.getpid(),'started_at_ns':time.time_ns(),'native_children':0})
    material=json.loads((ROOT/'MATERIALS_MANIFEST.json').read_bytes())
    for row in material: assert digest(ROOT/row['path'])==row['sha256']
    env=ROOT/'environment';wheels=ROOT/'wheels'
    write(ROOT/'SETUP_RECOVERY.json',{'reason':'Original selector expected a universal Python wheel; the already-frozen latest Hypothesis release provides platform wheels. Setup failed before venv creation or any native child. Select the matching CPython3.12 manylinux x86_64 wheel of the identical version6.170.16.', 'original_setup_script_preserved':True,'original_metadata_preserved':True,'native_children_before_recovery':0,'native_protocol_unchanged':True,'no_native_retry':True})
    assert digest(PREVIOUS/'environment/WHEELS.json') == 'f2d87178a1da20cf9e04abc0a6728b040cc60c9f071a648c837fa068d534fece'
    wanted={'attrs','iniconfig','packaging','pluggy','pygments','pytest','pytest_timeout'}
    reused=[row for row in json.loads((PREVIOUS/'environment/WHEELS.json').read_bytes()) if row['name'].split('-')[0].lower() in wanted]
    assert len(reused)==7
    requirements=[]
    for row in reused:
        assert (wheels/row['name']).stat().st_size==row['bytes'] and digest(wheels/row['name'])==row['sha256']
        distribution,version=row['name'].split('-')[:2];requirements.append(distribution+'=='+version)
    added=[]
    for distribution in ['hypothesis','sortedcontainers']:
        metadata_url='https://pypi.org/pypi/'+distribution+'/json';metadata_file=env/(distribution+'.pypi.json')
        if distribution=='hypothesis':
            metadata=json.loads(metadata_file.read_bytes());assert metadata['info']['version']=='6.170.16'
            expected_name='hypothesis-6.170.16-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl'
            selected=[r for r in metadata['urls'] if r['filename']==expected_name and r['packagetype']=='bdist_wheel' and not r.get('yanked')]
        else:
            metadata=json.loads(checked_fetch(metadata_url,32*1024*1024,metadata_file))
            selected=[r for r in metadata['urls'] if r['packagetype']=='bdist_wheel' and (r['filename'].endswith('-py3-none-any.whl') or r['filename'].endswith('-py2.py3-none-any.whl')) and not r.get('yanked')]
        assert len(selected)==1
        chosen=selected[0];version=metadata['info']['version'];b=checked_fetch(chosen['url'],8*1024*1024,wheels/chosen['filename'])
        assert len(b)==chosen['size'] and hashlib.sha256(b).hexdigest()==chosen['digests']['sha256']
        requirements.append(distribution+'=='+version)
        added.append({'distribution':distribution,'version':version,'requires_python':metadata['info'].get('requires_python'),'requires_dist':metadata['info'].get('requires_dist'),'metadata_url':metadata_url,'metadata_sha256':digest(metadata_file),'wheel_url':chosen['url'],'wheel':chosen['filename'],'bytes':len(b),'sha256':digest(wheels/chosen['filename'])})
    write(env/'DEPENDENCY_FREEZE_BEFORE_INSTALL.json',{'reused_wheels_manifest_sha256':digest(PREVIOUS/'environment/WHEELS.json'),'reused_wheels':reused,'added_dependencies':added,'direct_exact_requirements':requirements,'purpose':'Original conftest import only; selected test has no generated Hypothesis examples. Both variants use this identical environment.','new_native_children':0})
    python=str(ROOT/'venv/bin/python')
    commands=[[sys.executable,'-m','venv',str(ROOT/'venv')],[python,'-m','pip','--isolated','--disable-pip-version-check','install','--no-index','--no-deps','--find-links',str(wheels),*requirements],[python,'-m','pip','check'],[python,'-I','-c','import sys,pytest,pytest_timeout,hypothesis,sortedcontainers; assert sys.version_info[:2] == (3,12); print(sys.version); print(pytest.__version__); print(hypothesis.__version__)']]
    for i,argv in enumerate(commands):
        began=time.perf_counter()
        with (env/f'{i}.stdout').open('xb') as out,(env/f'{i}.stderr').open('xb') as err:process=subprocess.run(argv,stdout=out,stderr=err,timeout=180)
        write(env/f'{i}.EXIT.json',{'argv':argv,'exit_code':process.returncode,'wall_seconds':time.perf_counter()-began})
        assert process.returncode==0,{'stage':i,'exit_code':process.returncode}
    freeze=subprocess.run([python,'-m','pip','freeze','--all'],capture_output=True,check=True,timeout=30).stdout;(env/'pip-freeze.txt').write_bytes(freeze)
    write(env/'WHEELS.json',[{'name':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(wheels.iterdir())])
    for row in material:assert digest(ROOT/row['path'])==row['sha256']
    write(ROOT/'ACQUISITION.json',{'status':'ACQUIRED','material_manifest_sha256':digest(ROOT/'MATERIALS_MANIFEST.json'),'snapshots_sha256':digest(ROOT/'SOURCE_RECEIPTS.json'),'plan_sha256':digest(ROOT/'ACQUISITION_PLAN.json'),'dependency_freeze_sha256':digest(env/'DEPENDENCY_FREEZE_BEFORE_INSTALL.json'),'wheel_manifest_sha256':digest(env/'WHEELS.json'),'pip_freeze_sha256':digest(env/'pip-freeze.txt'),'setup_recovery_sha256':digest(ROOT/'SETUP_RECOVERY.json'),'native_children':0,'model_calls':0,'training_updates':0,'source_growth_qualified':False})
    print(json.dumps({'status':'READY_FOR_PRE_NATIVE_FREEZE','exact_requirements':requirements,'native_children':0}),flush=True)

if __name__=='__main__':main()
