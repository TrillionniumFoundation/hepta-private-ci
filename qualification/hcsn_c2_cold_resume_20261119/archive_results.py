"""Archive exact C2 diagnostic outputs and the two immutable input checkpoints."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
from zipfile import ZIP_DEFLATED, ZipFile

HERE = Path(__file__).resolve().parent


def main():
    request = json.loads((HERE / "REQUEST.json").read_text())
    output = HERE / "RUN_OUTPUT"
    if not (output / "TERMINAL.json").is_file():
        raise ValueError("a diagnostic terminal record is required before archival")
    members = {}

    def add(name, path):
        if path.is_symlink() or not path.is_file():
            raise ValueError("regular exact artifact required: " + str(path))
        data = path.read_bytes()
        if len(data) > 4 * 1024**2:
            raise ValueError("unexpectedly large bounded diagnostic member: " + name)
        members[name] = data

    for name in ("runner.py", "REQUEST.json", "FREEZE.json", "SOURCE_EXPECTATIONS.json",
                 "WHEEL_RECOVERY.json"):
        add("source/" + name, HERE / name)
    runtime = {"python": platform.python_version(), "executable": sys.executable,
               "packages": {dist.metadata["Name"]: {
                   "version": dist.version,
                   "record_sha256": hashlib.sha256((dist.read_text("RECORD") or "").encode()).hexdigest(),
               } for dist in importlib.metadata.distributions()},
               "scope": "Metadata only, collected after numerical process termination; no model imports"}
    members["source/RUNTIME_PACKAGES.json"] = (json.dumps(runtime, indent=2, sort_keys=True) + "\n").encode()
    for path in sorted(output.rglob("*")):
        if path.is_file():
            add("run/" + path.relative_to(output).as_posix(), path)
    root = Path(request["original_root"])
    for fit in request["fits"]:
        native = root / "c2-native-execution-20261110-c385-v1" / "fits" / fit["name"]
        commit_path = native / "commits" / f"epoch-{fit['epoch']:04d}.json"
        commit = json.loads(commit_path.read_text())
        prefix = "original/" + fit["name"] + "/"
        add(prefix + "CHECKPOINT.pt", Path(commit["checkpoint_path"]))
        add(prefix + "COMMIT.json", commit_path)
        add(prefix + "PLAN.json", root / "campaign-v2" / fit["name"] / "plan.json")
        if hashlib.sha256(members[prefix + "CHECKPOINT.pt"]).hexdigest() != fit["checkpoint_sha256"]:
            raise ValueError("original checkpoint changed before archival")
        if hashlib.sha256(members[prefix + "COMMIT.json"]).hexdigest() != fit["commit_sha256"]:
            raise ValueError("original commit changed before archival")
    if sum(map(len, members.values())) > 20 * 1024**2:
        raise ValueError("unexpected archive size")
    manifest = {"schema": "hcsn-c2-cold-resume-exact-artifact-v1", "identity": request["identity"],
                "members": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                            for name, data in sorted(members.items())}}
    archive = HERE / "c2-cold-resume-exact-artifact.zip"
    with archive.open("xb") as stream, ZipFile(stream, "w", ZIP_DEFLATED, compresslevel=9) as zipfile:
        for name, data in sorted(members.items()):
            zipfile.writestr(name, data)
        zipfile.writestr("MANIFEST.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    receipt = {"archive": str(archive), "bytes": archive.stat().st_size,
               "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
               "members": len(members) + 1, "uncompressed_bytes": sum(map(len, members.values())),
               "scope": "Exact original checkpoint inputs, frozen diagnostic source, and all generated output files"}
    with (HERE / "ARTIFACT.json").open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
