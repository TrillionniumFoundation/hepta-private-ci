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
    def ancestor_chain(self,pid):
        if self.root_identity is None: return None
        seen=set()
        chain=[]
        for _ in range(64):
            if pid in seen or pid<=1: return None
            seen.add(pid)
            parent,start=self.process_state(Path('/proc')/str(pid))
            chain.append({'pid':pid,'ppid':parent,'start_ticks':start})
            if pid==self.root_identity[0]:
                return chain if start==self.root_identity[1] else None
            pid=parent
        return None
    def in_gate_subtree(self,pid):
        return self.ancestor_chain(pid) is not None
    @staticmethod
    def file_identity(info):
        return {'device':info.st_dev,'inode':info.st_ino,'bytes':info.st_size,
                'mtime_ns':info.st_mtime_ns,'ctime_ns':info.st_ctime_ns}
    def process_observation(self,proc):
        parent,start=self.process_state(proc)
        args=(proc/'cmdline').read_bytes().split(b'\0')
        # Keep complete argv, including empty arguments. /proc appends one NUL.
        if args and args[-1]==b'': args.pop()
        executable=os.readlink(proc/'exe')
        info=os.stat(proc/'exe')
        if self.process_state(proc)!=(parent,start):
            return None
        return {'pid':int(proc.name),'ppid':parent,'start_ticks':start,
                'argv':[os.fsdecode(a) for a in args],'actual_executable':executable,
                'image':self.file_identity(info)}
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
                        # Observe both live processes around the two actual FD
                        # opens. The retained FDs then preserve that bounded
                        # observation even if either process exits during copy.
                        observation_started=time.time()
                        child_before=self.process_observation(proc)
                        chain_before=self.ancestor_chain(int(proc.name))
                        if child_before is None or chain_before is None or len(chain_before)<2: continue
                        parent_proc=Path('/proc')/str(child_before['ppid'])
                        parent_before=self.process_observation(parent_proc)
                        if parent_before is None: continue
                        with (proc/'exe').open('rb') as elf, (parent_proc/'exe').open('rb') as parent_elf:
                            info=os.fstat(elf.fileno())
                            parent_info=os.fstat(parent_elf.fileno())
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
                            child_after=self.process_observation(proc)
                            parent_after=self.process_observation(parent_proc)
                            chain_after=self.ancestor_chain(int(proc.name))
                            if (child_before!=child_after or parent_before!=parent_after
                                or chain_before!=chain_after
                                or child_before['image']!=self.file_identity(info)
                                or parent_before['image']!=self.file_identity(parent_info)
                                or chain_before[0]!={'pid':int(proc.name),'ppid':child_before['ppid'],'start_ticks':start_ticks}
                                or chain_before[1]!={'pid':parent_before['pid'],'ppid':parent_before['ppid'],'start_ticks':parent_before['start_ticks']}):
                                continue
                            observation_finished=time.time()
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
                            if (self.file_identity(os.fstat(elf.fileno()))!=self.file_identity(info)
                                or self.file_identity(os.fstat(parent_elf.fileno()))!=self.file_identity(parent_info)):
                                raise RuntimeError('held child or parent image changed after live relationship observation')
                            record={'source':self.identity,'actual_executable':executable,'retained_copy':str(final),
                                    'sha256':hexdigest,'bytes':info.st_size,'device':info.st_dev,'inode':info.st_ino,
                                    'mtime_ns':info.st_mtime_ns,'ctime_ns':info.st_ctime_ns,'argv':child_before['argv'],
                                    'pid':int(proc.name),'start_ticks':start_ticks,'wrapper_pid':self.root_identity[0],'wrapper_start_ticks':self.root_identity[1],
                                    'wrapper_descendant_verified':True,'post_open_task_and_exe_verified':True,
                                    'process_before':child_before,'process_after':child_after,
                                    'direct_parent_before':parent_before,'direct_parent_after':parent_after,
                                    'ancestor_chain_before':chain_before,'ancestor_chain_after':chain_after,
                                    'relationship_observed_before_unix':observation_started,'relationship_observed_after_unix':observation_finished,
                                    'held_child_and_parent_images_stable_through_retention':True,
                                    'relationship_scope':'two live observations around actual child and direct-parent FD opens; no claim either task remains alive at copy completion',
                                    'observed_selected_tests':cases,'captured_unix':time.time()}
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

