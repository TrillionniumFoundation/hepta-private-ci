"""Bounded deterministic cells and a host-injected external tool port."""

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Protocol

from .lifecycle import (
    CellError,
    ComponentIdentity,
    ReadbackResult,
    StepResult,
    _bounded_json,
    _hex,
    _token,
    digest,
)


def _configuration(kind, canonical):
    return hashlib.sha256((kind + "\0" + canonical).encode()).hexdigest()


def _counter(state, name):
    if (
        not isinstance(state, dict)
        or set(state) != {name}
        or type(state[name]) is not int
        or not 0 <= state[name] < 10**12
    ):
        raise CellError("invalid component state")
    return {name: state[name] + 1}


def _number(value):
    if (
        type(value) not in (int, float)
        or abs(value) > 1e100
        or not math.isfinite(value)
    ):
        raise CellError("expected a bounded finite number")
    return value


class ExactRetriever:
    """Literal key lookup, constrained by the cell's pinned {'keys': [...]} view."""

    def __init__(self, records, bundle_digest):
        if not isinstance(records, dict) or len(records) > 2048:
            raise CellError("retrieval corpus must be a bounded mapping")
        self._records = _bounded_json(records)
        self._bundle_digest = bundle_digest
        _hex(bundle_digest)

    @property
    def identity(self):
        return ComponentIdentity(
            "exact_retrieval",
            self._bundle_digest,
            configuration_digest=_configuration("exact_retrieval.v1", self._records),
        )

    def initial_state(self):
        return {"queries": 0}

    def step(self, payload, state, context):
        if (
            not isinstance(payload, dict)
            or set(payload) != {"key"}
            or not isinstance(payload["key"], str)
        ):
            raise CellError("retrieval requires one literal key")
        view = context.retrieval_view
        if (
            not isinstance(view, dict)
            or set(view) != {"keys"}
            or not isinstance(view["keys"], list)
            or len(view["keys"]) > 2048
        ):
            raise CellError("retrieval view must declare a bounded keys list")
        if not all(isinstance(key, str) for key in view["keys"]):
            raise CellError("retrieval view keys must be strings")
        records = json.loads(self._records)
        allowed = payload["key"] in view["keys"]
        found = allowed and payload["key"] in records
        return StepResult(
            {"found": found, "value": records[payload["key"]] if found else None},
            _counter(state, "queries"),
            len(view["keys"]) + 1,
        )


class RuleVerifier:
    """Finite rule grammar: required, equal, member, or inclusive range."""

    def __init__(self, rules, bundle_digest):
        if not isinstance(rules, list) or not 1 <= len(rules) <= 128:
            raise CellError("expected between one and 128 rules")
        for rule in rules:
            if not isinstance(rule, dict) or not isinstance(rule.get("field"), str):
                raise CellError("rule requires a literal field")
            op = rule.get("op")
            keys = {
                "required": {"field", "op"},
                "equal": {"field", "op", "value"},
                "member": {"field", "op", "values"},
                "range": {"field", "op", "min", "max"},
            }
            if op not in keys or set(rule) != keys[op]:
                raise CellError("unsupported rule grammar")
            if op == "member" and (
                not isinstance(rule["values"], list) or len(rule["values"]) > 128
            ):
                raise CellError("membership rule exceeds its bound")
            if op == "range" and _number(rule["min"]) > _number(rule["max"]):
                raise CellError("reversed numeric range")
        self._rules = _bounded_json(rules)
        self._bundle_digest = bundle_digest
        _hex(bundle_digest)

    @property
    def identity(self):
        return ComponentIdentity(
            "rule_verifier",
            self._bundle_digest,
            configuration_digest=_configuration("rule_verifier.v1", self._rules),
        )

    def initial_state(self):
        return {"checks": 0}

    def step(self, payload, state, context):
        if not isinstance(payload, dict):
            raise CellError("rule input must be a mapping")
        failed, rules = [], json.loads(self._rules)
        work_units = 1
        for index, rule in enumerate(rules):
            key, op = rule["field"], rule["op"]
            value, ok = payload.get(key), key in payload
            work_units += len(rule["values"]) if op == "member" else 1
            if ok and op == "equal":
                ok = _bounded_json(value) == _bounded_json(rule["value"])
            if ok and op == "member":
                ok = any(
                    _bounded_json(value) == _bounded_json(candidate)
                    for candidate in rule["values"]
                )
            if ok and op == "range":
                ok = (
                    type(value) in (int, float)
                    and math.isfinite(value)
                    and rule["min"] <= value <= rule["max"]
                )
            if not ok:
                failed.append(index)
        return StepResult(
            {"passed": not failed, "failed_rules": failed},
            _counter(state, "checks"),
            work_units,
        )


