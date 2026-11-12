"""Frozen optional-check offers and pre-choice consumption in original journals.

The host still owns every permission and terminal gate. These SQLite records
prove local ordering/consistency, not trusted clocks, random-source custody,
complete free observations, independent truth, execution or scientific benefit.
An offer propensity is not the propensity of actually purchasing the check.
"""

from contextlib import contextmanager
from dataclasses import asdict
import json
import secrets

from .contracts import _pairs, _require, _sha, _text, canonical_json, digest
from .prospective import MAX_ATTEMPTS, MAX_BODY, MAX_EVENTS
from .treatment import TreatmentJournal


def _original(connection, treatment):
    original = treatment._read(connection)
    roots, decisions = [digest(original[0])], {}
    for seq, body, sha in connection.execute(
        "SELECT seq, body, sha FROM treatment_events ORDER BY seq"
    ):
        event = json.loads(body, object_pairs_hook=_pairs)
        if event["kind"] == "choice":
            key = event["value"]["result"]["record_sha256"]
            decisions.setdefault(original[3]["choices"][key]["trajectory_id"], seq)
        elif event["kind"] == "disposition":
            decisions.setdefault(event["value"]["trajectory_id"], seq)
        roots.append(sha)
    return original, roots, decisions


def _anchor(context, trajectory, value):
    original, roots, decisions = context
    _, forecasts, finishes, shadow_roots = original[2]
    s, t = value["shadow_seq"], value["treatment_seq"]
    _require(
        type(s) is int
        and 0 <= s < len(shadow_roots)
        and type(t) is int
        and 0 <= t < len(roots)
        and shadow_roots[s] == value["shadow_sha256"]
        and roots[t] == value["treatment_sha256"]
        and finishes.get(trajectory, MAX_EVENTS + 1) > s
        and decisions.get(trajectory, MAX_EVENTS + 1) > t,
        "offer/consumption must precede the original choice and disposition",
    )
    current = [
        p for seq, p in forecasts if seq <= s and p.snapshot.trajectory_id == trajectory
    ]
    _require(bool(current), "original predecision prediction required")
    return current[-1].snapshot


def _position(original):
    return dict(
        shadow_seq=original[1][5],
        shadow_sha256=original[1][4],
        treatment_seq=original[5],
        treatment_sha256=original[4],
    )


def _plan(original, configuration):
    policies = configuration["policies"]
    _require(
        type(policies) is dict and 2 <= len(policies) <= 8,
        "two to eight policies required",
    )
    for name, sha in policies.items():
        _text(name, "policy")
        _require(len(name) <= 256 and name.isprintable(), "invalid policy identity")
        _sha(sha, "policy manifest")
    _require(
        len(set(policies.values())) == len(policies),
        "distinct policy identities required",
    )
    base = original[1][0]
    _require(digest(base) in policies.values(), "source policy is not frozen")
    frontier = configuration["frontier"]
    _require(
        type(frontier) is int and frontier in base["frontiers"], "unplanned frontier"
    )
    n, d = configuration["offer_numerator"], configuration["offer_denominator"]
    _require(
        type(n) is int and type(d) is int and 0 < n < d <= 2**32,
        "nondegenerate bounded integer offer probability required",
    )
    for key in (
        "free_view_schema_sha256",
        "mandatory_contract_sha256",
        "evaluation_spec_sha256",
    ):
        _sha(configuration[key], key)
    _text(configuration["checker_id"], "optional checker")
    checkers = {item["checker_id"]: item for item in original[0]["checkers"]}
    _require(configuration["checker_id"] in checkers, "unregistered optional checker")
    return dict(
        schema="hepta.verify.check-opportunities.v1",
        **configuration,
        shadow_manifest_sha256=digest(base),
        treatment_registry_sha256=digest(original[0]),
        roster=base["roster"],
        target=base["target"],
        checker_version_sha256=checkers[configuration["checker_id"]]["version_sha256"],
    )


CONFIGURATION = (
    "policies",
    "frontier",
    "checker_id",
    "offer_numerator",
    "offer_denominator",
    "free_view_schema_sha256",
    "mandatory_contract_sha256",
    "evaluation_spec_sha256",
)
POSITION = {"shadow_seq", "shadow_sha256", "treatment_seq", "treatment_sha256"}
PREDECISION = POSITION | {
    "trajectory_id",
    "source_group",
    "subject_sha256",
    "free_snapshot_sha256",
    "free_evidence_sha256",
    "eligible",
    "ineligible_reason",
    "eligibility_evidence_sha256",
}


