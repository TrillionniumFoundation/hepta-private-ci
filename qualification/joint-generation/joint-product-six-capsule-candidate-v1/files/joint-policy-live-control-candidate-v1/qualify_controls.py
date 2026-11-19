"""Metadata-only protocol negatives; not model faults or reboot experiments."""
import os,time,struct,copy
from control_channel import FrameReader,ChannelError,canonical as channel_canonical
from live_control import Clock
from contracts import ContractError
from persistence import canonical,sha

def qualify(clock):
 checks=[];refusals=[]
 def check(n,v):
  if not v:raise AssertionError(n)
  checks.append(n)
 def reject(n,fn,typ):
  try:fn()
  except typ as e:refusals.append({'name':n,'error':str(e)})
  else:raise AssertionError(n)
 def pipe_case(name,data,expect_error=False):
  r,w=os.pipe()
  try:
   if data:
    mid=max(1,len(data)//2);os.write(w,data[:mid]);os.write(w,data[mid:])
   os.close(w);w=None;reader=FrameReader(r)
   if expect_error:reject(name,lambda:reader.read(time.monotonic_ns()+100_000_000),ChannelError)
   else:check(name,reader.read(time.monotonic_ns()+100_000_000)==clock.command())
  finally:
   os.close(r)
   if w is not None:os.close(w)
 raw=channel_canonical(clock.command());frame=struct.pack('!I',len(raw))+raw
 pipe_case('split_writes_valid_frame',frame)
 pipe_case('partial_eof',frame[:-1],True)
 pipe_case('clean_eof',b'',True)
 pipe_case('oversize',struct.pack('!I',2049),True)
 pipe_case('noncanonical',struct.pack('!I',3)+b' {}',True)
 bad=clock.command();bad['request_sha256']='0'*64
 reject('wrong_identity',lambda:clock.validate(bad),ContractError)
 bad=clock.command();bad['sequence']=True
 reject('bool_sequence',lambda:clock.validate(bad),ContractError)
 m=clock.manifest;wrong='0'*32 if m['run_epoch']!='0'*32 else '1'*32
 reject('wrong_epoch_before_work',lambda:Clock(m,clock.pin,wrong),ContractError)
 expired=copy.deepcopy(m);expired['deadline_ns']=time.monotonic_ns()-1
 reject('expired_before_work',lambda:Clock(expired,sha(canonical(expired)),m['run_epoch']).live(),ContractError)
 reverse=Clock(m,clock.pin,m['run_epoch'],provider=lambda:m['origin_ns']-1)
 reject('injected_clock_reversal',reverse.live,ContractError)
 check('actual_monotonic_live',clock.live()<m['deadline_ns'])
 return {'checks':checks,'refusals':refusals,'scope':'metadata-only; split writes no thread, mismatch not actual reboot, no backend effects; failing reader discarded, no retries'}
