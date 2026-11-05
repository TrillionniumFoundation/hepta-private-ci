"""Retain actual executing test ELF from one exact wrapper subtree.

This is a collector, not a test runner or qualification decision. Callers bind
one wrapper PID after Popen, preserve original test commands and budgets, and
pair the resulting capture with that runner's source identity and binary count.
Polling may miss short cases; observed_selected_tests states actual coverage.
No later build or glob listing may substitute for a missing capture.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import threading
import time

class ExecutedBinaryCapture:
    """Capture actual running test ELF through /proc, never select a glob result."""
    def __init__(self,name,crate,selected,identity,*,target,evidence):
        self.name,self.crate,self.selected,self.identity=name,crate,selected,identity
        self.target=Path(target)
        if str(os.getpid())!=os.readlink('/proc/self'):
            raise RuntimeError('collector requires the process and /proc to share a PID namespace')
        self.directory=Path(evidence)/('executed-binaries-'+name)
        self.directory.mkdir()
        self.stop=threading.Event()
        self.records=[]
        self.errors=[]
        self.seen=set()
        self.images={}
        self.root_identity=None
        self.thread=threading.Thread(target=self.watch,daemon=True)
    @staticmethod
    def process_state(proc):
        fields=(proc/'stat').read_text().rpartition(')')[2].split()
        return int(fields[1]), fields[19]
    def bind(self,pid):
        self.root_identity=(pid,self.process_state(Path('/proc')/str(pid))[1])
    def in_gate_subtree(self,pid):
        if self.root_identity is None: return False
        seen=set()
        for _ in range(64):
            if pid in seen or pid<=1: return False
            seen.add(pid)
            parent,start=self.process_state(Path('/proc')/str(pid))
            if pid==self.root_identity[0]: return start==self.root_identity[1]
            pid=parent
        return False
    def watch(self):
        try:
            while not self.stop.is_set():
                for proc in Path('/proc').iterdir():
                    if not proc.name.isdigit(): continue
                    try:
                        executable=os.readlink(proc/'exe')
                        path=Path(executable)
                        if not executable.startswith(str(self.target)+'/') or not re.fullmatch(re.escape(self.crate)+r'-[a-f0-9]+',path.name): continue
                        args=(proc/'cmdline').read_bytes().split(b'\0')
                        cases=[a.decode() for a in args if a and self.selected(a.decode(errors='replace'))]
                        if not cases: continue
                        process_state=self.process_state(proc)
                        start_ticks=process_state[1]
                        process=(proc.name,start_ticks)
                        if process in self.seen or not self.in_gate_subtree(int(proc.name)): continue
                        with (proc/'exe').open('rb') as elf:
                            info=os.fstat(elf.fileno())
                            # Bind the opened image to the same still-live task
                            # after opening, not a PID/exec observation from before it.
                            after_state=self.process_state(proc)
                            after_args=(proc/'cmdline').read_bytes().split(b'\0')
                            after_path=os.readlink(proc/'exe')
                            linked=os.stat(proc/'exe')
                            if (after_state!=process_state or after_args!=args or after_path!=executable
                                or (linked.st_dev,linked.st_ino)!=(info.st_dev,info.st_ino)
                                or not self.in_gate_subtree(int(proc.name))):
                                continue
                            self.seen.add(process)
                            image=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
                            if image in self.images:
                                hexdigest,final=self.images[image]
                            else:
                                first=elf.read(4)
                                if first!=b'\x7fELF': raise RuntimeError('executing test image is not ELF')
                                elf.seek(0)
                                temporary=self.directory/(proc.name+'-'+start_ticks+'.elf')
                                h=hashlib.sha256()
                                with temporary.open('xb') as copy:
                                    for part in iter(lambda:elf.read(1024*1024),b''): h.update(part);copy.write(part)
                                    copy.flush();os.fsync(copy.fileno())
                                after=os.fstat(elf.fileno())
                                if (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)!=image:
                                    raise RuntimeError('executing test ELF changed while retained')
                                hexdigest=h.hexdigest()
                                final=self.directory/(hexdigest+'.elf')
                                if final.exists(): temporary.unlink()
                                else: temporary.replace(final)
                                self.images[image]=(hexdigest,final)
                            record={'source':self.identity,'actual_executable':executable,'retained_copy':str(final),
                                    'sha256':hexdigest,'bytes':info.st_size,'device':info.st_dev,'inode':info.st_ino,
                                    'pid':int(proc.name),'start_ticks':start_ticks,'wrapper_pid':self.root_identity[0],'wrapper_start_ticks':self.root_identity[1],
                                    'wrapper_descendant_verified':True,'post_open_task_and_exe_verified':True,'observed_selected_tests':cases,'captured_unix':time.time()}
                            self.records.append(record)
                            (self.directory/'capture.json').write_text(json.dumps(self.records,indent=2)+'\n')
                    except (FileNotFoundError,ProcessLookupError,PermissionError):
                        continue
                self.stop.wait(0.01)
        except Exception as error:
            self.errors.append(repr(error))
    def start(self): self.thread.start()
    def finish(self):
        self.stop.set();self.thread.join(timeout=60)
        if self.thread.is_alive(): self.errors.append('binary collector did not finish')
        return {'records':self.records,'errors':self.errors,'unique_actual_elf_sha256':sorted({r['sha256'] for r in self.records}),
                'observed_selected_tests':sorted({case for r in self.records for case in r['observed_selected_tests']}),
                'capture_scope':'actual executing test-image binding; polling may miss individual short-lived cases'}

