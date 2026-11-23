"""Verify the exact two removed private projections from a Git checkout.

Run with both requested commits and the qualified donor locally available.
"""
from pathlib import Path
from functools import cache
import base64
import hashlib
import json
import subprocess
import sys

BASE = "c6a3ed9c36f88707d2f29630efe1e3ea4ee0e902"
CANDIDATE = "4adbacbd99f4d37e415cb90bc15a27b5b105e393"
DONOR = "24abd04c825cb0d5d0ce27b52ac5008eda13dde4"
PREFIX = "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_"


def git(*args):
    return subprocess.check_output(["git", "-C", str(Path(sys.argv[1]).resolve()), *args])


@cache
def source(commit, suffix):
    if sys.argv[1] == "--github":
        endpoint = f"repos/TrillionniumFoundation/hepta-private-ci/contents/{PREFIX}{suffix}.rs?ref={commit}"
        data = json.loads(subprocess.check_output(["gh", "api", endpoint]))
        body = base64.b64decode(data["content"])
        header = f"blob {len(body)}".encode() + bytes([0])
        assert hashlib.sha1(header + body).hexdigest() == data["sha"]
        return body
    return git("show", commit + ":" + PREFIX + suffix + ".rs")


def main():
    if sys.argv[1] == "--github":
        comparison = json.loads(subprocess.check_output(
            ["gh", "api", f"repos/TrillionniumFoundation/hepta-private-ci/compare/{BASE}...{CANDIDATE}"]))
        assert comparison["ahead_by"] == 1 and comparison["behind_by"] == 0
        paths = sorted(f["filename"] for f in comparison["files"])
    else:
        paths = git("diff", "--name-only", BASE, CANDIDATE).decode().splitlines()
    assert paths == [PREFIX + n + ".rs" for n in ("member", "wire")]
    member = source(BASE, "member")
    for deleted in (b"    pub estimand: Digest32,\n", b"        estimand: bundle.estimand,\n"):
        assert member.count(deleted) == 1
        member = member.replace(deleted, b"")
        assert deleted not in source(DONOR, "member")
    assert member == source(CANDIDATE, "member")
    assert b"    estimand: Digest32,\n" in member
    assert b"let estimand = reader.digest()?;" in member
    assert b"if Digest32::of_bytes(&member.estimand) != bundle.estimand {" in member
    wire = source(BASE, "wire")
    start = wire.index(b"    pub(super) fn context(&self)")
    end = wire.index(b"    }\n", start) + 6
    assert len(wire[start:end].splitlines()) == 5
    assert wire[:start] + wire[end:] == source(CANDIDATE, "wire") == source(DONOR, "wire")
    for check in (b"self.schema != 1", b"self.purpose != PURPOSE", b"self.id != id",
                  b"!(1..=128).contains(&id)", b"self.context != context.to_string()"):
        assert check in source(CANDIDATE, "wire")
    for module, checks in (("proofs", (b"holdout.digest()? != bundle.estimand",
                                         b"if estimand != member.estimand")),
                           ("service", (b"request.require(request_id, context)?;",))):
        unchanged = source(BASE, module)
        assert unchanged == source(CANDIDATE, module)
        assert all(check in unchanged for check in checks)
    print(json.dumps({"base": BASE, "candidate": CANDIDATE, "donor": DONOR,
                      "deleted_lines": 7, "changed_paths": paths,
                      "member_sha256": hashlib.sha256(member).hexdigest()}, indent=2))


if __name__ == "__main__":
    main()
