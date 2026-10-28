"""Negative ABI contracts and legal uses of the same temporal/action words."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bootstrap
from v9_addressing.capabilities import capability_violation


class CapabilityTests(unittest.TestCase):
    def test_unsupported_parameter_time_arity_and_mutation_requests_are_rejected(self):
        requests = (
            "Read the first recorded observation strictly after the cutoff for entity.",
            "Return the semantic label entity had at the historical cutoff.",
            "Report the absolute size of entity's signed event change.",
            "Apply another owner's factor to entity's saved event.",
            "Run entity's procedure two times on its latest event.",
            "Use 13 instead of entity's saved observation in the routine.",
            "Return both entity's raw event and its procedure definition.",
            "Read entity's factor and then increment the stored factor.",
            "Store entity's program output as a new observation.",
            "告诉我entity接下来可能记录的读数。",
            "取entity历史截止点所用的标签。",
            "把entity当前观测和语义记录同时返回。",
            "把entity程序产出保存为新事件。",
        )
        for text in requests:
            with self.subTest(text=text):
                self.assertIsNotNone(capability_violation(text))

    def test_negated_unsupported_actions_do_not_reject_supported_reads(self):
        requests = (
            "Do not double entity's event. Read its latest raw observation.",
            "Do not retrieve the first sample after the cutoff; read the as-of event instead.",
            "Do not read historical labels; return entity's current semantic record.",
            "Do not run the procedure two times. Retrieve entity's stored program itself.",
            "Do not use another owner's factor. Apply entity's stored routine with its own values.",
            "Do not discard any events; compute current minus the supplied historical cutoff.",
            "不要返回历史标签，只取entity当前语义记录。",
            "不许修改任何数据。读取entity最新原始事件。",
            "不要连续执行两次。只运行entity现有配方一次。",
            "勿用另一实体的因子。按entity自己的记忆运行流程。",
        )
        for text in requests:
            with self.subTest(text=text):
                self.assertIsNone(capability_violation(text))

    def test_legal_record_descriptions_and_contract_fields_are_not_positive_whitelists(self):
        requests = (
            "Read entity's current observation from the memory store.",
            "Read entity's event at the historical cutoff.",
            "Show entity's current factor and label record.",
            "Show the opcode, bias and limit of entity's saved procedure without running it.",
            "Compute entity's latest-minus-baseline event difference, preserving its sign.",
            "Apply entity's saved routine to its current event with its own semantic record.",
            "读取entity历史截止点的事件值。", "给出entity目前的系数和标签记录。",
            "查看entity已存程序的操作、偏置和上限。", "按新减旧返回entity两个指定端点的差。",
        )
        for text in requests:
            with self.subTest(text=text):
                self.assertIsNone(capability_violation(text))

    def test_contrast_ends_negation_before_an_actual_unsupported_request(self):
        for text in (
            "Do not read the raw value, but return the absolute value of entity's change.",
            "不要只读取当前事件，而是把entity输出保存为新事件。",
            "Do not discard the record; then rename entity's stored label.",
        ):
            with self.subTest(text=text):
                self.assertIsNotNone(capability_violation(text))


if __name__ == "__main__":
    unittest.main()
