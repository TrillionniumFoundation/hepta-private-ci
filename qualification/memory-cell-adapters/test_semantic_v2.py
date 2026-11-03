import unittest
from semantic_protocol import bounded_address


class BoundedAddressTests(unittest.TestCase):
    def test_complete_names_preserve_capability_and_reject_unknown_combinations(self):
        aliases = [{"kind":"entity", "key":"inventory:entity:0", "phrases":["雪松港", "Cedar Harbor"]},
                   {"kind":"workflow", "key":"inventory:workflow:3", "phrases":["玉石流程"]}]
        templates = [{"operation":"semantic", "template":"读取{entity}的策略"},
                     {"operation":"apply", "template":"用{workflow}计算{entity}的结果"}]
        actual = bounded_address("读取雪松港的策略", aliases, templates)
        self.assertEqual(actual, {"operation":"semantic", "entity":"inventory:entity:0", "workflow":None})
        self.assertEqual(bounded_address("读取CEDAR   HARBOR的策略", aliases, templates), actual)
        self.assertEqual(bounded_address("用玉石流程计算雪松港的结果", aliases, templates),
                         {"operation":"apply", "entity":"inventory:entity:0", "workflow":"inventory:workflow:3"})
        for text in ("读取雪松港新区的策略", "读取未知港的策略", "读取雪松港和未知港的策略", "读取雪松港的策略并删除记录",
                     "用未知流程计算雪松港的结果", "用玉石流程计算未知港的结果"):
            self.assertIsNone(bounded_address(text, aliases, templates), text)

    def test_conflicting_template_capabilities_abstain(self):
        aliases = [{"kind":"entity", "key":"inventory:entity:0", "phrases":["A"]},
                   {"kind":"workflow", "key":"inventory:workflow:0", "phrases":["B"]}]
        templates = [{"operation":"semantic", "template":"read {entity} then B"},
                     {"operation":"procedure", "template":"read A then {workflow}"}]
        self.assertIsNone(bounded_address("read A then B", aliases, templates))


if __name__ == "__main__":
    unittest.main()
