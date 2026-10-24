"""Freeze legacy dependencies and qualify both whole pandas source revisions."""

import argparse
import json
from pathlib import Path
import shutil

from pandas_source_pilot import PYTHON, REVISIONS, command, resources, sha, verify_plan, write_new


REQUIREMENTS = """numpy==1.18.4 Cython==0.29.19 python-dateutil==2.8.1 pytz==2020.1
six==1.15.0 pytest==5.4.3 hypothesis==5.16.0 sortedcontainers==2.1.0
attrs==19.3.0 atomicwrites==1.4.0 more-itertools==8.3.0 packaging==20.4
pluggy==0.13.1 py==1.8.1 pyparsing==2.4.7 wcwidth==0.2.3""".split()
BOOTSTRAP = ["pip==24.0", "setuptools==49.6.0", "wheel==0.36.2"]
BUILD_ENV = {"CC": "/usr/bin/gcc", "CXX": "/usr/bin/g++", "CFLAGS": "-O1 -g0",
    "CXXFLAGS": "-O1 -g0", "MAKEFLAGS": "-j1", "NPY_NUM_BUILD_JOBS": "1",
    "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONHASHSEED": "0"}
METADATA = Path("/workspace/scratch/f1f83ab8f2f0/upstream-bugsinpy/projects/pandas/bugs/5")


