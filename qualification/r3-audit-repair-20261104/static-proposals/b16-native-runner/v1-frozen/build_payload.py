#!/usr/bin/env python3
"""Reconstruct approved B deltas in a new, isolated, uncompiled Git directory."""

import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
WS = HERE.parents[1]
OLD = WS / "architecture-audit/b16-native-adoption-runner-20261105"
FOUND = WS / "architecture-audit/b16-b-serial-alignment-20261105"
ADOPT = WS / "architecture-audit/sqlx-adoption-test-entry-20261105"
DRIVER = WS / "architecture-audit/sqlx-native-lifetime-token-20261105"
POOL = WS / "architecture-audit/b16-state-native-token-binding-20261105"
CHECK = WS / "research-audit/b16-recovery-checkpoint-custody"
VENDOR = "codex-rs/third_party/sqlx-sqlite-0.9.0"


def ident(b):
    return {"blob": hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest(),
            "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}


def load(p):
    return json.loads(p.read_bytes())


def main():
    plan = load(OLD / "execution-plan.json")
    work = HERE / "isolated-payload-reconstruction"
    work.mkdir(exist_ok=False)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    sources, deltas, events = {}, {}, []

    def record(b):
        row = ident(b)
        sources[row["blob"]] = {**row, "text": b.decode("utf-8")}
        return row["blob"]

    def inventory():
        return {str(p.relative_to(work)): record(p.read_bytes())
                for p in sorted((work / "codex-rs").rglob("*")) if p.is_file()}

    def put(path, b):
        p = work / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
        p.chmod(0o644)

    initial = load(FOUND / "input-manifest.json")["initial_source_map"]
    for path, blob in initial.items():
        if blob is not None:
            b = (FOUND / "objects" / (blob + ".txt")).read_bytes()
            assert ident(b)["blob"] == blob
            put(path, b)
    for path, parent in [("codex-rs/Cargo.toml", ADOPT),
                         ("codex-rs/hepta-memory/Cargo.toml", CHECK),
                         ("codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs", CHECK)]:
        b = (parent / "source" / path).read_bytes()
        put(path, b)
        initial[path] = ident(b)["blob"]
    initial_present = inventory()

    def transition(label, mutation, provenance):
        before = inventory()
        mutation()
        after = inventory()
        files = [{"path": p, "mode": "100644", "before_blob": before.get(p),
                  "after_blob": after.get(p), **{k: sources[after[p]][k] for k in ("bytes", "sha256")}}
                 for p in sorted(set(before) | set(after)) if before.get(p) != after.get(p)]
        assert files and all(f["after_blob"] is not None for f in files)
        deltas[label] = {"label": label, "files": files, "provenance": provenance}
        events.append({"label": label, "files": files, "source_map_after": after})

    def patch(label, p, blob, mapped=False):
        b = p.read_bytes()
        assert ident(b)["blob"] == blob, (p, ident(b))
        argv = ["git", "apply", "--whitespace=error-all"]
        if mapped:
            argv += ["-p2", "--directory=" + VENDOR]

        def mutate():
            for check in (True, False):
                command = argv + (["--check"] if check else []) + [str(p)]
                r = subprocess.run(command, cwd=work, capture_output=True, text=True)
                assert r.returncode == 0, (command, r.stdout, r.stderr)
        transition(label, mutate, {"patch": ident(b), "mapping": argv[3:]})

    history = load(FOUND / "static-verification.json")
    for e in history["events"]:
        if e["isolated_copy"] == "static-causal-sequence":
            patch(e["label"].replace(":", "-"), FOUND / "objects" / (e["patch_blob"] + ".txt"), e["patch_blob"])
    foundation_end = inventory()
    vendor = load(ADOPT / "complete-vendor-source-bundle.json")
    vendor_rows = vendor["files"]
    root_cargo = (ADOPT / "complete-vendor-static-assembly/codex-rs/Cargo.toml").read_bytes()

    def vendor_copy():
        assert not (work / VENDOR).exists()
        for f in vendor_rows:
            b = f["text"].encode()
            assert ident(b) == {k: f[k] for k in ("blob", "bytes", "sha256")}
            put(f["path"], b)
        put("codex-rs/Cargo.toml", root_cargo)
    transition("driver-adoption", vendor_copy, {"complete_payload": ident((ADOPT / "complete-vendor-source-bundle.json").read_bytes()),
              "original_archive_sha256": vendor["archive_sha256"], "vendor_regular_modes": "100644",
              "licenses": "Two mechanical full-license overlays; original 57-member archive is separately preserved."})
    driver = load(DRIVER / "repair-manifest.json")
    for n in driver["negative_controls"]:
        for key in ("patch", "restore"):
            f = n[key]
            patch("driver-" + n["name"] + "-" + key, DRIVER / f["path"], f["blob"], True)
    pool = load(POOL / "repair-manifest.json")
    patch("pool-binding", POOL / pool["patch"]["path"], pool["patch"]["blob"])
    for key in ("patch", "restore"):
        f = pool["counterfactual"][key]
        patch("pool-" + key, POOL / f["path"], f["blob"])
    checkpoint = load(CHECK / "repair-manifest.json")
    for section, filename in [("production_cohort", "production-custody.patch"),
                              ("physical_control_cohort", "memory-physical-control.patch")]:
        patch("checkpoint-" + section, CHECK / filename, checkpoint[section]["patch"]["blob"])
    p = checkpoint["physical_control_cohort"]
    patch("checkpoint-negative", CHECK / "negative-checkpoint-native-binding.patch", p["negative"]["patch"]["blob"])
    patch("checkpoint-restore", CHECK / "restore-checkpoint-native-binding.patch", p["restore"]["blob"])
    final = inventory()
    old_final = {str(p.relative_to(OLD / "static-final-partial-tree-v3")): ident(p.read_bytes())["blob"]
                 for p in (OLD / "static-final-partial-tree-v3/codex-rs").rglob("*") if p.is_file()}
    assert final == old_final, "Final 81-file composition drifted from dc12 plan"

    # Explicit operation order: repairs in finally are not applied twice.
    p = plan["phases"]
    ops = [[] for _ in range(5)]

    def apply(epoch, name):
        ops[epoch].append({"kind": "apply", "delta": name})

    def scope(epoch, i, before=(), restore=None, oracle=None):
        phase = p[i]
        groups = phase.get("commands") if phase.get("commands") and isinstance(phase["commands"][0], dict) else [phase]
        scopes = []
        for j, g in enumerate(groups):
            argv = g["argv"]
            pkg = argv[argv.index("-p") + 1]
            names = g.get("exact_names", g.get("exact_names_on_linux"))
            scopes.append({"label": phase["id"] + ("-" + pkg if len(groups) > 1 else ""),
                           "package": pkg, "exact_names": names, "authored_argv": argv,
                           "oracle": oracle, "supports": []})
            if pkg == "sqlx-sqlite":
                scopes[-1]["supports"] = ["options::connection_lifetime::tests::owned_scenario"]
            elif i in (15, 16) and pkg == "codex-state":
                scopes[-1]["supports"] = ["sqlite::native_custody_tests::owned_state_scenario"]
            elif i in (18, 19):
                scopes[-1]["supports"] = ["cognitive_store::recovery::tests::checkpoint_custody::owned_checkpoint_scenario"]
        ops[epoch].append({"kind": "negative" if restore else "scopes", "id": phase["id"],
                           "before": list(before), "restore": restore, "scopes": scopes})

    scope(0, 0, ["r2c-v3-full"])
    apply(0, "r2d-full")
    scope(0, 1, ["r2d-without-close-on-drop"], "r2d-restore-close-on-drop", "barrier")
    scope(0, 2)
    scope(0, 3, ["r2e1-test-only-baseline"], "r2e1-repair-after-baseline", "interlock")
    scope(0, 4)
    scope(0, 5, ["r2e2a-full"])
    scope(0, 6, ["r2e2b-full"])
    scope(0, 7, ["r2e3-test-only-baseline"], "r2e3-repair-after-baseline", "custody")
    scope(0, 8, ["r2e3-without-native-anchor"], "r2e3-restore-native-anchor", "anchor")
    scope(0, 9)
    apply(1, "driver-adoption")
    ops[1].append({"kind": "locks", "id": p[10]["id"], "change": "driver"})
    scope(1, 11, ["driver-no_worker_token-patch"], "driver-no_worker_token-restore", "driver-worker")
    scope(1, 12, ["driver-unwind_releases-patch"], "driver-unwind_releases-restore", "driver-close")
    scope(1, 13)
    ops[1].append({"kind": "bazel-registration", "id": p[14]["id"], "target": p[14]["target"]})
    apply(2, "pool-binding")
    scope(2, 15, ["pool-patch"], "pool-restore", "pool")
    scope(2, 16)
    apply(3, "checkpoint-production_cohort")
    apply(3, "checkpoint-physical_control_cohort")
    ops[3].append({"kind": "locks", "id": p[17]["id"], "change": "checkpoint"})
    scope(3, 18, ["checkpoint-negative"], "checkpoint-restore", "checkpoint")
    scope(3, 19)
    ops[4].append({"kind": "owning", "id": p[20]["id"], "packages": ["codex-state", "codex-hepta-memory"]})
    ops[4].append({"kind": "hygiene", "id": "B20_hygiene"})
    names = ["foundation", "driver", "pool", "checkpoint", "owning"]
    for epoch, operations in zip(names, ops):
        (HERE / ("epoch-" + epoch + ".json")).write_text(json.dumps({"epoch": epoch, "operations": operations}, indent=2) + "\n")
    pieces, part = [], {}
    for blob, row in sorted(sources.items()):
        candidate = {**part, blob: row}
        if len(json.dumps(candidate).encode()) > 350000 and part:
            pieces.append(part)
            part = {}
        part[blob] = row
    if part:
        pieces.append(part)
    payloads = []
    for i, piece in enumerate(pieces):
        name = f"source-payload-{i:02}.json"
        b = (json.dumps(piece, ensure_ascii=False, indent=2) + "\n").encode()
        assert len(b) < 480000
        (HERE / name).write_bytes(b)
        payloads.append({"path": name, **ident(b)})
    manifest = {"schema": "hepta-b16-guarded-native-payload-v1", "status": "SOURCE_ONLY_NOT_LAUNCHED",
                "frozen_plan": ident((OLD / "execution-plan.json").read_bytes()),
                "final_A_tree": None, "initial_preimages": initial, "deltas": deltas,
                "payloads": payloads, "epochs": names,
                "epoch_files": [{"path": "epoch-" + n + ".json", **ident((HERE / ("epoch-" + n + ".json")).read_bytes())} for n in names],
                "foundation_end_map": foundation_end, "final_partial_source_map": final,
                "counts": plan["counts"], "open_limits": plan["still_open_after_native_pass"],
                "native_commands_run": False, "source_reconstruction": "Only isolated Python/Git apply. No Cargo, Bazel, native host or refs."}
    (HERE / "payload-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (HERE / "payload-reconstruction.json").write_text(json.dumps({"initial": initial_present, "events": events,
            "final_equals_frozen_plan": True, "final_paths": len(final), "native_executed": False}, indent=2) + "\n")
    print(json.dumps({"deltas": len(deltas), "source_objects": len(sources), "payload_parts": len(pieces), "final_paths": len(final)}))


if __name__ == "__main__":
    main()
