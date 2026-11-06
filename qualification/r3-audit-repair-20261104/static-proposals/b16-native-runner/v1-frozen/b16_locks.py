"""Actual resolution and original Bazel recipes; no handcrafted lock edits."""

from contextlib import contextmanager
import json
from pathlib import Path
import re
import tomllib

from b16_guard import identity, need, record, same_record
from b16_native import DRIVER_FEATURES, graph

VENDOR = "codex-rs/third_party/sqlx-sqlite-0.9.0"
TARGET = "//" + VENDOR + ":sqlx-sqlite-unit-tests"


def validate_graph_change(before, after, change, tree):
    old = {p["id"]: p for p in before["packages"]}
    new = {p["id"]: p for p in after["packages"]}
    bn, an = {n["id"]: n for n in graph(before)["nodes"]}, {n["id"]: n for n in graph(after)["nodes"]}
    changed_package = "sqlx-sqlite" if change == "driver" else "codex-hepta-memory"
    remap = {}
    if change == "driver":
        original = [p for p in old.values() if p["name"] == "sqlx-sqlite"]
        current = [p for p in new.values() if p["name"] == "sqlx-sqlite"]
        need(len(original) == len(current) == 1, "duplicate or missing driver package")
        old_driver, driver = original[0], current[0]
        need(driver["version"] == old_driver["version"] == "0.9.0" and driver["source"] is None, "wrong adopted package identity")
        need(Path(driver["manifest_path"]).resolve() == (tree / VENDOR / "Cargo.toml").resolve(), "adopted driver outside approved vendor")
        need(driver["id"] in after["workspace_members"], "dependency tests still not a workspace member")
        need(sorted(an[driver["id"]]["features"]) == DRIVER_FEATURES, "actual driver features differ")
        remap[old_driver["id"]] = driver["id"]
        need(set(after["workspace_members"]) == set(before["workspace_members"]) | {driver["id"]}, "unexpected workspace membership change")
        need(len(an) == len(bn), "unrelated package added or removed during adoption")
    else:
        need(before["workspace_members"] == after["workspace_members"], "checkpoint changed membership")
        need(set(old) == set(new), "checkpoint introduced unrelated packages")
    normalize = lambda value: json.loads(_replace_ids(json.dumps(value, sort_keys=True), remap))
    for old_id, node in bn.items():
        new_id = remap.get(old_id, old_id)
        need(new_id in an, "resolved package disappeared")
        if old[old_id]["name"] != changed_package:
            need(normalize(node) == an[new_id], "unreviewed dependency/features change: " + old[old_id]["name"])
        else:
            need(node["features"] == an[new_id]["features"], "unreviewed features on modified package")
            allowed = "sqlx_core" if change == "driver" else "libsqlite3_sys"
            before_deps = {d["name"]: normalize(d) for d in node["deps"]}
            after_deps = {d["name"]: d for d in an[new_id]["deps"]}
            need(set(after_deps) - set(before_deps) <= {allowed}, "unreviewed new dependency edge")
            need(set(before_deps) <= set(after_deps), "dependency removed")
            for name, dep in before_deps.items():
                if name != allowed:
                    need(dep == after_deps[name], "unreviewed dependency kind change")
            need(allowed in after_deps and any(k["kind"] == "dev" for k in after_deps[allowed]["dep_kinds"]), "required dev edge absent")
    cores = [p for p in new.values() if p["name"] == "sqlx-core" and p["version"] == "0.9.0"]
    need(len(cores) == 1 and "_rt-tokio" in an[cores[0]["id"]]["features"], "actual core test runtime absent")
    sqlite = [p for p in new.values() if p["name"] == "libsqlite3-sys"]
    need(len(sqlite) == 1 and sqlite[0]["version"] == "0.37.0" and sqlite[0].get("links") == "sqlite3", "native SQLite link closure changed")
    return {"change": change, "id_remapping": remap, "unrelated_resolved_nodes_unchanged": True,
            "workspace_members": len(after["workspace_members"]), "nodes": len(an),
            "runtime_core": cores[0]["id"], "sqlite_native_package": sqlite[0]["id"]}


