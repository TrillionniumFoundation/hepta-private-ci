"""Publish complete frozen confirmation evidence; never changes the experiment."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import resource
import tarfile
import time


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def put(path, value):
    raw = (json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+"\n").encode()
    with path.open("xb") as stream:
        stream.write(gzip.compress(raw,mtime=0) if path.suffix == ".gz" else raw)


def main():
    wall, cpu = time.perf_counter(), time.process_time()
    destination = Path(__file__).resolve().parent
    repo = destination.parents[3]
    base = Path("/dev/shm/hepta-task-policy-v2-20261031")
    source, process = base/"formal_confirmation01", base/"formal_confirmation01_process"
    result = json.loads((source/"CONFIRMATION.json").read_text())
    manifest = json.loads((source/"CONFIRMATION_MANIFEST.json").read_text())
    for relative,expected in manifest["files"].items():
        if sha((source/relative).read_bytes()) != expected:
            raise ValueError(("Confirmation bytes changed",relative))
    prepared = json.loads((base/"formal_campaign01/PREPARED_MANIFEST.json").read_text())
    for relative,expected in prepared["source_sha256"].items():
        if sha((repo/relative).read_bytes()) != expected:
            raise ValueError(("Frozen source changed",relative))
    records, rows, failures = [], 0, 0
    for report in result["reports"]:
        name = f"seed{report['seed']}"
        folder = source/name
        for split in ("test","ood"):
            raw = json.loads(gzip.decompress((folder/f"{split}_RUNS_AND_DIAGNOSIS.json.gz").read_bytes()))
            if len(raw["rows"]) != 384:
                raise ValueError("Incomplete seed/split evidence")
            rows += len(raw["rows"])
            failures += sum(r["counts"]["failed_read_attempts"] for r in raw["rows"])
        contents = {r:expected for r,expected in manifest["files"].items() if r.startswith(name+"/")}
        target = destination/(name+".tar.gz")
        with target.open("xb") as stream:
            with gzip.GzipFile(filename="",fileobj=stream,mode="wb",mtime=0) as compressed:
                with tarfile.open(fileobj=compressed,mode="w",format=tarfile.PAX_FORMAT) as tar:
                    for relative,expected in sorted(contents.items()):
                        data = (source/relative).read_bytes()
                        if sha(data) != expected:
                            raise ValueError("Source bytes changed during packaging")
                        info = tarfile.TarInfo(relative)
                        info.size,info.mode,info.mtime = len(data),0o644,0
                        tar.addfile(info,io.BytesIO(data))
                    data = json.dumps(contents,sort_keys=True,separators=(",", ":")).encode()
                    info = tarfile.TarInfo(name+"/ARCHIVE_CONTENTS.json")
                    info.size,info.mode,info.mtime = len(data),0o644,0
                    tar.addfile(info,io.BytesIO(data))
        with tarfile.open(target,"r:gz") as tar:
            for relative,expected in contents.items():
                if sha(tar.extractfile(relative).read()) != expected:
                    raise ValueError("Archived member differs")
        records.append(dict(seed=report["seed"],path=str(target.relative_to(repo)),sha256=sha(target.read_bytes()),
            bytes=target.stat().st_size,original_files=len(contents),all_members_verified=True))
    if rows != 3840 or failures:
        raise ValueError(("Unexpected completion or failed-read count",rows,failures))
    for original in (source/"CONFIRMATION.json",source/"VERIFIED_FREEZE.json",process/"PROCESS.json",process/"OUTPUT.log"):
        with (destination/original.name).open("xb") as stream:
            stream.write(original.read_bytes())
    with (destination/"CONFIRMATION_MANIFEST.json.gz").open("xb") as stream:
        stream.write(gzip.compress((source/"CONFIRMATION_MANIFEST.json").read_bytes(),mtime=0))
    aggregate = {}
    for split in ("test","ood"):
        aggregate[split] = {}
        for policy in ("exact_teacher","one_read","nonzero_residual"):
            group = [r["splits"][split][policy] for r in result["reports"]]
            aggregate[split][policy] = {key:sum(row[key] for row in group)/5 for key in (
                "utility","correct_fraction","completed_fraction","wrong_fraction","teacher_regret",
                "full_cpu_seconds","controller_cpu_seconds","query_cost","latency_cost","reads")}
    put(destination/"COMPACT_RESULTS.json",dict(gates=result["gates"],task_level_learned_admission=False,
        main_activation=False,runs=rows,failed_reads=failures,per_policy=aggregate,
        primary_contrasts=result["splits"],process=json.loads((process/"PROCESS.json").read_text()),
        scope="Prospective frozen five-seed evidence; confidence intervals use paired seed means, not 3840 independent training replications"))
    put(destination/"ARCHIVE_INDEX.json",dict(archives=records,confirmation_runs=rows,
        original_manifest_sha256=sha((source/"CONFIRMATION_MANIFEST.json").read_bytes()),
        frozen_source_files_verified=len(prepared["source_sha256"]),
        frozen_commit=result["freeze"]["receipt"]["commit"],scope="Complete raw packets, terminal labels, owner traces and diagnoses; source and model bytes unchanged"))
    paths = [str(p.relative_to(repo)) for p in sorted(destination.iterdir()) if p.is_file()]
    paths += [str((destination/name).relative_to(repo)) for name in ("PACKAGING_COST.json","PUBLISH_ALLOWLIST.json")]
    put(destination/"PUBLISH_ALLOWLIST.json",dict(paths=sorted(paths)))
    put(destination/"PACKAGING_COST.json",dict(cpu_seconds=time.process_time()-cpu,
        wall_seconds=time.perf_counter()-wall,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        archive_bytes=sum(r["bytes"] for r in records),scope="Local publication packaging, all original hashes and decompressed archived-member verification; excludes final small cost receipt and remote publication; not added again to frozen policy CPU"))
    print(json.dumps(dict(archives=records,runs=rows,failed_reads=failures,destination=str(destination)),indent=2),flush=True)


if __name__ == "__main__":
    main()
