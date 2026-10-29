"""An append-only local adapter gate: authenticated closure precedes settlement."""

import hashlib
import json
import os
from pathlib import Path

from experiments.free_boundary_neuron.owner.common import canonical, digest


class CreditGate:
    """Recover every admission and terminal closure before authorizing a write.

    This is an adapter around the unchanged owner executable. It does not grant
    production authority or claim the owner API itself verifies ledger signatures.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.phase, self.case, self.pending = "idle", None, None
        self.opened, self.admission = None, None
        self.head, self.sequence = "0" * 64, 0
        if self.path.exists():
            data = self.path.read_bytes()
            if not data.endswith(b"\n"):
                raise ValueError("Torn gate journal; recovery must fail closed")
            for raw in data.splitlines():
                row = json.loads(raw)
                body = row["body"]
                if (
                    row["sha256"] != digest(body)
                    or body["predecessor"] != self.head
                    or body["sequence"] != self.sequence + 1
                ):
                    raise ValueError("Gate journal identity or sequence changed")
                self._apply(body["kind"], body["case"], body["value"])
                self.head, self.sequence = row["sha256"], body["sequence"]

    def _apply(self, kind, case, value):
        if kind == "opened":
            self.require_next()
            if value["request"]["case"] != case or value["binding"]["case"] != case:
                raise ValueError("Opened episode identity differs")
            if any(
                value["binding"][key] != value["request"][key]
                for key in ("organ", "model_sha256")
            ):
                raise ValueError("Opened model or organ binding differs")
            context = value["request"]["context"]
            expected_admission = {
                **value["binding"],
                "context": [
                    context["reliability_ppm"] / 1_000_000,
                    context["cost_ppm"] / 1_000_000,
                    context["deadline"],
                ],
                "budget": value["request"]["budget"],
                "initial_account": value["status"]["initial_account"],
                "admission": "execute-trained-readout",
                "future_evidence_included": False,
            }
            if json.loads(value["admission_support_json"]) != expected_admission:
                raise ValueError("Admission support differs from actual opened state")
            self.phase, self.case, self.pending = "opened", case, None
            self.opened, self.admission = value, None
        else:
            if case != self.case:
                raise ValueError("Gate event belongs to another episode")
            if kind == "admitted":
                expected = {
                    **self.opened["binding"],
                    "support_digest": hashlib.sha256(
                        self.opened["admission_support_json"].encode()
                    ).hexdigest(),
                }
                if (
                    self.phase != "opened"
                    or not value["accepted"]
                    or value["binding"] != expected
                ):
                    raise ValueError("Unaccepted decision cannot admit work")
                self.phase, self.admission = "admitted", value
            elif kind == "terminal":
                if self.phase != "admitted" or not value["native_terminal"]:
                    raise ValueError("Only an admitted terminal task can settle")
                if (
                    any(
                        value[key] != expected
                        for key, expected in self.opened["binding"].items()
                    )
                    or value["signed_admission_chain"]
                    != self.admission["decision"]["chain_digest"]
                    or value["terminal_checkpoint"]
                    != value["terminal_status"]["checkpoint"]
                    or not value["terminal_status"]["terminal"]
                    or value["terminal_status"]["settled"]
                    or value["actual_resource_work"]
                    != value["terminal_status"]["current_neural_credit_state"]["work"]
                    or json.loads(value["closure_request"]["support_json"])
                    != {
                        key: entry
                        for key, entry in value.items()
                        if key != "closure_request"
                    }
                ):
                    raise ValueError("Terminal attestation differs from admitted owner")
                self.phase, self.pending = "terminal", value
            elif kind == "closure_rejected":
                if (
                    self.phase != "terminal"
                    or value["accepted"]
                    or value["resource_settlement_authorized"]
                ):
                    raise ValueError("Rejected closure cannot authorize resources")
            elif kind == "closure_accepted":
                expected = {
                    **self.opened["binding"],
                    **{
                        key: self.pending[key]
                        for key in ("terminal_checkpoint", "outcome_digest", "reward")
                    },
                    "support_digest": hashlib.sha256(
                        self.pending["closure_request"]["support_json"].encode()
                    ).hexdigest(),
                }
                if (
                    self.phase not in {"terminal", "authorized"}
                    or not value["accepted"]
                    or not value["resource_settlement_authorized"]
                    or value["authority"] != "DENY_ALL"
                    or value["binding"] != expected
                    or value["outcome"]["sequence"]
                    != self.admission["decision"]["sequence"] + 1
                    or value["credit"]["sequence"] != value["outcome"]["sequence"] + 1
                    or value["after"]["head"] != value["credit"]["chain_digest"]
                    or value["after"]["sequence"] != value["credit"]["sequence"]
                ):
                    raise ValueError("Incomplete authenticated closure")
                self.phase = "authorized"
            elif kind == "settled":
                if self.phase not in {"authorized", "settled"}:
                    raise ValueError("Unsigned terminal cannot update resources")
                record = value["native_response"]["record"]
                payload = json.loads(record["payload_json"])
                expected_support = digest(
                    {
                        "case": case,
                        "checkpoint": self.pending["terminal_checkpoint"],
                        "reward": self.pending["reward"],
                        "outcome_digest": self.pending["outcome_digest"],
                    }
                )
                if (
                    record["record_digest"]
                    != hashlib.sha256(record["payload_json"].encode()).hexdigest()
                    or payload["support_digest"] != expected_support
                    or payload["case"] != case
                    or payload["organ"] != self.opened["binding"]["organ"]
                    or payload["before"] != self.opened["status"]["initial_account"]
                    or payload["actual_work"] != self.pending["actual_resource_work"]
                    or payload["budget"] != self.opened["request"]["budget"]
                    or payload["owner_checkpoint"]
                    != self.pending["terminal_checkpoint"]
                    or payload["reward"] != self.pending["reward"]
                    or value["settlement_file"]
                    != {
                        "outcome_digest": self.pending["outcome_digest"],
                        "reward": self.pending["reward"],
                        "support_digest": expected_support,
                        "account_record": record,
                    }
                ):
                    raise ValueError("Settlement differs from signed outcome")
                self.phase = "settled"
            else:
                raise ValueError("Unknown gate event")

    def append(self, kind, case, value):
        # Validate before a durable append. If the write fails this object is
        # discarded; reopening checks the last complete chain and fails on a tear.
        self._apply(kind, case, value)
        body = {
            "sequence": self.sequence + 1,
            "predecessor": self.head,
            "kind": kind,
            "case": case,
            "value": value,
        }
        row = {"body": body, "sha256": digest(body)}
        with self.path.open("ab") as output:
            output.write(canonical(row) + b"\n")
            output.flush()
            os.fsync(output.fileno())
        directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        self.head, self.sequence = row["sha256"], body["sequence"]

    def require_next(self):
        if self.phase not in {"idle", "settled"}:
            raise PermissionError("Previous terminal closure or settlement is pending")

    def require_observation(self):
        if self.phase != "admitted":
            raise PermissionError("A signed admission is required before neural work")

    def settle(self, native, *, lose_acknowledgement=False):
        if self.phase not in {"authorized", "settled"}:
            raise PermissionError("Signed terminal credit has not committed")
        result = native.call(
            {
                "command": "Settle",
                "reward": self.pending["reward"],
                "outcome_digest": self.pending["outcome_digest"],
            }
        )
        if not lose_acknowledgement:
            self.append(
                "settled",
                self.case,
                {
                    "native_response": result,
                    "settlement_file": json.loads(
                        (native.root / self.case / "SETTLEMENT.json").read_text()
                    ),
                },
            )
        return result
