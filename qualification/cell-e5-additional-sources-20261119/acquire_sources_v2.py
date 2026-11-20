"""Recover E5 acquisition through exact raw Git blobs; native protocol is unchanged."""

import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import resource
import time
import urllib.request

from acquire_sources import digest, setup, write


def selected_files(entry, tree):
    prefixes = entry["product_roots"] + ["tests", "test"]
    if entry["index"] == 9:
        prefixes.append("json")
    if entry["index"] == 5:
        prefixes.append("data")
    selected, omitted = [], []
    for row in tree["tree"]:
        if row["type"] != "blob":
            continue
        assert not Path(row["path"]).is_absolute() and ".." not in Path(row["path"]).parts
        wanted = "/" not in row["path"] or any(row["path"].startswith(prefix + "/") for prefix in prefixes)
        if not wanted:
            omitted.append({**row, "reason": "outside original package, test, fixture and root metadata scope"})
        elif row["mode"] not in ("100644", "100755"):
            assert entry["index"] == 9 and row["path"] == "json/tests/latest", row
            omitted.append({**row, "reason": "unused convenience symlink; original Suite selects explicit draft directories; never followed or materialized"})
        else:
            assert 0 <= row["size"] <= 2 * 1024 * 1024
            selected.append(row)
    return selected, omitted


def acquire(root, plan):
    snapshots, wanted = [], {}
    for entry in plan["projects"]:
        for variant in ("before", "after"):
            tree = json.loads((root / "upstream-api" / f"{entry['index']}-{variant}-tree.json").read_bytes())
            assert not tree["truncated"]
            selected, omitted = selected_files(entry, tree)
            snapshots.append((entry, variant, selected, omitted))
            for row in selected:
                wanted.setdefault(row["sha"], {**row, "url": f"https://raw.githubusercontent.com/{entry['project_id']}/{entry[variant + '_commit']}/{row['path']}"})
    blobs = root / "git-blobs"
    blobs.mkdir(exist_ok=False)
    write(root / "RAW_DOWNLOAD_INTENT.json", {"unique_blobs": len(wanted), "unique_bytes": sum(row["size"] for row in wanted.values()), "network_workers": 4, "per_request_seconds": 40, "native_budget_unchanged": True, "original_commit_and_test_selection_unchanged": True})

    def fetch(item):
        began = time.perf_counter()
        request = urllib.request.Request(item["url"], headers={"User-Agent": "hepta-e5-source-intake/1"})
        with urllib.request.urlopen(request, timeout=40) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        assert len(raw) == item["size"] and actual == item["sha"], item["url"]
        with (blobs / actual).open("xb") as stream:
            stream.write(raw)
        return {"git_blob_sha1": actual, "sha256": digest(raw), "bytes": len(raw), "url": item["url"], "wall_seconds": time.perf_counter() - began}

    downloaded, failures = {}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch, item): key for key, item in wanted.items()}
        for future in concurrent.futures.as_completed(futures):
            key = futures[future]
            try:
                downloaded[key] = future.result()
            except Exception as error:
                failures.append({"git_blob_sha1": key, "error": repr(error), "url": wanted[key]["url"]})
            if (len(downloaded) + len(failures)) % 50 == 0 or failures:
                print(json.dumps({"downloaded": len(downloaded), "failures": len(failures), "total": len(wanted)}), flush=True)
    write(root / "BLOBS.json", sorted(downloaded.values(), key=lambda row: row["git_blob_sha1"]))
    write(root / "RAW_DOWNLOAD_FAILURES.json", failures)
    assert not failures, "exact raw Git blob acquisition failed"
    outcomes = []
    for entry, variant, selected, omitted in snapshots:
        folder = root / "repositories" / str(entry["index"]) / variant
        folder.mkdir(parents=True, exist_ok=False)
        files = []
        for row in selected:
            data = (blobs / row["sha"]).read_bytes()
            destination = folder / row["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(data)
            destination.chmod(int(row["mode"][-3:], 8))
            files.append({"path": row["path"], "bytes": len(data), "git_blob_sha1": row["sha"], "sha256": digest(data), "mode": row["mode"]})
        record = {"project_id": entry["project_id"], "variant": variant, "revision": entry[variant + "_commit"], "files": files, "omitted_from_execution_snapshot": omitted, "scope": "complete original runtime package, tests, required fixtures and root metadata; full Git trees retained independently"}
        write(root / "snapshots" / f"{entry['index']}-{variant}.json", record)
        outcomes.append({"identity": [entry["index"], variant], "status": "ACQUIRED", "files": len(files), "manifest_sha256": digest((root / "snapshots" / f"{entry['index']}-{variant}.json").read_bytes())})
    write(root / "SNAPSHOT_ACQUISITION.json", outcomes)
    return outcomes


def main(root):
    started = time.perf_counter()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    plan = json.loads((root / "ACQUISITION_PLAN.json").read_bytes())
    write(root / "ACQUISITION_STARTED.json", {"started_at_ns": time.time_ns(), "plan_sha256": digest((root / "ACQUISITION_PLAN.json").read_bytes()), "runner_sha256": digest(Path(__file__).read_bytes()), "transport_recovery": "original raw Git blob acquisition", "new_model_calls": 0, "new_training_updates": 0})
    outcomes, stages = [], []
    try:
        outcomes = acquire(root, plan)
        stages = setup(root)
        status, error = "ACQUIRED", None
    except Exception as failure:
        status, error = "FAILED", repr(failure)
    final = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {"status": status, "error": error, "snapshots": outcomes, "setup_stages": stages, "new_model_calls": 0, "new_training_updates": 0, "new_native_children": 0, "new_authenticated_users": 0, "source_growth_qualified": False, "wall_seconds": time.perf_counter() - started, "completed_child_cpu_seconds": final.ru_utime + final.ru_stime - usage.ru_utime - usage.ru_stime, "full_system_cost_known": False}
    write(root / "ACQUISITION.json", result)
    print(json.dumps(result), flush=True)
    return 0 if status == "ACQUIRED" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    raise SystemExit(main(parser.parse_args().root.resolve(strict=True)))
