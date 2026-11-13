#!/usr/bin/env python3
"""Prepare exact approved input bytes locally; does not invoke H or any main."""
import ast
import base64
import gzip
import hashlib
import json
from pathlib import Path

OUT=Path(__file__).parent
CONTROL=Path('/tmp/hepta-36fa-source-repair-finalfmt-246d-v1')
PKT=Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1/NONRUST_APPLY_PACKET.json')
CFG=Path('/tmp/hepta-36fa-source-repair-root-inputs-v1/APPROVED_CONFIG.json')
NORMAL=Path('/tmp/hepta-36fa-final-source-qualification-launch-v1/SOURCE_STATUS_05.original.json')
def pin(b):
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def save(n,b):
    with (OUT/n).open('xb') as f:f.write(b)
    return {'name':n,**pin(b)}

driver=(CONTROL/'driver.HOLD.py').read_bytes();cfg=CFG.read_bytes();packet=PKT.read_bytes();normal=NORMAL.read_bytes()
assert pin(driver)=={'bytes':28621,'sha256':'0a7cc51c0ad9e1ef3b68e96f2942c36db04c3d42ee9dfcf8913099ea81a90228','git_blob':'9101b44fb2ab24ae41a1344425dd74b536a40de4'}
assert pin(cfg)=={'bytes':2057,'sha256':'a05f349b0691b37087527f6b22dad15b3e6850088abd5a88b971f970306399dc','git_blob':'baafb1a5f302f129716ae01ed24dea7b3bf3b5c1'}
assert pin(packet)=={'bytes':2209423,'sha256':'4e735b9402495886f079f5b35026bdc54e56e7ebb1bd179e3de07c25854ce29b','git_blob':'35debe83e69774f855ed198d35edaa762ae09573'}
assert pin(normal)=={'bytes':952,'sha256':'6499d8231230665037a977da78fe840177325f93b2b1e62f30a146251895d906','git_blob':'bcc7b94d9f9f721f6592632db5a6408468014270'}
v=json.loads(cfg);p=json.loads(packet)
assert v['driver']==pin(driver) and v['nonrust_packet']==pin(packet)
assert v['status']=='ROOT_APPROVED_TO_EXECUTE' and v['root_execution_approved'] is True
assert v['allowed_paths']==[x['path'] for x in p['changes']] and v['expected_after_physical_tree']==p['expected_after_physical_tree']
assert v['fmt_seconds']==900 and v['preflight_seconds']==600 and v['record_seconds']==300 and v['outer_seconds']==2100
template=(CONTROL/'BOOTSTRAP_TEMPLATE.HOLD.py').read_text()
assert template.count("'NONRUST_PACKET.json': None")==1 and template.count("'APPROVED_CONFIG.json': None")==1
code=template.replace("'NONRUST_PACKET.json': None","'NONRUST_PACKET.json': "+repr(pin(packet))).replace("'APPROVED_CONFIG.json': None","'APPROVED_CONFIG.json': "+repr(pin(cfg)))
ast.parse(code);compile(code,str(OUT/'ACTUAL_BOOTSTRAP.py'),'exec')
assert code.replace("'NONRUST_PACKET.json': "+repr(pin(packet)),"'NONRUST_PACKET.json': None").replace("'APPROVED_CONFIG.json': "+repr(pin(cfg)),"'APPROVED_CONFIG.json': None")==template
compressed=gzip.compress(packet,mtime=0)
assert gzip.decompress(compressed)==packet and pin(compressed)['sha256']=='2478ec462c8ae600c1c240ca3a420620090fe3275705794d9457180f68252080'
files={'driver.py':driver,'SOURCE_GATES_NORMAL.original.json':normal,'NONRUST_PACKET.json':compressed,'APPROVED_CONFIG.json':cfg}
stdin=(json.dumps({'format':'hepta-final-nonrust-format-bootstrap-v1','files':{k:base64.b64encode(b).decode() for k,b in files.items()}},sort_keys=True,separators=(',',':'))+'\n').encode()
assert len(stdin)<1048576
typed={'host':'desktop','executable':'/usr/bin/python3','args':['-B','-c',code],
       'cwd':'/home/qian-qi','timeout_seconds':2100,
       'idempotency_key':'hepta-utility-36fa-source-repair-246d-final-fmt-v1','stdin':stdin.decode()}
rows=[save('ACTUAL_BOOTSTRAP.py',code.encode()),save('ACTUAL_STDIN.json',stdin),
      save('ACTUAL_PROCESS_INPUT.json',(json.dumps(typed,indent=2,sort_keys=True)+'\n').encode()),
      save('APPROVED_CONFIG.original.json',cfg)]
manifest={'format':'hepta-source-repair-246d-final-format-exact-launch-v1',
 'status':'EXACT_INPUTS_SEALED_WAITING_ROOT_LAUNCH_REVIEW','native_main_dispatched':False,
 'source_writes':False,'H_calls':0,'qualification':False,'files':rows,
 'raw_inputs':{k:pin(b) for k,b in {'driver.py':driver,'SOURCE_GATES_NORMAL.original.json':normal,'NONRUST_PACKET.json':packet,'APPROVED_CONFIG.json':cfg}.items()},
 'transported_packet_gzip':pin(compressed),'bootstrap_two_none_replacements_only':True,
 'source_before':'246d8cb614770252ee42029a5c014f2a4904176a','before_tree':'d5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087',
 'expected_after_physical_tree':p['expected_after_physical_tree'],'approved_paths':v['allowed_paths'],
 'budgets':{'preflight':600,'fmt':900,'record':300,'outer':2100},'idempotency_key':typed['idempotency_key'],
 'source_failure_retained_as':'FAILED, normal exit 1; not reclassified and not a qualification prerequisite PASS',
 'source_mutation_scope':'Exactly five reviewed existing non-Rust files, then original just fmt --base c0f; no fix, tests, source refs, reset, rollback or dependency install.'}
save('EXACT_LAUNCH_MANIFEST.json',(json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode())
print(json.dumps({'files':rows,'manifest':pin((OUT/'EXACT_LAUNCH_MANIFEST.json').read_bytes()),'input_bytes':len(stdin),'dispatch_performed':False},indent=2))
