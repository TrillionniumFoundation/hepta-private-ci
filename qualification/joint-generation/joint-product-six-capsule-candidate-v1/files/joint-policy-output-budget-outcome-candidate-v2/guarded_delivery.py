"""Mandatory cooperating local writer lease for public delivery entrypoints.

Not a hostile-code sandbox. One trusted root on a local Linux filesystem only.
Direct use of guarded_core, deleting/replacing lockfiles, or modifying the model
outside this wrapper violates the declared single-writer protocol.
"""
import os,stat,fcntl,threading
from pathlib import Path
from contextlib import contextmanager
from contracts import ContractError
from guarded_core import GuardedDelivery as _Core,UncertainEffect,BeforeGeneratorFailure
class GuardedDelivery:
 def __init__(self,backend,artifact,root,budget):
  self._pid=os.getpid();self._gate=threading.Lock();self._fd=None;self._core=None
  self._root=Path(root).resolve(strict=True)
  if not self._root.is_dir():raise ContractError('existing trusted directory required')
  self._lockpath=self._root/'.hepta-writer.lock'
  fd=os.open(self._lockpath,os.O_RDWR|os.O_CREAT|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
  try:
   st=os.fstat(fd)
   if not stat.S_ISREG(st.st_mode)or st.st_nlink!=1:raise ContractError('single regular local lock inode required')
   try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError as e:raise ContractError('another local writer already owns this root')from e
   self._fd=fd;self._identity=(st.st_dev,st.st_ino);self._check()
   self._core=_Core(backend,artifact,self._root,budget)
  except BaseException:
   # Closing this acquired or unacquired descriptor cannot unlock another
   # independently opened writer; no explicit unlock of foreign descriptors.
   self._fd=None;os.close(fd);raise
 def _check(self):
  if os.getpid()!=self._pid:raise ContractError('inherited writer may not be used after fork')
  if self._fd is None:raise ContractError('writer is closed')
  a=os.fstat(self._fd);b=os.stat(self._lockpath,follow_symlinks=False)
  if (a.st_dev,a.st_ino)!=self._identity or(b.st_dev,b.st_ino)!=self._identity or a.st_nlink!=1 or not stat.S_ISREG(b.st_mode):raise ContractError('writer lock identity changed')
 @contextmanager
 def _operation(self):
  if os.getpid()!=self._pid:raise ContractError('inherited writer may not be used after fork')
  if not self._gate.acquire(blocking=False):raise ContractError('concurrent operation on this writer refused')
  try:self._check();yield
  finally:self._gate.release()
 @property
 def work(self):
  with self._operation():return {k:(list(v)if type(v)is list else v)for k,v in self._core.work.items()}
 def start(self,*args,**kwargs):
  with self._operation():return self._core.start(*args,**kwargs)
 def restore(self,*args,**kwargs):
  with self._operation():return self._core.restore(*args,**kwargs)
 def publish(self,*args,**kwargs):
  with self._operation():return self._core.publish(*args,**kwargs)
 def close(self):
  if os.getpid()!=self._pid:raise ContractError('inherited writer may not close parent lease')
  if self._fd is None:return
  with self._operation():
   fd=self._fd;self._fd=None;self._core=None;os.close(fd)
 def __enter__(self):
  with self._operation():return self
 def __exit__(self,*args):self.close()
