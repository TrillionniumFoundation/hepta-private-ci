import os,sys,time,resource,signal,json
initial=(2,3)
def sample(tag):
 u=resource.getrusage(resource.RUSAGE_SELF)
 return dict(tag=tag,PROF=time.clock_gettime(-8),SCHED=time.clock_gettime(-6),process_time=time.process_time(),rusage=u.ru_utime+u.ru_stime,rlimit=list(resource.getrlimit(resource.RLIMIT_CPU)))
rows=[]
def stopped(sig,frame):
 rows.append(sample('SIGXCPU'))
 print(json.dumps(dict(initial_rlimit=initial,rows=rows,signal=sig)),flush=True)
 sys.exit(0)
signal.signal(signal.SIGXCPU,stopped)
resource.setrlimit(resource.RLIMIT_CPU,initial)
rows.append(sample('start'))
last=0.;value=1
while True:
 for i in range(12000):value=(value*1664525+1013904223)&0xffffffff
 current=time.process_time()
 if current-last>.2:
  last=current;rows.append(sample('running'))
