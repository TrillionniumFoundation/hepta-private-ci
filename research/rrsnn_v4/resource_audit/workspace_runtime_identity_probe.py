import sys,os,json,pathlib,hashlib,importlib.util,importlib.metadata,datetime
roots={'old':'/workspace/scratch/38ad1e295a60/rrsnn_v4','new':'/dev/shm/rrsnn-v4-recovery-g38d3wgp/rrsnn_v4'}
affinity_before=sorted(os.sched_getaffinity(0))
audit_cpu=8 if 8 in affinity_before else affinity_before[0]
os.sched_setaffinity(0,{audit_cpu})
def sha(path):
 h=hashlib.sha256()
 with pathlib.Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def stat(path):
 p=pathlib.Path(path);s=p.stat()
 return {'path':str(p),'resolved_path':str(p.resolve()),'bytes':s.st_size,'device':s.st_dev,'inode':s.st_ino,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}
packages={}
for name in ['numpy','scipy','torch']:
 spec=importlib.util.find_spec(name);dist=importlib.metadata.distribution(name)
 origin=pathlib.Path(spec.origin);base=origin.parent
 packages[name]={'version_from_dist_info':dist.version,'dist_info_path':str(dist._path),'module_origin':str(origin),'module_origin_sha256':sha(origin),'package_directory':str(base),'top_level_module_loaded':name in sys.modules}
paths={}
numpy=pathlib.Path(packages['numpy']['package_directory']);scipy=pathlib.Path(packages['scipy']['package_directory']);torch=pathlib.Path(packages['torch']['package_directory'])
for key,root,pattern in [('numpy_multiarray_umath',numpy/'_core','_multiarray_umath*.so'),('scipy_brent_zeros',scipy/'optimize','_zeros*.so'),('torch_C',torch,'_C*.so')]:
 candidates=list(root.glob(pattern));assert len(candidates)==1,(key,candidates)
 p=candidates[0];paths[key]={**stat(p),'sha256':sha(p)}
p=torch/'lib/libc10.so';paths['torch_libc10']={**stat(p),'sha256':sha(p)}
paths['torch_libtorch_cpu']={**stat(torch/'lib/libtorch_cpu.so'),'fresh_sha256_not_computed':True,'reason':'Large library intentionally not rescanned during a live high-memory benchmark window. Prior independently recorded digest and same-file metadata are reported separately.'}
cgroup={}
for name in ['cpu.max','cpuset.cpus','cpuset.cpus.effective','memory.max']:
 p=pathlib.Path('/sys/fs/cgroup')/name
 try:cgroup[name]=p.read_text().strip()
 except OSError as e:cgroup[name]={'error':type(e).__name__}
ns={}
for name in ['mnt','pid','user']:
 try:ns[name]=os.readlink('/proc/self/ns/'+name)
 except OSError as e:ns[name]={'error':type(e).__name__}
mounts=[]
for line in pathlib.Path('/proc/self/mountinfo').read_text().splitlines():
 a=line.split();separator=a.index('-')
 if a[4] in ['/','/dev/shm','/sys/fs/cgroup','/tmp']:
  mounts.append({'mountpoint':a[4],'root':a[3],'major_minor':a[2],'fs_type':a[separator+1],'source':a[separator+2],'options':a[5]})
print(json.dumps({'created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'python':{'version':sys.version,'version_info':list(sys.version_info),'executable':sys.executable,'real_executable':str(pathlib.Path(sys.executable).resolve()),'executable_sha256':sha(sys.executable),'prefix':sys.prefix,'base_prefix':sys.base_prefix,'sys_path':sys.path},'packages':packages,'binary_fingerprints':paths,'cpu_affinity_before_pinning':affinity_before,'audit_process_cpu_affinity':sorted(os.sched_getaffinity(0)),'single_thread_environment':{k:os.environ.get(k) for k in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS']},'cgroup':cgroup,'process_cgroup':pathlib.Path('/proc/self/cgroup').read_text().strip(),'namespaces':ns,'selected_mounts':mounts,'root_visibility':{k:pathlib.Path(v).is_dir() for k,v in roots.items()},'probe_scope':'stdlib metadata and bounded file hashing only; no numpy/scipy/torch import, numerical kernel, actor, or training.'},sort_keys=True))
