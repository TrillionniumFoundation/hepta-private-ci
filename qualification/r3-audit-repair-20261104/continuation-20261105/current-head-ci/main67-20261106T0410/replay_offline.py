from pathlib import Path
import subprocess,hashlib,json
D=Path('/tmp/hepta-runtime-recovery-20261106/format-review-recovery/main92-six-artifacts-delivery-v2')
R=Path('/tmp/hepta-runtime-recovery-20261106/format-review-recovery/main92-v2-offline-restored/root')
ORIG=Path('/tmp/hepta-runtime-recovery-20261106/format-review-recovery')
DIAG=Path('/workspace/scratch/07dd58cc9630/recovery-20261106/diagnostic-terminal-0410')
def ident(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
calls=[
 ('decode-five',['python3',str(R/'main/decode_five_compacts.py')],ORIG/'main67-failures-0410/decode.stdout.jsonl'),
 ('decode-GNU',['python3',str(R/'main/decode_gnu_compact.py')],ORIG/'main67-failures-0410/gnu-addendum/decode.stdout.jsonl'),
 ('verify-main',['python3',str(R/'main/verify_packet.py')],ORIG/'main67-failures-0410/VERIFICATION.json'),
 ('bind-B23',['python3',str(R/'b23-review/bind_b23_compacts_portable.py'),'--main',str(R/'main'),'--diagnostic',str(DIAG),'--decoder',str(R/'b23-review/borrowed/decode_compact.py'),'--main-display',str(ORIG/'main67-failures-0410'),'--diagnostic-display',str(DIAG)],ORIG/'b23-native-scope-independent-20261106/COMPACT_BINDING.json'),
 ('verify-B23',['python3',str(R/'b23-review/verify_original_scope.py'),'--main',str(R/'main'),'--diagnostic',str(DIAG),'--source',str(R/'b23-review/source'),'--binding',str(D/'bind-B23.replay.stdout.json')],ORIG/'b23-native-scope-independent-20261106/SCOPE_VERIFICATION.json')]
results=[]
for name,cmd,expected in calls:
 p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
 (D/(name+'.replay.stdout.json')).write_bytes(p.stdout);(D/(name+'.replay.stderr.txt')).write_bytes(p.stderr)
 assert p.returncode==0 and p.stderr==b'',(name,p.returncode,p.stderr.decode())
 assert p.stdout==expected.read_bytes(),name
 results.append({'name':name,'command':cmd,'exit_code':p.returncode,'stderr':ident(p.stderr),'stdout':ident(p.stdout),'frozen_stdout_bytes_equal':True})
manifest=json.loads((D/'bundle-manifest.json').read_bytes())
for item in manifest['members']:
 b=(R.parent/item['path']).read_bytes();assert ident(b)==item['identity'],item['path']
for item in manifest['nested_archives']:
 for member in item['members']:
  b=(R.parent/item['expanded_root']/member['path']).read_bytes();assert ident(b)==member['identity']
receipt={'schema':'main92-lossless-restoration-and-offline-replay-receipt-v2','archive':manifest['archive'],'restored_member_count':len(manifest['members'])+sum(len(z['members']) for z in manifest['nested_archives']),'all_restored_files_still_exact_after_replays':True,'replays':results,'external_diagnostic_dependency_scope':'Only already saved original root B23 artifacts/API were read. Their SHA256 identities are in bundle-manifest; no new API/native execution.','display_path_alias_scope':'B23 portable checker changes only printed historical absolute log path prefix, all actual reads use independent restored main root.'}
(D/'offline-replay-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'all_passed':True,'replays':len(results),'members':receipt['restored_member_count'],'stdout_bytes':[x['stdout']['bytes'] for x in results]},indent=2))

