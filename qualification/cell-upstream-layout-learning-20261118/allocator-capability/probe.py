import fcntl, hashlib, importlib.util, json, os, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent
started, cpu = time.perf_counter(), time.process_time()
lock = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a/research-round03-20261118-392934-b/WORKER.lock")
owner_path = Path("/home/qian-qi/work/hepta-upstream-current-policy-20261118-2e9b/execution-code/owner.py")
assert hashlib.sha256(owner_path.read_bytes()).hexdigest() == "fc9ec2aa4600b8d554f4a9ef9ee802bf196cc68e8fad890a4090538497bb0ac1"
spec = importlib.util.spec_from_file_location("energy_original", owner_path)
owner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owner)
with lock.open("a+b") as held:
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    admission=owner.gpu_admission()
    first=owner.energy_sample()
    import torch
    assert os.environ["PYTORCH_CUDA_ALLOC_CONF"] == "expandable_segments:True"
    torch.cuda.set_per_process_memory_fraction(0.70, 0)
    allocation=torch.empty(8*1024*1024, dtype=torch.uint8, device="cuda:0")
    snapshot=torch.cuda.memory._snapshot()
    segments=[{key: segment.get(key) for key in ("device","total_size","allocated_size","segment_type","is_expandable")}
              for segment in snapshot["segments"]]
    supported=any(segment["is_expandable"] is True for segment in segments)
    result={"status":"PASS" if supported else "UNCONFIRMED","actual_torch":torch.__version__,
            "allocator_backend":torch.cuda.memory.get_allocator_backend(),
            "environment":os.environ["PYTORCH_CUDA_ALLOC_CONF"],
            "allocator_settings":snapshot.get("allocator_settings"),
            "segments":segments,"real_probe_allocation_bytes":allocation.numel(),
            "memory_fraction":torch.cuda.get_per_process_memory_fraction(0),
            "gpu_admission":admission,"actual_gpu_runtime_allocation":True,
            "model_loaded":False,"model_forward_calls":0,"model_generation_calls":0,"optimizer_updates":0,
            "energy_samples":[first,owner.energy_sample()],
            "wall_seconds":time.perf_counter()-started,"self_cpu_seconds":time.process_time()-cpu,
            "full_system_cost_known":False}
    (ROOT/"RESULT.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result),flush=True)
    del allocation
    torch.cuda.empty_cache()
    assert supported and result["allocator_backend"]=="native" and result["memory_fraction"]==0.70
