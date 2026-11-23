"""Verify the 69 signature pairs and all existing donor type declarations from Git objects."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


BASE = "c12ee03f3185d5a13949faca54f066dfd634e509"
DONOR = "24abd04c825cb0d5d0ce27b52ac5008eda13dde4"
HERE = Path(__file__).resolve().parent
TYPES = re.compile(r"\b(?:struct|enum|type|trait)\s+(\w+)")
IDENT = re.compile(r"[A-Z][A-Za-z0-9_]*")


def signature(text, start):
    token = re.search(r"\bfn\s+(\w+)\s*(?:<[^\n]*?>)?\s*\(", text[start:])
    assert token
    left = start + token.end()
    nested = []
    result = []
    for offset in range(left, len(text)):
        char = text[offset]
        if char in ",)" and not nested:
            item = " ".join(text[left:offset].split())
            if item:
                result.append(item)
            if char == ")":
                return token.group(1), result
            left = offset + 1
        elif char in "([{<":
            nested.append(char)
        elif char in ")]}" and nested:
            nested.pop()
        elif char == ">" and text[offset-1] != "-" and nested and nested[-1] == "<":
            nested.pop()
    raise ValueError(token.group(1))


def git(*args, data=None):
    return subprocess.check_output(["git", "-C", sys.argv[1], *args], input=data)


def object_hash(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def rust_files(rev):
    tree = {}
    for entry in git("ls-tree", "-rz", rev, "--", "codex-rs").split(b"\0"):
        if not entry:
            continue
        meta, name = entry.split(b"\t", 1)
        if name.endswith(b".rs"):
            mode, kind, oid = meta.split(b" ")
            assert kind == b"blob", (kind, name)
            tree[name.decode()] = oid.decode()
    return tree


def all_contents(tree):
    ids = list(dict.fromkeys(tree.values()))
    proc = subprocess.Popen(["git", "-C", sys.argv[1], "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for oid in ids:
            proc.stdin.write((oid + "\n").encode())
            proc.stdin.flush()
            key, kind, size = proc.stdout.readline().split()
            assert key.decode() == oid and kind == b"blob"
            data = proc.stdout.read(int(size))
            assert proc.stdout.read(1) == b"\n" and object_hash(data) == oid
            yield oid, data.decode()
    finally:
        proc.stdin.close()
        proc.stdout.close()
        assert proc.wait() == 0


def main():
    rows = json.loads((HERE/"signature-pair.json").read_text())
    expected = json.loads((HERE/"current-types.json").read_text())
    base = rust_files(BASE)
    local = "--cached-source" in sys.argv
    if local:
        donor = {"codex-rs/hepta-agentd/src/" + name: oid for name, oid, _ in json.loads((HERE/"donor-map.json").read_text())}
        cut = json.loads((HERE.parent/"daemon_scope_2909/c12-rust-paths.json").read_text())
        roots = [HERE/"physical", HERE.parent/"ci_formatter/full-tree", HERE.parent/"memory_startup_c12", HERE.parent/"hcsn-combined-native/physical",
                 HERE.parent/"private16_verify/callers-candidate", HERE.parent/"strict_union/snapshot", HERE.parent/"strict_private_enum/candidate"]
        def cached_current():
            seen = set()
            for path, oid in base.items():
                if oid in seen:
                    continue
                files = [Path(cut[path])] if path in cut else []
                files.extend(root/path for root in roots)
                for file in files:
                    if file.is_file() and object_hash(data := file.read_bytes()) == oid:
                        yield oid, data.decode()
                        seen.add(oid)
                        break
                else:
                    raise ValueError(("missing content", path, oid))
        current_contents = cached_current()
        donor_sources = {}
        for name, oid in donor.items():
            data = (HERE/"donor"/Path(name).name).read_bytes()
            assert object_hash(data) == oid
            donor_sources[oid] = data.decode()
    else:
        donor = rust_files(DONOR)
        current_contents = all_contents(base)
        donor_sources = dict(all_contents({r["path"]: donor[r["path"]] for r in rows}))
    assert len(base) == expected["matched_rust_files"] == 9141
    assert list(range(1, 70)) == [r["index"] for r in rows]
    assert len({r["path"] for r in rows}) == 54
    by_blob = {}
    for path, oid in base.items():
        by_blob.setdefault(oid, []).append(path)
    references = set(expected["declarations"])
    declared = {name: [] for name in references}
    want = {r["current_blob"] for r in rows}
    input_sources = {}
    for oid, src in current_contents:
        if oid in want:
            input_sources[oid] = src
        for match in TYPES.finditer(src):
            name = match.group(1)
            if name in references:
                line = src.count("\n", 0, match.start()) + 1
                declared[name].extend([path, oid, line] for path in by_blob[oid])
    assert {k: sorted(v) for k, v in declared.items()} == {k: sorted(v) for k, v in expected["declarations"].items()}
    for row in rows:
        p = row["path"]
        assert base[p] == row["current_blob"] and donor[p] == row["donor_blob"]
        src = input_sources[base[p]]
        offset = sum(map(len, src.splitlines(keepends=True)[:row["line"] - 1]))
        assert signature(src, offset) == (row["name"], row["current"])
        new = donor_sources[donor[p]]
        found = [signature(new, x.start())[1] for x in re.finditer(r"\bfn\s+" + row["name"] + r"\b", new)]
        assert (row["donor"] in found and len(found) == row["overloads_in_donor"]
                and len(row["current"]) > 7 and len(row["donor"]) <= 7)
        assert sorted(set(IDENT.findall(" ".join(row["donor"]))) - set(IDENT.findall(" ".join(row["current"])))) == row["new_types"]
    groups = Counter("existing donor type" if any(declared.get(t) for t in row["new_types"]) else "none already declared" for row in rows)
    print(json.dumps({"base": BASE, "donor": DONOR, "rust_files": len(base), "diagnostics": len(rows),
                      "agentd_sources": len({r["path"] for r in rows}), "counts": groups}, indent=2))


if __name__ == "__main__":
    main()
