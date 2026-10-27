"""Join delivered bytes, partial feedback, causal decisions and final rows."""

from collections import Counter
import hashlib

import numpy as np

from feedback_evidence import event, nonnative_action
from runtime_audit_support import canonical, object_sha, require
from runtime_bank_media_audit import DeliveryAudit, plan, validate_packet
from runtime_media_context import array_sha


class SelectedTraceAudit:
    """One completed seed/profile trace; native arithmetic has a separate audit."""

    def __init__(self, media, arithmetic, policies, cases, groups, seed, profile, role="runtime_audit"):
        self.delivery, self.arithmetic = DeliveryAudit(media), arithmetic
        self.policies, self.cases = policies, cases
        self.seed, self.profile, self.role = seed, profile, role
        self.hashes = {arm: object_sha(controller) for arm, controller in policies.items()}
        self.groups = [(arm, group) for group in groups for arm in policies]
        self.row_order = [(arm, case) for arm, group in self.groups for case in group]
        self.group_index, self.journal_index, self.last_time = 0, 0, 0
        self.live, self.finished, self.initial_payloads = {}, {}, {}
        self.current_cases, self.counts = [], Counter()
        self.by_arm = {arm: Counter() for arm in policies}
        self.native_coverage = hashlib.sha256()

    def process(self, row):
        require(row["record_index"] == self.journal_index and type(row["committed_monotonic_ns"]) is int and
                row["committed_monotonic_ns"] >= self.last_time, "Selected journal commitment order differs")
        self.journal_index += 1
        self.last_time = row["committed_monotonic_ns"]
        require(row["role"] == self.role and row["arm"] in self.policies, "Selected event role/arm differs")
        cases = row["case_ids"]
        require(cases and len(cases) == len(set(cases)) and set(cases) <= set(self.cases), "Unexpected or duplicate selected cases")
        if row["kind"] == "initial_delivery":
            self.initial(row)
        elif row["kind"] == "selected_actions_before_execution":
            self.selection(row)
        elif row["kind"] == "selected_revision_delivery":
            self.revision(row)
        else:
            raise ValueError("Unregistered event or counterfactual branch in selected execution")

    def initial(self, row):
        arm, cases = row["arm"], row["case_ids"]
        require(not self.live and self.group_index < len(self.groups) and self.groups[self.group_index] == (arm, cases),
                "Initial episode group differs from canonical source/arm order")
        self.group_index += 1
        self.current_cases = cases.copy()
        require(len(row["media"]) == len(cases) and np.asarray(row["public_events"]).shape == (len(cases), 16),
                "Initial media/event coverage differs")
        for index, (case, receipt) in enumerate(zip(cases, row["media"], strict=True)):
            key, private = (arm, case), self.cases[case]
            require(key not in self.finished, "Duplicate selected episode")
            record = self.delivery.read(receipt, case, 0, row["committed_monotonic_ns"])
            first = event(self.arithmetic.public(record, private["mask"]))
            require(np.array_equal(row["public_events"][index], first), "Initial public event differs from delivered media")
            if case in self.initial_payloads:
                require(self.initial_payloads[case] == record["record_sha256"], "Common initial output differs between control arms")
            else:
                self.initial_payloads[case] = record["record_sha256"]
            self.live[key] = {"history": [first], "record": record, "media": [receipt], "feedback": [],
                "actions": [], "decisions": [], "depth": 0, "node": 0, "pending": False}
            self.counts["public_events_rebuilt"] += 1
            self.by_arm[arm]["episodes"] += 1

    def selection(self, row):
        arm, cases, stage, summary = row["arm"], row["case_ids"], row["round"], row["selection"]
        controller, identity = self.policies[arm], self.hashes[arm]
        require(type(stage) is int and stage in (0, 1, 2) and
                cases == [case for case in self.current_cases if (arm, case) in self.live],
                "Decision stage or causal active-source order differs")
        states = [self.live[(arm, case)] for case in cases]
        require(all(not state["pending"] and state["depth"] == stage for state in states),
                "Decision precedes its own selected output/feedback")
        history = np.asarray([state["history"] for state in states], dtype=np.float64)
        require(np.array_equal(row["public_history"], history) and history.shape == (len(cases), stage + 1, 16) and
                row["delivered_record_sha256"] == [state["record"]["record_sha256"] for state in states],
                "Decision history includes altered, future, or non-delivered public evidence")
        require(row["controller_sha256"] == summary["controller_sha256"] == identity and
                summary["round"] == stage and summary["target_accesses"] == summary["future_events_accessed"] == 0,
                "Decision policy identity or private/future-access declaration differs")
        actions = summary["action_indices"]
        require(isinstance(actions, list) and len(actions) == len(cases) and
                all(type(action) is int and action in range(5) for action in actions), "Invalid selected action vector")
        fixed = controller.get("kind") == "fixed"
        representation = "fixed" if fixed else controller["representation"]
        native = representation in ("native", "reset_native")
        require(summary["representation"] == representation and summary["native_tick_calls"] == (2 * len(cases) if native else 0),
                "Selected representation or native tick opportunity differs")
        if fixed:
            require(controller["actions"] == plan(controller["node"]), "Fixed action plan differs from its frozen terminal node")
            expected = controller["actions"][stage] if stage < len(controller["actions"]) else 0
            require(actions == [expected] * len(cases), "Executed action differs from the frozen strong fixed policy")
        else:
            require(summary["schema"] == "hepta.field-bridge-v3.runtime-selection.v1" and
                    summary["rows"] == len(cases) and summary["public_history_sha256"] == array_sha(history) and
                    summary["native_receipt_path"] is None and summary["authority"] == "DENY_ALL" and
                    summary["native_owner_integration"] is False and summary["requires_calibration"] is native,
                    "Decision input/authority schema differs")
            if native:
                native_records = summary["native_records"]
                require(len(native_records) == len(cases), "Native public-history receipt coverage differs")
                for case, h, action, record in zip(cases, history, actions, native_records, strict=True):
                    require(record["case"] == case and record["round"] == stage and record["action"] == action and
                            record["controller_sha256"] == identity and np.array_equal(record["raw_history"], h) and
                            record["raw_history_sha256"] == array_sha(h), "Native record differs from actual media-derived causal history")
                    self.native_coverage.update(canonical({"arm": arm, "case": case, "round": stage,
                        "controller_sha256": identity, "history_sha256": array_sha(h), "action": action}) + b"\n")
            else:
                require(representation in ("current", "history") and summary["native_records"] == [],
                        "Unregistered non-native control or hidden native work")
                rebuilt = [nonnative_action(controller, h) for h in history]
                require(actions == [item[0] for item in rebuilt] and
                        summary["feature_matrix_sha256"] == array_sha(np.asarray([item[1] for item in rebuilt])),
                        "Frozen non-native feature arithmetic or head action differs")
                self.counts["nonnative_head_actions_replayed"] += len(cases)
        for name in ("select_wall_ns", "select_python_cpu_ns", "native_ns"):
            require(type(summary[name]) is int and summary[name] >= 0 and (name != "native_ns" or native or summary[name] == 0),
                    "Invalid measured selection timing")
            self.counts[name] += summary[name]
        self.counts["native_tick_calls"] += summary["native_tick_calls"]
        self.counts["selection_batches"] += 1
        self.counts["selection_rows"] += len(cases)
        commitment = object_sha(row)
        for case, action, state in zip(cases, actions, states, strict=True):
            state["actions"].append(action)
            state["decisions"].append(commitment)
            state.update(pending=action != 0, action=action, decision_time=row["committed_monotonic_ns"], decision=commitment)
            self.by_arm[arm]["decisions"] += 1
            self.by_arm[arm][f"round_{stage}_decisions"] += 1
            if action == 0:
                self.close(arm, case, row["committed_monotonic_ns"])

    def revision(self, row):
        arm, cases, depth, action = row["arm"], row["case_ids"], row["depth"], row["action"]
        require(type(depth) is int and depth in (1, 2, 3) and type(action) is int and action in (1, 2, 3, 4) and
                row["future_or_unchosen_branches_executed"] == 0, "Illegal or unselected continuation")
        expected = [case for case in self.current_cases if (arm, case) in self.live and
                    self.live[(arm, case)]["pending"] and self.live[(arm, case)]["action"] == action]
        require(cases == expected and len(row["media"]) == len(cases) and
                (row["feedback"] is None if depth == 3 else len(row["feedback"]) == len(cases)),
                "Selected action group/delivery/feedback coverage differs")
        for index, (case, receipt) in enumerate(zip(cases, row["media"], strict=True)):
            state, private = self.live[(arm, case)], self.cases[case]
            require(state["depth"] + 1 == depth and state["decision"] == row["decision_sha256"],
                    "Continuation differs from its earlier committed selected action")
            record = self.delivery.read(receipt, case, depth, row["committed_monotonic_ns"], state["decision_time"])
            state["media"].append(receipt)
            state.update(record=record, depth=depth, node=4 * state["node"] + action, pending=False)
            if depth == 3:
                self.close(arm, case, row["committed_monotonic_ns"])
            else:
                packet = row["feedback"][index]
                feedback = validate_packet(packet, receipt, case, private, record, depth, row["committed_monotonic_ns"])
                state["feedback"].append(packet)
                state["history"].append(event(self.arithmetic.public(record, private["mask"]), feedback, action))
                self.counts["public_events_rebuilt"] += 1
                self.counts["feedback_packets_rebuilt"] += 1

    def close(self, arm, case, commit_time):
        state, private = self.live.pop((arm, case)), self.cases[case]
        measured = {observer: self.arithmetic.score(state["record"], private["pixels"], private["labels"], observer, state["depth"])
                    for observer in ("reward", "audit")}
        expected = {"case_id": case, "source_ids": private["source_ids"], "role": self.role, "arm": arm,
            "actions": state["actions"], "terminal_node": state["node"], "depth": state["depth"],
            "media": state["media"], "decisions": state["decisions"], "feedback": state["feedback"], "scores": measured,
            "controller_sha256": self.hashes[arm], "unchosen_continuations_executed": 0,
            "seed": self.seed, "profile": self.profile, "condition": private["condition"], "pair_index": private["pair_index"]}
        require((arm, case) not in self.finished, "Episode closed twice")
        self.finished[(arm, case)] = (object_sha(expected), commit_time)
        self.by_arm[arm][f"terminal_depth_{state['depth']}"] += 1
        self.counts["dual_observer_scores_rebuilt"] += 2

    def finish(self, rows):
        require(not self.live and self.group_index == len(self.groups) and set(self.finished) == set(self.row_order),
                "Incomplete selected episode journal")
        count = 0
        for row in rows:
            require(count < len(self.row_order) and (row["arm"], row["case_id"]) == self.row_order[count],
                    "Final rows omit, duplicate or reorder source/arm episodes")
            key = self.row_order[count]
            expected_sha, earliest = self.finished[key]
            require(row["committed_monotonic_ns"] >= earliest and
                    object_sha({key: value for key, value in row.items() if key not in ("record_index", "committed_monotonic_ns")}) == expected_sha,
                    "Final row differs from independently rebuilt media, feedback, causal decisions or observer score")
            count += 1
        require(count == len(self.row_order), "Incomplete selected final rows")
        return {"episodes": count, "journal_records": self.journal_index, **dict(self.counts), **self.delivery.finish(),
                "per_arm": {arm: dict(counts) for arm, counts in self.by_arm.items()},
                "decision_coverage_sha256": self.native_coverage.hexdigest(),
                "native_arithmetic_scope": "Native/reset histories are bound to actual media; original-kernel and head replay are independently audited in a matching native-session receipt"}
