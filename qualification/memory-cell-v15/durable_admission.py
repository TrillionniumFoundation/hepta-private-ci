"""Reserve frozen Memory Cell comparisons before any trusted evaluator dispatch.

The caller supplies a fixed execution identity for its loader/source/runtime and
uses one persistent ExperimentLedger. All registered model callbacks and the
common executor are frozen together before the first dispatch. This is an opt-in
research entry point;
calling MatchedEvaluator directly remains diagnostic and has no durable guarantee.
"""

from copy import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

import cloudpickle

from execution_snapshot import freeze_execution

from admission import digest
from experiment_ledger import LedgerRejected, fingerprint
from cohort import INFORMATION


class DurableMatchedEvaluator:
    def __init__(self, evaluator, ledger, experiment, execution_identity, *, runs):
        if (not isinstance(execution_identity, str) or len(execution_identity) != 64
                or any(c not in "0123456789abcdef" for c in execution_identity)):
            raise LedgerRejected("missing frozen loader/source/runtime identity")
        self.evaluator, self.ledger, self.experiment = evaluator, ledger, experiment
        self.execution_identity = execution_identity
        registration = json.loads(evaluator._registration_wire)
        runs = tuple(sorted(runs, key=lambda run: run.bundle))
        expected = registration.get("arms", {}) if isinstance(registration, dict) else {}
        if (not runs or len({run.bundle for run in runs}) != len(runs)
                or {run.bundle for run in runs} != set(expected)
                or any({field: getattr(run, field) for field in INFORMATION} != expected[run.bundle]
                       for run in runs)):
            raise LedgerRejected("complete registered callback roster required before dispatch")
        callbacks, self.snapshot_digest, identities = freeze_execution(
            *(run.predict for run in runs), evaluator.executor_factory)
        self.frozen_runs = {run.bundle: replace(run, predict=callbacks[i]) for i,run in enumerate(runs)}
        self.frozen_executor = callbacks[-1]
        self.callback_roster = dict(zip((run.bundle for run in runs), identities[:-1], strict=True))
        self.executor_callback = identities[-1]

    def evaluate(self, operation, candidate, incumbent, candidate_cost, incumbent_cost, *, manifest):
        e = copy(self.evaluator)
        frozen = json.loads(json.dumps({"candidate_cost": candidate_cost, "incumbent_cost": incumbent_cost,
                                        "manifest": manifest}, allow_nan=False))
        candidate_cost, incumbent_cost, manifest = (frozen["candidate_cost"], frozen["incumbent_cost"],
                                                    frozen["manifest"])
        _, callback_digest, identities = freeze_execution(candidate.predict, incumbent.predict, e.executor_factory)
        if (self.callback_roster.get(candidate.bundle) != identities[0]
                or self.callback_roster.get(incumbent.bundle) != identities[1]
                or self.executor_callback != identities[2]):
            raise LedgerRejected("callback changed after full-roster freeze")
        candidate = replace(candidate, predict=self.frozen_runs[candidate.bundle].predict)
        incumbent = replace(incumbent, predict=self.frozen_runs[incumbent.bundle].predict)
        e.executor_factory = self.frozen_executor
        if e._registration_reasons:
            raise LedgerRejected("invalid prospective registration: " + ",".join(e._registration_reasons))
        if digest(vars(e.protocol)) != e._frozen_protocol_digest:
            raise LedgerRejected("protocol changed after freeze")
        registration = json.loads(e._registration_wire)
        look = registration.pop("look_index")
        claims = set()
        for case in json.loads(e._cases_wire):
            unit = registration["final_units"][case["key"]]
            claims.add(fingerprint(["source-unit", unit["unit"]]))
            claims.add(fingerprint(["source-cluster", case["cluster"]]))
            # Relabelling a unit/cluster/experiment cannot recycle identical inputs.
            # Semantic variants still need trusted ingestion/source lineage checks.
            claims.add(fingerprint(["public-input", case["query"], case["payload"]]))
        implementation = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                          for name in ("admission.py", "cohort.py", "isolated_runner.py", "typed_json.py", "durable_admission.py",
                                       "execution_snapshot.py", "experiment_ledger.py")}
        implementation.update(python=sys.version, cloudpickle=cloudpickle.__version__)
        family = {"implementation": implementation, "schema": "hepta.memory.experiment-family.v1", "registration": registration,
                  "protocol": vars(e._frozen_protocol), "execution_identity": self.execution_identity,
                  "callback_roster": self.callback_roster, "executor_callback": self.executor_callback,
                  "full_roster_snapshot": self.snapshot_digest,
                  "comparisons": registration["comparisons"],
                  "planned_looks": e._frozen_protocol.planned_looks, "source_claims": sorted(claims)}
        request = {"schema": "hepta.memory.evaluation-request.v1", "family": fingerprint(family),
                   "comparison": [candidate.bundle, incumbent.bundle], "look": look, "callbacks": callback_digest,
                   "candidate": e.cost_binding(candidate), "incumbent": e.cost_binding(incumbent),
                   "candidate_cost": candidate_cost, "incumbent_cost": incumbent_cost, "manifest": manifest}
        reserved = self.ledger.reserve(self.experiment, operation, family,
                                      request["comparison"], look, request)
        token = reserved.pop("dispatch_token")
        if token is None:
            return reserved
        self.ledger.start(operation, token)
        try:
            result = e.evaluate(candidate, incumbent, candidate_cost, incumbent_cost, manifest=manifest)
            result["durable_reservation"] = {"experiment": self.experiment, "operation": operation,
                "request": reserved["request"], "family": fingerprint(family), "look": look,
                "execution_identity": self.execution_identity, "callbacks": callback_digest}
            result.pop("evidence", None)
            result["evidence"] = digest(result)
            return self.ledger.finish(operation, token, result)
        except BaseException as exc:
            state = "cancelled" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "unknown"
            self.ledger.retain(operation, state, type(exc).__name__)
            raise
