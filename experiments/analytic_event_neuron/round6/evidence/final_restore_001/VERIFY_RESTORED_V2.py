from pathlib import Path
import hashlib, importlib, json, os, stat, sys
import importlib.util
from datetime import datetime,timezone
OUT=Path(__file__).resolve().parent
restored=Path(sys.argv[1]).resolve()
assert Path.cwd().resolve()==restored
manifest=json.loads((OUT/'input_bundle/BUNDLE.json').read_text())
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while data:=stream.read(1024*1024):h.update(data)
    return h.hexdigest()
expected={x['name']:x for x in manifest['members']}
actual={str(p.relative_to(restored)) for p in restored.rglob('*')}
assert actual==set(expected), ('Restored tree differs',sorted(actual-set(expected)),sorted(set(expected)-actual))
for name,m in expected.items():
    p=restored/name
    assert not p.is_symlink() and stat.S_IMODE(p.stat().st_mode)==m['mode'],name
    if m['kind']=='file':assert p.is_file() and p.stat().st_size==m['bytes'] and sha(p)==m['sha256'],name
    else:assert m['kind']=='dir' and p.is_dir(),name
assert stat.S_IMODE(restored.stat().st_mode)==manifest['root_mode']
R=Path('experiments/analytic_event_neuron/round6');run=restored/R/'evidence/registered_001'
keys={'RESULTS.json':'303e98b4c6679f7dd827bb2c3a7083d96010984adbba43e1c6548b7930f53a69','FREEZE.json':'1f4d994da28d3bd61853a904d3e9da03b6ea6c90fe9d680e217f976656450ca1','PREPARED.json':'01cd90245b3d024d5be8676a684266c44a2e8e608fd9d175625db979d48d688a','native/analytic_event':'b519cae26325f818d9596aab34504490a0b5355b9eb633369878e6f07a50e179'}
allkeys={str(R/'evidence/registered_001'/p):v for p,v in keys.items()}
allkeys.update({str(R/p):v for p,v in {'REPORT.md':'3da96f337bff2abbe80645ec8ecf01295b4dc3fd40c974647198e61c2c689e88','REPORT_SOURCE.json':'8bf91c60944460cbe6930cfaba81861b121cfd075e8298f595bec6215be2be9a','evidence/review_confirmation_registered_001/REVIEW.json':'ef2ef939432eaa457b97def830f8719030e5050afa79457e4c663d33e5f977f2','evidence/report_review_001/FINAL_REPORT_REVIEW.json':'4b629de565b73bea167f1fd0542606a5f89d833a10288264b6b019cd96f9a917','REPRODUCE.md':'8a74b89b1e3e830bae9f5bed49281f14bfe936935939b109d9e42125911f4cb3','artifact_bundle.py':'3c98bfe234c1bfba14b72e114f771cd18c06fc900d754be3c59d3145a12cbb66'}.items()})
for name,wanted in allkeys.items():assert sha(restored/name)==wanted,name
preparing=json.loads((run/'PREPARING.json').read_text())
assert len(preparing['sources_sha256'])==118
for name,wanted in preparing['sources_sha256'].items():assert sha(restored/name)==wanted,name
sys.path.insert(0,str(restored))
name='experiments.analytic_event_neuron.round6.lifecycle'
spec=importlib.util.find_spec(name)
expected_module=restored/R/'lifecycle.py'
assert Path(spec.origin).resolve()==expected_module.resolve()
module=importlib.import_module(name)
assert Path(module.__file__).resolve()==expected_module.resolve()
assert sys.executable=='/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python'
assert os.access(run/'native/analytic_event',os.X_OK)
assert {str(p.relative_to(restored)) for p in restored.rglob('*')}==set(expected)
result={'schema':'hepta.round6.restored-checkout-verification.v1','passed':True,'created_utc':datetime.now(timezone.utc).isoformat(),'restored_root':str(restored),'parts_only_input':not (OUT/'input_bundle/archive.tar.gz').exists(),'files_verified':sum(x['kind']=='file' for x in manifest['members']),'directories_verified':sum(x['kind']=='dir' for x in manifest['members']),'all_members_rehashed_after_documented_helper_readback':True,'all_modes_and_exact_tree_verified':True,'frozen_source_files':118,'lifecycle_import_origin':str(module.__file__),'lifecycle_import_from_restored_checkout':True,'python_executable':sys.executable,'native_binary_mode':stat.S_IMODE((run/'native/analytic_event').stat().st_mode),'native_binary_executable':True,'native_protocol_invoked':False,'science_rerun':False,'key_restored_sha256':allkeys}
with (OUT/'RESTORE_VERIFICATION.json').open('x') as stream:
    json.dump(result,stream,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
print(json.dumps({'restored_verification_passed':True,'files':result['files_verified'],'directories':result['directories_verified'],'restored_root':str(restored),'lifecycle_import_origin':str(module.__file__)}),flush=True)
