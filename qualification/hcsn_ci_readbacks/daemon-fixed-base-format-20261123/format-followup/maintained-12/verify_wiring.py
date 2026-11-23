"""Inventory literal module registrations in the six affected current package roots."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib


ROOT = Path(__file__).resolve().parent
OLD = "e4be1e972707f5c376033fd59e18fb4f260da891"
NEW = "97a379c5a347f0e66c5ed9a0cbd38303d1f92cb5"
PACKAGES = {
    "ext/hepta-prompt": ["v3"],
    "hepta-agentd": ["prompt_product_v3"],
    "hepta-context-compiler": ["preparation_archive"],
    "hepta-intelligence": ["prompt_product_v3"],
    "hepta-memory-federation-wire": ["attempt", "codec", "protocol", "replay", "tests"],
    "hepta-supervisor": ["lock_metrics", "qualification_fault", "recovery_diagnostics"],
}


def inventory(repo, ref):
    command = ["git", "-C", str(repo)]
    objects = (subprocess.check_output([*command, "ls-tree", "-r", "-z", ref, "--", "codex-rs/"]).decode().strip("\x00").split("\x00"))
    files = {}
    for entry in objects:
        spec, path = entry.split("\t", 1)
        mode, typ, sha = spec.split()
        assert typ == "blob"
        files[path] = sha
    report = {}
    batch = subprocess.Popen([*command, "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def read(sha):
        batch.stdin.write((sha + "\n").encode())
        batch.stdin.flush()
        header = batch.stdout.readline().split()
        assert header[0].decode() == sha and header[1] == b"blob"
        data = batch.stdout.read(int(header[2]))
        assert batch.stdout.read(1) == b"\n"
        assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\x00" + data).hexdigest() == sha
        return data

    try:
        for name, mods in PACKAGES.items():
            prefix = f"codex-rs/{name}/"
            inputs = {p: b for p, b in files.items() if p.startswith(prefix) and (p.endswith((".rs", ".toml", "/BUILD.bazel")))}
            hits = []
            for path, blob in inputs.items():
                text = read(blob).decode()
                for mod in mods:
                    pattern = rf'(?m)\bmod\s+{mod}\s*;|(?:"[^"\n]*/{mod}\.rs"|"{mod}\.rs")'
                    for match in re.finditer(pattern, text):
                        hits.append([path, mod, match.group(0)])
            report[name] = {"sources_manifests_and_build_files": len(inputs), "literal_references": hits}
        ws = tomllib.loads(read(files["codex-rs/Cargo.toml"]).decode())["workspace"]
        report["workspace"] = {"cargo_tree_blob": files["codex-rs/Cargo.toml"], "wire_explicit_member": "hepta-memory-federation-wire" in ws["members"], "member_globs": [m for m in ws["members"] if any(c in m for c in "*?[")]}
        assert not report["workspace"]["wire_explicit_member"] and not report["workspace"]["member_globs"]
        for n in PACKAGES:
            hits = report[n]["literal_references"]
            if n == "hepta-memory-federation-wire":
                assert {r[1] for r in hits} == set(PACKAGES[n])
            else:
                assert not hits, (n, hits)
        return report
    finally:
        batch.stdin.close()
        assert batch.wait() == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    old = inventory(args.repo, OLD)
    after = inventory(args.repo, NEW)
    assert old == after
    payload = json.dumps({"arms": [OLD, NEW], "scope": "literal module declarations and explicitly named source paths in Rust, Cargo and Bazel source files under the six package roots", "result": old}, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload)
    print(payload)