def _predecision(manifest, context, value):
    snapshot = _anchor(context, value["trajectory_id"], value)
    _require(
        snapshot.observed_step == manifest["frontier"]
        and digest(asdict(snapshot)) == value["free_snapshot_sha256"]
        and snapshot.source_group == value["source_group"]
        and snapshot.subject_sha256 == value["subject_sha256"],
        "opportunity snapshot changed",
    )
    for key in ("free_evidence_sha256", "eligibility_evidence_sha256"):
        _sha(value[key], key)
    _require(type(value["eligible"]) is bool, "invalid eligibility")
    if value["eligible"]:
        _require(
            value["ineligible_reason"] is None,
            "eligible opportunity has no exclusion reason",
        )
    else:
        _text(value["ineligible_reason"], "ineligible reason")
        _require(len(value["ineligible_reason"]) <= 256, "ineligible reason too long")


def _checkpoint(root, attempts):
    return digest(dict(tickets_sha256=root, attempts_sha256=digest(attempts)))


def _policy(context, manifest):
    original = context[0]
    base = original[1][0]
    versions = {
        item["checker_id"]: item["version_sha256"] for item in original[0]["checkers"]
    }
    _require(
        digest(base) in manifest["policies"].values()
        and base["roster"] == manifest["roster"]
        and base["target"] == manifest["target"],
        "unfrozen policy or changed roster/target",
    )
    _require(
        versions.get(manifest["checker_id"]) == manifest["checker_version_sha256"],
        "policy optional checker version changed",
    )


