"""Actual socket replay across OS processes, with source and target byte accounting."""
import argparse
import json
import multiprocessing as mp
import os
from pathlib import Path
import socket
import struct
import time
import numpy as np
from prepare import Panel,SIZE,CHOICES

N=3*SIZE
PAIR=struct.Struct('<ff'); INDEXED=struct.Struct('<Iff');ASK=struct.Struct('<IB');FLOAT=struct.Struct('<f');MASK=struct.Struct('<H');INT=struct.Struct('<I')
def scores(p,y):
    p=np.clip(np.asarray(p,dtype=float),1e-7,1-1e-7)
    return np.array([np.mean(-y*np.log(p)-(1-y)*np.log1p(-p)),np.mean(y*(1-p)**2+(1.-y)*p**2)])
def demand(fraction):
    rng=np.random.default_rng(855970);mask=rng.random(N)<fraction;h=rng.integers(0,2,size=N)
    return np.flatnonzero(mask),h[mask]
def endpoints(kind):
    if kind=='unix':return socket.socketpair(socket.AF_UNIX,socket.SOCK_STREAM)
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1',0));listener.listen(1)
        client=socket.create_connection(listener.getsockname());server,_=listener.accept()
    for sock in (client,server):sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
    return client,server

class Meter:
    def __init__(self,sock):
        self.sock=sock;self.tx=0;self.rx=0;self.sends=0;self.receives=0
    def write(self,frame):
        self.sock.sendall(frame);self.tx+=len(frame);self.sends+=1
    def read(self,n,allow_eof=False):
        buf=bytearray()
        while len(buf)<n:
            v=self.sock.recv(n-len(buf));self.receives+=1
            if not v:
                if allow_eof and not buf:return None
                raise EOFError('truncated frame')
            buf.extend(v);self.rx+=len(v)
        return bytes(buf)
    def counts(self):return dict(tx=self.tx,rx=self.rx,application_sends=self.sends,recv_syscalls=self.receives)
def send_worker(sock,peer,pipe,panel,mode,param):
    peer.close();io=Meter(sock);t=time.monotonic();cpu=time.process_time();nf=0;steps=0
    try:
        if mode in ('dense_two','dense_five'):
            vals=panel.pair if mode=='dense_two' else panel.all
            for row in vals:io.write(row.astype('<f4',copy=False).tobytes())
        elif mode in ('tolerance_index','tolerance_mask'):
            base=np.zeros(2);frame=bytearray();mask=0
            for i,row in enumerate(panel.pair):
                changed=i%SIZE==0 or np.max(abs(row-base))>param
                if changed:
                    base=row.copy();nf+=1
                    if mode=='tolerance_index':io.write(INDEXED.pack(i,*row))
                    else:mask|=1<<(i%16);frame.extend(PAIR.pack(*row))
                if mode=='tolerance_mask' and (i%16==15 or i==N-1):
                    io.write(MASK.pack(mask)+frame);frame=bytearray();mask=0
        elif mode.startswith('query_'):
            while True:
                req=io.read(5,allow_eof=True)
                if req is None:break
                i,h=ASK.unpack(req);nf+=1
                if mode=='query_frozen':p=panel.all[i,1 if h==2 else 3]
                elif mode=='query_lut':p=panel.dynamic(i,h);steps+=h
                else:
                    command=np.frombuffer(io.read(4*h),dtype='<f4')
                    p=panel.dynamic(i,h,command);steps+=h
                io.write(FLOAT.pack(p))
        elif mode=='events':
            for r in panel.data:
                for trial in r['spike'].T:
                    for ix in np.flatnonzero(trial):
                        io.write(INT.pack(ix));nf+=1
                    io.write(INT.pack(0xffffffff))
        else:raise ValueError(mode)
        sock.shutdown(socket.SHUT_WR)
        pipe.send(dict(**io.counts(),cpu=time.process_time()-cpu,wall=time.monotonic()-t,updates_or_answers=nf,
                       per_request_killed_transitions=steps,pid=os.getpid()))
    except Exception as exc:
        pipe.send({'error':repr(exc)});raise
    finally:sock.close();pipe.close()

