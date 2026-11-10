"""Evidence for one predeclared repair per task; no executor, signer or adoption.

Owner and label verifiers must use independently retained original evidence.
Hashes, issuer names and this journal do not establish independent custody.
"""

from contextlib import nullcontext
from dataclasses import asdict
import json

from .contracts import _pairs, _require, _sha, _text, canonical_json, digest
from .cost_ledger import CostItem, summarize_costs
from .prospective import MAX_ATTESTATION, MAX_BODY, ShadowJournal


def _authenticate(verifier, manifest, claim, attestation):
    _require(
        callable(verifier)
        and type(attestation) is str
        and 0 < len(attestation.encode("utf-8")) <= MAX_ATTESTATION,
        "bounded original attestation and verifier required",
    )
    original = canonical_json([manifest, claim])
    supplied_manifest, supplied_claim = json.loads(original)
    _require(
        verifier(supplied_manifest, supplied_claim, attestation) is True
        and canonical_json([supplied_manifest, supplied_claim]) == original,
        "original evidence authentication failed or changed its claim",
    )


def _manifest(parent, child, study_id, owner_id, owner_version_sha256, cost_roster):
    for value in (study_id, owner_id):
        _text(value, "repair identity")
        _require(len(value) <= 256, "repair identity too long")
    _sha(owner_version_sha256, "owner version")
    summarize_costs(cost_roster, [])
    parents = {row["trajectory_id"]: row for row in parent["roster"]}
    children = {row["trajectory_id"]: row for row in child["roster"]}
    _require(
        0 < len(parents) <= 128 and set(parents) == set(children),
        "bounded matched repair roster required",
    )
    _require(
        all(
            parents[key]["source_group"] == children[key]["source_group"]
            and parents[key]["subject_sha256"] != children[key]["subject_sha256"]
            for key in parents
        ),
        "repair needs distinct subjects in the same source group",
    )
    _require(
        parent["target"] != child["target"]
        and all(
            parent["target"][key] == child["target"][key] for key in ("domain", "event")
        ),
        "separate repair target for the same goal required",
    )
    _require(
        owner_id not in (parent["evaluator_id"], child["evaluator_id"]),
        "repair owner cannot also be the label evaluator",
    )
    return dict(
        schema="hepta.verify.repair-lineage.v1",
        study_id=study_id,
        owner_id=owner_id,
        owner_version_sha256=owner_version_sha256,
        parent=parent,
        child=child,
        cost_roster=[asdict(row) for row in cost_roster],
    )


