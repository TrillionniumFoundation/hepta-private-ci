import ast
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


class ReviewSourceTests(unittest.TestCase):
    def test_review_has_no_numerical_or_model_imports(self):
        tree = ast.parse((HERE / "review.py").read_text())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(item.name.split(".")[0] for item in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertTrue(imports.isdisjoint({"numpy", "scipy", "torch", "jax"}))

    def test_review_is_strictly_red(self):
        text = (HERE / "REVIEW.json").read_text()
        self.assertIn('"status": "RED"', text)
        self.assertIn('"qualification": false', text)
        self.assertIn('"all_closed": false', text)


if __name__ == "__main__":
    unittest.main()
