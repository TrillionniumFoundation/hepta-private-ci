"""Restore pinned public CPU dependencies without reading scientific data.

Wheels live in anonymous RAM files to avoid the wheel-plus-extraction disk peak.
Pip installs them offline. Only installed public torch/test and torch/include
are subsequently pruned. Every removed file is inventoried with SHA256.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import html
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import zipfile

from pip._vendor.packaging.tags import sys_tags
from pip._vendor.packaging.utils import parse_wheel_filename

HERE = Path(__file__).resolve().parent
ARCHIVE_ENV = HERE.parent / "field_bridge_v3_20261027/evidence/ARCHIVE_RUNTIME_ENVIRONMENT.json"
TARGET = Path("/tmp/hepta-field-v4-python")
DEPENDENCIES = Path("/tmp/hepta-field-v4-pinned-dependencies-stage")
LINKS = Path("/tmp/hepta-field-v4-public-wheels")
RECEIPT = HERE / "ENVIRONMENT_RESTORATION.json"
LOG = HERE / "ENVIRONMENT_RESTORATION.log"
RESERVE = 350_000_000
FINAL_RESERVE = 600_000_000
SAFETY = 16 * 1024 * 1024
TEST_PACKAGE_ROOTS = ("fsspec", "mpmath", "networkx", "setuptools", "sympy")
ALLOWED_HOSTS = {"pypi.org", "files.pythonhosted.org", "download.pytorch.org", "download-r2.pytorch.org"}
RANKS = {tag: i for i, tag in enumerate(sys_tags())}
NETWORK = []
FDS = []
started = time.perf_counter_ns()
cpu_started = time.process_time_ns()
state = {
    "schema": "hepta.field-bridge.v4.environment-restoration.1",
    "status": "initializing",
    "started_utc": datetime.now(timezone.utc).isoformat(),
    "target": str(TARGET),
    "authority": "DENY_ALL", "requires_calibration": True,
    "native_owner_integration": False, "scientific_gate_changed": False,
    "new_study_roles_accessed": [], "generator_calls": 0,
    "observer_calls": 0, "native_tick_calls": 0,
    "user_data_upload_bytes": 0,
    "reserve_bytes": RESERVE,
    "final_research_output_reserve_bytes": FINAL_RESERVE,
    "final_additional_safety_bytes": SAFETY,
    "commands": [], "failures": [], "public_sources": [],
    "cost_scope": "This restoration script, including public dependency download, install, pruning, smoke, and inventory. Earlier read-only space/index/range/PyPI metadata preflight was separate and not timed here.",
    "preflight_external_to_timing": {
        "result": "Ordinary disk wheel+expanded torch would leave about 245MB; rejected before installation.",
        "torch_official_wheel_bytes": 183914597,
        "torch_expanded_4k_estimate_bytes": 708751360,
        "torch_test_include_4k_estimate_bytes": 145014784,
        "mem_available_observed_kib": 4217248,
        "install_attempts": 0,
    },
}
log = None


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def space():
    s = os.statvfs("/tmp")
    return {"free_all_bytes": s.f_bfree * s.f_frsize,
            "available_nonroot_bytes": s.f_bavail * s.f_frsize}


def say(message):
    line = datetime.now(timezone.utc).isoformat() + " " + message
    print(line, flush=True)
    if log:
        log.write(line + "\n")
        log.flush()


def checkpoint():
    state["current_space"] = space()
    state["wall_ns"] = time.perf_counter_ns() - started
    state["script_cpu_ns"] = time.process_time_ns() - cpu_started
    state["network_requests"] = NETWORK
    RECEIPT.write_text(json.dumps(state, indent=2, sort_keys=True, allow_nan=False) + "\n")


def allowed(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:
        raise ValueError("Non-public-source URL rejected: " + url)


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(PublicRedirect())


def fetch(url):
    allowed(url)
    begin = time.perf_counter_ns()
    with OPENER.open(url, timeout=60) as response:
        allowed(response.url)
        data = response.read()
        entry = {"url": url, "final_url": response.url, "bytes": len(data),
                 "wall_ns": time.perf_counter_ns() - begin, "status": response.status}
    NETWORK.append(entry)
    return data


def pypi_choice(package):
    name, version = package["name"], package["version"]
    index = f"https://pypi.org/pypi/{name}/{version}/json"
    data = json.loads(fetch(index))
    candidates = []
    for item in data["urls"]:
        if item["packagetype"] != "bdist_wheel":
            continue
        tags = parse_wheel_filename(item["filename"])[3]
        ranks = [RANKS[tag] for tag in tags if tag in RANKS]
        if ranks:
            candidates.append((min(ranks), item["filename"], item))
    _, _, item = min(candidates)
    return {"name": name, "version": version, "index": index,
            "filename": item["filename"], "url": item["url"],
            "expected_bytes": item["size"], "sha256": item["digests"]["sha256"]}


def torch_choice():
    index = "https://download.pytorch.org/whl/cpu/torch/"
    body = fetch(index).decode()
    filename = "torch-2.8.0+cpu-cp312-cp312-manylinux_2_28_x86_64.whl"
    matches = [html.unescape(href) for href in re.findall(r'href=[\"\x27]([^\"\x27]+)', body)
               if filename in urllib.parse.unquote(html.unescape(href))]
    assert len(matches) == 1
    url, fragment = urllib.parse.urldefrag(urllib.parse.urljoin(index, matches[0]))
    digest = urllib.parse.parse_qs(fragment)["sha256"][0]
    assert digest == "cb9a8ba8137ab24e36bf1742cb79a1294bd374db570f09fc15a5e1318160db4e"
    return {"name": "torch", "version": "2.8.0+cpu", "index": index,
            "filename": filename, "url": url, "sha256": digest,
            "expected_bytes": 183914597}


def wheel_to_memory(item):
    allowed(item["url"])
    fd = os.memfd_create("hepta-public-" + item["filename"], flags=os.MFD_CLOEXEC)
    FDS.append(fd)
    digest, size = hashlib.sha256(), 0
    begin = time.perf_counter_ns()
    with OPENER.open(item["url"], timeout=120) as response, os.fdopen(os.dup(fd), "wb") as stream:
        allowed(response.url)
        while block := response.read(1024 * 1024):
            stream.write(block)
            digest.update(block)
            size += len(block)
        final_url, status = response.url, response.status
    assert size == item["expected_bytes"], (item["name"], size)
    assert digest.hexdigest() == item["sha256"], item["name"]
    NETWORK.append({"url": item["url"], "final_url": final_url, "bytes": size,
                    "wall_ns": time.perf_counter_ns() - begin, "status": status})
    link = LINKS / item["filename"]
    link.symlink_to(f"/proc/{os.getpid()}/fd/{fd}")
    with zipfile.ZipFile(link) as archive:
        entries = archive.infolist()
        assert all(not p.filename.startswith("/") and ".." not in Path(p.filename).parts for p in entries)
        item["inventory"] = {"entries": len(entries),
            "expanded_bytes": sum(p.file_size for p in entries),
            "expanded_4k_estimate_bytes": sum(((p.file_size + 4095) // 4096) * 4096 for p in entries)}
        package_tests = [p for p in entries if "tests" in Path(p.filename).parts
                         and Path(p.filename).parts[0] in TEST_PACKAGE_ROOTS]
        item["dependency_tests_4k_estimate_bytes"] = sum(((p.file_size + 4095) // 4096) * 4096 for p in package_tests)
        if item["name"] == "torch":
            item["permitted_prune"] = {}
            for prefix in ("torch/test/", "torch/include/"):
                subset = [p for p in entries if p.filename.startswith(prefix)]
                item["permitted_prune"][prefix] = {"entries": len(subset),
                    "expanded_bytes": sum(p.file_size for p in subset),
                    "expanded_4k_estimate_bytes": sum(((p.file_size + 4095) // 4096) * 4096 for p in subset)}
    item["memory_wheel_verified"] = True
    item["wheel_storage"] = "anonymous RAM memfd; temporary public filename symlink only"
    item["final_download_url"] = final_url
    item["disk_wheel_bytes"] = 0
    say(f"Verified {item['filename']}: {size} bytes; expanded 4K estimate {item['inventory']['expanded_4k_estimate_bytes']}")
    return link


def run_command(label, argv, env):
    entry = {"label": label, "argv": argv, "space_before": space(),
             "started_utc": datetime.now(timezone.utc).isoformat()}
    start = time.perf_counter_ns()
    before_times = os.times()
    state["commands"].append(entry)
    checkpoint()
    say("Starting " + label)
    result_lines = []
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, env=env, bufsize=1)
    stop = threading.Event()
    monitor = {"min_free_all_bytes": entry["space_before"]["free_all_bytes"], "samples": 0,
               "terminated_for_reserve": False}
    def watch():
        while not stop.wait(.05):
            free = space()["free_all_bytes"]
            monitor["min_free_all_bytes"] = min(monitor["min_free_all_bytes"], free)
            monitor["samples"] += 1
            if free < RESERVE and process.poll() is None:
                monitor["terminated_for_reserve"] = True
                process.terminate()
                break
    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    try:
        for line in process.stdout:
            result_lines.append(line)
            log.write(line)
            log.flush()
            print(line.rstrip(), flush=True)
        code = process.wait()
    finally:
        stop.set()
        thread.join()
    after_times = os.times()
    entry.update(returncode=code, wall_ns=time.perf_counter_ns() - start,
                 child_user_seconds=after_times.children_user - before_times.children_user,
                 child_system_seconds=after_times.children_system - before_times.children_system,
                 space_after=space(), space_monitor=monitor)
    checkpoint()
    if code:
        state["failures"].append({"label": label, "returncode": code,
                                  "wall_ns": entry["wall_ns"], "log": str(LOG)})
        raise RuntimeError(f"{label} failed with {code}; full output preserved")
    return "".join(result_lines)


def compressed_manifest(path, data):
    payload = (json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    with path.open("xb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as stream:
            stream.write(payload)
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size,
            "uncompressed_bytes": len(payload), "uncompressed_sha256": hashlib.sha256(payload).hexdigest()}


def merge_public_stage(source, destination):
    """Rename the separately installed dependency tree, preserving torch's bin."""
    moved = []
    destination.mkdir(exist_ok=True)
    for child in sorted(source.iterdir()):
        final = destination / child.name
        if final.exists():
            assert child.is_dir() and final.is_dir(), (child, final)
            moved.extend(merge_public_stage(child, final))
        else:
            assert child.stat().st_dev == destination.stat().st_dev
            child.rename(final)
            moved.append(str(final.relative_to(TARGET)))
    source.rmdir()
    return moved


