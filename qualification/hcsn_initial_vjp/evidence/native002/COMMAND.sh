/home/qian-qi/hepta-hcsn-trainer-20261108-s3-v1/dependency-recovery-v2/venv/bin/python - <<'PY_HCSN_INITIAL_001'
import base64,gzip,hashlib,io,json,os,resource,subprocess,sys,tarfile,time
from pathlib import Path
root=Path("/home/qian-qi/hcsn-initial-amplitude-20261112-c06d-002")
root.mkdir(parents=False,exist_ok=False)
payload=Path("/home/qian-qi/hcsn-initial-amplitude-20261112-c06d-002.bundle.tar.gz").read_bytes()
if hashlib.sha256(payload).hexdigest()!="424407ffbbc484768eefa1898c2599c6276a16cd02d8f6e9e98a5ba3c6ab45e8":
    raise ValueError("transported source bundle hash differs")
(root/"BUNDLE.tar.gz").write_bytes(payload)
with tarfile.open(fileobj=io.BytesIO(payload),mode="r:gz") as archive:
    for member in archive.getmembers():
        path=Path(member.name)
        if not member.isfile() or path.is_absolute() or ".." in path.parts:
            raise ValueError("unexpected bundle entry")
        target=root/path
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(archive.extractfile(member).read())
manifest=json.loads((root/"SOURCE.json").read_text())
for name,expected in manifest["source_sha256"].items():
    if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:
        raise ValueError("source failed transported readback")
environment=dict(os.environ)
environment.update(OPENBLAS_NUM_THREADS="1",OMP_NUM_THREADS="1",MKL_NUM_THREADS="1",PYTHONDONTWRITEBYTECODE="1")
(root/"PREEXECUTION.json").write_text(json.dumps(dict(source_commit=manifest["source_commit"],source_sha256=manifest["source_sha256"],bundle_sha256=hashlib.sha256(payload).hexdigest(),python=sys.executable,requested_optimizer_calls=0,api_forward_budget=64),indent=2,sort_keys=True)+"\n")
started=time.perf_counter()
with (root/"native.stdout").open("wb") as out,(root/"native.stderr").open("wb") as err:
    try:
        process=subprocess.run([sys.executable,"-B","-m","qualification.hcsn_initial_vjp.native_probe","--source-manifest","SOURCE.json","--expected-arrays","EXPECTED.npz","--output","native-result"],cwd=root,env=environment,stdout=out,stderr=err,timeout=300)
        code=process.returncode
    except subprocess.TimeoutExpired:
        code=124
usage=resource.getrusage(resource.RUSAGE_CHILDREN)
receipt=dict(source_commit=manifest["source_commit"],child_returncode=code,wall_seconds=time.perf_counter()-started,child_cpu_seconds=usage.ru_utime+usage.ru_stime,child_maximum_rss_kib=usage.ru_maxrss,native_result_produced=(root/"native-result/RESULT.json").exists(),optimizer_updates=0)
(root/"WRAPPER-RESULT.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
files=[root/name for name in ("BUNDLE.tar.gz","SOURCE.json","PREEXECUTION.json","WRAPPER-RESULT.json","native.stdout","native.stderr")]
files+=list((root/"native-result").glob("*")) if (root/"native-result").exists() else []
index={str(p.relative_to(root)):dict(size=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files}
(root/"FILES.json").write_text(json.dumps(index,indent=2,sort_keys=True)+"\n")
files.append(root/"FILES.json")
with (root/"NATIVE-ORIGINALS.tar.gz").open("wb") as raw,gzip.GzipFile(fileobj=raw,mode="wb",mtime=0) as compressed,tarfile.open(fileobj=compressed,mode="w") as archive:
    for path in sorted(files):
        data=path.read_bytes()
        entry=tarfile.TarInfo(str(path.relative_to(root)))
        entry.size=len(data)
        entry.mode=0o644
        archive.addfile(entry,io.BytesIO(data))
archive=root/"NATIVE-ORIGINALS.tar.gz"
receipt.update(originals_size=archive.stat().st_size,originals_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
print(json.dumps(receipt,sort_keys=True),flush=True)
raise SystemExit(code)
PY_HCSN_INITIAL_001
