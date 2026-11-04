"""Bound local file persistence, NOT authenticated authority or production security.

Caller supplies trusted expected request/spec/sequence and out-of-band file digest.
No model, no request execution, no grant. File fsync only: not crash-durable.
"""
import json,hashlib,os,tempfile,time
from pathlib import Path
from contracts import ContractError,RunSession,RunSpec
from content_input import convert,unique
MAX_BYTES=2*2**20
SCHEMA='local-bound-delivery-checkpoint-v1'
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode('ascii')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def stamp(value):
 if type(value)is not int or not 0<=value<2**63:raise ContractError('explicit nonnegative integer observation time')
 return value
def binding(raw,sequence,spec):
 if not isinstance(spec,RunSpec):raise ContractError('expected RunSpec required')
 # Validate content binding without granting liveness; expired/cancelled states
 # may be persisted for audit, but load delegates current-time expiry to restore.
 bound=convert(raw,expected_artifact_sha256=spec.artifact_sha256,sequence=sequence,now_ns=0)
 if bound.run_spec.payload()!=spec.payload():raise ContractError('full request/session identity-budget mismatch')
 return {'raw_request_sha256':sha(raw),'qualified_request_identity_sha256':bound.request_sha256,'sequence':sequence,'spec':spec.payload()}
def save(session,path,*,raw_request,sequence,observed_ns):
 start=time.process_time()
 if not isinstance(session,RunSession):raise ContractError('local RunSession required')
 b=binding(raw_request,sequence,session.spec)
 payload={'schema':SCHEMA,'binding':b,'observed_ns':stamp(observed_ns),'session':session.checkpoint()}
 raw=canonical({'payload':payload,'sha256':sha(canonical(payload))})
 if len(raw)>MAX_BYTES:raise ContractError('bounded local checkpoint')
 target=Path(path);fd,temp=tempfile.mkstemp(prefix='.delivery-',dir=target.parent)
 try:
  with os.fdopen(fd,'wb')as f:f.write(raw);f.flush();os.fsync(f.fileno())
  os.link(temp,target)
 finally:os.unlink(temp)
 return {'bytes_written':len(raw),'sha256':sha(raw),'CPU_seconds':time.process_time()-start,'crash_durable':False,'authority':'none; digest must be held by trusted local caller'}
def load(path,*,raw_request,sequence,expected_spec,expected_file_sha256,now_ns):
 start=time.process_time();now=stamp(now_ns)
 if type(expected_file_sha256)is not str or len(expected_file_sha256)!=64:raise ContractError('explicit expected file digest')
 with open(path,'rb')as f:raw=f.read(MAX_BYTES+1)
 if len(raw)>MAX_BYTES or sha(raw)!=expected_file_sha256:raise ContractError('file length/digest mismatch')
 try:data=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda s:(_ for _ in ()).throw(ValueError('nonfinite')))
 except (ValueError,UnicodeError)as e:raise ContractError('invalid checkpoint JSON')from e
 if type(data)is not dict or set(data)!={'payload','sha256'}:raise ContractError('checkpoint envelope')
 payload=data['payload']
 if type(payload)is not dict or set(payload)!={'schema','binding','observed_ns','session'} or payload['schema']!=SCHEMA or sha(canonical(payload))!=data['sha256']:raise ContractError('checkpoint schema/digest')
 if now<stamp(payload['observed_ns']):raise ContractError('time reversal across checkpoint')
 if payload['binding']!=binding(raw_request,sequence,expected_spec):raise ContractError('expected request/sequence/spec binding')
 record=payload['session']
 if type(record)is not dict or set(record)!={'payload','sha256'} or type(record['payload'])is not dict or record['payload'].get('spec')!=expected_spec.payload():raise ContractError('session spec mismatch')
 session=RunSession.restore(payload['session'],expected_artifact_sha256=expected_spec.artifact_sha256,now_ns=now)
 return session,{'bytes_read':len(raw),'sha256':sha(raw),'CPU_seconds':time.process_time()-start,'authority':'none; trusted digest and expected full binding only'}
