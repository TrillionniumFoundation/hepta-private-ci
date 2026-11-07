"""Rebind selected reviewed E17 source bytes; execute no candidate code."""

import hashlib
import json
import stat
from pathlib import Path

ROOT = Path("/workspace/scratch/3f6a885bb83c")
WORK = Path("/dev/shm/ndu_root_continuation_20261107")
OWNER = Path("/dev/shm/ndu_e17_production_review_20261107")


def require(value, message):
    if not value:
        raise ValueError(message)


def read(path, expected=None):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), "Non-regular input")
    raw = path.read_bytes()
    after = path.lstat()
    fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    require(
        all(getattr(before, field) == getattr(after, field) for field in fields),
        "Input metadata changed while reading",
    )
    digest = hashlib.sha256(raw).hexdigest()
    if expected:
        require(digest == expected, f"Input SHA differs: {path}")
    return raw, {
        "path": str(path),
        "bytes": len(raw),
        "sha256": digest,
        "mode": format(stat.S_IMODE(before.st_mode), "04o"),
    }


def git_object(kind, raw):
    header = f"{kind} {len(raw)}".encode() + b"\0"
    return hashlib.sha1(header + raw).hexdigest()


def load(path, expected=None):
    raw, record = read(path, expected)
    return json.loads(raw), record


def main():
    manifest, owner_pin = load(
        OWNER / "MANIFEST.json",
        "a5588bb6c2026fd0408560d5be6320c5406fda97c6fb6c2767cd340d2a8ce7d6",
    )
    retained = []
    for item in manifest["files"] + manifest["prior_safe_inputs"]:
        _, actual = read(Path(item["path"]), item["sha256"])
        require(actual == item, "Owner manifest identity or mode differs")
        retained.append(actual)
    first, _ = load(OWNER / "SOURCE_BINDING.json")
    second, _ = load(OWNER / "SOURCE_BINDING_ADDENDUM.json")
    api, api_pin = load(
        WORK / "e17_current_root_api.json",
        "39c75a2e34848fb307b8a15ea95dfea40ae444adc5ec646080723acfd4cfe958",
    )
    tip = api["checked_main"]
    require(tip["pr"] == 5276, "Reviewed main changed")
    require(api["commit_API"]["sha"] == tip["commit"], "Commit identity")
    require(api["commit_API"]["tree"]["sha"] == tip["tree"], "Commit tree")
    source = api["git_source"]
    require(source["root_tree"] == tip["tree"], "Root tree identity")
    for prefix, tree in source["trees"].items():
        require(tree["truncated"] is False, "Incomplete tree")
        entries = sorted(
            tree["tree"],
            key=lambda row: (
                row["path"] + ("/" if row["type"] == "tree" else "")
            ).encode(),
        )
        raw = b"".join(
            (row["mode"].lstrip("0") + " " + row["path"]).encode()
            + b"\0"
            + bytes.fromhex(row["sha"])
            for row in entries
        )
        require(git_object("tree", raw) == tree["sha"], f"Tree SHA: {prefix}")
        if prefix:
            parent, _, name = prefix.rpartition("/")
            entry = next(
                row for row in source["trees"][parent]["tree"] if row["path"] == name
            )
            require(
                entry["type"] == "tree" and entry["sha"] == tree["sha"],
                "Ancestor chain",
            )
        else:
            require(tree["sha"] == tip["tree"], "Main root differs")
    selected = first["selected_sources"] + second["additional_repository_sources"]
    require(len(selected) == 13 and len(source["leaves"]) == 13, "Selected roster")
    source_rows = []
    for item in selected:
        path = item["repository_path"]
        local = Path(item.get("frozen_source_path", item.get("path", "")))
        if not local.is_absolute():
            local = ROOT / local
        raw, pin = read(local, item["sha256"])
        require(len(raw) == item["bytes"], "Selected source length")
        require(
            git_object("blob", raw) == item["git_blob"], "Local source Git identity"
        )
        parent, _, name = path.rpartition("/")
        entry = next(
            row for row in source["trees"][parent]["tree"] if row["path"] == name
        )
        require(entry == source["leaves"][path], "Selected leaf mismatch")
        require(entry["mode"] == "100644" and entry["type"] == "blob", "Source mode")
        require(entry["sha"] == item["git_blob"], "Current main source differs")
        source_rows.append(
            {"repository_path": path, "git_blob": item["git_blob"], **pin}
        )
    kernel = []
    for item in second["kernel_selected_sources"]:
        raw, pin = read(Path(item["path"]), item["sha256"])
        require(len(raw) == item["bytes"], "Kernel source length")
        require(
            git_object("blob", raw) == item["git_blob"], "Kernel source Git identity"
        )
        kernel.append({"repository_path": item["repository_path"], **pin})
    exec_entries = source["trees"]["codex-rs/exec-server/src"]["tree"]
    require(
        not any(
            row["path"] == "read_delegation_guard_tests.rs" for row in exec_entries
        ),
        "Guard unexpectedly on main",
    )
    result = {
        "schema": "e17-root-selected-source-review-v1",
        "checked_main": tip,
        "owner_manifest": owner_pin,
        "root_fresh_API": api_pin,
        "complete_ancestor_trees_rehashed": len(source["trees"]),
        "selected_current_repository_sources": source_rows,
        "fixed_kernel_sources_rehashed_against_frozen_bindings": kernel,
        "retained_owner_and_prior_input_count": len(retained),
        "reviewed_source_facts": [
            "Non-macOS authorized bounded read returns Unsupported; capability is false.",
            "Runtime paths have executable paths only, no trusted view constructor.",
            "CLONE_FS isolates shared fs_struct but does not copy a mount namespace.",
            "statmount clears detached mount fields and holds no admission-long lock.",
            "Exact deny aliases are canonicalized samples, not lifetime authority.",
        ],
        "limitations": [
            "Selected call-chain review is not a whole-repository absence proof.",
            "Kernel byte binding does not identify a running kernel or deployment.",
            "No native candidate, syscall, archive observer or scientific execution.",
            "No production constructor, capability activation, direct Linux41 case or E17 closure.",
        ],
        "E17": "OPEN",
    }
    out = WORK / "e17_root_review"
    out.mkdir(exist_ok=False)
    path = out / "ROOT_REVIEW.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    _, pin = read(path)
    print(json.dumps(pin))


if __name__ == "__main__":
    main()
