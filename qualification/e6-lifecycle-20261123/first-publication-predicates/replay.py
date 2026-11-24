"""Recompute both first-publication predicates on the frozen failing cold01 capture."""
from pathlib import Path
import base64
import hashlib
import json
import sys
import tarfile

if not __debug__:
    raise RuntimeError("Run this verifier with normal Python assertions enabled")

def sha(data):return hashlib.sha256(data).digest()
def be64(n):return n.to_bytes(8,'big')
def compact(v):return json.dumps(v,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
def digest(domain,obj):return sha(domain+b'\0'+compact(obj))
def json_from(b):
    def unique(pairs):
        out={}
        for k,v in pairs:
            if k in out:raise ValueError('duplicate JSON key '+k)
            out[k]=v
        return out
    return json.loads(b,object_pairs_hook=unique)

archive=Path(sys.argv[1] if len(sys.argv)>1 else 'original-physical-data.tar.gz')
assert sha(archive.read_bytes()).hex()=='47364fc10bd07779339fbce47456586bab173a01b23ad45c83151f703f7fa5d4'
with tarfile.open(archive) as t:
    members = t.getmembers()
    assert len(members) == 35 and all(m.isfile() for m in members)
    files = {m.name: t.extractfile(m).read() for m in members}
    assert len(files) == len(members)
manifest=json_from(files['RESULT.json'])
assert set(manifest['files']) == set(files) - {'RESULT.json'}
for n,row in manifest['files'].items():
    assert len(files[n])==row['bytes'] and sha(files[n]).hex()==row['sha256']
def obj(n):return json_from(files[n])
stage='physical/ordinary-whole-phase/'
actual_fronts=[obj(n)['frontier'] for n in files if n.startswith('physical/authority/frontier-')]
accept=next(f['publication'] for f in actual_fronts if 'publication' in f)
profile=next(f['profile']['original'] for f in actual_fronts if 'registered_identity' in f)
completed=obj(stage+'actual-root-current.json')
pub=accept['current']['published'];signed=pub['signed'];grant=signed['grant']
material=obj('runtime/post-a-data/original-publication-material.json')
target=obj(stage+'original-c-target.json')
assert material['target']==target
cfg=material['target']['generation'];init=cfg['initial']
journal=files['runtime/post-a-data/c-generation.journal']
w=files['runtime/post-a-witnesses/c-generation.witness']
header=journal[:40];magic=b'HPTACG03'
# CellGenerationOwnerBindingV1::new hashes the ordered config plus its record bound.
assert header==magic+digest(b'hepta.cell.generation-owner.v2',[cfg,target['journal_records']])
n=int.from_bytes(journal[40:44],'big');payload=journal[44:44+n];frame_hash=journal[44+n:]
assert n==17 and len(journal)==40+4+17+32 and payload==b'{"event":"drain"}'
assert frame_hash==sha(b'hepta.cell.generation-frame.v2\0'+sha(header)+be64(1)+be64(n)+payload)
witheader=b'HPTNWA01'+bytes(target['witness_scope'])+bytes(target['witness_objective'])+be64(target['witness_generation'])
assert len(w)==224 and w[:112]==witheader+sha(witheader)
assert w[112:192]==be64(0)+bytes(32)+be64(1)+frame_hash and w[192:]==sha(w[112:192])
manifest_digest=digest(b'hepta.cell.backend.v2',cfg['manifest'])
assert manifest_digest==bytes(init['manifest_digest'])
snapshot_digest=digest(b'hepta.cell.runtime-state.v2',init)
assert snapshot_digest==bytes(profile['intent']['target']['initial_snapshot_digest'])
assert not init['state'] and init['revision']==0 and init['prefix']==[] and init['stopped'] is False
# Drain sets draining=true; it changes neither task snapshot nor costs nor pending work.
def observation(seq,head,size):
    ck=sha(b'hepta.cell.generation-continuity.v2\0'+header+be64(seq)+head+be64(size))
    obs=dict(task_digest=cfg['task_digest'],source_frontier=cfg['source_frontier'],initial_snapshot_digest=list(snapshot_digest),
             first_advance_input_digest=None,owner_checkpoint=list(ck),snapshot=init,
             cost=dict(schema_version=2,identity=dict(task_digest=cfg['task_digest'],source_digest=cfg['manifest']['source_digest']),entries=[]),
             pending_request_digest=None,pending_output=None)
    return ck,digest(b'hepta.cell.generation-observation.v1',obs)
gen_ck,gen_obs=observation(0,bytes(32),40)
end_ck,end_obs=observation(1,frame_hash,93)
assert gen_ck==bytes(profile['intent']['genesis_checkpoint'])

# Read the frozen HEPLCP02 encoding by fields. Offsets follow Reader::bundle and
# codec::decode. The stored digest is checked against the registered profile.
encoded=obj('physical/post-a-historical.json')['initial']['initial_snapshot']
raw=base64.b64decode(encoded+'='*(-len(encoded)%4),validate=True)
assert base64.b64encode(raw).decode().rstrip('=')==encoded
class Reader:
    def __init__(self,data):self.data=data;self.at=0
    def take(self,count):
        end=self.at+count
        if end>len(self.data):raise ValueError('truncated checkpoint')
        part=self.data[self.at:end];self.at=end;return part
    def uint(self,size):return int.from_bytes(self.take(size),'big')
    def stable_id(self):
        n=self.uint(1);assert 1<=n<=128
        return self.take(n).decode('utf-8')
    def optional(self,bytes_if_present):
        present=self.uint(1);assert present in (0,1)
        if present:self.take(bytes_if_present)
rd=Reader(raw)
assert rd.take(8)==b'HEPLCP02'
request_ids=[rd.stable_id() for _ in range(5)]
assert request_ids[0]==profile['learning_operation']
rd.take(3*32);rd.stable_id();assert rd.uint(8)>0;rd.take(11*32)
for _ in range(3):rd.optional(32)
rd.optional(4*32)
envelope_id=rd.stable_id();rd.take(4*32)
rd.take(2+8+2+1)
expiry_offset=rd.at;expiry=rd.uint(8)
rd.take(4+4*8+32)
for _ in range(7):rd.stable_id()
assert rd.uint(1)==0 and rd.take(32).hex()==profile['initial'] and rd.at==len(raw)

# CurrentHead::initial uses serde default/skip for None. Compare typed JSON
# objects for Eq; only compact canonical struct-order bytes are used for Rust hashes.
rev=accept['accepted_revocations'];vt=accept['verified_at_unix_ms']
rows=[]
def check(name,old,new=None,derived=None,previously_checked=False):
    v={'field':name,'parent_61503':bool(old),'candidate_bf6d':bool(old if new is None else new)}
    if derived is not None:v['readback']=derived
    if previously_checked:v['already_in_20261121_capture']=True
    rows.append(v)
check('schema == 1',accept['schema']==1,derived=accept['schema'])
check('purpose is the original publication acceptance purpose',accept['purpose']=='runtime.learning.original-publication-accepted.v1',derived=accept['purpose'])
check('original_profile == profile.binding',accept['original_profile']==profile['binding'],previously_checked=True)
check('current == completed.current',accept['current']==completed,previously_checked=True)
check('current.current == profile.intent.target',accept['current']['current']==profile['intent']['target'])
check('current.prepared.is_none()',accept['current'].get('prepared') is None)
check('current.initial.is_none()',accept['current'].get('initial') is None)
check('published.intent == profile.intent',pub['intent']==profile['intent'])
check('verified_at_unix_ms > 0',vt>0,derived=vt)
check('original_work_expiry_seconds == initial.request.envelope.expiry_unix_seconds',accept['original_work_expiry_seconds']==expiry,derived={'offset':expiry_offset,'stored':accept['original_work_expiry_seconds'],'decoded':expiry})
check('previous_observation == profile.intent.previous_observation',accept['previous_observation']==bytes(profile['intent']['previous_observation']).hex(),derived=accept['previous_observation'])
check('target_observation matches required Generation cut',accept['target_observation']==end_obs.hex(),accept['target_observation']==gen_obs.hex(),{'accepted':accept['target_observation'],'parent_final_cut':end_obs.hex(),'candidate_initial_cut':gen_obs.hex()})
end_head=1
old_genesis=end_head==0 and len(journal)==40
# The observed state began with no pending/outbox; the sole event sets draining=true.
is_drained=json_from(payload)=={'event':'drain'}
check('completed.generation requires genesis (old) or drained (candidate)',old_genesis,is_drained,{'is_genesis':old_genesis,'is_drained':is_drained,'journal_bytes':len(journal),'frames':end_head})
gd=digest(b'hepta.agentd.generation-update-signed-grant.v1',signed).hex()
check('computed signed_grant_digest == published.signed_grant_digest',gd==bytes(pub['signed_grant_digest']).hex(),derived=gd)
check('accepted_revocations.authority_epoch == published grant epoch',rev['authority_epoch']==grant['authority_epoch'],derived=[rev['authority_epoch'],grant['authority_epoch']])
check('published grant_id absent from accepted revoked_grant_ids',grant['grant_id'] not in rev['revoked_grant_ids'],derived={'number_revoked':len(rev['revoked_grant_ids'])})
main=list(rows);rows=[]
check('verified_at >= grant.not_before',vt>=grant['not_before_unix_ms'],derived=[vt,grant['not_before_unix_ms']])
check('verified_at < grant.expires',vt<grant['expires_at_unix_ms'],derived=[vt,grant['expires_at_unix_ms']])
check('verified_at / 1000 < original work expiry',vt//1000<accept['original_work_expiry_seconds'],derived=[vt//1000,accept['original_work_expiry_seconds']])
check('published witness verified_at <= verified_at',pub['witness']['verified_at_unix_ms']<=vt,derived=[pub['witness']['verified_at_unix_ms'],vt])
assert len(main)==16 and sum(r['parent_61503'] for r in main)==14 and all(r['candidate_bf6d'] for r in main)
assert len(rows)==4 and all(r['parent_61503'] and r['candidate_bf6d'] for r in rows)
print(json.dumps(dict(schema='hepta.e6.offline_first_publication_predicates.v1',original_capture_sha256=sha(archive.read_bytes()).hex(),
  original_source='61503a7d3bc87a5584cd2f20b8b17ea3838fdcfd',candidate_source='bf6d51904c8bcda5d50f3782c85ece84cb73a78f',frozen_members_verified=len(manifest['files']),
  main_conjunction=main,historical_time_conjunction=rows,journal=dict(header_sha256=sha(header).hex(),frame_anchor=frame_hash.hex(),genesis_checkpoint=gen_ck.hex(),final_checkpoint=end_ck.hex(),witness_bytes=len(w),events=['drain']),
  checkpoint=dict(magic='HEPLCP02',bytes=len(raw),expiry_offset=expiry_offset,recorded_head_equals_registered_initial=True,initial_receipts=0),
  original_first_false_position=12,second_false_position_if_individually_evaluated=13,candidate_main_true=16,historical_time_checks_true=4,
  scope='Python port on frozen cold01 inputs. Original Rust short-circuited its first conjunction. Rust initializer or live observer stamps, capability or signature issuance, cold expiry, restart, Adopt and future tasks were not executed. No compiler, native test, or daemon was invoked.',independent_tasks=0),ensure_ascii=False,indent=2))