class CheckOpportunityJournal:
    """One source TreatmentJournal; all policy consumers pin its original tickets."""

    def __init__(
        self, treatment, *, expected_manifest_sha256=None, expected_ledger_sha256=None
    ):
        _require(type(treatment) is TreatmentJournal, "exact TreatmentJournal required")
        self.treatment, self.manifest_sha256 = treatment, expected_manifest_sha256
        for sha in (expected_manifest_sha256, expected_ledger_sha256):
            if sha is not None:
                _sha(sha, "expected root")
        with treatment.shadow._transaction() as connection:
            manifest, _, root, _, attempts = self._read(connection)
        _require(
            expected_ledger_sha256 is None
            or _checkpoint(root, attempts) == expected_ledger_sha256,
            "opportunity ledger changed",
        )
        self.manifest_sha256 = digest(manifest)

    @classmethod
    def create(cls, treatment, **configuration):
        _require(
            type(treatment) is TreatmentJournal
            and set(configuration) == set(CONFIGURATION),
            "exact journal and complete opportunity configuration required",
        )
        with treatment.shadow._transaction() as connection:
            original = treatment._read(connection)
            _require(
                original[1][5] == original[5] == 0,
                "freeze opportunities before all observations",
            )
            manifest = _plan(original, configuration)
            body = canonical_json(manifest)
            _require(len(body.encode()) <= MAX_BODY, "opportunity manifest too large")
            connection.execute(
                "CREATE TABLE opportunity_frozen (body TEXT NOT NULL, sha TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE opportunity_attempts (trajectory TEXT PRIMARY KEY, body TEXT NOT NULL, sha TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE opportunity_tickets (seq INTEGER PRIMARY KEY, body TEXT NOT NULL, sha TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO opportunity_frozen VALUES (?, ?)", (body, digest(manifest))
            )
        return cls(treatment, expected_manifest_sha256=digest(manifest))

    def _read(self, connection):
        context = _original(connection, self.treatment)
        sizes = connection.execute(
            "SELECT length(CAST(body AS BLOB)) FROM opportunity_frozen LIMIT 2"
        ).fetchall()
        _require(
            len(sizes) == 1 and sizes[0][0] <= MAX_BODY,
            "invalid opportunity manifest size",
        )
        body, root = connection.execute(
            "SELECT body, sha FROM opportunity_frozen"
        ).fetchone()
        manifest = json.loads(body, object_pairs_hook=_pairs)
        _require(
            type(manifest) is dict and all(key in manifest for key in CONFIGURATION),
            "invalid manifest",
        )
        _require(
            manifest == _plan(context[0], {key: manifest[key] for key in CONFIGURATION})
            and digest(manifest) == root
            and (self.manifest_sha256 is None or self.manifest_sha256 == root),
            "frozen opportunity identity changed",
        )
        attempts = {}
        rows = connection.execute(
            "SELECT trajectory, length(CAST(body AS BLOB)) FROM opportunity_attempts LIMIT ?",
            (MAX_ATTEMPTS + 1,),
        ).fetchall()
        _require(
            len(rows) <= len(manifest["roster"]), "opportunity attempt roster exceeded"
        )
        for trajectory, size in rows:
            _require(size <= MAX_BODY, "opportunity intent too large")
            body, sha = connection.execute(
                "SELECT body, sha FROM opportunity_attempts WHERE trajectory=?",
                (trajectory,),
            ).fetchone()
            attempt = json.loads(body, object_pairs_hook=_pairs)
            _require(
                type(attempt) is dict
                and set(attempt) == PREDECISION
                and attempt["trajectory_id"] == trajectory
                and digest(attempt) == sha,
                "invalid opportunity intent",
            )
            _predecision(manifest, context, attempt)
            attempts[trajectory] = dict(attempt, intent_sha256=sha)
        rows = connection.execute(
            "SELECT seq, length(CAST(body AS BLOB)) FROM opportunity_tickets ORDER BY seq LIMIT ?",
            (MAX_ATTEMPTS + 1,),
        ).fetchall()
        _require(len(rows) <= len(manifest["roster"]), "opportunity roster exceeded")
        tickets = {}
        for expected, (seq, size) in enumerate(rows, 1):
            _require(
                seq == expected and size <= MAX_BODY, "invalid ticket sequence/size"
            )
            body, sha = connection.execute(
                "SELECT body, sha FROM opportunity_tickets WHERE seq=?", (seq,)
            ).fetchone()
            ticket = json.loads(body, object_pairs_hook=_pairs)
            _require(
                type(ticket) is dict
                and set(ticket)
                == PREDECISION
                | {
                    "draw",
                    "offered",
                    "offer_propensity",
                    "previous_sha256",
                    "intent_sha256",
                }
                and ticket["previous_sha256"] == root
                and digest(ticket) == sha,
                "invalid ticket identity",
            )
            trajectory = ticket["trajectory_id"]
            _require(trajectory not in tickets, "duplicate ticket")
            _require(
                trajectory in attempts
                and attempts[trajectory]
                == {key: ticket[key] for key in PREDECISION | {"intent_sha256"}},
                "ticket differs from durable draw intent",
            )
            _require(type(ticket["offered"]) is bool, "invalid offer")
            propensity = ticket["offer_propensity"]
            _require(
                type(propensity) is dict
                and set(propensity) == {"numerator", "denominator"}
                and all(type(value) is int for value in propensity.values()),
                "invalid offer propensity",
            )
            n, d, draw = (
                manifest["offer_numerator"],
                manifest["offer_denominator"],
                ticket["draw"],
            )
            if ticket["eligible"]:
                _require(
                    ticket["ineligible_reason"] is None
                    and type(draw) is int
                    and 0 <= draw < d
                    and ticket["offered"] is (draw < n)
                    and ticket["offer_propensity"]
                    == {"numerator": n, "denominator": d},
                    "invalid randomized offer",
                )
            else:
                _text(ticket["ineligible_reason"], "ineligible reason")
                _require(
                    len(ticket["ineligible_reason"]) <= 256
                    and draw is None
                    and not ticket["offered"]
                    and ticket["offer_propensity"]
                    == {"numerator": 0, "denominator": 1},
                    "ineligible offer",
                )
            tickets[trajectory] = dict(ticket, receipt_sha256=sha)
            root = sha
        return manifest, tickets, root, context, attempts

    def reserve(
        self,
        trajectory_id,
        free_evidence_sha256,
        *,
        eligible,
        eligibility_evidence_sha256,
        ineligible_reason=None,
    ):
        for key, sha in (
            ("free evidence", free_evidence_sha256),
            ("eligibility evidence", eligibility_evidence_sha256),
        ):
            _sha(sha, key)
        _require(type(eligible) is bool, "explicit eligibility required")
        if eligible:
            _require(
                ineligible_reason is None,
                "eligible opportunity has no exclusion reason",
            )
        else:
            _text(ineligible_reason, "ineligible reason")
            _require(len(ineligible_reason) <= 256, "ineligible reason too long")
        with self.treatment.shadow._transaction() as connection:
            manifest, _, _, context, attempts = self._read(connection)
            _require(
                trajectory_id not in attempts,
                "opportunity already attempted; never redraw a missing reply",
            )
            position = _position(context[0])
            snapshot = _anchor(context, trajectory_id, position)
            _require(
                snapshot.observed_step == manifest["frontier"],
                "freeze all free information at the planned frontier",
            )
            attempt = dict(
                trajectory_id=trajectory_id,
                source_group=snapshot.source_group,
                subject_sha256=snapshot.subject_sha256,
                free_snapshot_sha256=digest(asdict(snapshot)),
                free_evidence_sha256=free_evidence_sha256,
                eligible=eligible,
                ineligible_reason=ineligible_reason,
                eligibility_evidence_sha256=eligibility_evidence_sha256,
                **position,
            )
            body = canonical_json(attempt)
            _require(len(body.encode()) <= MAX_BODY, "opportunity intent too large")
            connection.execute(
                "INSERT INTO opportunity_attempts VALUES (?, ?, ?)",
                (trajectory_id, body, digest(attempt)),
            )
        # Commit the one-use intent before contacting the entropy source. An
        # interrupted second transaction remains pending and cannot draw again.
        with self.treatment.shadow._transaction() as connection:
            manifest, tickets, root, context, attempts = self._read(connection)
            _require(
                _position(context[0]) == position,
                "original journals changed after draw intent",
            )
            n, d = manifest["offer_numerator"], manifest["offer_denominator"]
            draw = secrets.randbelow(d) if eligible else None
            _require(
                not eligible or (type(draw) is int and 0 <= draw < d),
                "invalid entropy result",
            )
            ticket = dict(
                **attempts[trajectory_id],
                draw=draw,
                offered=eligible and draw < n,
                offer_propensity=dict(
                    numerator=n if eligible else 0, denominator=d if eligible else 1
                ),
                previous_sha256=root,
            )
            body, sha = canonical_json(ticket), digest(ticket)
            _require(len(body.encode()) <= MAX_BODY, "ticket too large")
            connection.execute(
                "INSERT INTO opportunity_tickets VALUES (?, ?, ?)",
                (len(tickets) + 1, body, sha),
            )
            ticket["receipt_sha256"] = sha
            self._bind(connection, context, manifest, ticket, free_evidence_sha256)
        return ticket

    @contextmanager
    def _locked(self, treatment):
        _require(type(treatment) is TreatmentJournal, "exact TreatmentJournal required")
        _require(
            treatment.shadow.path == self.treatment.shadow.path
            or not treatment.shadow.path.samefile(self.treatment.shadow.path),
            "different paths alias the same physical journal",
        )
        with self.treatment.shadow._transaction() as source:
            manifest, tickets, _, context, _ = self._read(source)
            if treatment.shadow.path == self.treatment.shadow.path:
                yield source, manifest, tickets, context
            else:
                with treatment.shadow._transaction() as target:
                    yield target, manifest, tickets, _original(target, treatment)

    def _bind(self, connection, context, manifest, ticket, free_evidence_sha256):
        _policy(context, manifest)
        position = _position(context[0])
        snapshot = _anchor(context, ticket["trajectory_id"], position)
        _require(
            digest(asdict(snapshot)) == ticket["free_snapshot_sha256"]
            and free_evidence_sha256 == ticket["free_evidence_sha256"],
            "policies must consume the identical free view",
        )
        body = dict(
            trajectory_id=ticket["trajectory_id"],
            manifest_sha256=digest(manifest),
            receipt_sha256=ticket["receipt_sha256"],
            free_snapshot_sha256=ticket["free_snapshot_sha256"],
            free_evidence_sha256=free_evidence_sha256,
            **position,
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS opportunity_bindings (trajectory TEXT PRIMARY KEY, body TEXT NOT NULL, sha TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO opportunity_bindings VALUES (?, ?, ?)",
            (ticket["trajectory_id"], canonical_json(body), digest(body)),
        )

    def bind_policy(self, treatment, trajectory_id, *, free_evidence_sha256):
        """Consume the original ticket after the forecast and before any choice.

        The source policy is bound atomically by reserve. Duplicate binding refuses;
        recovery reads the original record rather than treating a timeout as absence.
        """
        with self._locked(treatment) as (connection, manifest, tickets, context):
            _require(trajectory_id in tickets, "original opportunity ticket required")
            self._bind(
                connection,
                context,
                manifest,
                tickets[trajectory_id],
                free_evidence_sha256,
            )

    def _audit(self, connection, manifest, tickets, context):
        original = context[0]
        _policy(context, manifest)
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='opportunity_bindings'"
        ).fetchone()
        bindings = {}
        rows = (
            []
            if exists is None
            else connection.execute(
                "SELECT trajectory, length(CAST(body AS BLOB)) FROM opportunity_bindings LIMIT ?",
                (MAX_ATTEMPTS + 1,),
            ).fetchall()
        )
        _require(len(rows) <= len(manifest["roster"]), "consumption roster exceeded")
        for trajectory, size in rows:
            _require(
                size <= MAX_BODY and trajectory in tickets,
                "invalid consumption identity/size",
            )
            body, sha = connection.execute(
                "SELECT body, sha FROM opportunity_bindings WHERE trajectory=?",
                (trajectory,),
            ).fetchone()
            binding = json.loads(body, object_pairs_hook=_pairs)
            ticket = tickets[trajectory]
            _require(
                type(binding) is dict
                and set(binding)
                == POSITION
                | {
                    "trajectory_id",
                    "manifest_sha256",
                    "receipt_sha256",
                    "free_snapshot_sha256",
                    "free_evidence_sha256",
                }
                and digest(binding) == sha
                and binding["trajectory_id"] == trajectory
                and binding["manifest_sha256"] == digest(manifest)
                and all(
                    binding[key] == ticket[key]
                    for key in (
                        "receipt_sha256",
                        "free_snapshot_sha256",
                        "free_evidence_sha256",
                    )
                ),
                "changed opportunity consumption",
            )
            _require(
                digest(asdict(_anchor(context, trajectory, binding)))
                == ticket["free_snapshot_sha256"],
                "changed consumed snapshot",
            )
            bindings[trajectory] = binding
        for choice in original[3]["choices"].values():
            _require(
                choice["trajectory_id"] in bindings,
                "choice did not consume its original opportunity",
            )
        for start in original[3]["starts"].values():
            ticket = tickets.get(start["trajectory_id"])
            _require(
                ticket is not None
                and ticket["eligible"]
                and ticket["offered"]
                and start["snapshot_sha256"] == ticket["free_snapshot_sha256"]
                and start["checker_id"] == manifest["checker_id"],
                "unoffered or different optional check executed",
            )
        return bindings

    def audit_treatment(self, treatment):
        with self._locked(treatment) as (connection, manifest, tickets, context):
            bindings = self._audit(connection, manifest, tickets, context)
            return dict(
                consumed_trajectory_ids=sorted(bindings),
                bindings_sha256=digest([bindings[key] for key in sorted(bindings)]),
                missing_consumption_ids=sorted(
                    row["trajectory_id"]
                    for row in manifest["roster"]
                    if row["trajectory_id"] not in bindings
                ),
            )

    def start_optional(self, treatment, choice_sha256, operation_id):
        """Persist original start intent atomically; this never invokes the checker."""
        with self._locked(treatment) as (connection, manifest, tickets, context):
            self._audit(connection, manifest, tickets, context)
            original = context[0]
            choice = original[3]["choices"].get(choice_sha256)
            _require(choice is not None, "unrecorded choice")
            ticket = tickets[choice["trajectory_id"]]
            _require(
                ticket["offered"]
                and choice["snapshot_sha256"] == ticket["free_snapshot_sha256"]
                and choice["result"]["selection"] is not None
                and choice["result"]["selection"]["checker_id"]
                == manifest["checker_id"],
                "check opportunity unavailable",
            )
            _require(original[5] < MAX_EVENTS, "treatment event limit exceeded")
            event = dict(
                kind="start",
                value=dict(choice_sha256=choice_sha256, operation_id=operation_id),
                previous_sha256=original[4],
                shadow_seq=original[1][5],
                shadow_sha256=original[1][4],
            )
            treatment._apply(original[0], original[2], event, original[3])
            body = canonical_json(event)
            _require(len(body.encode()) <= MAX_BODY, "treatment event too large")
            connection.execute(
                "INSERT INTO treatment_events VALUES (?, ?, ?)",
                (original[5] + 1, body, digest(event)),
            )

    def report(self):
        with self.treatment.shadow._transaction() as connection:
            manifest, tickets, root, _, attempts = self._read(connection)
        return dict(
            manifest=manifest,
            manifest_sha256=digest(manifest),
            tickets=tickets,
            ledger_sha256=_checkpoint(root, attempts),
            pending_opportunity_ids=sorted(set(attempts) - set(tickets)),
            pending_draw_status="UNKNOWN",
            unstarted_opportunity_ids=sorted(
                row["trajectory_id"]
                for row in manifest["roster"]
                if row["trajectory_id"] not in attempts
            ),
            missing_opportunity_ids=sorted(
                row["trajectory_id"]
                for row in manifest["roster"]
                if row["trajectory_id"] not in tickets
            ),
            random_source_authenticated=False,
            independent_evaluation_established=False,
            wall_clock_prospectiveness_proved=False,
            full_physical_cost_complete=False,
            scientific_admission="HOLD",
            production_authority="NONE",
        )
