"""Launch and reconcile the real CPU worker through the native supervisor."""

import os
from pathlib import Path
import sys
import time

from .native_build import native_libraries


def dispatch(root, workspace, rustc, artifacts, signed_worker=None):
    from .verify_bridge import REPO, read, run, sha, write_new
    if artifacts is None:
        raise ValueError("supervised fixture requires the exact successful Cargo artifact stream")
    sources = {}
    for name in ("lib.rs", "hcsn_job.rs", "hcsn_supervisor.rs", "hcsn_taskflow.rs"):
        relative = Path("hepta-automation/src")/name
        path = REPO/"codex-rs"/relative
        if sha(path) != sha(workspace/relative):
            raise ValueError(f"linked native automation source differs: {relative}")
        sources[str(relative)] = sha(path)
    if signed_worker is None:
        deps = Path(os.environ.get("CARGO_TARGET_DIR", workspace/"target")).resolve()/"debug/deps"
        names = ("codex_hepta_automation", "codex_hepta_contracts", "serde_json")
        native = root/"native-supervisor-fixture"
        source = Path(__file__).with_name("supervisor_fixture.rs")
        command = [rustc, "--edition=2024", "--crate-name", "hcsn_supervisor_fixture", str(source),
                   "-L", f"dependency={deps}", "-o", str(native)]
        libraries = {}
        for name, library in native_libraries(deps, names, artifacts).items():
            command += ["--extern", f"{name}={library}"]
            libraries[name] = dict(path=str(library), sha256=sha(library))
        run(root, "native-supervisor-build", command)
        write_new(root/"native-supervisor-build.json", dict(sources=sources, libraries=libraries,
            fixture_source_sha256=sha(source), executable_sha256=sha(native), cargo_artifacts_sha256=sha(artifacts)))
    script, store = Path(__file__).with_name("supervisor.py").resolve(), root/"supervisor-store"
    run(root, "supervisor-initialize", [sys.executable, "-I", "-B", script, "--root", store, "--initialize"])
    write_new(root/"supervisor-config.json", dict(python_executable=sys.executable,
        python_sha256=sha(sys.executable), repository_root=str(REPO), supervisor_sha256=sha(script), durable_root=str(store)))
    if signed_worker is not None:
        executable = Path(signed_worker).resolve(strict=True)
        run(root, "signed-taskflow-real-worker", [executable, "--ignored", "--exact",
            "signed_authority_real_worker_cold_recovery", "--nocapture"],
            env={**os.environ, "HEPTA_HCSN_SIGNED_WORKER_ROOT": str(root)})
        signed = read(root/"signed-taskflow.json")
        observation = signed["observation"]
        write_new(root/"signed-worker-executable.json", dict(path=str(executable), sha256=sha(executable)))
    else:
        run(root, "native-supervisor-start", [native, "start", root])
        deadline, index = time.monotonic()+60, 0
        while True:
            label = f"native-supervisor-status-{index:03d}"
            run(root, label, [native, "status", root])
            observation = read(root/f"{label}.stdout")
            if observation["state"] in ("succeeded", "failed", "cancelled"):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("supervised fixture remains unresolved; retained job must not be restarted")
            index += 1
            time.sleep(.05)
    if observation["state"] != "succeeded":
        raise RuntimeError(f"supervised worker terminal result: {observation}")
    # The original launch reply may be lost. Exact replay must only observe.
    if signed_worker is None:
        run(root, "native-supervisor-repeat", [native, "start", root])
        if read(root/"native-supervisor-repeat.stdout") != observation:
            raise AssertionError("same dispatch changed after terminal replay")
    import hashlib
    key_hash = hashlib.sha256(observation["target"]["key"].encode()).hexdigest()
    job = store/"jobs"/key_hash
    output = job/observation["target"]["output_id"]
    (root/"worker").mkdir()
    mapping = {"candidate.pt": "candidate_sha256", "receipt.json": "receipt_sha256", "handoff.bin": "handoff_sha256"}
    for name, key in mapping.items():
        if sha(output/name) != observation["evidence"][key]:
            raise AssertionError("native observation differs from actual output bytes")
        write_new(root/"worker"/name, (output/name).read_bytes())
    write_new(root/"supervisor-observation.json", dict(observation=observation,
        runner=read(job/"runner.json"), terminal=read(job/"terminal.json"),
        same_dispatch_same_terminal=True, candidate_only=True,
        scope=("actual signed TaskFlow/SQLite/native supervisor/worker and fresh-process recovery; synthetic trust"
               if signed_worker else "actual native process transport; separate signed TaskFlow integration covers authority")))
    return dict(pid=observation["process"]["process_id"])
