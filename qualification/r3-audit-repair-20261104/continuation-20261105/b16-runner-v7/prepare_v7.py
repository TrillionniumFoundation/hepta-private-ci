"""Prepare only the reviewed original-catalog correction; no native operations."""

import base64
import bz2
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "build-only-current-host-v6" / "v6-candidate"
OUT = ROOT / "v7-candidate"
WORKSPACE = ROOT.parents[2]
ORIGINAL = WORKSPACE / "ci-audit/recovered-20261105/full-fb9-complete-archive/decoded-verified-v1/full-workspace-catalog.stdout"

assert not OUT.exists(), "preserve an existing candidate instead of silently replacing it"
shutil.copytree(BASE, OUT, ignore=shutil.ignore_patterns("__pycache__"))
raw = ORIGINAL.read_bytes()
assert len(raw) == 2846923
assert hashlib.sha256(raw).hexdigest() == "37aa98bace85dfa81d9c729820de24912d913bd85c3a10b60243f4dba67e4001"
compressed = bz2.compress(raw)
(OUT / "observed-original-A-catalog.json").write_text(json.dumps({
    "schema": "hepta-b16-observed-original-A-catalog-v1",
    "role": "HISTORICAL_ORIGINAL_CATALOG_ONLY",
    "source_tree": "fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff",
    "argv": ["cargo", "nextest", "list", "--locked", "--cargo-profile", "dev-small", "--message-format=json"],
    "original_exit_code": 0,
    "encoding": "bzip2+base64",
    "original": {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                 "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()},
    "compressed": {"bytes": len(compressed), "sha256": hashlib.sha256(compressed).hexdigest()},
    "scope": "Exact historical bytes, including original paths. Catalog presence is not test execution or a current-host artifact receipt.",
    "data": base64.b64encode(compressed).decode(),
}, indent=2) + "\n")

path = OUT / "b16_build_only.py"
text = path.read_text()
text = text.replace("import collections\n", "import base64\nimport bz2\nimport collections\nimport hashlib\n", 1)
marker = "\ndef load_build_only(binding):\n"
assert text.count(marker) == 1
text = text.replace(marker, '''
def original_catalog():
    envelope = json.loads(Path(__file__).with_name("observed-original-A-catalog.json").read_bytes())
    need(envelope.get("schema") == "hepta-b16-observed-original-A-catalog-v1" and
         envelope.get("encoding") == "bzip2+base64", "original A catalog envelope differs")
    raw = bz2.decompress(base64.b64decode(envelope["data"], validate=True))
    need(len(raw) == 2846923 and hashlib.sha256(raw).hexdigest() ==
         "37aa98bace85dfa81d9c729820de24912d913bd85c3a10b60243f4dba67e4001",
         "original A catalog bytes differ")
    return json.loads(raw)


def catalog_case_counter(catalog):
    cases = collections.Counter()
    for binary_id, suite in catalog["rust-suites"].items():
        for name, item in suite["testcases"].items():
            ignored, selected = item.get("ignored"), item.get("filter-match")
            need((ignored is False and selected == {"status": "matches"}) or
                 (ignored is True and selected == {"status": "mismatch", "reason": "ignored"}),
                 "build-only catalog contains a non-original filter form")
            cases[(binary_id, name, ignored)] += 1
    return cases


def load_build_only(binding):
''', 1)
old = '''    need(all(item["filter-match"]["status"] == "matches" for suite in catalog["rust-suites"].values()
             for item in suite["testcases"].values()), "build-only catalog was filtered")'''
new = '''    original_cases = catalog_case_counter(original_catalog())
    need(sum(count for (_, _, ignored), count in original_cases.items() if not ignored) == 19506 and
         sum(count for (_, _, ignored), count in original_cases.items() if ignored) == 57,
         "original A catalog counts differ")
    need(catalog_case_counter(catalog) == original_cases,
         "build-only complete original 19506/57 named case Counter differs")'''
assert text.count(old) == 1
path.write_text(text.replace(old, new, 1))

path = OUT / "test_build_only_guard.py"
text = path.read_text()
text = text.replace('"""Only provenance guards, using tiny synthetic files; no native qualification."""',
                    '"""Real original catalog, synthetic provenance files; no native qualification."""', 1)
text = text.replace("import copy\n", "import base64\nimport bz2\nimport copy\nimport hashlib\n", 1)
old = '        self.family = json.loads(frozen_path.read_bytes())\n'
new = '''        self.family = json.loads(frozen_path.read_bytes())
        envelope = json.loads((Path(__file__).parent / "observed-original-A-catalog.json").read_bytes())
        raw_catalog = bz2.decompress(base64.b64decode(envelope["data"], validate=True))
        self.assertEqual(hashlib.sha256(raw_catalog).hexdigest(),
                         "37aa98bace85dfa81d9c729820de24912d913bd85c3a10b60243f4dba67e4001")
        self.original_catalog = json.loads(raw_catalog)
        original_cases = [case for suite in self.original_catalog["rust-suites"].values()
                          for case in suite["testcases"].values()]
        self.assertEqual(sum(case["ignored"] is False for case in original_cases), 19506)
        self.assertEqual(sum(case["ignored"] is True for case in original_cases), 57)
'''
assert text.count(old) == 1
text = text.replace(old, new, 1)
old = '"binary-path": program["path"], "testcases": {"fixture": {"filter-match": {"status": "matches"}}},'
new = '"binary-path": program["path"],\n                "testcases": copy.deepcopy(self.original_catalog["rust-suites"][row["binary_id"]]["testcases"]),'
assert text.count(old) == 1
text = text.replace(old, new, 1)
marker = '\n\nif __name__ == "__main__":\n'
assert text.count(marker) == 1
text = text.replace(marker, '''
    def test_original_catalog_rejects_other_filter_forms(self):
        eligible = next((sid, name) for sid, suite in self.catalog["rust-suites"].items()
                        for name, case in suite["testcases"].items() if case["ignored"] is False)
        ignored = next((sid, name) for sid, suite in self.catalog["rust-suites"].items()
                      for name, case in suite["testcases"].items() if case["ignored"] is True)
        mutations = [
            (eligible, {"ignored": False, "filter-match": {"status": "mismatch", "reason": "ignored"}}),
            (eligible, {"ignored": False, "filter-match": {"status": "matches", "reason": "ignored"}}),
            (ignored, {"ignored": True, "filter-match": {"status": "matches"}}),
            (ignored, {"ignored": True, "filter-match": {"status": "mismatch", "reason": "expression"}}),
            (ignored, {"ignored": True, "filter-match": {"status": "mismatch", "reason": "ignored", "extra": True}}),
            (eligible, {"ignored": 0, "filter-match": {"status": "matches"}}),
        ]
        for (sid, name), replacement in mutations:
            changed = copy.deepcopy(self.catalog)
            changed["rust-suites"][sid]["testcases"][name] = replacement
            pin = self.write("catalog.json", changed)
            self.receipt["catalog"] = self.receipt["commands"][2]["stdout"] = pin
            self.pin_receipt()
            with self.subTest(replacement=replacement), self.assertRaisesRegex(RuntimeError, "non-original filter form"):
                load_build_only(self.binding)

    def test_original_catalog_rejects_different_names_or_ignored_membership(self):
        eligible = next((sid, name) for sid, suite in self.catalog["rust-suites"].items()
                        for name, case in suite["testcases"].items() if case["ignored"] is False)
        ignored = next((sid, name) for sid, suite in self.catalog["rust-suites"].items()
                      for name, case in suite["testcases"].items() if case["ignored"] is True)
        for mutation in ("eligible-name", "ignored-name", "swap-ignored-membership"):
            changed = copy.deepcopy(self.catalog)
            if mutation == "swap-ignored-membership":
                for (sid, name), value in ((eligible, True), (ignored, False)):
                    case = changed["rust-suites"][sid]["testcases"][name]
                    case["ignored"] = value
                    case["filter-match"] = {"status": "mismatch", "reason": "ignored"} if value else {"status": "matches"}
            else:
                sid, name = eligible if mutation == "eligible-name" else ignored
                cases = changed["rust-suites"][sid]["testcases"]
                cases[name + "__unauthorized_replacement"] = cases.pop(name)
            pin = self.write("catalog.json", changed)
            self.receipt["catalog"] = self.receipt["commands"][2]["stdout"] = pin
            self.pin_receipt()
            with self.subTest(mutation=mutation), self.assertRaisesRegex(RuntimeError, "named case Counter differs"):
                load_build_only(self.binding)


if __name__ == "__main__":
''', 1)
path.write_text(text)
print(json.dumps({"candidate": str(OUT), "reference_envelope_bytes": (OUT / "observed-original-A-catalog.json").stat().st_size}))
