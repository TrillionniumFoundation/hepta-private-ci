"""ExplicitSession lifecycle protected by the same cooperating local root lease.

Not a root-level latest-checkpoint index or global token ledger. A caller chooses
one trusted checkpoint; external callback effects are not rolled back/replayed.
"""
import re
from pathlib import Path
from contracts import ContractError
from session import ExplicitSession,state_hash
from training_root_lease import LocalRootLease
class SessionWriter:
 def __init__(self,*args,**kwargs):raise TypeError('use create or load factories')
 @classmethod
 def create(cls,root,model_factory,batches,*,objective_profile,source_sha256,lr):
  out=cls.__new__(cls);out._lease=LocalRootLease(root);out._session=None
  try:
   with out._lease._operation():
    if not callable(model_factory):raise ValueError('explicit local model factory')
    out._session=ExplicitSession(model_factory(),batches,objective_profile=objective_profile,source_sha256=source_sha256,lr=lr)
   return out
  except BaseException:out._lease.close();raise
 @classmethod
 def load(cls,root,name,batches,*,objective_profile,source_sha256,lr):
  out=cls.__new__(cls);out._lease=LocalRootLease(root);out._session=None
  try:
   with out._lease._operation():
    path=out._file(name)
    if path.is_symlink():raise ValueError('checkpoint symlink outside profile')
    out._session,receipt=ExplicitSession.load(path,batches,objective_profile=objective_profile,source_sha256=source_sha256,lr=lr)
   return out,receipt
  except BaseException:out._lease.close();raise
 def _file(self,name):
  if type(name)is not str or re.fullmatch(r'[a-z][a-z0-9_-]{0,63}\.json',name)is None:raise ValueError('simple root-local checkpoint filename required')
  return self._lease._root/name
 def prepare(self,**kwargs):
  with self._lease._operation():return self._session.prepare(**kwargs)
 def commit(self,pending):
  with self._lease._operation():return self._session.commit(pending)
 def abort(self,pending):
  with self._lease._operation():return self._session.abort(pending)
 def advance(self,**kwargs):
  with self._lease._operation():return self._session.advance(**kwargs)
 def payload(self):
  with self._lease._operation():return self._session.payload()
 def save(self,name):
  with self._lease._operation():return self._session.save(self._file(name))
 def committed_hash(self):
  with self._lease._operation():return state_hash(self._session.model)
 @property
 def cursor(self):
  with self._lease._operation():return self._session.cursor
 @property
 def has_pending(self):
  with self._lease._operation():return self._session.pending is not None
 def close(self):
  def ready():
   if self._session is not None and self._session.pending is not None:raise ContractError('pending candidate must commit or abort before explicit close')
   self._session=None
  self._lease.close(before_release=ready)
 def __enter__(self):
  with self._lease._operation():return self
 def __exit__(self,*args):self.close()
