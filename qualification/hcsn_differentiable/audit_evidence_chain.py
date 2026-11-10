"""Check HCSN P0 artifact bytes, historical HOLDs, and CURRENT.md links.

This checks the *integrity of the declared evidence index*, not authenticity
of training execution and never converts a missing receipt into a passing fit.
Only exact in-tree files with explicit SHA-256 entries are counted as bound.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


SCHEMA = "hcsn-evidence-chain-v1"
LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def _within(root, path):
    root = root.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("evidence path escapes repository root")
    return target


def check_chain(repo_root, ledger):
    """Return an auditable result or fail closed on a bad BOUND declaration."""
    root = Path(repo_root).resolve()
    if ledger.get("schema") != SCHEMA:
        raise ValueError("unknown evidence-chain schema")
    bound = ledger.get("bound_files")
    holds = ledger.get("holds")
    if not isinstance(bound, list) or not bound or not isinstance(holds, list) or not holds:
        raise ValueError("expected nonempty bound and HOLD lists")
    ids = [row.get("id") for row in bound + holds]
    if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("missing or duplicate evidence IDs")
    observations = []
    for row in bound:
        path = row.get("path")
        digest = row.get("sha256")
        if not isinstance(path, str) or not re.fullmatch(r"[a-f0-9]{64}", str(digest)):
            raise ValueError("BOUND entry needs path and exact lowercase SHA-256")
        target = _within(root, path)
        if not target.is_file():
            raise FileNotFoundError("BOUND artifact missing: " + path)
        hash_state = hashlib.sha256()
        with target.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hash_state.update(chunk)
        if hash_state.hexdigest() != digest:
            raise ValueError("BOUND artifact content mismatch: " + path)
        observations.append({"id": row["id"], "path": path,
                             "bytes": target.stat().st_size, "sha256": digest})
    for row in holds:
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise ValueError("HOLD entry needs a nonempty reason")
        if "sha256" in row or row.get("passed") is True:
            raise ValueError("HOLD cannot masquerade as a validated artifact")
        if "expected_missing_path" in row:
            path = row["expected_missing_path"]
            if not isinstance(path, str):
                raise ValueError("invalid HOLD path")
            _within(root, path)
    current = root / "qualification" / "hcsn_differentiable" / "CURRENT.md"
    if not current.is_file():
        raise FileNotFoundError("CURRENT.md missing")
    checked_links = []
    for raw in LINK_PATTERN.findall(current.read_text(encoding="utf-8")):
        url = urlsplit(raw.strip().split(" ", 1)[0])
        if url.scheme in ("http", "https", "mailto") or raw.startswith("#"):
            continue
        if url.scheme or url.netloc or not url.path:
            raise ValueError("unrecognized local link: " + raw)
        target = _within(root, str(current.parent.relative_to(root) / unquote(url.path)))
        if not target.exists():
            raise FileNotFoundError("CURRENT.md broken link: " + raw)
        checked_links.append(raw)
    return {"schema": "hcsn-evidence-chain-audit-v1", "status": "HOLD",
            "bound_artifacts": observations,
            "checked_current_links": sorted(checked_links),
            "open_holds": [{"id": row["id"], "reason": row["reason"]} for row in holds],
            "scientific_admission": False,
            "claim": "Bound bytes and existing links only; no original 18-fit replay, trained posterior qualification or comparative gain."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("--output already exists; do not overwrite execution receipts")
    root = Path(__file__).resolve().parents[2]
    report = {"schema": "hcsn-evidence-chain-audit-v1", "status": "AUDIT_FAILED",
              "scientific_admission": False}
    exit_code = 1
    try:
        ledger = json.loads((Path(__file__).resolve().parent / "EVIDENCE_CHAIN.json").read_text())
        report = check_chain(root, ledger)
        exit_code = 0  # The audit itself passes; HOLDs remain HOLDs.
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "output": str(args.output),
                      "scientific_admission": False}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