def _replace_ids(text, remap):
    for old, new in remap.items():
        text = text.replace(json.dumps(old), json.dumps(new))
    return text


def validate_cargo_lock(before, after, change):
    old, new = tomllib.loads(before.decode()), tomllib.loads(after.decode())
    key = lambda p: (p["name"], p["version"], p.get("source"))
    a, b = {key(p): p for p in old["package"]}, {key(p): p for p in new["package"]}
    affected = {"sqlx-sqlite"} if change == "driver" else {"codex-hepta-memory"}
    untouched_a = {k: v for k, v in a.items() if k[0] not in affected}
    untouched_b = {k: v for k, v in b.items() if k[0] not in affected}
    need(untouched_a == untouched_b, "unrelated Cargo lock changes require separate review")
    need({k: v for k, v in old.items() if k != "package"} == {k: v for k, v in new.items() if k != "package"}, "lock format/metadata changed")
    rows_a = [v for k, v in a.items() if k[0] in affected]
    rows_b = [v for k, v in b.items() if k[0] in affected]
    need(len(rows_a) == len(rows_b) == 1, "affected package cardinality changed")
    x, y = rows_a[0], rows_b[0]
    need(x["version"] == y["version"], "package upgrade was not authorized")
    if change == "driver":
        need(x.get("source") is not None and y.get("source") is None and y.get("checksum") is None,
             "driver did not become local")
        need(x.get("dependencies", []) == y.get("dependencies", []), "driver dependency list changed beyond the existing core edge")
    else:
        need({k: v for k, v in x.items() if k != "dependencies"} == {k: v for k, v in y.items() if k != "dependencies"}, "Memory identity changed")
        need(set(y.get("dependencies", [])) == set(x.get("dependencies", [])) | {"libsqlite3-sys"}, "unexpected Memory lock edge")
    return {"unrelated_packages_byte_structure_equal": True, "changed_package_before": x, "changed_package_after": y}


@contextmanager
def private_bazel(native, label):
    g = native.g
    directory = Path(g.b["bazel_cache_directory"]).resolve()
    need(not directory.is_relative_to(g.tree) and directory != native.target and not directory.is_symlink(), "bad private Bazel cache path")
    # The epoch's approved cache root must be new; subsequent operations in this
    # same runner reuse only this root. No deletion or shared cache rewriting.
    if not getattr(native, "bazel_cache_created", False):
        directory.mkdir(parents=True, exist_ok=False)
        native.bazel_cache_created = True
    p = g.tree / "user.bazelrc"
    need(not p.exists() and not p.is_symlink(), "existing user.bazelrc must be reviewed, never replaced")
    content = "".join(prefix + str(directory / name) + "\n" for name, prefix in [
        ("output-user-root", "startup --output_user_root="),
        ("repo-contents-cache", "common --repo_contents_cache="),
        ("repository-cache", "common --repository_cache="), ("disk-cache", "common --disk_cache=")])
    with p.open("xb") as f:
        f.write(content.encode())
    g.extra_untracked["user.bazelrc"] = record(p)
    g.save(label + "-private-bazel-config", {"text": content, "file": record(p), "no_existing_cache_removed": True})
    primary = None
    try:
        yield
    except BaseException as error:
        primary = error
        raise
    finally:
        cleanup_error = None
        try:
            r = native.command(label + "-owned-bazel-shutdown", ["bazel", "shutdown"], cwd=g.tree, separate=True)
            need(r["exit_code"] == 0, "owned Bazel shutdown failed")
        except BaseException as error:
            cleanup_error = error
        finally:
            need(same_record(p, g.extra_untracked["user.bazelrc"]), "temporary config drift; refusing deletion")
            p.unlink()
            del g.extra_untracked["user.bazelrc"]
            g.save(label + "-bazel-cleanup", {"cache_preserved": str(directory), "temporary_config_removed": True,
                        "primary_error": repr(primary) if primary is not None else None,
                        "cleanup_error": repr(cleanup_error) if cleanup_error is not None else None})
        if primary is None and cleanup_error is not None:
            raise cleanup_error