SMOKE = r'''
import hashlib,json,sys
from pathlib import Path
from importlib import metadata
import numpy as np
import PIL
import torch
from pip._vendor.packaging.requirements import Requirement
expected=json.loads(sys.argv[1])
torch.set_num_threads(2)
torch.set_num_interop_threads(1)
torch.manual_seed(0)
x=np.asarray([[1.,2.],[-1.,3.],[2.,-1.]],dtype=np.float64)
y=np.asarray([.5,-1.,2.5],dtype=np.float64)
w=torch.tensor([1.5,-.5],dtype=torch.float64,requires_grad=True)
tx,ty=torch.from_numpy(x),torch.from_numpy(y)
loss=((tx@w-ty)**2).mean();loss.backward()
expected_grad=2*x.T@(x@w.detach().numpy()-y)/len(y)
gradient_error=float(np.max(np.abs(w.grad.numpy()-expected_grad)))
assert gradient_error<1e-12
before=float(loss.detach());opt=torch.optim.SGD([w],lr=.01);opt.step()
after=float((((tx@w)-ty)**2).mean().detach());assert after<before
v=torch.tensor([2.,-3.],dtype=torch.float64,requires_grad=True)
adam=torch.optim.Adam([v],lr=.01)
adam_before=float((v*v).sum().detach())
(v*v).sum().backward();adam.step()
adam_after=float((v*v).sum().detach());assert adam_after<adam_before
identities=[];requirements=[]
for name,version in expected.items():
 d=metadata.distribution(name);assert d.version==version,(name,d.version,version)
 files={}
 for basename in ('METADATA','RECORD'):
  path=Path(d._path)/basename
  if path.exists():files[basename]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
 identities.append({'name':name,'version':d.version,'metadata_path':str(d._path),'metadata_files':files})
 for raw in d.requires or []:
  req=Requirement(raw)
  if req.marker is not None and not req.marker.evaluate({'extra':''}):continue
  actual=metadata.version(req.name);assert actual in req.specifier,(name,str(req),actual)
  requirements.append({'package':name,'requirement':str(req),'satisfied_version':actual})
assert str(torch.__file__).startswith('/tmp/hepta-field-v4-python/')
print('HEPTA_SMOKE_JSON='+json.dumps({'status':'passed','torch':torch.__version__,'numpy':np.__version__,'pillow':PIL.__version__,'torch_path':torch.__file__,'python':sys.version,'device':'cpu','threads':torch.get_num_threads(),'interop_threads':torch.get_num_interop_threads(),'autograd_max_error':gradient_error,'sgd_loss_before':before,'sgd_loss_after':after,'adam_loss_before':adam_before,'adam_loss_after':adam_after,'installed_identities':identities,'required_dependency_checks':requirements,'study_role_or_checkpoint_loads':0},sort_keys=True))
'''