def inventory(root):
    return [{"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size, "sha256": sha(p)}
        for p in sorted(Path(root).rglob("*")) if p.is_file() and not p.is_symlink()
        and "__pycache__" not in p.parts]


def verify_files(root, records):
    root = Path(root)
    for r in records:
        path = root / r["path"]
        if not path.is_file() or path.is_symlink() or path.stat().st_size != r["bytes"] or sha(path) != r["sha256"]:
            raise ValueError("frozen file changed: " + str(path))


def freeze_dependencies(root):
    root = Path(root).resolve()
    plan = verify_plan(root)
    metadata = (METADATA / "requirements.txt").read_text().splitlines()
    if any(value.lower() not in {v.lower() for v in metadata} for value in REQUIREMENTS):
        raise ValueError("selected direct dependency differs from exact bug metadata")
    source = json.loads((root / "source-acquisition.json").read_bytes())
    source_files = {}
    for role in REVISIONS:
        checkout = root / "checkouts" / role
        records = [r for r in inventory(checkout) if r["path"] != ".git"]
        target = root / ("source-files-" + role + ".json")
        write_new(target, records)
        source_files[role] = {"path": str(target), "sha256": sha(target), "files": len(records)}
    direct = root / "direct-requirements.txt"
    with direct.open("x") as stream:
        stream.write("\n".join(REQUIREMENTS + BOOTSTRAP) + "\n")
    result = {"schema": "hepta.pandas-pilot-dependency-freeze.v1", "pilot_plan_sha256": sha(root / "pilot-plan.json"),
        "protocol_sha256": plan["protocol_sha256"], "source_acquisition_sha256": sha(root / "source-acquisition.json"),
        "source_revisions": source["revisions"], "source_file_inventories": source_files,
        "direct_requirements_sha256": sha(direct), "requirements": REQUIREMENTS, "bootstrap": BOOTSTRAP,
        "build_environment": BUILD_ENV, "build_command_tail": ["setup.py", "build_ext", "--inplace", "-j1"],
        "source_metadata_files": {p.name: sha(p) for p in sorted(METADATA.iterdir()) if p.is_file()},
        "static_evidence": ["setup.py requires Cython>=0.29.16 and NumPy>=1.15.4; exact metadata0.29.19/1.18.4 retained.",
            "Build directly without PEP517 isolation; pyproject historical NumPy1.15.4 build pin is not installed over metadata1.18.4.",
            "pandas/conftest.py imports hypothesis, pytest, numpy, dateutil and pytz; groupby conftest adds no mandatory external package.",
            "Optional IO/plot/scipy dependencies excluded; no benchmark observed to choose this set.",
            "Whole native builds remain independent, even though actual Git diff contains only docs/groupby Python/test files.",
            "CFLAGS/CXXFLAGS -O1 -g0 and compiler job1 declared before build to bound resource use; same for both revisions.",
            "Metadata bug_patch.txt refers to an unrelated indexes change. Actual full Git revision pair, not that patch text, defines implementation."],
        "compiler_executables": {n: {"path": str(Path(n).resolve()), "sha256": sha(Path(n).resolve())}
                                 for n in ("/usr/bin/gcc", "/usr/bin/g++")},
        "uv": {"path": str(Path(shutil.which("uv")).resolve()), "sha256": sha(shutil.which("uv"))},
        "builder_source_sha256": sha(__file__), "benchmark_commands_run": 0}
    write_new(root / "dependency-plan.json", result)
    return result


def dependency_plan(root):
    root = Path(root)
    verify_plan(root)
    plan = json.loads((root / "dependency-plan.json").read_bytes())
    if (plan["pilot_plan_sha256"] != sha(root / "pilot-plan.json")
            or plan["source_acquisition_sha256"] != sha(root / "source-acquisition.json")
            or plan["direct_requirements_sha256"] != sha(root / "direct-requirements.txt")):
        raise ValueError("dependency/source plan binding changed")
    for entry in plan["source_file_inventories"].values():
        if sha(entry["path"]) != entry["sha256"]:
            raise ValueError("source inventory changed")
    for name, expected in plan["source_metadata_files"].items():
        if sha(METADATA / name) != expected:
            raise ValueError("frozen upstream metadata changed")
    for item in [plan["uv"], *plan["compiler_executables"].values()]:
        if sha(item["path"]) != item["sha256"]:
            raise ValueError("build tool changed")
    return plan


def build_runtime(root):
    root = Path(root).resolve()
    plan = dependency_plan(root)
    env = root / "runtime" / "environment"
    env.parent.mkdir(parents=True, exist_ok=True)
    command(root, "10-runtime-venv", [PYTHON, "-m", "venv", "--without-pip", env], timeout=60)
    python = env / "bin/python"
    uv = plan["uv"]["path"]
    common = ["--python", str(python), "--default-index", "https://pypi.org/simple",
        "--cache-dir", str(root / "uv-cache"), "--no-python-downloads", "--no-build-isolation"]
    resolved = root / "resolved-requirements.txt"
    command(root, "11-runtime-resolve", [uv, "pip", "compile", *common, "--generate-hashes",
        "--output-file", resolved, root / "direct-requirements.txt"], env=BUILD_ENV)
    command(root, "12-runtime-install", [uv, "pip", "install", *common, "--link-mode", "copy",
        "--require-hashes", "-r", resolved], env=BUILD_ENV)
    command(root, "13-runtime-pip-check", [python, "-I", "-B", "-m", "pip", "check"], timeout=60)
    locked = command(root, "14-runtime-freeze", [python, "-I", "-B", "-m", "pip", "freeze", "--all"], timeout=60)
    if any(line.lower().startswith("pandas==") for line in locked.read_text().splitlines()):
        raise ValueError("runtime installed target pandas instead of source")
    command(root, "15-runtime-dependency-import", [python, "-I", "-B", "-c",
        "import json,numpy,Cython,pytest,hypothesis;print(json.dumps({x.__name__:x.__version__ for x in (numpy,Cython,pytest,hypothesis)}))"],
        env=BUILD_ENV, timeout=60)
    manifest = root / "runtime-files.json"
    write_new(manifest, inventory(env))
    result = {"python": str(python), "python_sha256": sha(python), "root": str(env),
        "dependency_plan_sha256": sha(root / "dependency-plan.json"),
        "resolved_requirements_sha256": sha(resolved), "pip_freeze_sha256": sha(locked),
        "runtime_inventory_sha256": sha(manifest), "resources": resources(root),
        "benchmark_commands_run": 0, "target_project_imports_run": 0}
    write_new(root / "runtime-complete.json", result)
    return result


def build_one(root, role):
    root = Path(root).resolve()
    plan = dependency_plan(root)
    runtime = json.loads((root / "runtime-complete.json").read_bytes())
    if (runtime["dependency_plan_sha256"] != sha(root / "dependency-plan.json")
            or runtime["runtime_inventory_sha256"] != sha(root / "runtime-files.json")):
        raise ValueError("runtime binding changed")
    verify_files(runtime["root"], json.loads((root / "runtime-files.json").read_bytes()))
    checkout = root / "checkouts" / role
    source_files = json.loads(Path(plan["source_file_inventories"][role]["path"]).read_bytes())
    verify_files(checkout, source_files)
    for compiler in ("gcc", "g++"):
        command(root, "20-" + role + "-" + compiler, ["/usr/bin/" + compiler, "--version"], timeout=30)
    python = runtime["python"]
    command(root, "21-native-build-" + role,
        [python, *plan["build_command_tail"]], cwd=checkout, env=plan["build_environment"], timeout=600)
    verify_files(checkout, source_files)
    script = ("import json,pathlib,sys,sysconfig; root=pathlib.Path(" + repr(str(checkout)) + ");"
        "sys.path.insert(0,str(root)); import pandas,numpy; "
        "native={n:m.__file__ for n,m in sys.modules.items() if n.startswith('pandas.') and getattr(m,'__file__','') and m.__file__.endswith('.so')};"
        "assert pathlib.Path(pandas.__file__).is_relative_to(root);assert native;"
        "assert all(pathlib.Path(p).is_relative_to(root) for p in native.values());"
        "print(json.dumps({'pandas_file':pandas.__file__,'pandas_version':pandas.__version__,'numpy_version':numpy.__version__,"
        "'python_version':sys.version,'soabi':sysconfig.get_config_var('SOABI'),'imported_native':native},sort_keys=True))")
    # Python3.8 lacks Path.is_relative_to; use a lexical, resolved ancestor assertion.
    script = script.replace("pathlib.Path(pandas.__file__).is_relative_to(root)", "root in pathlib.Path(pandas.__file__).resolve().parents")
    script = script.replace("pathlib.Path(p).is_relative_to(root)", "root in pathlib.Path(p).resolve().parents")
    imported = command(root, "22-source-import-" + role, [python, "-I", "-B", "-c", script],
        cwd=checkout, env=BUILD_ENV, timeout=60)
    extensions = [{"path": p.relative_to(checkout).as_posix(), "bytes": p.stat().st_size, "sha256": sha(p)}
                  for p in sorted(checkout.rglob("*.so"))]
    result = {"role": role, "source": plan["source_revisions"][role], "checkout": str(checkout),
        "source_inventory_sha256": plan["source_file_inventories"][role]["sha256"],
        "runtime_complete_sha256": sha(root / "runtime-complete.json"),
        "dependency_plan_sha256": sha(root / "dependency-plan.json"), "build_environment": BUILD_ENV,
        "extension_files": extensions, "extension_bytes": sum(r["bytes"] for r in extensions),
        "import": json.loads(imported.read_bytes()), "import_log_sha256": sha(imported),
        "build_artifact_reuse": False, "benchmark_commands_run": 0,
        "resources": resources(root), "authority": "DENY_ALL"}
    write_new(root / ("build-complete-" + role + ".json"), result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "runtime", "base", "candidate"))
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    result = freeze_dependencies(args.root) if args.action == "freeze" else (
        build_runtime(args.root) if args.action == "runtime" else build_one(args.root, args.action))
    print(json.dumps(result, sort_keys=True))
