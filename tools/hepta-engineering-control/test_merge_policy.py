import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from control_engineering_v2.merge_policy import build_merge_policy_receipt


class MergePolicyTests(unittest.TestCase):
    def git(self, root, *args):
        return subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, check=True
        ).stdout.strip()

    def write(self, root, path, text):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self, root, message):
        self.git(root, "add", "-A")
        self.git(root, "commit", "-qm", message)
        return self.git(root, "rev-parse", "HEAD")

    def test_merge_commit_preserves_observation_and_squash_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.git(root, "init", "-q")
            self.git(root, "config", "user.name", "Merge policy")
            self.git(root, "config", "user.email", "merge@example.invalid")
            self.write(root, "tools/hepta-engineering-control/source.py", "base = 1\n")
            base = self.commit(root, "base")
            self.git(root, "checkout", "-qb", "feature")
            self.write(root, "tools/hepta-engineering-control/source.py", "base = 2\n")
            observation = self.commit(root, "feature")
            observation_tree = self.git(root, "rev-parse", f"{observation}^{{tree}}")
            self.write(
                root,
                "docs/modules/control.engineering/IMPLEMENTATION_MAP.json",
                json.dumps(
                    {
                        "module": "control.engineering",
                        "mappingSourceIdentityMode": "exact_blob",
                        "observedAtHead": {"commit": observation, "tree": observation_tree},
                    }
                ),
            )
            feature = self.commit(root, "feature map")
            self.git(root, "checkout", "-qb", "main", base)
            self.git(root, "merge", "--no-ff", "feature", "-m", "merge feature")
            merged = self.git(root, "rev-parse", "HEAD")
            receipt = build_merge_policy_receipt(
                root, base_sha=base, head_sha=merged, mode="post-merge-main"
            )
            self.assertTrue(receipt["postMergeMethodVerified"])
            self.assertEqual(receipt["requiredMergeMethod"], "merge")

            self.git(root, "checkout", "-qb", "squashed", base)
            self.git(root, "read-tree", f"{feature}^{{tree}}")
            self.git(root, "checkout-index", "-a", "-f")
            squashed = self.commit(root, "squash")
            with self.assertRaisesRegex(ValueError, "squash_or_rebase_rejected"):
                build_merge_policy_receipt(
                    root, base_sha=base, head_sha=squashed, mode="post-merge-main"
                )


if __name__ == "__main__":
    unittest.main()