def run(panel,transport,mode,param):
    s0,s1=endpoints(transport);report,reply=mp.get_context('fork').Pipe(duplex=False)
    child=mp.get_context('fork').Process(target=send_worker,args=(s1,s0,reply,panel,mode,param))
    t=time.monotonic();cpu=time.process_time();child.start();s1.close();reply.close();io=Meter(s0)
    out=np.empty_like(panel.pair);times=[];idx=hi=None;extra={}
    if mode.startswith('dense'):
        width=2 if mode=='dense_two' else 5
        for i in range(N):
            a=np.frombuffer(io.read(width*4),dtype='<f4');out[i]=a if width==2 else a[[1,3]]
    elif mode=='tolerance_index':
        last=0;base=None
        while True:
            buff=io.read(12,allow_eof=True)
            if buff is None:break
            i,p,q=INDEXED.unpack(buff)
            if base is not None:out[last:i]=base
            base=np.array([p,q],dtype=np.float32);last=i
        out[last:]=base
    elif mode=='tolerance_mask':
        last=None
        for k in range(0,N,16):
            mask=MASK.unpack(io.read(2))[0]
            if mask:vals=np.frombuffer(io.read(8*mask.bit_count()),dtype='<f4').reshape(-1,2)
            j=0
            for i in range(k,min(k+16,N)):
                if mask & (1<<(i%16)):last=vals[j];j+=1
                out[i]=last
    elif mode.startswith('query_'):
        idx,hi=demand(param);yret=np.empty(len(idx),dtype=np.float32)
        for j,(i,k) in enumerate(zip(idx,hi)):
            h=CHOICES[k];buf=ASK.pack(i,h)
            if mode=='query_explicit':
                site,loc=divmod(i,SIZE);buf+=panel.data[site]['forcing'][loc,:h].astype('<f4').tobytes()
            at=time.perf_counter_ns();io.write(buf);yret[j]=FLOAT.unpack(io.read(4))[0];times.append(time.perf_counter_ns()-at)
        s0.shutdown(socket.SHUT_WR)
    elif mode=='events':
        lanes=[]
        for src in panel.data:
            for trial in src['spike'].T:
                slots=[]
                while True:
                    ix=INT.unpack(io.read(4))[0]
                    if ix==0xffffffff:break
                    slots.append(ix)
                assert np.array_equal(np.flatnonzero(trial),slots);lanes.append(len(slots))
        extra['event_counts_by_lane']=lanes
    duration=time.monotonic()-t;parentcpu=time.process_time()-cpu
    child.join(timeout=30)
    if child.is_alive():raise RuntimeError('sender stalled')
    telemetry=report.recv();s0.close();report.close()
    if child.exitcode or 'error' in telemetry:raise RuntimeError(telemetry)
    counts=io.counts()
    if telemetry['tx']!=counts['rx'] or telemetry['rx']!=counts['tx']:raise RuntimeError('byte mismatch')
    data=dict(transport=transport,mode=mode,parameter=param,source=telemetry,sink={**counts,'cpu':parentcpu,'pid':os.getpid()},wall=duration,
              two_way_bytes=telemetry['tx']+telemetry['rx'],**extra)
    if mode!='events':
        original=panel.pair if idx is None else panel.pair[idx,hi]
        reconstructed=out if idx is None else yret
        obs=panel.obs[:,[1,3]] if idx is None else panel.obs[idx,np.array([1,3])[hi]]
        err=np.asarray(reconstructed,dtype=float)-original
        data.update(queries=int(reconstructed.size),max_abs=float(np.max(abs(err))),mae=float(np.mean(abs(err))),
               rmse=float(np.sqrt(np.mean(err*err))),p99_abs=float(np.quantile(abs(err),.99)),
               nll_brier=scores(reconstructed,obs).tolist(),delta_nll_brier=(scores(reconstructed,obs)-scores(original,obs)).tolist())
    if times:data['per_rtt_us']=np.quantile(np.asarray(times)/1000.,[.5,.95,.99]).tolist()
    return data
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('cache',type=Path);p.add_argument('out',type=Path)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);pan=Panel(a.cache);rows=[]
    config=[('dense_two',0),('dense_five',0),('events',0)]
    config += [(n,t) for t in (.001,.005,.01,.05) for n in ('tolerance_index','tolerance_mask')]
    config += [(n,f) for f in (.1,.5,1.) for n in ('query_frozen','query_lut','query_explicit')]
    for rep in range(3):
        jobs=[(tr,mode,value) for tr in ('unix','tcp') for mode,value in config]
        np.random.default_rng(855971+rep).shuffle(jobs)
        for tr,mode,value in jobs:
            rows.append(dict(rep=rep,**run(pan,tr,mode,value)))
            (a.out/'wire.json').write_text(json.dumps(rows,separators=(',',':'),allow_nan=False)+'\n')
            print(rep,tr,mode,value,rows[-1]['two_way_bytes'],round(rows[-1]['wall'],3),flush=True)
