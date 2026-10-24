"""Stage real ParametricOwner versions outside the atomic population pointer.

Every version has its own owner database. A staged replacement cannot overwrite
the owner read by the live topology. The owner generation and stable cell ID are
preserved through a SQLite backup and real owner CAS. This is local research
authority, not a native HNMF or independent-trainer attestation.
"""

from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sqlite3
import sys

from evolution_common import digest, file_digest, read_json, require, retain


class ActualOwners:
    """Only this bridge imports the existing tensor-validating parameter owner."""

    def __init__(self, scripts):
        scripts = Path(scripts).resolve()
        for name in ("memory_cell", "memory_cell_service"):
            sys.path.insert(0, str(scripts / name))
        from parametric_owner import Frontier, ParametricOwner
        from service_types import verify_snapshot

        require(
            Path(sys.modules["parametric_owner"].__file__).resolve().parent
            == scripts / "memory_cell",
            "unexpected parameter owner import",
        )
        self.Owner, self.Frontier, self.verify_snapshot = (
            ParametricOwner,
            Frontier,
            verify_snapshot,
        )

    def provider(self, current):
        return lambda: self.Frontier(
            current["scope"], current["epoch"], tuple(current["revoked"])
        )

    def stage(self, candidate, frontier, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        source = Path(candidate["directory"]).resolve()
        require(
            not Path(candidate["directory"]).is_symlink(), "candidate directory symlink"
        )
        require(
            file_digest(source / "lineage.json") == candidate["manifest_sha256"],
            "candidate manifest digest",
        )
        lineage = read_json(source / "lineage.json")
        require(
            set(candidate["support_roots"])
            <= set(lineage["roots"])
            <= set(frontier["roots"]),
            "checkpoint ancestry/support closure",
        )
        parents = candidate["parents"]
        if candidate["derivation"] == "inherit":
            inherited = set().union(*(set(p["roots"]) for p in parents))
            require(
                parents and inherited <= set(lineage["roots"]),
                "inherited checkpoint dropped ancestor roots",
            )
            require(
                lineage["training"].get("learned_parent_manifest_sha256")
                in [p["manifest_sha256"] for p in parents],
                "learned parent receipt mismatch",
            )
        elif candidate["derivation"] == "clean_replay":
            training = lineage["training"]
            require(
                training.get("initialization") == "frozen_base"
                and training.get("inherited_roots") == []
                and training.get("learned_parent_manifest_sha256") is None,
                "clean replay initialization not measured",
            )
            require(
                set(lineage["roots"])
                == set(candidate["support_roots"])
                == set(training.get("source_digests", [])),
                "clean replay source closure",
            )
        elif candidate["derivation"] == "reuse":
            allowed = [p["manifest_sha256"] for p in parents]
            previous = candidate["previous"]
            if previous:
                allowed.append(previous["manifest_sha256"])
            require(
                candidate.get("rollback_pinned_manifest")
                == candidate["manifest_sha256"]
                or candidate["manifest_sha256"] in allowed,
                "reuse requires a retained checkpoint identity",
            )
        checkpoint = directory / "checkpoint"
        if not checkpoint.exists():
            checkpoint.mkdir()
        for name in (
            "adapter_model.safetensors",
            "adapter_config.json",
            "lineage.json",
        ):
            origin, target = source / name, checkpoint / name
            require(
                not origin.is_symlink() and origin.is_file(),
                "regular checkpoint file required",
            )
            if target.exists():
                require(
                    file_digest(target) == file_digest(origin),
                    "staged checkpoint changed",
                )
            else:
                with origin.open("rb") as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
                    dst.flush()
                    import os

                    os.fsync(dst.fileno())
        owner_path = directory / "parameters.sqlite"
        previous = candidate["previous"]
        if previous and not owner_path.exists():
            old = sqlite3.connect(
                Path(previous["owner_database"]).resolve().as_uri() + "?mode=ro",
                uri=True,
            )
            new = sqlite3.connect(owner_path)
            try:
                old.backup(new)
            finally:
                new.close()
                old.close()
        owner = self.Owner(owner_path)
        current = owner.current(candidate["cell_id"], frontier["scope"])
        expected = previous["manifest_sha256"] if previous else None
        if (
            current
            and current.generation == candidate["version"]
            and current.manifest_sha256 == candidate["manifest_sha256"]
        ):
            active = owner.invoke(
                candidate["cell_id"],
                frontier["scope"],
                self.provider(frontier),
                lambda cell: cell,
            )
        else:
            active = owner.activate(
                candidate["cell_id"],
                checkpoint,
                candidate["manifest_sha256"],
                scope=frontier["scope"],
                expected_current=expected,
                generation=candidate["version"],
                provider=self.provider(frontier),
                allowed_roots=frontier["roots"],
                parent_manifest_sha256=expected,
            )
        require(
            active.directory == str(checkpoint.absolute())
            and active.generation == candidate["version"],
            "owner staged version identity",
        )
        if previous:
            require(
                active.base_identity == previous["base_identity"],
                "stable cell base changed",
            )
        return dict(
            cell_id=candidate["cell_id"],
            role=candidate["role"],
            version=candidate["version"],
            directory=str(checkpoint.resolve()),
            manifest_sha256=active.manifest_sha256,
            roots=list(active.roots),
            support_roots=candidate["support_roots"],
            base_identity=active.base_identity,
            owner_database=str(owner_path.resolve()),
            source_epoch=frontier["epoch"],
            parents=parents,
            derivation=candidate["derivation"],
            owner_active=asdict(active),
        )

    def verify(self, version, frontier):
        require(
            set(version["roots"]) <= set(frontier["roots"]),
            "version source ancestry no longer current",
        )
        owner = self.Owner(version["owner_database"])
        active = owner.invoke(
            version["cell_id"],
            frontier["scope"],
            self.provider(frontier),
            lambda cell: cell,
        )
        actual = asdict(active)
        actual["roots"] = list(actual["roots"])
        expected = dict(version["owner_active"])
        expected["roots"] = list(expected["roots"])
        require(actual == expected, "owner differs from topology-bound version")
        return active

    def invoke(self, version, current_provider, callback, query_roots):
        owner = self.Owner(version["owner_database"])

        def provider():
            view = current_provider()
            require(
                set(version["roots"]) <= set(view["roots"]),
                "source ancestry no longer authorized",
            )
            return self.Frontier(view["scope"], view["epoch"], tuple(view["revoked"]))

        def selected(active):
            require(
                active.manifest_sha256 == version["manifest_sha256"]
                and active.generation == version["version"],
                "topology/owner version changed",
            )
            return callback(active)

        return owner.invoke(
            version["cell_id"],
            version["owner_active"]["scope"],
            provider,
            selected,
            query_roots=query_roots,
        )
