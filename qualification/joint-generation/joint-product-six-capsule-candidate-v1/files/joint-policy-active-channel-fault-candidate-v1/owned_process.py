"""Single-thread Linux owned fork/exec; no blocking exec in parent registration.

Only cooperative children of this process. Noncatchable parent death, kernel
stalls or failed cleanup/storage remain outside a universal reap guarantee.
"""
import os,sys,time,signal
class Child:
 __slots__=('role','pid','reaped','returncode','usage')
 def __init__(self,role):self.role=role;self.pid=None;self.reaped=False;self.returncode=None;self.usage=None

def spawn(argv,outfd,errfd,*,role,alarm_seconds,env,owned,events,pass_fds=(),close_fds=()):
 if len(os.listdir('/proc/self/task'))!=1:raise RuntimeError('fork requires exactly one native task')
 child=Child(role);owned.append(child) # visible even if a pending alarm prevents return
 previous=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGALRM})
 if signal.SIGALRM in previous:
  signal.pthread_sigmask(signal.SIG_SETMASK,previous)
  raise RuntimeError('parent deadline must not already be masked')
 try:pid=os.fork()
 except BaseException:
  signal.pthread_sigmask(signal.SIG_SETMASK,previous);raise
 if pid==0:
  # Never enter parent cleanup/finally in this child. Alarm/resources apply even
  # if dup/exec fails or executable startup blocks. Hard caps are inherited.
  try:
   signal.signal(signal.SIGALRM,signal.SIG_DFL);signal.alarm(alarm_seconds)
   signal.pthread_sigmask(signal.SIG_SETMASK,set(previous)-{signal.SIGALRM})
   os.dup2(outfd,1);os.dup2(errfd,2)
   for fd in close_fds:os.close(fd)
   for fd in pass_fds:os.set_inheritable(fd,True)
   os.execve(argv[0],argv,env)
  except BaseException:
   try:os.write(2,b'owned child setup/exec failed\n')
   except BaseException:pass
  os._exit(127)
 try:
  child.pid=pid # preallocated shared ownership object, before signal delivery
  events.append({'event':'launch','role':role,'pid':pid,'monotonic_ns':time.monotonic_ns()})
  return child
 finally:signal.pthread_sigmask(signal.SIG_SETMASK,previous)

def poll(child,receipts,events):
 if child.pid is None:raise ValueError('no forked PID')
 if child.reaped:return True
 previous=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGALRM})
 try:
  pid,status,u=os.wait4(child.pid,os.WNOHANG)
  if pid:
   # Ownership is marked first, before allocating optional log records.
   child.reaped=True;child.usage=u;child.returncode=os.waitstatus_to_exitcode(status)
   receipts.append({'pid':pid,'role':child.role,'exit_code':child.returncode,'CPU_seconds':u.ru_utime+u.ru_stime,'max_RSS_kib':u.ru_maxrss})
   events.append({'event':'reap','role':child.role,'pid':pid,'monotonic_ns':time.monotonic_ns()})
  return bool(pid)
 finally:signal.pthread_sigmask(signal.SIG_SETMASK,previous)
def wait(child,receipts,events):
 while not poll(child,receipts,events):time.sleep(.01)
 return child.returncode
def kill_owned(child):
 if child.pid is None or child.reaped:raise ValueError('not an owned unreaped child')
 try:os.kill(child.pid,signal.SIGKILL)
 except ProcessLookupError:pass

def cleanup(owned,receipts,events):
 for child in owned:
  if child.pid is not None and not child.reaped:
   kill_owned(child);wait(child,receipts,events)
