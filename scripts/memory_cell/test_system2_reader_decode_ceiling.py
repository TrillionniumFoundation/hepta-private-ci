"""Archive pinning, prompt parity and no-leak 128-token Reader controls."""

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system2_multihop_counterfactual import select
from system2_reader_decode_ceiling import (
    NEW_ARMS,
    PARENT_RAW_SEAL,
    PLANNED,
    READER_ID,
    assess,
    decode_128,
    load_parent,
    match_historical,
    run,
)

ARCHIVE = Path(
    os.environ.get(
        "HEPTA_SYSTEM2_DECODE_PARENT",
        "/mnt/data/hepta-system2-counterfactual-hosted-160.zip",
    )
)


class DecodeBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ARCHIVE.is_file():
            cls.parent = load_parent(ARCHIVE)
        else:
            cls.parent = None

    def require_archive(self):
        if self.parent is None:
            self.skipTest("external completed GitHub archive not locally mounted")
        return self.parent

    def test_exact_parent_hash_and_full_census(self):
        p = self.require_archive()
        self.assertEqual((p["verified_files"], len(p["by_key"])), (21, 160))
        self.assertEqual(p["raw_seal"], PARENT_RAW_SEAL)
        self.assertEqual(PLANNED, 96)
        self.assertEqual(len(NEW_ARMS), 3)

    def test_baseline_capped_outputs_are_not_independent_questions(self):
        p = self.require_archive()
        rows = list(p["by_key"].values())
        self.assertEqual(sum(r["reader"]["generated_tokens"] == 64 for r in rows), 99)
        self.assertEqual(len({r["qid"] for r in rows}), 32)
        self.assertEqual(sum(r["arm"] in NEW_ARMS for r in rows), PLANNED)

    def test_original_baseline_response_forbidden_to_mutate(self):
        p = self.require_archive()
        r = next(
            r for r in p["by_key"].values() if r["reader"]["generated_tokens"] < 64
        )
        bad = copy.deepcopy(r)
        bad["reader"]["input_ids_digest"] = "0" * 64
        rec = copy.deepcopy(bad["reader"])
        rec["generated_ids_digest"] = r["reader"]["generated_ids_digest"]
        rec["generated_tokens"] = r["reader"]["generated_tokens"]
        with self.assertRaisesRegex(ValueError, "same-prompt"):
            match_historical(bad, r["reader"], r["answer"])

    def test_capped_64_prefix_must_be_byte_exact(self):
        p = self.require_archive()
        r = next(
            r for r in p["by_key"].values() if r["reader"]["generated_tokens"] == 64
        )
        receipt = copy.deepcopy(r["reader"])
        receipt["first64_ids_digest"] = r["reader"]["generated_ids_digest"]
        self.assertEqual(
            match_historical(r, receipt, r["answer"]), "prefix64-identical"
        )
        receipt["first64_ids_digest"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "first-64"):
            match_historical(r, receipt, r["answer"])
        receipt["first64_ids_digest"] = r["reader"]["generated_ids_digest"]
        receipt["generated_tokens"] = 12
        with self.assertRaises(ValueError):
            match_historical(r, receipt, r["answer"])

    def test_early_stop_must_be_identical_at_larger_limit(self):
        p = self.require_archive()
        r = next(
            r for r in p["by_key"].values() if r["reader"]["generated_tokens"] < 64
        )
        receipt = copy.deepcopy(r["reader"])
        self.assertEqual(match_historical(r, receipt, r["answer"]), "same-early-eos")
        with self.assertRaisesRegex(ValueError, "early-EOS"):
            match_historical(r, receipt, r["answer"] + " other")

    def test_complete_postseal_counterfactual_census(self):
        p = self.require_archive()
        records = []
        for case_pair in p["pairs"]:
            for case in case_pair:
                for arm in NEW_ARMS:
                    row = p["by_key"][case.question.identity, arm]
                    rec = copy.deepcopy(row["reader"])
                    records.append(
                        dict(
                            qid=row["qid"],
                            arm=arm,
                            status="succeeded",
                            answer=row["answer"],
                            receipt=rec,
                            prefix_match="historical-control",
                        )
                    )
        d, s = assess(records, p)
        self.assertEqual((len(d), len(s)), (PLANNED, 3))
        self.assertTrue(all(q["strict64"] == q["strict128"] for q in d))
        self.assertEqual(sum(x["strict64"] for x in s), 0)
        with self.assertRaises(ValueError):
            assess(records[:-1], p)
        with self.assertRaises(ValueError):
            assess(records + [records[0]], p)

    def test_no_input_regeneration_change_while_decoding(self):
        # Same tokenization, same prompt receipt, only output cap changes.
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        import torch
        import sys
        import types

        native = types.ModuleType("native")
        import system2_multihop_evidence

        native.digest = system2_multihop_evidence.digest
        bundle = types.ModuleType("bundle_reader")
        bundle.GENERATION = dict(
            max_new_tokens=64, do_sample=False, num_beams=1, use_cache=True
        )
        bundle.SYSTEM = "Use supplied evidence and cite."
        with patch.dict(sys.modules, {"native": native, "bundle_reader": bundle}):
            reader = SimpleNamespace()
            reader.identity = READER_ID
            reader.tokenizer = SimpleNamespace(
                eos_token_id=10,
                chat_template="chat",
                decode=lambda ids, **kwargs: "TOKEN " + str(len(ids)),
            )
            reader.model = SimpleNamespace(
                config=SimpleNamespace(max_position_embeddings=2048),
                generate=MagicMock(
                    side_effect=lambda input_ids, **kwargs: torch.cat(
                        [input_ids, torch.tensor([[11, 12, 13, 14]], dtype=torch.long)],
                        dim=1,
                    )
                ),
            )
            reader.verify_frozen = lambda: None
            reader.compile_input = lambda q, b, o, **k: (
                [1, 2, 3],
                dict(
                    input_ids_digest="abc",
                    bundle_digest="xyz",
                    query_digest="q",
                    input_tokens=3,
                    token_limit=1024,
                ),
            )

            class Bundle:
                def validate(self, *a, **kw):
                    return None

            answer, receipt = decode_128(
                reader, object(), Bundle(), {}, frontier="pinned"
            )
            self.assertEqual(
                (receipt["generated_tokens"], receipt["max_new_tokens"]), (4, 128)
            )
            self.assertTrue(answer)
            cfg = reader.model.generate.call_args.kwargs
            self.assertEqual(
                (cfg["max_new_tokens"], cfg["do_sample"], cfg["num_beams"]),
                (128, False, 1),
            )

    def test_restricted_score_does_not_count_unsupported_token_as_success(self):
        p = self.require_archive()
        case = p["pairs"][0][0]
        selected = select("missing_start_top3", case.question, case.documents)
        from system2_multihop_counterfactual_trial import score

        result = score(case, selected, case.answer)
        self.assertFalse(result["strict_success"])
        self.assertTrue(result["copied_target_without_path"])

    def test_archive_sha_tampering_is_fatal(self):
        self.require_archive()
        with tempfile.TemporaryDirectory() as t:
            copy_path = Path(t) / "changed.zip"
            raw = ARCHIVE.read_bytes()
            copy_path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
            with self.assertRaises(ValueError):
                load_parent(copy_path)

    def test_full_96_position_immutable_baseline_echo(self):
        p = self.require_archive()
        from types import SimpleNamespace

        class Reader:
            identity = READER_ID

            def verify_frozen(self):
                return None

        def fixed_bundle(case, selected, arm):
            return SimpleNamespace(arm=arm), {}, "same-source-frontier"

        def fake_decode(reader, question, bundle, originals, *, frontier):
            original = p["by_key"][question.identity, bundle.arm]
            receipt = copy.deepcopy(original["reader"])
            receipt["first64_ids_digest"] = receipt["generated_ids_digest"]
            receipt["max_new_tokens"] = 128
            return original["answer"], receipt

        with (
            tempfile.TemporaryDirectory() as td,
            patch("system2_reader_decode_ceiling.load_parent", return_value=p),
            patch("system2_reader_decode_ceiling.evidence", side_effect=fixed_bundle),
            patch("system2_reader_decode_ceiling.decode_128", side_effect=fake_decode),
        ):
            out = Path(td) / "complete"
            result = run(ARCHIVE, out, Reader(), source_commit="c" * 40)
            self.assertEqual(sum(x["completed"] for x in result), PLANNED)
            self.assertEqual([x["strict128"] for x in result], [0, 0, 0])
            seal = json.loads((out / "raw-seal.json").read_text())
            self.assertEqual(
                seal["sha256"],
                hashlib.sha256((out / "raw-answers.jsonl").read_bytes()).hexdigest(),
            )
            self.assertEqual(seal["rows"], 96)
            self.assertFalse((out / "run-failure.json").exists())

    def test_no_model_run_is_counted_on_failure(self):
        p = self.require_archive()

        class Reader:
            identity = READER_ID

            def verify_frozen(self):
                return None

        with (
            tempfile.TemporaryDirectory() as td,
            patch("system2_reader_decode_ceiling.load_parent", return_value=p),
            patch(
                "system2_reader_decode_ceiling.evidence", return_value=(None, {}, "x")
            ),
            patch(
                "system2_reader_decode_ceiling.decode_128",
                side_effect=RuntimeError("injected"),
            ),
        ):
            output = Path(td) / "report"
            with self.assertRaises(RuntimeError):
                run(ARCHIVE, output, Reader(), source_commit="b" * 40)
            self.assertEqual(
                len((output / "starts.jsonl").read_text().splitlines()), PLANNED
            )
            self.assertTrue((output / "run-failure.json").exists())
            self.assertFalse((output / "summary.json").exists())
            lines = [
                json.loads(x)
                for x in (output / "raw-answers.jsonl").read_text().splitlines()
            ]
            self.assertTrue(all(x["status"] == "failed" for x in lines))

    def test_source_identity_is_checked_before_file_creation(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "out"
            with self.assertRaises(ValueError):
                run(ARCHIVE, output, object(), source_commit="wrong")
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
