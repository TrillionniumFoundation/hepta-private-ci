"""Check the 4,175 original rows and optionally rerun Rustfmt from exact Git object contents."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import difflib
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile


HERE = Path(__file__).resolve().parent
OLD = "e4be1e972707f5c376033fd59e18fb4f260da891"
NEW = "97a379c5a347f0e66c5ed9a0cbd38303d1f92cb5"
RAW_SHA = "cc7c5da82a1457f2db23f4dfcf6b8280df3fa6f6c2743bf612d6cb9591096133"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def call(command, root=None):
    return subprocess.check_output(command, cwd=root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, help="Git checkout containing both frozen commits")
    parser.add_argument("--rustfmt", type=Path, help="Official Linux 1.96 formatter binary, requires --repo")
    args = parser.parse_args()
    raw = gzip.decompress((HERE / "remaining-4175.jsonl.gz").read_bytes())
    assert sha(raw) == RAW_SHA
    rows = list(map(json.loads, raw.splitlines()))
    pairs = json.loads((HERE / "sources.json").read_bytes())
    failures = [r for r in rows if r["exit"]]
    paths = [r["path"] for r in failures]
    assert len(rows) == len({r["path"] for r in rows}) == 4175
    assert paths == [r["path"] for r in pairs] and len(paths) == 12
    assert sum(r["headers_total"] for r in failures) == 56
    with zipfile.ZipFile(HERE.parent / "registered-44.zip") as archive:
        full = json.loads(gzip.decompress(archive.read("original-rust.json.gz")))
        exempt = {c["path"] for c in json.loads(archive.read("actual-44.json"))}
        assert [p for p in full if p not in exempt] == [r["path"] for r in rows]
    owner = json.loads((HERE / "context-owner.json").read_bytes())["dependencies"]
    assert len(owner) == 26 and sum(r["state"] == "missing" for r in owner) == 5
    print("4,175 retained ordinary path results: 4,163 pass, 12 formatting differences, 56 Rustfmt diff headings.")
    if args.repo is None:
        if args.rustfmt:
            parser.error("--rustfmt requires --repo")
        return
    repo = args.repo.resolve()

    def git(*argv):
        return call(["git", *argv], repo)

    assert git("diff", "--name-only", OLD, NEW).decode().splitlines() == paths
    patch = []
    for p in pairs:
        k = p["path"]
        original = git("show", f"{OLD}:{k}")
        formatted = git("show", f"{NEW}:{k}")
        assert sha(original) == p["original_sha256"] and sha(formatted) == p["formatted_sha256"]
        assert git("rev-parse", f"{OLD}:{k}").decode().strip() == p["original_blob"]
        assert git("rev-parse", f"{NEW}:{k}").decode().strip() == p["formatted_blob"]
        patch.extend(difflib.unified_diff(original.decode().splitlines(True), formatted.decode().splitlines(True), "a/" + k, "b/" + k))
    assert "".join(patch).encode() == (HERE / "changes.patch").read_bytes()
    print("Both original Git trees and SHA-256 agree for all 12 source pairs; the published unified diff is exact.")
    if not args.rustfmt:
        return
    formatter = args.rustfmt.resolve()
    assert sha(formatter.read_bytes()) == "342c3d56e8958da0b108108a39e37ceac64ebdd42e6eefafa237d219e5b7eb0c"
    assert call([str(formatter), "--version"]).strip() == b"rustfmt 1.9.0-stable (ac68faa20c 2026-05-25)"
    with tempfile.TemporaryDirectory(prefix="hepta-owner-rustfmt-") as temp:
        root = Path(temp)
        configs = {}
        for i, name in enumerate(sorted({r["config"] or "" for r in rows})):
            cfg = root / f"rule-{i}.toml"
            cfg.write_bytes(git("show", f"{OLD}:{name}") if name else b"")
            configs[name] = cfg

        def test(r):
            k = r["path"]
            file = root / "source" / k
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(git("show", f"{OLD}:{k}"))
            command = [str(formatter), "--edition", r["edition"], "--config-path", str(configs[r["config"] or ""]), "--config", "imports_granularity=Item,skip_children=true"]
            res = subprocess.run([*command, "--check", "--", str(file)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            assert res.returncode == r["exit"], k
            if res.returncode:
                assert sha(res.stdout.replace(str(file).encode(), k.encode())) == r["normalized_output_sha256"], k
                subprocess.run([*command, "--", str(file)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
                assert file.read_bytes() == git("show", f"{NEW}:{k}"), k

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(test, rows))
    print("Actual formatter replay passed on 4,175 original files and produced all 12 published replacements byte for byte.")


if __name__ == "__main__":
    main()
