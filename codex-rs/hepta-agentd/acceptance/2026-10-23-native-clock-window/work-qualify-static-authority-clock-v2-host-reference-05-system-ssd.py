from pathlib import Path
import hashlib, json, os, subprocess, sys, time

BASE=Path(__file__).resolve().parents[1]
DATA=Path('/data/asterinas-audit-build.8tdrjboi')
BUILD=DATA/'native-authority-static-5a2-clock-03'
OUT=DATA/'native-authority-clock-v2-static-host-reference-05-system-ssd'
OUT.mkdir(mode=0o700,exist_ok=False)
sys.dont_write_bytecode=True
sys.path.insert(0,str(BASE/'work/desktop-closure/tests/kernel/control'))
from run_g1c_guest import inspect_probe_elf

receipt=json.loads((BUILD/'result.json').read_text())
assert receipt['built'] and receipt['packaged'] and receipt['source_inputs_unchanged']
products={name:BUILD/'packaged'/name for name in receipt['products']}
report={'schema':'hepta.static-authority-host-reference.v1','source_head':receipt['source_head'],
        'source_tree':receipt['source_tree'],'products':{},'passed':False,
        'production_authority':False,'g2_complete':False,'native_execution':False}
for name,path in products.items():
    assert hashlib.sha256(path.read_bytes()).hexdigest()==receipt['products'][name]['packaged_sha256']
    report['products'][name]=inspect_probe_elf(path.read_bytes())
report['shape_original_checker']='original unmodified run_g1c_guest.inspect_probe_elf; file8MiB, mapped16MiB, original LOAD permissions/alignment'
launcher=DATA/'native-authority-v2-qualification-launcher-01'
report['launcher_sha256']=hashlib.sha256(launcher.read_bytes()).hexdigest()
report['launcher_source_sha256']=hashlib.sha256((BASE/'work/native_authority_v2_qualification_launcher.c').read_bytes()).hexdigest()
public=Path('/data/hepta-static-authority-clock-v2-reference-bin-05')
setup="""import os,shutil,sys,json
from pathlib import Path
dest=Path(sys.argv[1]); dest.mkdir(mode=0o755)
for item in sys.argv[2:]:
 source=Path(item);target=dest/source.name;shutil.copyfile(source,target);os.chmod(target,0o755)
print(json.dumps({'path':str(dest),'uid':dest.stat().st_uid,'mode':oct(dest.stat().st_mode&0o777)}))
"""
created=subprocess.run(['sudo','-n','/usr/bin/python3','-I','-B','-c',setup,str(public),str(launcher),*[str(p) for p in products.values()]],capture_output=True,text=True,check=True,timeout=60)
report['root_public_binary_copy']=json.loads(created.stdout)
assert report['root_public_binary_copy']['uid']==0
for p in [launcher,*products.values()]:assert hashlib.sha256((public/p.name).read_bytes()).digest()==hashlib.sha256(p.read_bytes()).digest()
# Read both complete executables before initializing any protected clock/lease.
# This is an explicit warm-page qualification, not a cold-start performance claim.
for path in products.values():
    with (public/path.name).open('rb') as stream:
        while stream.read(1024*1024): pass
report['whole_elf_prefetched_before_fresh_authority_init']=True
scope=json.dumps(list(hashlib.sha256(b'hepta:agentd:signed-objective:v1\0'+b'018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12').digest()),separators=(',',':'))
command=['sudo','-n',str(public/launcher.name),'/var/lib/hepta-authority-os3-ssd-20261023/native-clock-v2-static-reference-05','/var/lib/hepta-authority-os3-ssd-20261023','/var/lib/hepta-authority-private-os3-ssd-20261023',str(public/'hepta-authority-host'),str(public/'authority_host_peer_qualification'),scope]
report['storage_configuration']='fresh Root-only actual system SSD bind, distinct from build/data device; no migration/reset or original deadline changes'
report['command']=command
(OUT/'result.json').write_text(json.dumps(report,indent=2)+'\n')
start=time.monotonic()
with (OUT/'reference.log').open('xb') as log:
    result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=120)
text=(OUT/'reference.log').read_text(errors='replace')
observations=[]
for line in text.splitlines():
    if line.startswith('{'):
        try: item=json.loads(line)
        except json.JSONDecodeError: continue
        if item.get('qualification')=='root_authority_original_peer_v1': observations.append(item)
original_checks=(len(observations)==1 and observations[0]['uid']==60001
    and observations[0]['feed_elapsed_ms']<=500
    and observations[0]['objective_sequence']==2 and observations[0]['final_use_sequence']==3
    and observations[0]['checkpoint_ack'] is False
    and observations[0]['capabilities_clear'] and observations[0]['no_new_privileges'])
report['observations']=observations

report.update(exit_code=result.returncode,seconds=round(time.monotonic()-start,3),passed=result.returncode==0 and original_checks and text.count('NATIVE_AUTHORITY_COMPLETE pass=1 production_ready=0 g2_complete=0')==1,log_sha256=hashlib.sha256((OUT/'reference.log').read_bytes()).hexdigest())
(OUT/'result.json').write_text(json.dumps(report,indent=2)+'\n')
assert report['passed'],'actual frozen static authority Linux reference failed'
