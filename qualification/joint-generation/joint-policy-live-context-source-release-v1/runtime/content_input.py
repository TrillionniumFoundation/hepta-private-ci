"""Pure qualified-profile conversion; no inference, effect authority or budget grant."""
from dataclasses import dataclass
import hashlib,json,time
import numpy as np
from contracts import ContractError,RunSpec
from multimodal_contract import MediaEnvelope,BackendCapabilities,Modality,UnsupportedCapability
PROFILE='fashion-j-actor-selective-v1'
SEQUENCES=('actor-J-v1',)
CAPABILITIES=BackendCapabilities(PROFILE,frozenset((Modality.IMAGE,)),frozenset((Modality.TEXT,Modality.IMAGE)))
MAX_INPUT_WIRE=256*2**10
COUNTS={'attempts':0,'wire_bytes':0,'accepted':0,'rejected':0,'converted_pixel_elements':0,'CPU_seconds':0.}
@dataclass(frozen=True)
class ContentInput:
 pixels: np.ndarray
 run_spec: RunSpec
 sequence: str
 request_sha256: str
 source_wire_bytes: int
 decoding_seed: int
 input_byte_limit: int
 decoded_rgb_bytes: int

def unique(pairs):
 out={}
 for k,v in pairs:
  if k in out:raise ContractError('duplicate request field')
  out[k]=v
 return out

def convert(raw,*,expected_artifact_sha256,sequence,now_ns):
 """One RGB-gray28 envelope -> copied readonly float64 [1,784].

 Parse and bind caller-declared RunSpec; no model call and no authority or
 actual compute/output-budget enforcement. Later execution must re-admit.
 """
 start=time.process_time();COUNTS['attempts']+=1
 if type(raw) is bytes:COUNTS['wire_bytes']+=len(raw)
 try:
  if type(raw) is not bytes or not 1<=len(raw)<=MAX_INPUT_WIRE:raise ContractError('bounded request wire')
  if type(sequence) is not str or sequence not in SEQUENCES:raise UnsupportedCapability('fixed published sequence')
  try:value=json.loads(raw.decode('utf-8'),object_pairs_hook=unique)
  except (UnicodeError,ValueError) as e:raise ContractError('invalid request JSON') from e
  env=MediaEnvelope.parse(value,now_ns=now_ns);CAPABILITIES.require(env)
  if len(env.streams)!=1:raise UnsupportedCapability('exactly one image stream')
  if env.artifact_sha256!=expected_artifact_sha256:raise ContractError('selected artifact mismatch')
  if env.decoding_mode!='greedy' or env.decoding_seed!=0:raise UnsupportedCapability('mean/argmax profile requires greedy seed0')
  rgb=env.streams[0].payload.pixels
  if rgb.shape!=(28,28,3) or not np.array_equal(rgb[:,:,0],rgb[:,:,1]) or not np.array_equal(rgb[:,:,0],rgb[:,:,2]):raise UnsupportedCapability('normalized28 gray replicatedRGB only')
  spec=RunSpec.parse({'objective_id':env.objective_id,'run_id':env.run_id,'artifact_sha256':env.artifact_sha256,'modalities':[m.value for m in env.outputs],'budget':vars(env.budget),'deadline_ns':env.deadline_ns},now_ns=now_ns)
  pixels=rgb[:,:,0].astype(np.float64,copy=True).reshape(1,784);pixels.flags.writeable=False
  key=hashlib.sha256(PROFILE.encode()+b'\0'+sequence.encode()+b'\0'+raw).hexdigest()
  COUNTS['accepted']+=1;COUNTS['converted_pixel_elements']+=pixels.size
  return ContentInput(pixels,spec,sequence,key,len(raw),env.decoding_seed,env.input_bytes,rgb.nbytes)
 except Exception:
  COUNTS['rejected']+=1;raise
 finally:COUNTS['CPU_seconds']+=time.process_time()-start
