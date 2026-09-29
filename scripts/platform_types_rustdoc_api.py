#!/usr/bin/env python3
"""Normalize rustdoc JSON and fail closed on real public API removals or mutations."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


class RustdocApiError(RuntimeError):
    """The rustdoc public API snapshot or comparison is invalid."""


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RustdocApiError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise RustdocApiError(f"JSON object required: {path}")
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


class _Normalizer:
    """Turn unstable rustdoc item IDs into path/structural references.

    Rustdoc serializes `Id` as a JSON number while object-map keys are strings.
    Treating every integer as an item ID is unsafe because rustdoc also contains
    ordinary numeric values. IDs are therefore resolved only in schema fields
    that carry `Id` or `Vec<Id>` values. `Visibility::Restricted.parent` is a
    single `Id`; struct/enum child rosters and tuple-variant payloads are
    `Vec<Id>`. Leaving any of them raw makes unchanged APIs drift when unrelated
    items are added and rustdoc renumbers its internal index.

    Public paths are compared independently. Parent items intentionally do not
    recursively absorb implementation blocks, module/trait item rosters, or the
    complete signature of a separately public referenced type: doing so would
    turn an additive method or unrelated impl change into a cascade of false
    breaking changes. Fields and variants are owned semantic children of their
    enclosing type, so their signatures remain embedded even when rustdoc does
    not assign them an independent public path.
    """

    ID_SINGLE_KEYS = frozenset({"id", "parent"})
    ID_LIST_KEYS = frozenset({"fields", "variants", "tuple"})
    ITEM_IGNORED_KEYS = frozenset(
        {"id", "crate_id", "span", "docs", "links", "deprecation"}
    )
    NESTED_IGNORED_KEYS = frozenset(
        {
            "crate_id",
            "span",
            "docs",
            "links",
            "deprecation",
            "foreign_impls",
            "implementations",
            "impls",
            "items",
        }
    )

    def __init__(self, document: dict[str, Any]) -> None:
        index = document.get("index")
        paths = document.get("paths")
        root = str(document.get("root"))
        if not isinstance(index, dict) or not isinstance(paths, dict) or root not in index:
            raise RustdocApiError("rustdoc JSON is missing root/index/paths")
        self.document = document
        self.index: dict[str, Any] = {str(key): value for key, value in index.items()}
        self.paths: dict[str, Any] = {str(key): value for key, value in paths.items()}
        root_item = self.index[root]
        if not isinstance(root_item, dict) or not isinstance(root_item.get("crate_id"), int):
            raise RustdocApiError("rustdoc root has no crate_id")
        self.crate_id = root_item["crate_id"]
        self.all_paths: dict[str, str] = {}
        self.public_paths: dict[str, str] = {}
        for raw_item_id, row in self.paths.items():
            if not isinstance(row, dict):
                continue
            path = row.get("path")
            if not (
                isinstance(path, list)
                and path
                and all(isinstance(part, str) for part in path)
            ):
                continue
            item_id = str(raw_item_id)
            rendered = "::".join(path)
            self.all_paths[item_id] = rendered
            if row.get("crate_id") == self.crate_id and len(path) > 1:
                # The crate root is intentionally omitted. Additive exports are
                # represented as new paths, not mutations of every ancestor.
                self.public_paths[item_id] = rendered
        self.memo: dict[str, Any] = {}
        self.visiting: set[str] = set()

    def _label(self, item_id: str) -> str:
        public = self.all_paths.get(item_id)
        if public is not None:
            return public
        item = self.index.get(item_id)
        if not isinstance(item, dict):
            return f"unresolved-item:{item_id}"
        inner = item.get("inner")
        kind = next(iter(inner), "unknown") if isinstance(inner, dict) else "unknown"
        name = item.get("name")
        return f"private:{kind}:{name or '<anonymous>'}"

    def _reference(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            return self.normalize(value)
        # A separately referenced type is identified by its stable path. That
        # item is fingerprinted independently, so an additive impl does not
        # mutate every function or field that merely names the type.
        return {"item": self._label(str(value))}

    def _owned_reference(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            return self.normalize(value)
        item_id = str(value)
        return {
            "item": self._label(item_id),
            "signature": self.item_signature(item_id),
        }

    def item_signature(self, item_id: str) -> Any:
        if item_id in self.memo:
            return self.memo[item_id]
        if item_id in self.visiting:
            return {"cycle": self._label(item_id)}
        item = self.index.get(item_id)
        if not isinstance(item, dict):
            return {"missing": item_id}
        self.visiting.add(item_id)
        cleaned = {
            key: self.normalize(value, key=key)
            for key, value in item.items()
            if key not in self.ITEM_IGNORED_KEYS
        }
        self.visiting.remove(item_id)
        self.memo[item_id] = cleaned
        return cleaned

    def normalize(self, value: Any, *, key: str | None = None) -> Any:
        if key in self.ID_SINGLE_KEYS:
            return self._reference(value)
        if key in self.ID_LIST_KEYS and isinstance(value, list):
            return [self._owned_reference(item) for item in value]
        if isinstance(value, list):
            return [self.normalize(item) for item in value]
        if isinstance(value, dict):
            return {
                str(child_key): self.normalize(item, key=str(child_key))
                for child_key, item in sorted(
                    value.items(), key=lambda pair: str(pair[0])
                )
                if child_key not in self.NESTED_IGNORED_KEYS
            }
        return value

    def snapshot(self) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for item_id, path in sorted(self.public_paths.items(), key=lambda row: row[1]):
            path_row = self.paths[item_id]
            kind = path_row.get("kind") if isinstance(path_row, dict) else None
            signature = self.item_signature(item_id)
            items.append(
                {
                    "path": path,
                    "kind": kind,
                    "fingerprintSha256": hashlib.sha256(_canonical(signature)).hexdigest(),
                }
            )
        if not items:
            raise RustdocApiError("rustdoc JSON exposed no public paths")
        return {
            "schema": "hepta.platform-types.rustdoc-public-api.v2",
            "schemaVersion": 2,
            "rustdocFormatVersion": self.document.get("format_version"),
            "crateVersion": self.document.get("crate_version"),
            "itemCount": len(items),
            "items": items,
            "snapshotSha256": hashlib.sha256(_canonical(items)).hexdigest(),
        }


def snapshot(rustdoc_json: Path) -> dict[str, Any]:
    return _Normalizer(_read_object(rustdoc_json)).snapshot()


def diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    for name, value in (("old", old), ("new", new)):
        if value.get("schema") != "hepta.platform-types.rustdoc-public-api.v2":
            raise RustdocApiError(f"{name} snapshot schema mismatch")
        if value.get("schemaVersion") != 2 or not isinstance(value.get("items"), list):
            raise RustdocApiError(f"{name} snapshot items missing")
    old_by_path = {item["path"]: item for item in old["items"]}
    new_by_path = {item["path"]: item for item in new["items"]}
    removed = sorted(set(old_by_path) - set(new_by_path))
    added = sorted(set(new_by_path) - set(old_by_path))
    changed = []
    for path in sorted(set(old_by_path) & set(new_by_path)):
        before = old_by_path[path]
        after = new_by_path[path]
        if (
            before.get("kind") != after.get("kind")
            or before.get("fingerprintSha256") != after.get("fingerprintSha256")
        ):
            changed.append(
                {
                    "path": path,
                    "oldKind": before.get("kind"),
                    "newKind": after.get("kind"),
                    "oldFingerprintSha256": before.get("fingerprintSha256"),
                    "newFingerprintSha256": after.get("fingerprintSha256"),
                }
            )
    breaking = bool(removed or changed)
    return {
        "schema": "hepta.platform-types.rustdoc-semver-diff.v2",
        "schemaVersion": 2,
        "policy": "fail_closed_on_removed_or_semver_significant_signature_changes",
        "oldSnapshotSha256": old.get("snapshotSha256"),
        "newSnapshotSha256": new.get("snapshotSha256"),
        "oldItemCount": old.get("itemCount"),
        "newItemCount": new.get("itemCount"),
        "removed": removed,
        "changed": changed,
        "added": added,
        "breaking": breaking,
        "status": "failed" if breaking else "passed",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--rustdoc-json", type=Path, required=True)
    snapshot_parser.add_argument("--output", type=Path, required=True)
    diff_parser = subparsers.add_parser("diff")
    diff_parser.add_argument("--old", type=Path, required=True)
    diff_parser.add_argument("--new", type=Path, required=True)
    diff_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "snapshot":
            value = snapshot(args.rustdoc_json)
            _write(args.output, value)
            print(f"rustdoc public API snapshot: {value['itemCount']} items")
            return 0
        old = _read_object(args.old)
        new = _read_object(args.new)
        value = diff(old, new)
        _write(args.output, value)
        print(
            "rustdoc public API diff: "
            f"removed={len(value['removed'])} changed={len(value['changed'])} "
            f"added={len(value['added'])}"
        )
        return 1 if value["breaking"] else 0
    except RustdocApiError as error:
        print(f"platform.types rustdoc API failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
