"""Trusted local clock epoch and one-command cooperative control; no owner auth."""
import json,time,re,select
from persistence import canonical,sha
from contracts import ContractError
class Clock:
 def __init__(self,manifest,expected_sha256,expected_epoch,*,provider=None):
  if type(manifest)is not dict or set(manifest)!={'schema','run_epoch','origin_ns','deadline_ns','request_sha256','artifact_sha256','namespace','source_freeze','root_instance'}:raise ContractError('clock manifest schema')
  if manifest['schema']!='local-live-control-v1' or type(expected_epoch)is not str or not re.fullmatch('[0-9a-f]{32}',expected_epoch)or manifest['run_epoch']!=expected_epoch or sha(canonical(manifest))!=expected_sha256:raise ContractError('clock epoch or external manifest pin mismatch')
  if any(type(manifest[k])is not int or not 0<=manifest[k]<2**63 for k in ('origin_ns','deadline_ns'))or manifest['origin_ns']>=manifest['deadline_ns']:raise ContractError('clock interval')
  for k in ('request_sha256','artifact_sha256','namespace','source_freeze'):
   if type(manifest[k])is not str or not re.fullmatch('[0-9a-f]{64}',manifest[k]):raise ContractError('clock digest')
  if type(manifest['root_instance'])is not list or len(manifest['root_instance'])!=2 or any(type(x)is not int or x<0 for x in manifest['root_instance']):raise ContractError('root instance')
  self.manifest=json.loads(canonical(manifest));self.pin=expected_sha256;self.last=manifest['origin_ns'];self._provider=provider or time.monotonic_ns
 def observe(self):
  n=self._provider()
  if type(n)is not int or not self.last<=n<2**63:raise ContractError('clock reversal or invalid sample')
  self.last=n;return n
 def live(self):
  n=self.observe()
  if n>=self.manifest['deadline_ns']:raise ContractError('live deadline expired')
  return n
 def command(self):
  return {'schema':'local-cancel-v1','manifest_sha256':self.pin,'run_epoch':self.manifest['run_epoch'],'request_sha256':self.manifest['request_sha256'],'artifact_sha256':self.manifest['artifact_sha256'],'namespace':self.manifest['namespace'],'sequence':1,'reason':'user_cancel'}
 def validate(self,message):
  if canonical(message)!=canonical(self.command()):raise ContractError('control command identity/schema mismatch')
  return self.observe()
 def bind(self,raw,artifact,namespace,root_instance,source):
  m=self.manifest
  if (sha(raw),artifact,namespace,root_instance,source)!=(m['request_sha256'],m['artifact_sha256'],m['namespace'],m['root_instance'],m['source_freeze']):raise ContractError('control request/root/source binding')
def available(reader):return reader is not None and bool(select.select([reader.fd],[],[],0)[0])
