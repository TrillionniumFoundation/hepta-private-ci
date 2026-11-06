#!/usr/bin/env python3
"""Prepare C4 from the actual C3 tree and fixed, fully retrieved evidence.

Offline only.  No product execution, network, ref, PR or workflow operation is
performed.  All inputs are rehashed before and after the exclusive outputs.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
from urllib.parse import unquote, urlsplit


REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
PREFIX = "qualification/r3-audit-repair-20261104/continuation-20261105/"
BASE_COMMIT = "f7bb5019d311dacc142f20cacdcf19889109b4ba"
BASE_TREE = "d7716cca653bf7795307b052352e8671cd9fd944"
OLD_LATEST = "6cf9e7e4cad5c9c87277508f067280378b08511d"
LEDGER = "ea5ad333eacf2f49326a8f80a39e94ad771d818d"
COUNTS = {"CLOSED_SCOPED": 16, "OPEN": 6, "SCIENTIFIC_HOLD": 1}
CONTRACT_FIELDS = ("id", "name", "status", "closure_class", "original_exit_condition_zh")
DOCUMENT_NAMES = (
    "POST_AUDIT_EXECUTION_UPDATE_V3.zh-CN.md", "post-audit-execution-v3.json",
    "LATEST.md", "LATEST.zh-CN.md",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(body):
    return {
        "bytes": len(body),
        "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest(),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def fields(value):
    return {key: value[key] for key in ("bytes", "git_blob", "sha256")}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def safe_path(path, audit=False):
    require(isinstance(path, str) and path and "\\" not in path and "\0" not in path, "invalid path")
    require(not path.startswith("/") and not path.endswith("/"), "nonrelative path")
    require(all(part not in ("", ".", "..") for part in path.split("/")), "unsafe path")
    require(str(PurePosixPath(path)) == path, "noncanonical path")
    require(not audit or path.startswith(PREFIX), "product path in audit append")
    return path


def tree_row(row):
    item = {key: row[key] for key in ("path", "mode", "type", "sha")}
    safe_path(item["path"])
    require(re.fullmatch(r"[0-9a-f]{40}", item["sha"]) is not None, "invalid object id")
    require((item["type"], item["mode"]) in {
        ("tree", "040000"), ("blob", "100644"), ("blob", "100755"), ("blob", "120000")
    }, "unsupported tree entry")
    return item


def merkle(leaves):
    root = {}
    for path, row in sorted(leaves.items()):
        require(row["path"] == path and row["type"] != "tree", "nonleaf Merkle input")
        node = root
        parts = safe_path(path).split("/")
        for part in parts[:-1]:
            child = node.setdefault(part, {"children": {}})
            require("children" in child, "file/directory collision")
            node = child["children"]
        require(parts[-1] not in node, "duplicate tree leaf")
        node[parts[-1]] = {"leaf": row}
    directories = []

    def visit(node, prefix):
        buffer = bytearray()
        for name, child in sorted(node.items(), key=lambda pair: (
            pair[0] + ("/" if "children" in pair[1] else "")
        ).encode()):
            path = prefix + name
            if "children" in child:
                sha = visit(child["children"], path + "/")
                mode = "40000"
                directories.append({"path": path, "mode": "040000", "type": "tree", "sha": sha})
            else:
                mode, sha = child["leaf"]["mode"], child["leaf"]["sha"]
            buffer.extend(mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha))
        return hashlib.sha1(b"tree " + str(len(buffer)).encode() + b"\0" + buffer).hexdigest()

    sha = visit(root, "")
    return {"sha": sha, "truncated": False,
            "tree": sorted(list(leaves.values()) + directories, key=lambda row: row["path"])}


def original_content(raw):
    require(raw.get("isError") is False, "unsuccessful full GET")
    body = raw["structuredContent"]["content"]
    require(isinstance(body, str), "GET lacks complete UTF-8 string")
    return body.encode()


def restore_get(recipe, body, bound_blob=None):
    require(recipe.get("payload_git_blob", bound_blob) == identity(body)["git_blob"], "GET recipe source mismatch")
    marker = recipe["marker"]
    require(recipe["template"].count(marker) == recipe["occurrences"] > 0, "GET marker mismatch")
    raw = json.loads(recipe["template"].replace(marker, json.dumps(body.decode(), ensure_ascii=False)[1:-1]))
    require(original_content(raw) == body, "lossless GET payload mismatch")


class Builder:
    def __init__(self, root, config_path):
        self.root = root.resolve()
        self.config_path = config_path
        self.inputs = {}
        self.outputs = {}
        self.evidence = {}
        self.markdown = {}
        self.origins = []

    def read(self, name):
        safe_path(name)
        path = self.root / name
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(self.root), f"unsafe input: {name}")
        body = path.read_bytes()
        require(self.inputs.setdefault(name, identity(body)) == identity(body), f"input changed: {name}")
        return body

    def read_json(self, name, pin=None):
        body = self.read(name)
        require(pin is None or identity(body)["git_blob"] == pin, f"input pin differs: {name}")
        return json.loads(body), body

    def stage(self, name, body):
        require(name.startswith(("third-post-audit-documents/", "publication/third-post-audit-")), "output outside C4")
        require(name not in self.inputs, "attempt to replace frozen input")
        require(self.outputs.setdefault(name, body) == body, "conflicting output")

    def add(self, path, body, origin, role="actual_payload"):
        safe_path(path, audit=True)
        require(path not in self.evidence, f"duplicate evidence path: {path}")
        item = {"path": path, "mode": "100644", "type": "blob", **identity(body),
                "provenance": origin, "role": role,
                "qualification_scope": "actual object custody; no transfer of native acceptance"}
        self.evidence[path] = item
        if path.lower().endswith((".md", ".markdown")):
            self.markdown[path] = body
        return {"path": path, "mode": "100644", "type": "blob", "sha": item["git_blob"]}

    def import_component(self, component):
        directory = component["directory"]
        registry, body = self.read_json(directory + "/registry.actual.json", component["registry_blob"])
        require(registry["schema"] == component["schema"] and registry["repository"] == REPOSITORY, "registry identity differs")
        prefix = registry["prefix"]
        require(prefix == PREFIX + component["prefix"] and prefix.endswith("/"), "registry prefix differs")
        raw, _ = self.read_json(component["root_full_GET"])
        require(original_content(raw) == body, "root full registry GET differs")
        rows = registry[component["rows"]]
        require(len(rows) == component["payload_paths"], "registry count differs")
        adapter = component["adapter"]
        receipts = {}
        materialized_trees = {}
        if adapter == "materialized":
            for sha, name in component["materialized_trees"].items():
                raw_tree, _ = self.read_json(name)
                actual_tree = json.loads(original_content(raw_tree))
                require(actual_tree["sha"] == sha and actual_tree["truncated"] is False, "materialized complete tree differs")
                actual_leaves = {entry["path"]: tree_row(entry) for entry in actual_tree["tree"] if entry["type"] != "tree"}
                require(merkle(actual_leaves)["sha"] == sha, "materialized full-tree Merkle differs")
                materialized_trees[sha] = actual_leaves
            materialization_creates = {}
            for name in component["receipt_collections"]:
                collection, _ = self.read_json(directory + "/" + name)
                sha = collection["materialization_tree"]
                require(sha in materialized_trees, "unverified materialization tree")
                if "materialization_create_tool_return" in collection:
                    create = collection["materialization_create_tool_return"]
                    require(create.get("isError") is False and create["structuredContent"]["sha"] == sha, "materialization create differs")
                    materialization_creates[sha] = create
                for record in collection["records"]:
                    require(record["path"] not in receipts, "duplicate materialized receipt")
                    receipts[record["path"]] = {"record": record, "tree": sha}
            sidecar, _ = self.read_json(directory + "/" + component["receipt_sidecar"])
            create = sidecar["materialization_create_tool_return"]
            require(create.get("isError") is False, "receipt materialization failed")
            sha = create["structuredContent"]["sha"]
            require(sha in materialized_trees, "unverified receipt materialization tree")
            materialization_creates[sha] = create
            for record in sidecar["records"]:
                require(record["path"] not in receipts, "duplicate receipt-of-receipt")
                receipts[record["path"]] = {"record": record, "tree": sha}
            require(set(materialization_creates) == set(materialized_trees), "missing original tree creation receipt")
        if adapter in ("fmt", "ci"):
            for name in component["receipt_collections"]:
                collection, _ = self.read_json(directory + "/" + name)
                for record in collection["records"]:
                    require(record["path"] not in receipts, "duplicate receipt selector")
                    receipts[record["path"]] = record
        if adapter == "batch_tree":
            for name in component["receipt_batches"]:
                batch, _ = self.read_json(directory + "/" + name)
                require(batch["create"].get("isError") is False, "batch tree creation failed")
                actual_tree = json.loads(original_content(batch["tree_full_get"]))
                require(actual_tree["truncated"] is False and actual_tree["sha"] == batch["create"]["structuredContent"]["sha"], "batch tree readback differs")
                actual_leaves = {entry["path"]: tree_row(entry) for entry in actual_tree["tree"] if entry["type"] != "tree"}
                for record in batch["full_gets"]:
                    suffix = record["source_file"]
                    require(suffix not in receipts, "duplicate batch GET selector")
                    require(actual_leaves[prefix + suffix]["sha"] == record["sha"], "batch actual leaf differs from GET")
                    receipts[suffix] = {"record": record, "tree": actual_tree["sha"]}
        entries = {}
        for row in rows:
            path = row.get("repo_path", row.get("repository_path", row["path"] if "path" in row else None))
            require(path.startswith(prefix), "evidence escaped declared prefix")
            suffix = path.removeprefix(prefix)
            payload = self.read(directory + "/" + suffix)
            require(identity(payload) == fields(row), f"local bytes differ: {path}")
            if adapter in ("standard", "standard_recipe"):
                require(row["actual_full_GET_complete_UTF8_equal"] is True, "incomplete standard GET")
                if adapter == "standard":
                    require(fields(row["full_blob_get_identity"]) == identity(payload), "standard GET digest differs")
                require(row["actual_create_original"].get("isError") is False, "standard create failed")
                restore_get(row["full_GET_original_lossless_recipe"], payload)
            elif adapter == "b11":
                require(row["actual_blob_full_GET_equal"] is True and row["actual_full_GET_requested_blob"] == row["git_blob"], "B11 GET differs")
                receipt, _ = self.read_json(directory + "/" + row["actual_receipt_local_file"])
                require(receipt["create"].get("isError") is False, "B11 create failed")
                matches = [record for record in receipt["gets"] if record["relative_path"] == suffix]
                require(len(matches) == 1 and matches[0]["git_blob"] == row["git_blob"], "B11 GET selector differs")
                require(original_content(matches[0]["raw"]) == payload, "B11 original GET bytes differ")
            elif adapter in ("fmt", "ci"):
                actual_key = "actual_full_GET_content_bytes_equal" if adapter == "fmt" else "full_utf8_bytes_equal"
                create_key = "actual_create_blob_sha" if adapter == "fmt" else "actual_create_sha"
                require(row[actual_key] is True and row[create_key] == row["git_blob"], "file registry actual identity differs")
                if suffix in receipts:
                    receipt = receipts[suffix]
                else:
                    require(suffix in component["receipt_self_files"], "missing complete receipt")
                    receipt, _ = self.read_json(directory + "/" + component["receipt_self_files"][suffix])
                if "reused_record_git_blob" in receipt:
                    require(adapter == "fmt" and receipt["reused_record_git_blob"] == row["git_blob"], "invalid format receipt alias")
                    candidates = [record for record in receipts.values() if record.get("git_blob") == row["git_blob"] and "create_blob" in record]
                    require(len(candidates) == 1 and fields(candidates[0]) == fields(row), "reused object has no unique full original receipt")
                    receipt = candidates[0]
                require(receipt["create_blob"].get("isError") is False, "blob creation failed")
                require(receipt["create_blob"]["structuredContent"]["sha"] == row["git_blob"], "created blob differs")
                require(original_content(receipt["full_GET"]) == payload, "full original file GET differs")
            elif adapter == "batch_tree":
                require(row["actual_tree_leaf_verified"] is True and row["actual_full_get"] is True and row["full_utf8_bytes_equal"] is True, "batch payload lacks complete verification")
                receipt = receipts[suffix]
                require(receipt["tree"] == row["actual_create_tree"] and receipt["record"]["sha"] == row["git_blob"], "batch creation identity differs")
                require(original_content(receipt["record"]["raw"]) == payload, "batch full GET bytes differ")
            elif adapter == "materialized":
                require(row["full_GET_complete_UTF8_bytes_equal"] is True, "materialized payload lacks complete GET")
                receipt = receipts[path]
                record = receipt["record"]
                require(receipt["tree"] == row["actual_materialization_tree"], "materialized row tree differs")
                require(materialized_trees[receipt["tree"]][path] == {"path": path, "mode": row["mode"], "type": row["type"], "sha": row["git_blob"]}, "materialized path leaf differs")
                require(record["complete_decoded_UTF8_equal"] is True and fields(record.get("expected", record)) == identity(payload), "materialized receipt identity differs")
                require(original_content(record["full_GET"]) == payload, "materialized original full GET bytes differ")
            else:
                raise ValueError("unreviewed registry adapter")
            entries[path] = self.add(path, payload, component["name"])
        registry_path = prefix + "registry.actual.json"
        entries[registry_path] = self.add(registry_path, body, component["name"], "actual_registry")
        if component.get("self_file"):
            self_body = self.read(directory + "/" + component["self_file"])
            require(identity(self_body)["git_blob"] == component["self_blob"], "registry self pin differs")
            self_raw, _ = self.read_json(component["self_root_full_GET"])
            require(original_content(self_raw) == self_body, "root self full GET differs")
            self_receipt = json.loads(self_body)
            registry_identity = self_receipt.get("registry_identity", self_receipt.get("registry"))
            registry_location = self_receipt.get("registry_path", self_receipt.get("registry_repo_path", self_receipt.get("registry_repository_path")))
            require(fields(registry_identity) == identity(body) and registry_location == registry_path, "self receipt binds another registry")
            if "full_GET_original_lossless_recipe" in self_receipt:
                restore_get(self_receipt["full_GET_original_lossless_recipe"], body, registry_identity["git_blob"])
            elif adapter == "batch_tree":
                require(self_receipt["actual_create_tree"].get("isError") is False and self_receipt["full_UTF8_equal"] is True, "batch self creation or GET failed")
                require(original_content(self_receipt["actual_full_GET"]) == body, "batch self registry GET differs")
            else:
                require(adapter == "b11" and original_content(self_receipt["registry_complete_GET"]) == body, "self receipt lacks complete registry GET")
            self_path = prefix + component["self_file"]
            entries[self_path] = self.add(self_path, self_body, component["name"], "actual_registry_self_receipt")
        listed, _ = self.read_json(directory + "/" + component["elements_file"])
        normalized = [tree_row(row) for row in listed]
        require(len(normalized) == len(entries) and {row["path"]: row for row in normalized} == entries, "tree list differs from registry payloads and self")
        self.origins.append({"name": component["name"], "schema": registry["schema"],
                             "prefix": prefix, "registry": identity(body), "paths": len(entries),
                             "source_input": directory + "/registry.actual.json"})

    def check_links(self, final, history_context):
        known = {row["path"] for row in final["tree"]}
        checked = []
        external = 0
        for path, body in sorted(self.markdown.items()):
            text = re.sub(r"(?ms)^\s*(```|~~~).*?^\s*\1[^\n]*$", "", body.decode())
            text = re.sub(r"(`+).*?\1", "", text, flags=re.S)
            hrefs = [match.group(1).strip() for match in re.finditer(r"!?\[[^\]]*\]\(([^)]+)\)", text)]
            hrefs += [match.group(1).strip() for match in re.finditer(r"(?m)^ {0,3}\[[^\]]+\]:\s*(<[^>]+>|\S+)", text)]
            for raw in hrefs:
                href = raw[1:raw.find(">")] if raw.startswith("<") else raw.split(maxsplit=1)[0]
                parsed = urlsplit(href)
                if parsed.scheme or parsed.netloc:
                    external += 1
                    continue
                if not parsed.path:
                    continue
                context = history_context.get(path, path)
                decoded = unquote(parsed.path)
                require(not decoded.startswith("/") and "\\" not in decoded and "\0" not in decoded, "unsafe relative link")
                target = posixpath.normpath(posixpath.join(posixpath.dirname(context), decoded))
                safe_path(target)
                require(target in known, f"broken relative link: {path} {href} -> {target}")
                checked.append({"document": path, "href": href, "target": target, "resolution_context": context})
        return {"markdown_documents": len(self.markdown), "relative_links": checked,
                "external_links_not_network_revalidated": external,
                "fragments_not_revalidated": True, "historical_links_checked_in_original_location": True}

    def prepare(self):
        config, _ = self.read_json(self.config_path)
        require(config["parent_commit"] == BASE_COMMIT and config["base_tree"] == BASE_TREE, "config baseline differs")
        self.read("prepare_third_post_audit_delta.py")
        base, base_body = self.read_json("publication/second-post-audit-final-full-tree.json", "fb19703fc3531a8c2261b47d1ec446c1a03fb0d1")
        require(base["sha"] == BASE_TREE and base["truncated"] is False, "wrong complete C3 tree")
        rows = [tree_row(row) for row in base["tree"]]
        require(len(rows) == len({row["path"] for row in rows}), "duplicate C3 path")
        leaves = {row["path"]: row for row in rows if row["type"] != "tree"}
        require(len(leaves) == 15232, "C3 leaf denominator differs")
        rebuilt = merkle(leaves)
        require(rebuilt["sha"] == BASE_TREE and rebuilt["tree"] == sorted(rows, key=lambda row: row["path"]), "C3 Merkle differs")
        ledger, ledger_body = self.read_json("documents/continuation-blocker-progress-v8.json", LEDGER)
        require(leaves[PREFIX + "continuation-blocker-progress-v8.json"]["sha"] == LEDGER, "old ledger leaf differs")
        contracts = [{key: row[key] for key in CONTRACT_FIELDS} for row in ledger["items"]]
        require([row["id"] for row in contracts] == [f"B{index:02}" for index in range(1, 24)], "original IDs differ")
        require(dict(Counter(row["closure_class"] for row in contracts)) == COUNTS, "original closure classes differ")
        machine, _ = self.read_json("third-post-audit-documents/post-audit-execution-v3.json", config["document_blobs"]["post-audit-execution-v3.json"])
        require(machine["original_blocker_contracts"] == contracts, "literal exit conditions changed")
        require(machine["counts"] == COUNTS and machine["closure_transitions_in_this_increment"] == [], "unsupported closure transition")
        require(machine["all_blockers_closed"] is False and machine["whole_candidate_qualified"] is False, "unsupported qualification")
        require(machine["fixed_predecessor_commit"] == BASE_COMMIT and machine["fixed_predecessor_tree"] == BASE_TREE, "machine predecessor differs")
        require(fields(machine["original_ledger"]) == identity(ledger_body), "machine original ledger identity differs")
        require(machine["evidence_index"] == "evidence-index-v13-addendum.json", "machine index differs")
        for component in config["components"]:
            self.import_component(component)
        require(not (set(leaves) & set(self.evidence)), "evidence overwrites old C3 path")
        merged = dict(leaves)
        for item in self.evidence.values():
            merged[item["path"]] = {"path": item["path"], "mode": item["mode"], "type": item["type"], "sha": item["git_blob"]}
        materialize = []
        authored = []
        for name in DOCUMENT_NAMES:
            local = "third-post-audit-documents/" + name
            body = self.read(local)
            require(identity(body)["git_blob"] == config["document_blobs"][name], "authored document changed")
            path = PREFIX + name
            merged[path] = {"path": path, "mode": "100644", "type": "blob", "sha": identity(body)["git_blob"]}
            item = {"repo_path": path, "local_path": str(self.root / local), **identity(body)}
            authored.append(item)
            materialize.append(item)
            if name.endswith(".md"):
                self.markdown[path] = body
        for auxiliary in config.get("auxiliary_sources", []):
            path = safe_path(auxiliary["repo_path"], audit=True)
            require(path.startswith(PREFIX + "reviews/post-audit-execution-v3-preparation-20261106/"), "auxiliary source outside preparation directory")
            require(path not in merged, "auxiliary source overwrites existing path")
            body = self.read(auxiliary["local_path"])
            require(identity(body)["git_blob"] == auxiliary["git_blob"], "auxiliary source changed")
            merged[path] = {"path": path, "mode": "100644", "type": "blob", "sha": identity(body)["git_blob"]}
            item = {"repo_path": path, "local_path": str(self.root / auxiliary["local_path"]), **identity(body)}
            authored.append(item)
            materialize.append(item)
        report_body = self.read("third-post-audit-documents/POST_AUDIT_EXECUTION_UPDATE_V3.zh-CN.md")
        require(fields(machine["report"]) == identity(report_body), "machine report digest differs")
        history_context = {}
        histories = []
        for name in ("LATEST.md", "LATEST.zh-CN.md"):
            path = PREFIX + name
            require(leaves[path]["sha"] == OLD_LATEST, "old pointer differs")
            body = self.read("second-post-audit-documents/" + name)
            require(identity(body)["git_blob"] == OLD_LATEST, "old pointer bytes differ")
            archive_path = PREFIX + "history/c3-f7bb5019-" + name
            require(archive_path not in merged, "history path reused")
            merged[archive_path] = {"path": archive_path, "mode": "100644", "type": "blob", "sha": OLD_LATEST}
            self.markdown[archive_path] = body
            history_context[archive_path] = path
            histories.append({"path": archive_path, "original_path": path, **identity(body)})
        index = {
            "schema": "hepta-registered-evidence-v13-addendum", "fixed_parent_commit": BASE_COMMIT,
            "fixed_parent_tree": BASE_TREE, "predecessor_addendum": {"path": "evidence-index-v12-addendum.json", "git_blob": leaves[PREFIX + "evidence-index-v12-addendum.json"]["sha"]},
            "predecessor_indexes_and_original_ledger_unchanged": True,
            "paths": len(self.evidence), "unique_blobs": len({row["git_blob"] for row in self.evidence.values()}),
            "registry_sources": self.origins, "items": sorted(self.evidence.values(), key=lambda row: row["path"]),
            "history_aliases_of_actual_C3_blobs": histories,
            "fixed_new_documents_separate_from_already_actual_evidence": authored,
            "index_self_identity_omitted_to_avoid_self_reference": True,
            "blocker_counts_unchanged": COUNTS, "closure_transitions": [],
            "all_blockers_closed": False, "whole_candidate_qualified": False,
            "qualification_limits": config["qualification_limits"],
        }
        index_body = encoded(index)
        index_local = "third-post-audit-documents/evidence-index-v13-addendum.json"
        self.stage(index_local, index_body)
        index_path = PREFIX + "evidence-index-v13-addendum.json"
        require(index_path not in merged, "V13 path already exists")
        merged[index_path] = {"path": index_path, "mode": "100644", "type": "blob", "sha": identity(index_body)["git_blob"]}
        materialize.append({"repo_path": index_path, "local_path": str(self.root / index_local), **identity(index_body)})
        allowed = {PREFIX + "LATEST.md", PREFIX + "LATEST.zh-CN.md"}
        changed = {path for path in leaves if merged[path] != leaves[path]}
        require(changed == allowed and all(merged[path] == row for path, row in leaves.items() if path not in allowed), "old C3 leaf changed")
        final = merkle(merged)
        links = self.check_links(final, history_context)
        delta = [row for path, row in sorted(merged.items()) if leaves.get(path) != row]
        require(len(merged) == len(leaves) + len(self.evidence) + 5 + len(config.get("auxiliary_sources", [])), "new leaf denominator differs")
        plan = {
            "parent_commit": BASE_COMMIT, "base_tree": BASE_TREE, "expected_tree": final["sha"],
            "tree_elements": delta, "content_to_materialize": materialize,
            "evidence_paths_added": len(self.evidence), "actual_evidence_unique_blobs": index["unique_blobs"],
            "new_leaf_paths": len(merged) - len(leaves), "changed_old_leaf_paths": 2,
            "delta_paths": len(delta), "old_leaves_retained": len(leaves) - 2,
            "only_old_paths_updated": sorted(allowed), "historical_pointers_bytes_preserved": True,
            "history_aliases": histories, "old_full_tree_file_unchanged": identity(base_body),
            "original_blocker_contract_verification": {"original_ledger": identity(ledger_body), "contracts_compared": 23, "fields_compared": list(CONTRACT_FIELDS), "literal_field_differences": [], "counts": COUNTS, "closure_transitions": []},
            "relative_links": links["relative_links"], "link_validation_scope": {key: value for key, value in links.items() if key != "relative_links"},
            "actual_registry_sources": self.origins, "no_product_source_paths_imported": True,
            "native_CI_ref_or_PR_operations_performed_by_this_script": False,
        }
        self.stage("publication/third-post-audit-delta.plan.json", encoded(plan))
        self.stage("publication/third-post-audit-final-full-tree.json", encoded(final))
        verification = {
            "schema": "hepta-C4-delta-local-preservation-verification-v1", "decision": "PREPARED_OFFLINE_NOT_PUBLISHED",
            "parent_commit": BASE_COMMIT, "base_tree": BASE_TREE, "expected_tree": final["sha"],
            "base_leaves": len(leaves), "old_leaves_retained": len(leaves) - 2, "final_leaves": len(merged),
            "new_leaf_paths": len(merged) - len(leaves), "delta_paths": len(delta),
            "actual_evidence_paths": len(self.evidence), "actual_evidence_unique_blobs": index["unique_blobs"],
            "group_paths": dict(sorted(Counter(row["provenance"] for row in self.evidence.values()).items())),
            "index": identity(index_body), "contract_check": plan["original_blocker_contract_verification"],
            "link_check": plan["link_validation_scope"], "all_frozen_inputs_rehashed_before_and_after": True,
            "input_file_identities": [{"path": path, **value} for path, value in sorted(self.inputs.items())],
            "outputs_except_this_summary": [{"path": path, **identity(body)} for path, body in sorted(self.outputs.items())],
            "native_CI_ref_or_PR_operations": [],
        }
        self.stage("publication/third-post-audit-delta.verification.json", encoded(verification))
        return verification

    def write_outputs(self):
        def verify_inputs():
            for name, expected in self.inputs.items():
                path = self.root / name
                require(path.is_file() and not path.is_symlink() and identity(path.read_bytes()) == expected, f"frozen input changed: {name}")
        verify_inputs()
        for name, body in self.outputs.items():
            path = self.root / name
            require(not path.is_symlink() and (not path.exists() or path.read_bytes() == body), f"different existing output: {name}")
        for name, body in self.outputs.items():
            path = self.root / name
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(body)
            require(path.read_bytes() == body, "written output differs")
        verify_inputs()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--config", default="third-post-audit-inputs/components.json")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    require(args.execute, "review source and frozen inputs, then pass --execute")
    builder = Builder(args.root, args.config)
    verification = builder.prepare()
    builder.write_outputs()
    print(json.dumps({key: value for key, value in verification.items() if key not in ("input_file_identities", "outputs_except_this_summary")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
