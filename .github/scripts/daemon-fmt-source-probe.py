"""Record all selected Rust paths for the pinned daemon formatter without editing source."""
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tomllib

ROOT = Path.cwd()
REPORT = Path(os.environ["RUNNER_TEMP"]) / "daemon-fmt-probe"
BASE = "b8e8c6e82abc1479c573f61a5e17d28d581e6cad"
HEAD = "c12ee03f3185d5a13949faca54f066dfd634e509"
ORIGIN = "5993cb909547070e4b56ca9465996a5a946fafca"
SCOPE = "AUDIT/2026-10-20-agent-continuation/cell_p0"
PROJECTION = f"{SCOPE}/sources/2909/"
OWNER = "codex-rs/Cargo.toml"
PKG = "codex-rs/hepta-control-plane/Cargo.toml"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    REPORT.mkdir(exist_ok=True)
    assert git("rev-parse", "HEAD").decode().strip() == HEAD
    assert git("status", "--porcelain", "--untracked-files=all") == b""
    module = runpy.run_path(str(ROOT / "scripts/format.py"))
    changed = module["changed_paths"](BASE)
    rust = module["rust_configuration_scope"](changed)
    rows = []
    for path in rust:
        try:
            command = module["rust_file_command"](path, check=True)
            args = command.args
            result = {"path": path, "edition": str(args[args.index("--edition") + 1])}
        except (ValueError, OSError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
            result = {"path": path, "error": str(error).replace(str(ROOT) + "/", "")}
        rows.append(result)
    for name, values in (("paths", changed), ("rust-editions", rows)):
        data = (json.dumps(values, ensure_ascii=False, indent=1) + "\n").encode()
        (REPORT / f"{name}.json.gz").write_bytes(gzip.compress(data, mtime=0))
    failed = [r for r in rows if "error" in r]
    owner_blob = git("rev-parse", f"{ORIGIN}:{OWNER}").decode().strip()
    assert owner_blob == "d2703b590935ab17316e6c258657c0ce5ab7412a"
    original = git("show", f"{ORIGIN}:{OWNER}")
    (REPORT / "original-workspace-manifest.txt").write_bytes(original)
    doc = tomllib.loads(original.decode())
    assert doc["workspace"]["package"]["edition"] == "2024"
    assert "hepta-control-plane" in doc["workspace"]["members"]
    manifest = tomllib.loads((ROOT / (PROJECTION + PKG)).read_text())
    assert manifest["package"]["edition"] == {"workspace": True}
    relative = sorted(path.relative_to(ROOT / PROJECTION).as_posix() for path in (ROOT / PROJECTION).rglob("*") if path.is_file())
    saved_sums = (ROOT / SCOPE / "SHA256SUMS").read_text().splitlines()
    identities = {}
    for name in relative:
        live = (ROOT / PROJECTION / name).read_bytes()
        origin = git("show", f"{ORIGIN}:{name}")
        assert live == origin
        digest = hashlib.sha256(live).hexdigest()
        assert f"{digest}  sources/2909/{name}" in saved_sums
        identities[name] = {"git_blob": git("rev-parse", f"{ORIGIN}:{name}").decode().strip(), "sha256": digest}
    out = {"head": HEAD, "base": BASE, "workspace_origin": ORIGIN, "original_workspace_git_blob": owner_blob,
           "original_edition": doc["workspace"]["package"]["edition"], "projection": identities,
           "changed_path_count": len(changed), "rust_path_count": len(rows), "unresolved_paths": failed,
           "resolved_editions": Counter(r["edition"] for r in rows if "edition" in r)}
    # The pinned, unmodified formatter plans all language groups before spawning any formatter.
    # Confirm the historical scope exception exists before replaying the original write-mode command.
    expected = "owning Rust workspace missing for " + str(ROOT / PROJECTION / PKG)
    assert any(r["error"] == expected.replace(str(ROOT) + "/", "") for r in failed)
    try:
        module["scoped_formatter_groups"](changed, check=False, base=BASE)
    except ValueError as err:
        assert str(err) == expected
    else:
        raise AssertionError("historical first failure did not reproduce during planning")
    p = subprocess.run(["just", "fmt", "--base", BASE], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (REPORT / "fmt.log").write_bytes(p.stdout)
    out["original_exit"] = p.returncode
    assert p.returncode == 2 and expected.encode() in p.stdout
    assert git("status", "--porcelain", "--untracked-files=all") == b""
    out["original_left_clean"] = True
    (REPORT/"probe.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({k:v for k,v in out.items() if k not in ("projection","unresolved_paths")}), flush=True)
    print("Unresolved Rust inputs:", len(failed), flush=True)


if __name__ == "__main__":
    main()