def main():
    global log
    assert not RECEIPT.exists() and not LOG.exists() and not TARGET.exists() and not LINKS.exists() and not DEPENDENCIES.exists()
    log = LOG.open("x")
    state["source_sha256"] = sha(__file__)
    state["archive_environment"] = {"path": str(ARCHIVE_ENV), "sha256": sha(ARCHIVE_ENV)}
    manifest = json.loads(ARCHIVE_ENV.read_text())
    state["pinned_environment"] = manifest
    state["initial_space"] = space()
    assert platform.machine() == manifest["machine"] and platform.system().lower() == manifest["platform"]
    assert platform.python_version() == manifest["python"]
    assert metadata.version("numpy") == manifest["numpy"] and metadata.version("pillow") == manifest["pillow"]
    assert hasattr(os, "memfd_create")
    assert state["initial_space"]["free_all_bytes"] - 708751360 - SAFETY >= RESERVE
    checkpoint()
    say("Preflight approved RAM wheel route; disk reserve >=350,000,000 bytes required")
    packages = manifest["runtime_package_versions"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        other = list(pool.map(pypi_choice, [p for p in packages if p["name"] != "torch"]))
    items = [torch_choice(), *other]
    state["public_sources"] = items
    checkpoint()
    LINKS.mkdir()
    links = [wheel_to_memory(item) for item in items]
    state["public_sources"] = items
    full_torch = items[0]["inventory"]["expanded_4k_estimate_bytes"]
    prunable = sum(p["expanded_4k_estimate_bytes"] for p in items[0]["permitted_prune"].values())
    other_size = sum(p["inventory"]["expanded_4k_estimate_bytes"] for p in other)
    other_tests = sum(p["dependency_tests_4k_estimate_bytes"] for p in other)
    state["installation_plan"] = {
        "torch_full_4k_bytes": full_torch, "permitted_prune_4k_bytes": prunable,
        "other_dependencies_4k_bytes": other_size, "disk_wheel_bytes": 0,
        "other_tests_permitted_prune_4k_bytes": other_tests,
        "estimated_min_free_bytes_including_safety": space()["free_all_bytes"] - max(full_torch, full_torch-prunable+other_size) - SAFETY,
        "estimated_final_free_bytes_including_safety": space()["free_all_bytes"] - (full_torch-prunable+other_size-other_tests) - SAFETY,
        "shared_existing_exact_dependencies": ["numpy=="+manifest["numpy"], "pillow=="+manifest["pillow"]],
        "no_venv_or_model_artifact_copy": True,
    }
    assert state["installation_plan"]["estimated_min_free_bytes_including_safety"] >= RESERVE
    assert state["installation_plan"]["estimated_final_free_bytes_including_safety"] >= FINAL_RESERVE
    state["status"] = "installing"
    checkpoint()
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", PIP_DISABLE_PIP_VERSION_CHECK="1")
    pip = [sys.executable, "-m", "pip", "--isolated", "--disable-pip-version-check", "install", "--no-index", "--no-deps", "--no-cache-dir", "--no-compile", "--target", str(TARGET)]
    run_command("install_exact_cpu_torch_from_verified_RAM_wheel", [*pip, str(links[0])], env)
    preserved = TARGET / "torch/bin/torch_shm_manager"
    shm_sha = sha(preserved)
    removals, roots = [], []
    before_prune = space()
    for relative in ("torch/test", "torch/include"):
        root = TARGET / relative
        assert root.is_dir() and not root.is_symlink() and root.resolve().is_relative_to(TARGET)
        rows = []
        for path in sorted(root.rglob("*")):
            if path.is_file():
                assert not path.is_symlink()
                rows.append({"path": str(path.relative_to(TARGET)), "bytes": path.stat().st_size,
                             "allocated_bytes": path.stat().st_blocks*512, "sha256": sha(path)})
        roots.append({"path": str(root), "files": len(rows), "file_bytes": sum(p["bytes"] for p in rows),
                      "allocated_file_bytes": sum(p["allocated_bytes"] for p in rows)})
        removals.extend(rows)
        shutil.rmtree(root)
        say("Removed permitted public installation subtree " + relative)
    assert preserved.is_file() and sha(preserved) == shm_sha
    state["permitted_public_pruning"] = {
        "roots": roots, "space_before": before_prune, "space_after": space(),
        "per_file_manifest": compressed_manifest(HERE / "ENVIRONMENT_PRUNED_PUBLIC_FILES.json.gz", removals),
        "torch_shm_manager": {"path": str(preserved), "sha256": shm_sha, "preserved": True},
        "bin_subtree_deleted": False,
    }
    checkpoint()
    dependency_pip = [str(DEPENDENCIES) if argument == str(TARGET) else argument for argument in pip]
    run_command("install_nine_exact_dependencies_from_verified_RAM_wheels", [*dependency_pip, *map(str,links[1:])], env)
    state["dependency_stage_merge"] = {
        "stage": str(DEPENDENCIES), "method": "same-filesystem rename; preserve and merge bin; no duplicate file overwrite",
        "moved_entries": merge_public_stage(DEPENDENCIES, TARGET),
    }
    candidates = sorted(p for package in TEST_PACKAGE_ROOTS for p in (TARGET/package).rglob("tests") if p.is_dir())
    test_roots = []
    for path in candidates:
        if not any(path.is_relative_to(parent) for parent in test_roots):
            test_roots.append(path)
    removed_tests, test_root_records = [], []
    for root in test_roots:
        assert root.resolve().is_relative_to(TARGET) and not root.is_symlink()
        rows = []
        for path in sorted(root.rglob("*")):
            if path.is_file():
                assert not path.is_symlink()
                rows.append({"path":str(path.relative_to(TARGET)),"bytes":path.stat().st_size,
                             "allocated_bytes":path.stat().st_blocks*512,"sha256":sha(path)})
        test_root_records.append({"path":str(root),"files":len(rows),"bytes":sum(p["bytes"] for p in rows)})
        removed_tests.extend(rows)
        shutil.rmtree(root)
    state["permitted_dependency_test_pruning"] = {
        "scope": "Only directories literally named tests under fsspec/mpmath/networkx/setuptools/sympy; sympy/testing and all runtime modules retained",
        "roots": test_root_records,
        "per_file_manifest": compressed_manifest(HERE / "ENVIRONMENT_PRUNED_DEPENDENCY_TESTS.json.gz", removed_tests),
    }
    assert (TARGET/"sympy/testing").is_dir() and sha(preserved)==shm_sha
    say(f"Removed {len(test_roots)} public dependency tests directories; runtime testing support and torch/bin preserved")
    checkpoint()
    for link in links:
        link.unlink()
    LINKS.rmdir()
    for fd in FDS:
        os.close(fd)
    FDS.clear()
    expected = {p["name"]: p["version"] for p in packages}
    expected.update(numpy=manifest["numpy"], pillow=manifest["pillow"])
    env["PYTHONPATH"] = str(TARGET)
    smoke = run_command("synthetic_cpu_autograd_sgd_adam_and_pinned_dependency_smoke",
        [sys.executable, "-c", SMOKE, json.dumps(expected, sort_keys=True)], env)
    state["smoke"] = json.loads(next(line.split("=",1)[1] for line in smoke.splitlines() if line.startswith("HEPTA_SMOKE_JSON=")))
    records = []
    for path in sorted(TARGET.rglob("*")):
        if path.is_file():
            assert not path.is_symlink()
            records.append({"path":str(path.relative_to(TARGET)), "bytes":path.stat().st_size,
                            "allocated_bytes":path.stat().st_blocks*512,"sha256":sha(path)})
    state["remaining_installation"] = {
        "files": len(records), "file_bytes": sum(p["bytes"] for p in records),
        "allocated_file_bytes": sum(p["allocated_bytes"] for p in records),
        "per_file_manifest": compressed_manifest(HERE / "ENVIRONMENT_REMAINING_FILES.json.gz", records),
        "bytecode_compilation_requested": False,
    }
    assert space()["free_all_bytes"] >= FINAL_RESERVE + SAFETY, ("Final output reserve plus safety not met", space())
    state["use_environment"] = {"python":sys.executable,"PYTHONPATH":str(TARGET),"PYTHONDONTWRITEBYTECODE":"1","OPENBLAS_NUM_THREADS":"1","training_torch_threads":2,"interop_threads":1}
    state["status"] = "restored_smoke_passed"
    state["ended_utc"] = datetime.now(timezone.utc).isoformat()
    state["final_space"] = space()
    checkpoint()
    say("Restoration complete; no scientific role executed; free_all="+str(space()["free_all_bytes"]))


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        state["status"] = "failed"
        state["exception"] = {"type":type(exc).__name__,"message":str(exc),"traceback":traceback.format_exc()}
        if log:
            log.write(traceback.format_exc());log.flush()
        checkpoint()
        raise
    finally:
        for fd in FDS:
            os.close(fd)
        if log:
            log.close()
