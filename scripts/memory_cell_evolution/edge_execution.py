"""Bounded live cell→cell execution with raw first output in the next prompt.

The metadata resolver returns keys, roots and prompt text, never a source answer.
An operator-supplied typed query is still required. Learned transitions are
separate from source authority and do not attest semantic correctness.
"""

import json
from pathlib import Path
import time

from evolution_common import digest, identifier, require, roots, retain


class GraphExecutor:
    def __init__(self, topology, resolver, reader, *, max_calls=2):
        require(
            max_calls == 2 and callable(resolver) and callable(reader),
            "registered bounded two-cell executor required",
        )
        self.topology, self.resolver, self.reader, self.max_calls = (
            topology,
            resolver,
            reader,
            max_calls,
        )

    def _capability(self, cell_id, entity, relation):
        result = self.resolver(cell_id, entity, relation)
        if result is None:
            return None
        require(
            type(result) is dict
            and set(result) == {"entity", "relation", "source_roots", "question"},
            "resolver cannot supply source answers",
        )
        require(
            (result["entity"], result["relation"]) == (entity, relation),
            "resolver changed query key",
        )
        require(
            type(result["question"]) is str
            and 0 < len(result["question"].encode()) <= 2048,
            "bounded key-bound prompt required",
        )
        roots(result["source_roots"])
        require(result["source_roots"], "nonempty source capability required")
        return result

    def _step(self, cell_id, capability, prompt, trace):
        require(len(prompt.encode()) <= 4096, "composed prompt exceeds bound")
        attempts = dict(
            cell_id=cell_id,
            capability=capability,
            prompt=prompt,
            started_ns=time.monotonic_ns(),
            actual_callbacks=0,
            raw=None,
        )
        trace.append(attempts)

        def invoke(active):
            require(
                sum(t["actual_callbacks"] for t in trace) < self.max_calls,
                "model call budget exhausted",
            )
            attempts["actual_callbacks"] += 1
            result = self.reader(active, prompt)
            require(
                type(result) is dict
                and result["question"] == prompt
                and result["answer_postprocessed"] is False,
                "raw question-bound model row required",
            )
            require(
                type(result["text"]) is str and len(result["text"].encode()) <= 2048,
                "bounded raw decoder output required",
            )
            attempts["raw"] = result
            return result

        try:
            raw = self.topology.invoke(cell_id, capability["source_roots"], invoke)
            attempts.update(status="generated", finished_ns=time.monotonic_ns())
            return raw
        except (ValueError, OSError) as error:
            attempts.update(
                status="indeterminate" if attempts["actual_callbacks"] else "denied",
                error=str(error),
                finished_ns=time.monotonic_ns(),
            )
            return None

    def run(self, task, policy, *, receipt_path):
        require(
            type(task) is dict and set(task) == {"task_id", "entity", "entry_cell"},
            "closed task without gold required",
        )
        for value in task.values():
            identifier(value)
        graph, frontier = self.topology.graph_snapshot()
        require(
            graph["edge_policy"] == policy.binding,
            "policy is not bound to committed topology",
        )
        policy.check()
        trace, decision = [], None
        result = dict(
            schema="hepta.edge-execution.v1",
            task=task,
            topology_generation=graph["generation"],
            policy_sha256=policy.binding["sha256"],
            source_frontier=frontier,
            trace=trace,
            decision=None,
            status="denied",
            answer=None,
            origin="parameters",
            correctness_verified=False,
            production_accepted=False,
        )
        try:
            entry = self._capability(task["entry_cell"], task["entity"], "hint")
            require(entry is not None, "entry source key unavailable")
            first = self._step(task["entry_cell"], entry, entry["question"], trace)
            require(
                first is not None, "entry decoder did not return an admitted raw row"
            )
            state = dict(
                question=entry["question"],
                cell_id=task["entry_cell"],
                raw_text=first["text"],
            )
            capabilities = {
                target: self._capability(target, task["entity"], "color")
                for target in policy.targets
            }
            eligible = [
                target
                for target, cap in capabilities.items()
                if cap is not None
                and target in graph["cells"]
                and set(cap["source_roots"])
                <= set(graph["cells"][target]["support_roots"])
            ]
            require(
                self.topology.graph_snapshot() == (graph, frontier),
                "source/topology changed between cells",
            )
            decision = policy.choose(state, eligible)
            result["decision"] = dict(state=state, next_cell=decision)
            committed = dict(
                task_id=task["task_id"],
                topology_generation=graph["generation"],
                policy_sha256=policy.binding["sha256"],
                decision=result["decision"],
                before_next_callback_ns=time.monotonic_ns(),
            )
            retain(Path(receipt_path).with_suffix(".decision.json"), committed)
            result["decision_sha256"] = digest(committed)
            if decision is None:
                result.update(status="stopped", answer=first["text"])
            else:
                require(
                    [task["entry_cell"], decision] in graph["edges"],
                    "next cell is not an admitted edge",
                )
                require(
                    decision != task["entry_cell"]
                    and decision in capabilities
                    and capabilities[decision] is not None,
                    "next cell has no typed source capability",
                )
                require(
                    self.topology.graph_snapshot() == (graph, frontier),
                    "source/topology changed before next invocation",
                )
                prompt = (
                    capabilities[decision]["question"]
                    + " Previous cell output: "
                    + json.dumps(first["text"], ensure_ascii=False)
                )
                second = self._step(decision, capabilities[decision], prompt, trace)
                require(
                    second is not None,
                    "next decoder did not return an admitted raw row",
                )
                result.update(status="generated", answer=second["text"])
            policy.check()
            require(
                self.topology.graph_snapshot() == (graph, frontier),
                "in-flight graph authority changed",
            )
        except (ValueError, OSError) as error:
            result.update(
                status="indeterminate"
                if any(t["actual_callbacks"] for t in trace)
                else "denied",
                answer=None,
                error=str(error),
            )
        except BaseException as error:
            result.update(
                status="execution_failed",
                answer=None,
                error_type=type(error).__name__,
                error=str(error),
                actual_callbacks=sum(t["actual_callbacks"] for t in trace),
                trace_sha256=digest(trace),
            )
            retain(receipt_path, result)
            raise
        result["actual_callbacks"] = sum(t["actual_callbacks"] for t in trace)
        result["actual_input_tokens"] = sum(
            t["raw"]["input_tokens"] for t in trace if t["raw"]
        )
        result["actual_output_tokens"] = sum(
            t["raw"]["generated_tokens"] for t in trace if t["raw"]
        )
        result["callbacks_without_complete_raw_row"] = sum(
            t["actual_callbacks"] for t in trace if t["raw"] is None
        )
        result["token_counts_are_lower_bound"] = (
            result["callbacks_without_complete_raw_row"] > 0
        )
        result["trace_sha256"] = digest(trace)
        retain(receipt_path, result)
        return result
