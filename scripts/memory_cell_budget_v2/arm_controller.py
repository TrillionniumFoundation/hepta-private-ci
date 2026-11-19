"""One arm/seed ledger, durable once-only effect claims and receipt settlement."""

import json
from pathlib import Path
import re

from common import (
    BudgetLedger,
    METERS,
    canonical,
    digest,
    file_identity,
    observations,
    quantities,
    read_json,
    save,
)
from receipt_bridge import collect
from tensor_capacity import admit


class ArmController:
    """Trusted single host controller; not a process or filesystem sandbox.

    Every stage uses this same object or reopens this exact directory/binding.
    Claims never authorize retries. A caller must not launch effects before
    begin returns, and must use a new registered event for a new attempt.
    """

    def __init__(self, directory, *, arm, seed, protocol_sha256, budget, capacity):
        if (
            not isinstance(arm, str)
            or not arm
            or type(seed) is not int
            or seed < 0
            or re.fullmatch(r"[0-9a-f]{64}", protocol_sha256) is None
        ):
            raise ValueError("explicit arm and nonnegative seed required")
        self.directory = Path(directory).absolute()
        if self.directory.is_symlink():
            raise ValueError("controller directory must not be a link")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.binding = json.loads(
            canonical(
                {
                    "schema": "hepta.memory-budget.controller.v2",
                    "arm": arm,
                    "seed": seed,
                    "protocol_sha256": protocol_sha256,
                    "budget": budget,
                    "capacity": capacity,
                    "controller_path": str(self.directory),
                }
            )
        )
        path = self.directory / "binding.json"
        try:
            save(path, self.binding)
        except FileExistsError:
            if read_json(path, file_identity(path)) != self.binding:
                raise ValueError("controller identity, capacity or budget changed")
        self.ledger = BudgetLedger(
            self.directory / "budget.sqlite3",
            arm=digest([arm, seed]),
            protocol_sha256=protocol_sha256,
            **budget,
        )
        self.claims = self.directory / "claims"
        self.claims.mkdir(exist_ok=True)
        self.receipt_claims = self.directory / "receipt-claims"
        self.receipt_claims.mkdir(exist_ok=True)

    def remaining(self):
        state = self.ledger.snapshot()
        return {
            "closed": state["closed"],
            "meters": {
                k: self.ledger.config["limits"][k]
                - state["used"][k]
                - state["pending"][k]
                for k in METERS
            },
            "priced_units": self.ledger.config["cost_limit"]
            - state["used_cost"]
            - state["pending_cost"],
        }

    def begin(self, event, phase, upper, request):
        if not isinstance(event, str) or not event or len(event) > 256:
            raise ValueError("bounded registered event ID required")
        upper = quantities(upper, complete=True)
        directory = self.claims / digest(event)
        directory.mkdir(exist_ok=False)
        ticket = {
            "schema": "hepta.memory-budget.ticket.v2",
            "binding_sha256": digest(self.binding),
            "event": event,
            "phase": phase,
            "upper": upper,
            "request_sha256": digest(request),
        }
        save(directory / "request.json", {"ticket": ticket, "request": request})
        try:
            capacity = admit(self.binding["capacity"])
            save(directory / "capacity.json", capacity)
            ticket["capacity_receipt_sha256"] = file_identity(
                directory / "capacity.json"
            )["sha256"]
            row = self.ledger.reserve(
                event,
                phase,
                upper,
                request_sha256=digest(ticket),
            )
            if row["state"] != "reserved":
                raise ValueError("terminal event never authorizes another effect")
            save(directory / "ticket.json", ticket)
            return ticket
        except BaseException as error:
            row = next(
                (r for r in self.ledger.snapshot()["events"] if r["event"] == event),
                None,
            )
            if row is not None and row["state"] == "reserved":
                self.ledger.abandon(event, reason="admission failed after reservation")
            save(directory / "refusal.json", {"error": repr(error)})
            raise

    def _active(self, ticket):
        if ticket.get("binding_sha256") != digest(self.binding):
            raise ValueError("ticket belongs to another arm/seed/controller")
        directory = self.claims / digest(ticket["event"])
        path = directory / "ticket.json"
        if read_json(path, file_identity(path)) != ticket:
            raise ValueError("ticket differs from durable admission")
        row = next(
            r for r in self.ledger.snapshot()["events"] if r["event"] == ticket["event"]
        )
        if row["state"] != "reserved" or row["request_sha256"] != digest(ticket):
            raise ValueError("settled, lost or changed operation cannot replay")
        return directory

    def finish(self, ticket, plan, *, status="completed"):
        if status not in {"completed", "failed", "timeout"}:
            raise ValueError("explicit operation completion status required")
        directory = self._active(ticket)
        try:
            measured = collect(plan)
            for row in measured["receipts"]:
                save(
                    self.receipt_claims / (row["identity"]["sha256"] + ".json"),
                    {"event": ticket["event"], "ticket_sha256": digest(ticket)},
                )
            if measured["infrastructure_status"] != "completed":
                status = measured["infrastructure_status"]
            observed = observations(measured["observation"])
            charge, basis = {}, {}
            for key, value in observed.items():
                upper = ticket["upper"][key]
                if status != "completed" or value is None:
                    charge[key] = max(upper, measured["lower_bounds"][key], value or 0)
                    basis[key] = (
                        "failure_reservation"
                        if status != "completed"
                        else "unknown_reservation"
                    )
                else:
                    charge[key], basis[key] = value, "observed"
            record = {
                "schema": "hepta.memory-budget.settlement.v2",
                "ticket_sha256": digest(ticket),
                "status": status,
                "receipt_plan": plan,
                "measured": measured,
                "charge": charge,
                "charge_basis": basis,
                "unknown_cost_is_zero": False,
            }
            save(directory / "settlement.json", record)
            self.ledger.settle(ticket["event"], charge, receipt_sha256=digest(record))
            return record
        except BaseException:
            row = next(
                r
                for r in self.ledger.snapshot()["events"]
                if r["event"] == ticket["event"]
            )
            if row["state"] == "reserved":
                self.ledger.abandon(
                    ticket["event"],
                    reason="receipt validation or settlement incomplete",
                )
            raise

    def lost(self, ticket, reason):
        directory = self._active(ticket)
        record = {
            "schema": "hepta.memory-budget.lost.v2",
            "ticket_sha256": digest(ticket),
            "reason": str(reason)[:1024],
            "observation": dict.fromkeys(METERS),
            "charge": ticket["upper"],
            "basis": "lost_full_reservation",
        }
        save(directory / "lost.json", record)
        self.ledger.abandon(ticket["event"], reason=reason)
        return record

    def run(self, event, phase, upper, request, effect):
        """The effect returns a raw receipt plan; exceptions consume its hold."""
        ticket = self.begin(event, phase, upper, request)
        try:
            return self.finish(ticket, effect(ticket))
        except BaseException as error:
            row = next(
                r for r in self.ledger.snapshot()["events"] if r["event"] == event
            )
            if row["state"] == "reserved":
                self.lost(ticket, repr(error))
            raise
