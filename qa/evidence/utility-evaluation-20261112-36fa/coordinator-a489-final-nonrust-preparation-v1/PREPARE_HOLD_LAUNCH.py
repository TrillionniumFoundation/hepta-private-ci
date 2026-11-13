#!/usr/bin/env python3
"""Create reviewable HOLD bytes only. No native tool invocation or exec."""
import ast
import base64
import difflib
import gzip
import hashlib
import json
from pathlib import Path

ROOT=Path('/tmp/hepta-36fa-coordinator-a489-final-nonrust-preparation-v1')
OUT=ROOT/'launch-hold-v1'
BASE='/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1'
OLD=Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-hold-v1/ORIGINAL_9101_BOOTSTRAP.py')
PACKET_DIR=Path('/tmp/hepta-36fa-a489-maintenance-nonrust-apply-packet-v1')
RUNTIME=Path('/tmp/hepta-36fa-coordinator-a489-maintenance-runtime-v1')

def identity(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def encode(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()

def save(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==raw
    else:
        with path.open('xb')as f:f.write(raw)
    return identity(raw)

def defs(raw):
    lines=raw.decode().splitlines(True)
    return {node.name:''.join(lines[node.lineno-1:node.end_lineno]) for node in ast.parse(raw).body if isinstance(node,ast.FunctionDef)}

old=OLD.read_bytes()
assert identity(old)=={'bytes':5711,'sha256':'be4d44559060e5129818b313c7142aa0fb934ae00c5a1e74f1e11ef8fb6a725a','git_blob':'9ca752893983b582f2394c054e92a0adc265cb8f'}
save(ROOT/'inputs/ORIGINAL_9101_BOOTSTRAP.py',old)
cfg=(ROOT/'WAITING_INPUT_BOUND_CONFIG.json').read_bytes()
parsed_cfg=json.loads(cfg)
assert parsed_cfg['root_execution_approved']is False and parsed_cfg['status']=='HOLD_ROOT_EXACT_REVIEW_REQUIRED'
packet=(PACKET_DIR/'NONRUST_PACKET.json').read_bytes()
packet_gz=(PACKET_DIR/'NONRUST_PACKET.json.gz').read_bytes()
assert gzip.decompress(packet_gz)==packet
assert identity(packet)==parsed_cfg['nonrust_packet']
files={
    'driver.py':(ROOT/'driver.HOLD.py').read_bytes(),
    'MAINTENANCE_NORMAL.original.json':(RUNTIME/'STATUS_06.original.json').read_bytes(),
    'NONRUST_PACKET.json':packet,
    'APPROVED_CONFIG.json':cfg,
}
pins={name:identity(raw)for name,raw in files.items()}
assert pins['driver.py']==parsed_cfg['driver']
assert pins['MAINTENANCE_NORMAL.original.json']==parsed_cfg['actual_prior_maintenance']['supervisor']
old_lines=old.decode().splitlines(True)
old_base=next(line for line in old_lines if line.startswith('BASE = '))
old_pins=next(line for line in old_lines if line.startswith('PINS = '))
new_base='BASE = pathlib.Path('+repr(BASE)+')\n'
new_pins='PINS = '+repr(pins)+'\n'
source=old.decode().replace(old_base,new_base,1).replace(old_pins,new_pins,1)
assert source.replace(new_base,old_base,1).replace(new_pins,old_pins,1).encode()==old
assert defs(source.encode())==defs(old)
assert len(defs(old))==4
compile(source,'ACTUAL_BOOTSTRAP.HOLD.py','exec')
payload={'format':'hepta-final-nonrust-format-bootstrap-v1',
         'files':{name:base64.b64encode(packet_gz if name=='NONRUST_PACKET.json'else raw).decode()for name,raw in files.items()}}
stdin=encode(payload)
request={'host':'desktop','executable':'/usr/bin/python3','args':['-B','-c',source],
         'cwd':'/home/qian-qi','stdin':stdin.decode(),'timeout_seconds':2100,
         'idempotency_key':'hepta-utility-36fa-provider-coordinator-a489-final-nonrust-format-v1'}
typed=encode(request)
assert set(request)=={'host','executable','args','cwd','stdin','timeout_seconds','idempotency_key'}
assert len(stdin)<=1048576 and len(typed)<=1048576
for name,pin in pins.items():
    decoded=base64.b64decode(json.loads(request['stdin'])['files'][name],validate=True)
    if name=='NONRUST_PACKET.json':decoded=gzip.decompress(decoded)
    assert identity(decoded)==pin and decoded==files[name]
bootstrap_pin=save(OUT/'ACTUAL_BOOTSTRAP.HOLD.py',source.encode())
stdin_pin=save(OUT/'ACTUAL_STDIN.HOLD.json',stdin)
request_pin=save(OUT/'ACTUAL_PROCESS_INPUT.HOLD.json',typed)
save(OUT/'APPROVED_CONFIG.HOLD.json',cfg)
save(OUT/'BOOTSTRAP_FROM_9101.diff',''.join(difflib.unified_diff(old.decode().splitlines(True),source.splitlines(True),
    fromfile='original-9ca752-bootstrap.py',tofile='ACTUAL_BOOTSTRAP.HOLD.py')).encode())
save(OUT/'INPUT_FILES.json',encode({'format':'hepta-last-nonrust-exact-four-inputs-v1','files':pins,
    'source_packet_compression':identity(packet_gz),'source_packet_bounded_manifest':'aa4e9a0118bee4521b192b14155ce0aab9a78be7',
    'source_packet_bounded_placement':'32075cb2e9533547a0537614f6600ee1b71b6570',
    'control':BASE,'output':BASE+'/run','qualification':False,'execution_authorized':False}))
encoded=[]
for name,body in [('ACTUAL_STDIN.HOLD.json',stdin),('ACTUAL_PROCESS_INPUT.HOLD.json',typed)]:
    if len(body)<=512000:continue
    compressed=gzip.compress(body,mtime=0)
    parts=[]
    for number,offset in enumerate(range(0,len(compressed),307200),1):
        chunk=compressed[offset:offset+307200]
        namepart=name+'.gz.part-%03d.b64'%number
        raw=base64.b64encode(chunk)+b'\n'
        pin=save(OUT/namepart,raw)
        assert pin['bytes']<=512000
        parts.append({'name':namepart,'decoded_offset':offset,'decoded':identity(chunk),**pin})
    assert b''.join(base64.b64decode((OUT/row['name']).read_bytes().rstrip(b'\n'),validate=True)for row in parts)==compressed
    assert gzip.decompress(compressed)==body
    encoded.append({'original_name':name,'raw':identity(body),'gzip':identity(compressed),'parts':parts,
                    'raw_standalone_git_storage_claimed':False})
save(OUT/'ENCODING_MANIFEST.json',encode({'format':'hepta-bounded-hold-launch-representations-v1',
    'leaf_limit':512000,'members':encoded,'note':'Lossless representations of exact local HOLD request/stdin; actual native observations do not exist.'}))
review={
    'format':'hepta-last-nonrust-exact-hold-launch-review-v1','status':'HOLD_NOT_DISPATCHED',
    'bootstrap':bootstrap_pin,'stdin':stdin_pin,'request':request_pin,'config':identity(cfg),'four_inputs':pins,
    'request_fields':sorted(request),'outer_seconds':2100,'stdin_bytes':len(stdin),'typed_bytes':len(typed),
    'no_env_field':True,'source_packet_bound':40000000,'all_four_decoded_bytes_equal':True,
    'bootstrap_original':identity(old),'exact_changes':['BASE fixed new control path','PINS exact four new input identities'],
    'full_inverse_equal':True,'unchanged_helper_bodies':list(defs(old)),
    'execution_order':['Verify bounded input and all four hashes in memory','Create fresh fixed control directory only','Create and fully read back original bootstrap/argv/payload plus four files, O_EXCL|O_NOFOLLOW, 0600','Retain STAGING_READBACK and fsync','exec original thin driver without holding any lock','Thin main alone acquires the original EX and revalidates full actual source/Git/runtime','Apply exactly four reviewed nonRust files','Original fmt900','Full actual retention and three final audits'],
    'single_ex_owner':'thin main only; no bootstrap fcntl or lease',
    'current_config_is_HOLD':True,'root_execution_approved':False,
    'request_is_not_dispatch_authority':True,'H_calls':0,'qualification':False,
    'unknown_policy':'No new key/path/variant, rollback or overwrite. No native request has been submitted. A future exact engineering approval must bind the final approved config and final request bytes.',
}
save(OUT/'EXACT_HOLD_LAUNCH_REVIEW.json',encode(review))
print(json.dumps({'bootstrap':bootstrap_pin,'stdin':stdin_pin,'request':request_pin,'config':identity(cfg),
                  'bounded_representations':len(encoded),'H_calls':0,'approved':False},indent=2))