class RepairLineage:
    """Companion ledger on the parent, joining a separately frozen child target.

    Retain both external roots. Preparing/recording an intent never dispatches;
    an unresolved original operation stays pending even after process recovery.
    """

    def __init__(
        self, parent, child, *, expected_manifest_sha256, expected_ledger_sha256=None
    ):
        _require(
            type(parent) is ShadowJournal
            and type(child) is ShadowJournal
            and not parent.path.samefile(child.path),
            "distinct exact parent/child journals required",
        )
        _sha(expected_manifest_sha256, "repair manifest")
        if expected_ledger_sha256 is not None:
            _sha(expected_ledger_sha256, "repair ledger")
        self.parent, self.child = parent, child
        self.manifest_sha256 = expected_manifest_sha256
        with parent._transaction() as db:
            root = self._read(db)[-1]
        _require(
            expected_ledger_sha256 is None or root == expected_ledger_sha256,
            "repair ledger differs from external checkpoint",
        )

    @classmethod
    def create(
        cls, parent, child, *, study_id, owner_id, owner_version_sha256, cost_roster
    ):
        _require(
            type(parent) is ShadowJournal
            and type(child) is ShadowJournal
            and not parent.path.samefile(child.path),
            "distinct exact parent/child journals required",
        )
        with parent._transaction() as db, child._transaction() as child_db:
            p, *_ = parent._read(db)
            c, *_, child_count = child._read(child_db)
            _require(child_count == 0, "freeze child roster before child execution")
            manifest = _manifest(
                p, c, study_id, owner_id, owner_version_sha256, cost_roster
            )
            body = canonical_json(manifest)
            _require(len(body) <= MAX_BODY, "repair manifest too large")
            db.execute(
                "CREATE TABLE repair_frozen (body TEXT NOT NULL, sha TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE repair_events (seq INTEGER PRIMARY KEY, body TEXT NOT NULL, sha TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO repair_frozen VALUES (?, ?)", (body, digest(manifest))
            )
            db.commit()  # Keep the child writer lock until the parent freeze is durable.
        return cls(parent, child, expected_manifest_sha256=digest(manifest))

    def _read(self, db, *, child_db=None):
        parent = self.parent._read(db)
        with (
            self.child._transaction() if child_db is None else nullcontext(child_db)
        ) as child_connection:
            child = self.child._read(child_connection)
            child_events = [
                (seq, json.loads(body, object_pairs_hook=_pairs), sha)
                for seq, body, sha in child_connection.execute(
                    "SELECT seq,body,sha FROM events ORDER BY seq"
                )
            ]
        rows = db.execute("SELECT body,sha FROM repair_frozen LIMIT 2").fetchall()
        _require(
            len(rows) == 1 and len(rows[0][0]) <= MAX_BODY, "invalid repair manifest"
        )
        manifest = json.loads(rows[0][0], object_pairs_hook=_pairs)
        _require(
            type(manifest) is dict
            and set(manifest)
            == {
                "schema",
                "study_id",
                "owner_id",
                "owner_version_sha256",
                "parent",
                "child",
                "cost_roster",
            },
            "invalid repair manifest fields",
        )
        _require(
            type(manifest["cost_roster"]) is list
            and 0 < len(manifest["cost_roster"]) <= 10000,
            "invalid frozen repair cost roster",
        )
        expected = _manifest(
            parent[0],
            child[0],
            manifest["study_id"],
            manifest["owner_id"],
            manifest["owner_version_sha256"],
            [CostItem(**row) for row in manifest["cost_roster"]],
        )
        _require(
            digest(manifest) == rows[0][1] == self.manifest_sha256
            and manifest == expected,
            "repair source manifest changed",
        )
        parent_roots = {digest(parent[0])} | {
            row[0] for row in db.execute("SELECT sha FROM events")
        }
        child_roots = [digest(child[0])] + [row[2] for row in child_events]
        first_child_event = {}
        for seq, event, _ in child_events:
            value = event["value"]
            if event["kind"] == "prediction":
                value = value["snapshot"]
            elif event["kind"] == "label_attested":
                value = value["label"]
            first_child_event.setdefault(value["trajectory_id"], seq)
        state = {row["trajectory_id"]: {} for row in parent[0]["roster"]}
        root, events, operations = digest(manifest), [], set()
        raw = db.execute(
            "SELECT seq,body,sha FROM repair_events ORDER BY seq LIMIT 257"
        ).fetchall()
        _require(len(raw) <= 2 * len(state), "repair event bound exceeded")
        for expected, (seq, body, sha) in enumerate(raw, 1):
            _require(
                seq == expected and len(body) <= MAX_BODY,
                "invalid repair event sequence/size",
            )
            event = json.loads(body, object_pairs_hook=_pairs)
            _require(
                set(event) == {"claim", "attestation", "previous_sha256"}
                and event["previous_sha256"] == root
                and digest(event) == sha,
                "repair event digest mismatch",
            )
            self._apply(
                event, state, operations, parent_roots, child_roots, first_child_event
            )
            root = sha
            events.append(event)
        return manifest, parent, child, state, events, root

    @staticmethod
    def _apply(event, state, operations, parent_roots, child_roots, first_child_event):
        claim = event["claim"]
        _require(
            type(claim) is dict and claim.get("attempt_id") in state, "unplanned repair"
        )
        entry = state[claim["attempt_id"]]
        if claim.get("status") in ("no_repair", "abstained"):
            _require(
                set(claim) == {"attempt_id", "status", "reason"}
                and not entry
                and event["attestation"] is None,
                "duplicate/invalid repair disposition",
            )
            _text(claim["reason"], "repair disposition reason")
            entry["skip"] = claim
            return
        _require(
            set(claim)
            == {
                "attempt_id",
                "status",
                "operation_id",
                "intent_sha256",
                "choice_sha256",
                "readback_sha256",
                "parent_root",
                "child_root",
            },
            "invalid repair claim fields",
        )
        _require(
            type(event["attestation"]) is str
            and 0 < len(event["attestation"].encode("utf-8")) <= MAX_ATTESTATION,
            "missing original repair attestation",
        )
        _require(
            claim["parent_root"] in parent_roots and claim["child_root"] in child_roots,
            "repair source ledger anchor missing",
        )
        _text(claim["operation_id"], "original operation")
        _require(len(claim["operation_id"]) <= 256, "operation identity too long")
        _sha(claim["choice_sha256"], "original choice")
        if claim["status"] == "pending":
            _require(
                not entry
                and claim["operation_id"] not in operations
                and claim["intent_sha256"] is None
                and claim["readback_sha256"] is None
                and child_roots.index(claim["child_root"])
                < first_child_event.get(claim["attempt_id"], 10001),
                "duplicate operation or intent after child execution",
            )
            entry["intent"] = claim
            operations.add(claim["operation_id"])
        else:
            _require(
                claim["status"] in ("completed", "failed")
                and "intent" in entry
                and "completion" not in entry,
                "unstarted or repeated repair completion",
            )
            intent = entry["intent"]
            _require(
                claim["operation_id"] == intent["operation_id"]
                and claim["choice_sha256"] == intent["choice_sha256"]
                and claim["intent_sha256"] == digest(intent),
                "wrong original repair operation",
            )
            _sha(claim["readback_sha256"], "original destination readback")
            entry["completion"] = claim

    def prepare(self, attempt_id, operation_id, choice_sha256):
        with self.parent._transaction() as db:
            _, parent, child, state, events, _ = self._read(db)
        claim = dict(
            attempt_id=attempt_id,
            status="pending",
            operation_id=operation_id,
            intent_sha256=None,
            choice_sha256=choice_sha256,
            readback_sha256=None,
            parent_root=parent[4],
            child_root=child[4],
        )
        _require(
            attempt_id in state
            and not state[attempt_id]
            and operation_id not in {e["claim"].get("operation_id") for e in events},
            "attempt/operation already recorded; reconcile original intent",
        )
        return claim

    def completion(self, attempt_id, status, readback_sha256):
        with self.parent._transaction() as db:
            _, parent, child, state, _, _ = self._read(db)
        _require(
            attempt_id in state
            and "intent" in state[attempt_id]
            and "completion" not in state[attempt_id]
            and status in ("completed", "failed"),
            "original pending repair required",
        )
        intent = state[attempt_id]["intent"]
        return dict(
            intent,
            status=status,
            intent_sha256=digest(intent),
            readback_sha256=readback_sha256,
            parent_root=parent[4],
            child_root=child[4],
        )

    def record(self, claim, *, attestation=None, authenticate=None):
        frozen_claim = json.loads(canonical_json(claim))
        with self.parent._transaction() as db:
            manifest, *_, root = self._read(db)
        if frozen_claim.get("status") not in ("no_repair", "abstained"):
            _authenticate(authenticate, manifest, frozen_claim, attestation)
        with self.parent._transaction() as db, self.child._transaction() as child_db:
            _, parent, child, _, events, current = self._read(db, child_db=child_db)
            _require(current == root, "repair ledger changed during authentication")
            if frozen_claim.get("status") not in ("no_repair", "abstained"):
                _require(
                    (frozen_claim["parent_root"], frozen_claim["child_root"])
                    == (parent[4], child[4]),
                    "stale repair source ledger",
                )
            event = dict(
                claim=frozen_claim, attestation=attestation, previous_sha256=root
            )
            body = canonical_json(event)
            _require(len(body) <= MAX_BODY, "repair receipt too large")
            db.execute(
                "INSERT INTO repair_events VALUES (?, ?, ?)",
                (len(events) + 1, body, digest(event)),
            )
            self._read(db, child_db=child_db)
            # Nested context managers release the child first. Commit the parent
            # explicitly while both locks still protect the validated ordering.
            db.commit()

    def report(
        self,
        *,
        authenticate_owner=None,
        authenticate_labels=None,
        cost_receipts=(),
        cost_rates=None,
        cost_attestation=None,
        authenticate_cost=None,
    ):
        with self.parent._transaction() as db:
            manifest, parent, child, state, events, root = self._read(db)
        if authenticate_owner is not None:
            for event in events:
                if event["claim"]["status"] not in ("no_repair", "abstained"):
                    _authenticate(
                        authenticate_owner,
                        manifest,
                        event["claim"],
                        event["attestation"],
                    )
        for journal, snapshot in ((self.parent, parent), (self.child, child)):
            journal.authentication_report(
                authenticate=authenticate_labels, expected_ledger_sha256=snapshot[4]
            )
        statuses = {
            key: (
                entry.get("skip")
                or entry.get("completion")
                or entry.get("intent")
                or {"status": "unrecorded"}
            )["status"]
            for key, entry in state.items()
        }
        terminal = [
            key for key, status in statuses.items() if status in ("completed", "failed")
        ]
        paired = [
            key
            for key in terminal
            if key in parent[3]
            and key in child[3]
            and parent[3][key].error is not None
            and child[3][key].error is not None
        ]
        authenticated = (
            authenticate_owner is not None and authenticate_labels is not None
        )
        costs = summarize_costs(
            [CostItem(**row) for row in manifest["cost_roster"]],
            cost_receipts,
            cost_rates,
        )
        cost_claim = dict(
            schema="hepta.verify.repair-cost-claim.v1",
            repair_root=root,
            parent_root=parent[4],
            child_root=child[4],
            roster_sha256=costs["roster_sha256"],
            receipts_sha256=costs["receipts_sha256"],
            full_physical_and_history_coverage=True,
        )
        cost_complete = False
        if authenticate_cost is not None:
            _authenticate(authenticate_cost, manifest, cost_claim, cost_attestation)
            cost_complete = (
                costs["declared_roster_complete"]
                and not costs["measurement_gaps"]
                and all(value is not None for value in costs["totals"].values())
            )
        with self.parent._transaction() as db:
            _, latest_parent, latest_child, _, _, latest = self._read(db)
        _require(
            (latest, latest_parent[4], latest_child[4]) == (root, parent[4], child[4]),
            "repair or source ledger changed during reporting",
        )
        return dict(
            schema="hepta.verify.repair-report.v1",
            manifest_sha256=self.manifest_sha256,
            ledger_sha256=root,
            parent_ledger_sha256=parent[4],
            child_ledger_sha256=child[4],
            planned_attempts=len(state),
            attempts=statuses,
            disposition_counts={
                status: list(statuses.values()).count(status)
                for status in (
                    "unrecorded",
                    "no_repair",
                    "abstained",
                    "pending",
                    "failed",
                    "completed",
                )
            },
            terminal_repairs_without_both_known_labels=len(terminal) - len(paired),
            authenticated_label_pairs=len(paired) if authenticated else 0,
            observed_error_corrections=sum(
                parent[3][key].error and not child[3][key].error for key in paired
            )
            if authenticated and paired
            else None,
            observed_errors_induced=sum(
                not parent[3][key].error and child[3][key].error for key in paired
            )
            if authenticated and paired
            else None,
            costs=costs,
            full_physical_cost_complete=cost_complete,
            independent_custody_established=False,
            causal_repair_benefit_established=False,
            scientific_admission="HOLD",
            production_authority="NONE",
        )
