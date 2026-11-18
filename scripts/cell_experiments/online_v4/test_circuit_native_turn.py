"""Exercise shared native turns with real repository verifications."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from .. import data
from .circuit_contract import Budget, Graph, digest
from .circuit_runtime import run_graph
from .test_circuit_runtime import STRONG, WEAK, WRONG, cells, task


class NativeTurnTests(unittest.TestCase):
    def test_receiving_cell_consumes_original_action_and_measured_feedback(self):
        for removed in (None, "answer", "feedback"):
            with self.subTest(removed=removed), tempfile.TemporaryDirectory() as tmp:
                registry, requests = cells(), []

                def generate(cell, request, directory):
                    requests.append(copy.deepcopy(request))
                    messages = request["task"]["messages"]
                    prior = [m["content"] for m in messages if m["role"] == "assistant"]
                    observation = (
                        json.loads(messages[-1]["content"]) if len(messages) > 1 else {}
                    )
                    recovered = (
                        prior == [WEAK] and observation.get("controls_rejected") == 0
                    )
                    answer = (
                        WEAK if len(requests) == 1 else STRONG if recovered else WRONG
                    )
                    return {
                        "answer": answer,
                        "loaded_model_digest": registry[cell].model_digest,
                        "input_tokens": len(data.canonical(messages)),
                        "output_tokens": len(answer),
                        "elapsed_seconds": 0.0,
                        "messages_sha256": digest(messages),
                    }

                result = run_graph(
                    task(),
                    Graph("native", ("first", "second")),
                    registry,
                    Budget(max_output_tokens_per_call=1024),
                    generate,
                    data.verify_answer,
                    Path(tmp) / "run",
                    drop_edge=removed,
                    message_style="native_turn_v1",
                )
                self.assertEqual(result["success"], removed is None)
                self.assertEqual(result["cost"]["model_calls"], 2)
                second = requests[1]["task"]["messages"]
                self.assertEqual(second[0], requests[0]["task"]["messages"][0])
                self.assertEqual(
                    [m["role"] for m in second],
                    ["user", "tool"]
                    if removed == "answer"
                    else ["user", "assistant", "tool"],
                )
                self.assertNotIn(STRONG, data.canonical(requests).decode())
                if removed == "answer":
                    self.assertNotIn(WEAK, data.canonical(second).decode())
                if removed == "feedback":
                    self.assertNotIn("controls_rejected", second[-1]["content"])
                contract = json.loads((Path(tmp) / "run/CONTRACT.json").read_text())
                self.assertEqual(contract["message_style"], "native_turn_v1")


if __name__ == "__main__":
    unittest.main()