class NumericAlgorithm:
    def __init__(self, operation, bundle_digest):
        if operation not in {"mean_variance", "dot"}:
            raise CellError("unsupported numeric algorithm")
        self.operation = operation
        self._bundle_digest = bundle_digest
        _hex(bundle_digest)

    @property
    def identity(self):
        return ComponentIdentity(
            "numeric_" + self.operation,
            self._bundle_digest,
            configuration_digest=_configuration("numeric.v1", self.operation),
        )

    def initial_state(self):
        return {"calls": 0}

    @staticmethod
    def _vector(values):
        if not isinstance(values, list) or not 1 <= len(values) <= 2048:
            raise CellError("numeric vectors require 1..2048 elements")
        return [_number(value) for value in values]

    def step(self, payload, state, context):
        if not isinstance(payload, dict) or set(payload) != (
            {"values"} if self.operation == "mean_variance" else {"left", "right"}
        ):
            raise CellError("invalid numeric arguments")
        if self.operation == "mean_variance":
            values = self._vector(payload["values"])
            mean = math.fsum(values) / len(values)
            result = {
                "count": len(values),
                "mean": mean,
                "variance": math.fsum((value - mean) ** 2 for value in values)
                / len(values),
            }
            work = 2 * len(values)
        else:
            left, right = self._vector(payload["left"]), self._vector(payload["right"])
            if len(left) != len(right):
                raise CellError("dot-product vector lengths differ")
            result, work = (
                {"value": math.fsum(a * b for a, b in zip(left, right))},
                len(left),
            )
        return StepResult(result, _counter(state, "calls"), work)


@dataclass(frozen=True)
class ToolInvocation:
    operation_id: str
    tool_name: str
    tool_digest: str
    partition_digest: str
    request_id: str
    component_digest: str
    arguments: Any
    epoch: int
    max_work_units: int
    deadline_ms: int


@dataclass(frozen=True)
class ToolReply:
    output: Any
    work_units: int
    original_elapsed_ns: int | None = None


class HostToolPort(Protocol):
    def invoke(self, invocation: ToolInvocation) -> ToolReply: ...
    def readback(self, invocation: ToolInvocation) -> ToolReply | None: ...


class ToolCell:
    """The host chooses one capability. Readback never calls invoke again."""

    def __init__(self, tool_name, tool_digest, port: HostToolPort, bundle_digest):
        _token(tool_name)
        _hex(tool_digest)
        self.tool_name, self.tool_digest, self.port = tool_name, tool_digest, port
        self._bundle_digest = bundle_digest
        _hex(bundle_digest)

    @property
    def identity(self):
        configuration = _bounded_json(
            dict(
                tool_name=self.tool_name,
                tool_digest=self.tool_digest,
                max_argument_bytes=16384,
            )
        )
        return ComponentIdentity(
            "host_tool",
            self._bundle_digest,
            effectful=True,
            configuration_digest=_configuration("host_tool.v1", configuration),
        )

    def initial_state(self):
        return {"completed": 0}

    def _invocation(self, payload, context):
        if not isinstance(payload, dict):
            raise CellError("tool arguments must be a bounded JSON mapping")
        arguments = json.loads(_bounded_json(payload, 16384))
        binding = [
            context.partition.digest,
            context.request_id,
            self.identity.digest,
            self.tool_name,
            self.tool_digest,
            arguments,
            context.epoch,
            context.budget.max_work_units,
            context.budget.max_elapsed_ms,
            context.retrieval_view,
        ]
        return ToolInvocation(
            digest(binding),
            self.tool_name,
            self.tool_digest,
            context.partition.digest,
            context.request_id,
            self.identity.digest,
            arguments,
            context.epoch,
            context.budget.max_work_units,
            context.budget.max_elapsed_ms,
        )

    @staticmethod
    def _result(reply, state):
        if not isinstance(reply, ToolReply):
            raise CellError("tool port returned an invalid reply")
        return StepResult(reply.output, _counter(state, "completed"), reply.work_units)

    def step(self, payload, state, context):
        next_state = _counter(state, "completed")
        reply = self.port.invoke(self._invocation(payload, context))
        if not isinstance(reply, ToolReply):
            raise CellError("tool port returned an invalid reply")
        return StepResult(reply.output, next_state, reply.work_units)

    def readback(self, pending):
        reply = self.port.readback(self._invocation(pending.payload, pending))
        return (
            None
            if reply is None
            else ReadbackResult(
                self._result(reply, pending.state), reply.original_elapsed_ns
            )
        )
