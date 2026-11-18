"""Reconcile retained development attempts with their durable event history.

This checks the existing journal without repairing it or refunding work. A
consistently replaced older database still needs an external freshness anchor;
neither a plan digest nor this replay authenticates that missing history.
"""

from collections import Counter
import json


def validate_trial_history(db, plan):
    """Reject lost, conflicting or reordered charges before another dispatch."""
    for table, columns in {
        "plan": [("body", "TEXT", 1, None, 0)],
        "attempts": [
            ("id", "TEXT", 0, None, 1),
            ("state", "TEXT", 1, None, 0),
            ("receipt", "TEXT", 0, None, 0),
        ],
        "events": [
            ("seq", "INTEGER", 0, None, 1),
            ("id", "TEXT", 1, None, 0),
            ("kind", "TEXT", 1, None, 0),
            ("detail", "TEXT", 1, None, 0),
        ],
    }.items():
        if [r[1:] for r in db.execute("PRAGMA table_info(" + table + ")")] != columns:
            raise ValueError("trial store schema is incomplete or changed: " + table)

    schedule = {a["attempt_id"]: a for a in plan["schedule"]}
    orders = {arm: [] for arm in plan["arms"]}
    for item in plan["schedule"]:
        orders[item["arm"]].append(item["attempt_id"])
    charges, counts = {}, Counter()

    def rejection(attempt_id):
        item = schedule.get(attempt_id)
        if item is None:
            return "unscheduled attempt"
        if attempt_id in charges:
            return "attempt already consumed; pending work must not be retried"
        used = counts[item["arm"]]
        if used >= plan["attempt_limit_per_arm"]:
            return "arm opportunity budget exhausted"
        if attempt_id != orders[item["arm"]][used]:
            return "attempt is outside the frozen arm order"
        return None

    for expected_seq, (seq, attempt_id, kind, raw) in enumerate(
        db.execute("SELECT seq,id,kind,detail FROM events ORDER BY seq"), start=1
    ):
        if seq != expected_seq:
            raise ValueError("trial event history has a sequence gap")
        try:
            detail = json.loads(raw)
            canonical = json.dumps(
                detail, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError) as error:
            raise ValueError("trial event detail is not canonical JSON") from error
        if raw != canonical:
            raise ValueError("trial event detail is not canonical JSON")
        if kind == "charged":
            if rejection(attempt_id) is not None or detail != schedule[attempt_id]:
                raise ValueError("trial charge conflicts with frozen order or budget")
            charges[attempt_id] = ("pending", None)
            counts[detail["arm"]] += 1
        elif kind == "rejected":
            reason = rejection(attempt_id)
            if reason is None or detail != {"reason": reason}:
                raise ValueError("trial rejection conflicts with retained history")
        elif kind == "terminal":
            if charges.get(attempt_id) != ("pending", None):
                raise ValueError("trial terminal has no unique pending charge")
            charges[attempt_id] = ("terminal", raw)
        elif kind == "settle_rejected":
            if charges.get(attempt_id) == ("pending", None):
                raise ValueError("trial settlement rejection conflicts with history")
        else:
            raise ValueError("trial event kind is unknown")
    rows = db.execute("SELECT id,state,receipt FROM attempts").fetchall()
    observed = {name: (state, receipt) for name, state, receipt in rows}
    if len(observed) != len(rows) or observed != charges:
        raise ValueError("trial attempts differ from retained charge/terminal history")
