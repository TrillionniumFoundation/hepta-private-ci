"""Persistent research-budget reservations; equal ceilings do not imply equal use.

Host-owned meters supply actual resource deltas. Unsettled effects retain their
reservation after a crash. An overrun is recorded and permanently closes the arm.
"""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time


METERS = (
    "wall_ns",
    "cpu_ns",
    "decoder_updates",
    "router_updates",
    "gradient_probes",
    "train_tokens",
    "decoder_queries",
    "feature_forwards",
    "input_tokens",
    "output_tokens",
    "read_bytes",
    "write_bytes",
    "tx_bytes",
    "rx_bytes",
    "storage_byte_ns",
)
GAUGES = ("retained_bytes", "private_bytes", "peak_rss_bytes")
PHASES = {
    "train",
    "feature",
    "index",
    "source",
    "base",
    "infer",
    "recover",
    "transport",
}


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def quantities(values, keys=METERS, complete=False):
    if type(values) is not dict or not set(values) <= set(keys):
        raise ValueError("unregistered resource dimension")
    if complete and set(values) != set(keys):
        raise ValueError("every hard resource ceiling must be explicit")
    if any(type(v) is not int or not 0 <= v < 2**127 for v in values.values()):
        raise ValueError("bounded nonnegative integer resources required")
    return {key: values.get(key, 0) for key in keys}


class BudgetExceeded(ValueError):
    pass


