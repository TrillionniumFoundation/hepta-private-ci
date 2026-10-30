from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
from datetime import datetime,timezone
OUT=Path(__file__).resolve().parent
SOURCE=OUT.parent/'final_bundle_001'
EXPECTED='539d5b59740faeb3e96f68428d7af093e48ec47156e14de2ab0b346e16426bfc'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,value):
    with (OUT/name).open('x') as stream:
        json.dump(value,stream,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
assert sha(SOURCE/'BUNDLE.json')==EXPECTED
manifest=json.loads((SOURCE/'BUNDLE.json').read_text())
assert len(manifest['parts'])==451 and manifest['archive']['bytes']==354658019
assert manifest['archive']['sha256']=='2a1b985439029ada9eb3493a6f2cb6d51d204fe051ef2327e9e7d2ef397e5336'
target=OUT/'input_bundle';target.mkdir()
shutil.copyfile(SOURCE/'BUNDLE.json',target/'BUNDLE.json')
for item in manifest['parts']:
    shutil.copyfile(SOURCE/item['name'],target/item['name'])
    assert (target/item['name']).stat().st_size==item['bytes'] and sha(target/item['name'])==item['sha256']
assert set(x.name for x in target.iterdir())=={'BUNDLE.json',*[x['name'] for x in manifest['parts']]}
assert not (target/'archive.tar.gz').exists()
index={'manifest_sha256':EXPECTED,'bundle_path':'experiments/analytic_event_neuron/round6/evidence/final_bundle_001'}
save('FINAL_PUBLICATION_INPUT.json',index);(OUT/'FINAL_PUBLICATION_INPUT.json').chmod(0o444)
save('INPUT_STAGING.json',{'schema':'hepta.round6.local-parts-only-restore-input.v1','created_utc':datetime.now(timezone.utc).isoformat(),'source':str(SOURCE),'destination':str(target),'source_kind':'local sealed package, not a new remote download','manifest_sha256':EXPECTED,'parts':451,'part_bytes':354658019,'input_files':452,'archive_tar_gz_omitted':True,'all_copied_part_hashes_verified':True,'publication_input_sha256':sha(OUT/'FINAL_PUBLICATION_INPUT.json'),'publication_input_status':'Immutable preliminary input containing the two guide-required fields; these fields must be identical in the final published index. The final published index does not yet exist in this verification.'})
env=dict(os.environ);env['TMPDIR']=str(OUT/'tmp')
command=['bash',str(OUT/'RUN_DOCUMENTED.sh'),str(OUT/'DOCUMENTED_COMMANDS.sh'),sys.executable,str(OUT/'VERIFY_RESTORED.py')]
save('DOCUMENTED_EXECUTION_INPUT.json',{'command':command,'TMPDIR':env['TMPDIR'],'default_mktemp_command_unchanged':True})
completed=subprocess.run(command,env=env)
if completed.returncode:sys.exit(completed.returncode)
assert sha(SOURCE/'BUNDLE.json')==EXPECTED
assert sha(target/'BUNDLE.json')==EXPECTED
assert not (target/'archive.tar.gz').exists()
print(json.dumps({'driver_passed':True,'input_staging_sha256':sha(OUT/'INPUT_STAGING.json'),'restored_verification_sha256':sha(OUT/'RESTORE_VERIFICATION.json')}),flush=True)