def lock_gate(native, operation):
    label, change, g = operation["id"], operation["change"], native.g
    before = (g.tree / "codex-rs/Cargo.lock").read_bytes()
    old_metadata = native.metadata
    actual_metadata = native.read_metadata(label + "-resolve", locked=False)
    lock_proof = validate_cargo_lock(before, (g.tree / "codex-rs/Cargo.lock").read_bytes(), change)
    graph_proof = validate_graph_change(old_metadata, actual_metadata, change, g.tree)
    native.expected_graph, native.metadata = graph(actual_metadata), actual_metadata
    native.g.save(label + "-resolution-proof", {"cargo_lock": lock_proof, "metadata_graph": graph_proof})
    with private_bazel(native, label):
        r = native.command(label + "-original-update", ["just", "bazel-lock-update"], cwd=g.tree,
                           separate=True, generated=("MODULE.bazel.lock",))
        need(r["exit_code"] == 0, "original Bazel lock generation failed")
        r = native.command(label + "-original-check", ["just", "bazel-lock-check"], cwd=g.tree, separate=True)
        need(r["exit_code"] == 0, "original Bazel lock check failed")
        r = native.command(label + "-dep-data-location", ["bazel", "query", "--output=location", "@crates//:data.bzl"], cwd=g.tree, separate=True)
        need(r["exit_code"] == 0, "actual generated DEP_DATA location is unavailable")
        matches = re.findall(r"(?m)^(.+?):[0-9]+(?::[0-9]+)?:", Path(r["stdout"]["path"]).read_text())
        need(len(matches) == 1, "DEP_DATA location must be unique")
        data_path = Path(matches[0]).resolve()
        need(data_path.is_relative_to(Path(g.b["bazel_cache_directory"]).resolve()), "DEP_DATA escaped the owned Bazel cache")
        raw = data_path.read_bytes()
        need(VENDOR.encode() in raw, "actual DEP_DATA omits adopted workspace package")
        copied = native.out / (label + "-actual-dep-data.bzl")
        with copied.open("xb") as f:
            f.write(raw)
        g.save(label + "-dep-data-identity", {"source": g.source, "generated_file": record(data_path),
                    "complete_copy": record(copied), "vendor_key": VENDOR,
                    "scope": "Exact generated bytes plus subsequent real macro loading/dependency graph; no guessed external repository path."})
        # Loading the actual macro dereferences DEP_DATA[native.package_name()]
        # and accesses its binaries field. Missing registration cannot pass query.
        r = native.command(label + "-generated-driver-rule", ["bazel", "query", "--output=build", TARGET], cwd=g.tree, separate=True)
        need(r["exit_code"] == 0 and "sqlx-sqlite-unit-tests" in Path(r["stdout"]["path"]).read_text(), "actual generated driver rule missing")
        r = native.command(label + "-generated-driver-deps", ["bazel", "query", "--output=label", "deps(" + TARGET + ")"], cwd=g.tree, separate=True)
        need(r["exit_code"] == 0, "actual generated dependency graph missing")
        text = Path(r["stdout"]["path"]).read_text()
        need("sqlx_core" in text or "sqlx-core" in text, "generated driver graph lacks sqlx-core")
        need("libsqlite3_sys" in text or "libsqlite3-sys" in text, "generated driver graph lacks native SQLite")
    native.read_metadata(label + "-post-lock")


def bazel_registration(native, operation):
    need(operation["target"] == TARGET, "unreviewed Bazel target")
    with private_bazel(native, operation["id"]):
        # Plain Bazel uses the checked-in host configuration, without inventing
        # credentials, remote endpoints, test filters or a hosted-CI qualification.
        r = native.command(operation["id"] + "-compile", ["bazel", "build", "--lockfile_mode=error", TARGET],
                           cwd=native.g.tree, separate=True)
        need(r["exit_code"] == 0, "new real Bazel test target did not compile")
        native.g.save(operation["id"] + "-qualification", {"source": native.g.source, "target": TARGET,
                    "actual_build_succeeded": True, "bazel_tests_executed": False,
                    "scope": "Actual generated macro/dependencies and compilation; original 12 cases run through just test in B14. Not hosted CI or platform-matrix acceptance."})