class BudgetLedger:
    """One arm, one frozen budget; SQLite serializes concurrent reservations."""

    def __init__(
        self, path, *, arm, protocol_sha256, limits, gauges, prices, cost_limit
    ):
        if not arm or len(protocol_sha256) != 64:
            raise ValueError("arm and frozen protocol identity required")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        config = dict(
            arm=arm,
            protocol_sha256=protocol_sha256,
            limits=quantities(limits, complete=True),
            gauges=quantities(gauges, GAUGES, complete=True),
            prices=quantities(prices, complete=True),
            cost_limit=cost_limit,
        )
        if type(cost_limit) is not int or cost_limit <= 0:
            raise ValueError("positive integer normalized cost ceiling required")
        with self._transaction() as db:
            for table, columns in (
                ("settings", "id INTEGER PRIMARY KEY, body TEXT"),
                ("events", "event TEXT PRIMARY KEY, body TEXT"),
                ("snapshots", "id INTEGER PRIMARY KEY, body TEXT"),
            ):
                db.execute(f"CREATE TABLE IF NOT EXISTS {table} ({columns})")
            old = db.execute("SELECT body FROM settings WHERE id=1").fetchone()
            if old and json.loads(old[0]) != config:
                raise ValueError(
                    "cannot reopen a budget with different identity or ceilings"
                )
            db.execute(
                "INSERT OR IGNORE INTO settings VALUES (1, ?)",
                (canonical(config).decode(),),
            )
            db.execute(
                "INSERT OR IGNORE INTO snapshots VALUES (1, ?)",
                (
                    canonical(
                        dict(gauges=quantities({}, GAUGES), evidence=None)
                    ).decode(),
                ),
            )
        self.config = config

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            if db.in_transaction:
                db.commit()
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def _events(self, db):
        return [
            json.loads(row[0])
            for row in db.execute("SELECT body FROM events ORDER BY event")
        ]

    def _state(self, db):
        events = self._events(db)
        used, pending = quantities({}), quantities({})
        executed, allocated, uncertain = quantities({}), quantities({}), quantities({})
        for event in events:
            destination = pending if event["state"] == "reserved" else used
            values = (
                event["reserved"]
                if event["state"] in ("reserved", "lost")
                else event["actual"]
            )
            for key in METERS:
                destination[key] += values[key]
                if event["state"] != "reserved":
                    origin = (
                        uncertain
                        if event["state"] == "lost"
                        else (
                            allocated
                            if event.get("cost_origin") == "allocated_shared"
                            else executed
                        )
                    )
                    origin[key] += values[key]
        cost = lambda values: sum(values[k] * self.config["prices"][k] for k in METERS)
        return dict(
            used=used,
            pending=pending,
            used_cost=cost(used),
            pending_cost=cost(pending),
            closed=any(x["state"] in ("overrun", "lost") for x in events),
            executed_used=executed,
            allocated_dependency_used=allocated,
            uncertain_work_charged=uncertain,
            measured_plus_allocated_plus_uncertain_equals_used=True,
            events=events,
            inventory=json.loads(
                db.execute("SELECT body FROM snapshots WHERE id=1").fetchone()[0]
            ),
        )

    def reserve(
        self,
        event_id,
        phase,
        upper_bound,
        *,
        request_sha256,
        cost_origin="executed",
        shared_receipt_sha256=None,
    ):
        if phase not in PHASES or not event_id or len(request_sha256) != 64:
            raise ValueError(
                "registered event, phase and exact request digest required"
            )
        reserved = quantities(upper_bound)
        if cost_origin not in ("executed", "allocated_shared"):
            raise ValueError(
                "physical execution and shared allocation must remain distinct"
            )
        if (
            cost_origin == "allocated_shared"
            and (
                type(shared_receipt_sha256) is not str
                or len(shared_receipt_sha256) != 64
            )
        ) or (cost_origin == "executed" and shared_receipt_sha256 is not None):
            raise ValueError(
                "only shared allocations bind an original shared-work receipt"
            )
        requested = dict(
            event=event_id,
            phase=phase,
            reserved=reserved,
            request_sha256=request_sha256,
            cost_origin=cost_origin,
            shared_receipt_sha256=shared_receipt_sha256,
        )
        with self._transaction() as db:
            existing = db.execute(
                "SELECT body FROM events WHERE event=?", (event_id,)
            ).fetchone()
            if existing:
                row = json.loads(existing[0])
                if any(row[k] != v for k, v in requested.items()):
                    raise ValueError("event replay changed its request or reservation")
                return row
            state = self._state(db)
            if state["closed"]:
                raise BudgetExceeded("arm closed after lost work or measured overrun")
            totals = {
                k: state["used"][k] + state["pending"][k] + reserved[k] for k in METERS
            }
            cost = sum(totals[k] * self.config["prices"][k] for k in METERS)
            if (
                any(totals[k] > self.config["limits"][k] for k in METERS)
                or cost > self.config["cost_limit"]
            ):
                raise BudgetExceeded(
                    "common cumulative ceiling exhausted before effect"
                )
            row = dict(requested, state="reserved", reserved_at_ns=time.time_ns())
            db.execute(
                "INSERT INTO events VALUES (?, ?)", (event_id, canonical(row).decode())
            )
            return row

    def settle(self, event_id, actual_delta, *, receipt_sha256):
        actual = quantities(actual_delta)
        if len(receipt_sha256) != 64:
            raise ValueError("raw measurement receipt digest required")
        with self._transaction() as db:
            found = db.execute(
                "SELECT body FROM events WHERE event=?", (event_id,)
            ).fetchone()
            if not found:
                raise ValueError("effects without prior reservation are inadmissible")
            row = json.loads(found[0])
            if (
                row.get("cost_origin") == "allocated_shared"
                and receipt_sha256 != row["shared_receipt_sha256"]
            ):
                raise ValueError(
                    "allocation settlement must bind the original physical-work receipt"
                )
            if row["state"] != "reserved":
                if (
                    row.get("actual") == actual
                    and row.get("receipt_sha256") == receipt_sha256
                ):
                    return row
                raise ValueError("settlement replay differs from the original receipt")
            overrun = [k for k in METERS if actual[k] > row["reserved"][k]]
            row.update(
                actual=actual,
                receipt_sha256=receipt_sha256,
                settled_at_ns=time.time_ns(),
                state="overrun" if overrun else "settled",
                overrun_dimensions=overrun,
            )
            db.execute(
                "UPDATE events SET body=? WHERE event=?",
                (canonical(row).decode(), event_id),
            )
        if overrun:
            raise BudgetExceeded(
                "actual overrun retained; arm is now closed: " + ", ".join(overrun)
            )
        return row

    def abandon(self, event_id, *, reason):
        """Unknown effects consume the reservation; restarting cannot refund them."""
        with self._transaction() as db:
            found = db.execute(
                "SELECT body FROM events WHERE event=?", (event_id,)
            ).fetchone()
            if not found:
                raise ValueError("unknown reservation")
            row = json.loads(found[0])
            if row["state"] == "reserved":
                row.update(
                    state="lost",
                    reason=str(reason)[:1024],
                    settled_at_ns=time.time_ns(),
                )
                db.execute(
                    "UPDATE events SET body=? WHERE event=?",
                    (canonical(row).decode(), event_id),
                )
            return row

    def observe_inventory(self, values, *, inventory_sha256):
        values = quantities(values, GAUGES, complete=True)
        if len(inventory_sha256) != 64:
            raise ValueError("complete inventory digest required")
        with self._transaction() as db:
            old = json.loads(
                db.execute("SELECT body FROM snapshots WHERE id=1").fetchone()[0]
            )
            values["peak_rss_bytes"] = max(
                values["peak_rss_bytes"], old["gauges"]["peak_rss_bytes"]
            )
            row = dict(
                gauges=values, evidence=inventory_sha256, observed_at_ns=time.time_ns()
            )
            exceeded = [k for k in GAUGES if values[k] > self.config["gauges"][k]]
            row["exceeded"] = exceeded
            db.execute(
                "UPDATE snapshots SET body=? WHERE id=1", (canonical(row).decode(),)
            )
            if exceeded:
                event_id = "inventory-overrun:" + inventory_sha256
                violation = dict(
                    event=event_id,
                    phase="source",
                    state="overrun",
                    actual=quantities({}),
                    reserved=quantities({}),
                    overrun_dimensions=exceeded,
                )
                db.execute(
                    "INSERT OR IGNORE INTO events VALUES (?, ?)",
                    (event_id, canonical(violation).decode()),
                )
        if exceeded:
            raise BudgetExceeded("complete retained inventory exceeds ceiling")
        return row

    def snapshot(self):
        with self._transaction() as db:
            return dict(config=self.config, **self._state(db))
