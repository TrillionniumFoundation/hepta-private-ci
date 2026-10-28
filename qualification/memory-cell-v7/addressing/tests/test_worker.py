"""Persistent frame binding and closed capabilities at the real worker entry."""

import io
import json
import unittest

from addressing.capabilities import capability_violation
from addressing.contracts import canonical
from addressing.worker import MAX_FRAME_BYTES, serve
from test_planner import ProbeModel, registry, request


class WorkerTests(unittest.TestCase):
    def frame(self, **changes):
        return {
            "schema": "hepta.memory.v7.address-worker-request.v1",
            "request": request(**changes),
            "registry": registry(),
        }

    def run_frames(self, raw, model=None):
        incoming, outgoing, errors = io.BytesIO(raw), io.BytesIO(), io.StringIO()
        status = serve(model or ProbeModel(), incoming, outgoing, errors)
        return (
            status,
            [json.loads(line) for line in outgoing.getvalue().splitlines()],
            errors.getvalue(),
        )

    def test_persistent_requests_keep_query_and_cut_binding_without_partial_failure(
        self,
    ):
        frames = [
            self.frame(query_id="q1"),
            self.frame(query_id="q2", scope="other"),
            self.frame(query_id="q3", text="Read Vega's latest value."),
        ]
        status, rows, errors = self.run_frames(
            b"".join(canonical(frame) + b"\n" for frame in frames)
        )
        self.assertEqual((status, len(rows), errors), (0, 3, ""))
        self.assertEqual([row["query_id"] for row in rows], ["q1", "q2", "q3"])
        self.assertEqual(
            [row["status"] for row in rows], ["accepted", "rejected", "accepted"]
        )
        self.assertIsNone(rows[1]["plan"])
        self.assertIsNone(rows[1]["request"])
        self.assertEqual(rows[2]["request"]["entity"], "meter-vega")
        self.assertEqual(rows[2]["source_cut"], "7" * 64)
        self.assertTrue(all(row["cost"]["request_body_bytes"] > 0 for row in rows))

    def test_duplicate_nonfinite_and_unexpected_frames_do_not_reach_inference(self):
        model = ProbeModel()
        raw = (
            b'{"schema":"x","schema":"y"}\n{"value":NaN}\n[]\n'
            + canonical({**self.frame(), "gold": "current"})
            + b"\n"
        )
        status, rows, _ = self.run_frames(raw, model)
        self.assertEqual((status, len(rows), model.seen), (0, 4, []))
        self.assertTrue(
            all(
                row["plan"] is None
                and row["request"] is None
                and row["status"] == "rejected"
                for row in rows
            )
        )

    def test_incomplete_and_oversized_frames_terminate_without_resynchronization(self):
        for raw in (
            canonical(self.frame()),
            b" " * (MAX_FRAME_BYTES + 1) + b"\n" + canonical(self.frame()) + b"\n",
        ):
            status, rows, _ = self.run_frames(raw)
            self.assertEqual((status, len(rows), rows[0]["plan"]), (2, 1, None))

    def test_semantic_capability_boundary_rejects_new_actions_but_respects_negation(
        self,
    ):
        unsupported = [
            "Square entity's saved factor.",
            "Guess the missing value for entity.",
            "Return two outputs: the procedure and its result.",
            "Apply the stored recipe to entity's historical observation.",
            "Return entity's old semantic attribute.",
            "Subtract the current event from the old event.",
            "用 entity 的旧值减当前值。",
            "假设 entity 的系数变了，再计算结果。",
            "读取最新值，然后删除该记录。",
        ]
        for value in unsupported:
            self.assertIsNotNone(capability_violation(value), value)
        supported = [
            "Read entity's latest value, not a forecast.",
            "Return the raw current reading without calculating an average.",
            "I want the saved procedure, do not execute or modify it.",
            "只读取 entity 最新数值，不要预测。",
            "查看 entity 流程，不需要改写。",
            "Subtract the old value from the current value.",
            "读取 entity 现在和当时的值，再返回现在减当时。",
            "把读数和语义系数输入记住的程序。",
            "将三个记忆组合求一个输出。",
        ]
        for value in supported:
            self.assertIsNone(capability_violation(value), value)


if __name__ == "__main__":
    unittest.main()
