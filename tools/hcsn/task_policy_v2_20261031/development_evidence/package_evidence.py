"""Archive every development result without changing the prepared candidate."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import resource
import tarfile
import time


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    raw = (json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+"\n").encode()
    with path.open("xb") as stream:
        stream.write(gzip.compress(raw,mtime=0) if path.suffix == ".gz" else raw)


def main():
    wall, cpu = time.perf_counter(), time.process_time()
    output = Path(__file__).resolve().parent
    repo = output.parents[3]
    base = Path("/dev/shm/hepta-task-policy-v2-20261031")
    names = ["one_read_probe01","student_dev01","student_dev02","student_dev03","residual_probe01","numeric_profile_probe01"]
    snapshots = list(base.glob("*/SOURCE_SNAPSHOT.json.gz"))
    sources, provenance = {}, {}
    for path in snapshots:
        for name,content in json.loads(gzip.decompress(path.read_bytes())).items():
            if isinstance(content,str):
                key = digest(content.encode())
                sources[key], provenance[key] = content, str(path)+"::"+name
    failed = base/"student_dev01/training_failed_source.py"
    key = digest(failed.read_bytes())
    sources[key], provenance[key] = failed.read_text(), str(failed)
    requirements = {}
    for name in names:
        receipt = base/name/("NUMERIC_PROBE.json.gz" if name.startswith("numeric") else
            "TEACHER_DATA.json.gz" if name.startswith("student_dev0") and name != "student_dev01" else
            "ABORTED.json" if name == "student_dev01" else "PROBE.json.gz")
        raw = receipt.read_bytes()
        record = json.loads(gzip.decompress(raw) if receipt.suffix == ".gz" else raw)
        required = record.get("source_hashes", {"training_failed_source.py":record.get("training_source_sha256")})
        requirements[name] = required
        for file,digest_value in required.items():
            if digest_value not in sources or digest(sources[digest_value].encode()) != digest_value:
                raise ValueError(("Missing exact historical source",name,file,digest_value))
    write_json(output/"HISTORICAL_SOURCES.json.gz",dict(schema="hepta.task.development.sources.v1",
        source_text_by_sha256=sources, original_locations=provenance, required_by_run=requirements,
        scope="Only byte-matching source snapshots already retained before publication; failed original source included"))
    records = []
    for name in names:
        source = base/name
        contents = {str(p.relative_to(source)):digest(p.read_bytes()) for p in sorted(source.rglob("*")) if p.is_file()}
        archive = output/(name+".tar.gz")
        with archive.open("xb") as destination:
            with gzip.GzipFile(filename="",mode="wb",fileobj=destination,mtime=0) as compressed:
                with tarfile.open(fileobj=compressed,mode="w",format=tarfile.PAX_FORMAT) as tar:
                    for relative,expected in contents.items():
                        raw = (source/relative).read_bytes()
                        if digest(raw) != expected:
                            raise ValueError("Development evidence changed while archiving")
                        info = tarfile.TarInfo(name+"/"+relative)
                        info.size, info.mode, info.mtime = len(raw), 0o644, 0
                        tar.addfile(info,io.BytesIO(raw))
                    raw = json.dumps(contents,sort_keys=True,separators=(",", ":")).encode()
                    info = tarfile.TarInfo(name+"/ARCHIVE_CONTENTS.json")
                    info.size, info.mode, info.mtime = len(raw), 0o644, 0
                    tar.addfile(info,io.BytesIO(raw))
        with tarfile.open(archive,"r:gz") as tar:
            for relative,expected in contents.items():
                if digest(tar.extractfile(name+"/"+relative).read()) != expected:
                    raise ValueError("Archive byte verification failed")
        records.append(dict(run=name,path=str(archive.relative_to(repo)),sha256=digest(archive.read_bytes()),
            bytes=archive.stat().st_size, original_files=len(contents),
            original_bytes=sum((source/r).stat().st_size for r in contents), archive_verified=True))
    index = dict(schema="hepta.task.development.publication.v1", archives=records,
        source_bundle=dict(path=str((output/"HISTORICAL_SOURCES.json.gz").relative_to(repo)),
                           sha256=digest((output/"HISTORICAL_SOURCES.json.gz").read_bytes())),
        scope="All preserved development failures, raw tasks, candidates, complete losses, selected weights and numerical replays; no formal confirmation")
    write_json(output/"INDEX.json",index)
    paths = [str(p.relative_to(repo)) for p in sorted(output.iterdir()) if p.is_file()]
    paths += [str((output/n).relative_to(repo)) for n in ("PACKAGING_COST.json","PUBLISH_ALLOWLIST.json")]
    write_json(output/"PUBLISH_ALLOWLIST.json",dict(paths=sorted(paths)))
    write_json(output/"PACKAGING_COST.json",dict(cpu_seconds=time.process_time()-cpu,
        wall_seconds=time.perf_counter()-wall, peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        archives=len(records), published_archive_bytes=sum(r["bytes"] for r in records),
        scope="Local complete evidence packaging plus full decompressed byte verification; excludes final cost-receipt write and remote GitHub publishing, which the orchestrator records separately",
        formal_source_or_model_modified=False))
    print(json.dumps(index,indent=2),flush=True)


if __name__ == "__main__":
    main()
