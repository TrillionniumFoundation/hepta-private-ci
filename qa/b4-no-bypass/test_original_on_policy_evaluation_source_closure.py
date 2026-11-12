"""Close paired on-policy provenance without manufacturing execution authority.

These are source-boundary mutations. They do not establish a production
Evaluator-only grant, eligible real data, native adoption or an ordinary task.
"""
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

from rust_source_marker_support import source_marker_span

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_on_policy_evaluation_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"

EXPECTED = {
    "learning_paired_source_protocol": [
        "codex-rs/hepta-agentd/src/circuit_on_policy_evaluation_read.rs"
    ],
    "learning_paired_source_checkpoint": [
        "codex-rs/hepta-agentd/src/circuit_on_policy_evaluation_episode.rs",
        "codex-rs/hepta-agentd/src/circuit_on_policy_evaluation_records.rs"
    ],
    "learning_paired_cohort_capture": [],
    "learning_paired_holdout_provider": [],
    "learning_paired_cohort_cold": [],
    "learning_paired_cohort_after_release": [],
    "learning_paired_cohort_retaining": [
        "codex-rs/hepta-agentd/src/circuit_on_policy_evaluation.rs"
    ],
    "learning_paired_cohort_current": [
        "codex-rs/hepta-agentd/src/circuit_on_policy_evaluation.rs",
        "codex-rs/hepta-agentd/src/circuit_evaluation_cohort_custody.rs"
    ],
    "learning_paired_cohort_member": [
        "codex-rs/hepta-agentd/src/circuit_evaluation_cohort_custody.rs"
    ],
    "learning_paired_cohort_authenticate": [
        "codex-rs/hepta-agentd/src/circuit_evaluation_cohort_custody.rs"
    ],
    "learning_paired_cohort_material": [
        "codex-rs/hepta-agentd/src/circuit_evaluation_cohort_custody.rs"
    ],
    "learning_paired_cohort_physical_read": [
        "codex-rs/hepta-agentd/src/circuit_on_policy_evaluation.rs"
    ],
    "learning_cohort_custody_current": [
        "codex-rs/hepta-agentd/src/neuron_cell_evaluation_panel_member.rs"
    ],
    "learning_cohort_custody_member": [
        "codex-rs/hepta-agentd/src/neuron_cell_evaluation_panel_binding.rs"
    ],
    "learning_cohort_custody_authenticate": [
        "codex-rs/hepta-agentd/src/neuron_cell_evaluation_panel_member.rs"
    ],
    "learning_cohort_custody_material": [
        "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_export.rs"
    ],
    "learning_shared_cohort_original_material": [
        "codex-rs/hepta-agentd/src/circuit_evaluation_cohort_custody.rs"
    ],
    "cell_paired_learning_evaluation_freeze": []
}
OWNED_RULES = [
    {
        "path": "codex-rs/hepta-agentd/src/circuit_on_policy_evaluation.rs",
        "functions": [
            "fn read_original(",
            "fn read_original_with_clock(",
            "fn into_final_holdout_provider(",
            "fn read_current_with_clock(",
            "fn authority(",
            "fn manifest_digest(",
            "fn manifest_with_clock(",
            "fn release_with_clock(",
            "fn now(",
            "fn into_readback_only(",
            "fn into_original_readback(",
            "fn release_after_consumption(",
            "fn release_paired_after_consumption("
        ],
        "generic": []
    },
    {
        "path": "codex-rs/hepta-agentd/src/circuit_on_policy_evaluation_read.rs",
        "functions": [
            "fn read_original_material(",
            "fn read_sources("
        ],
        "generic": []
    },
    {
        "path": "codex-rs/hepta-agentd/src/circuit_on_policy_evaluation_readback.rs",
        "functions": [
            "fn retaining(",
            "fn read_current(",
            "fn read_current_with_clock(",
            "fn require_original_member(",
            "fn authenticate_current(",
            "fn authority(",
            "fn original_model_commitment("
        ],
        "generic": []
    },
    {
        "path": "codex-rs/hepta-agentd/src/circuit_on_policy_evaluation_binding.rs",
        "functions": [
            "fn validate_configuration(",
            "fn authenticate_training(",
            "fn require_plan(",
            "fn pairing_contract(",
            "fn episode_lineage("
        ],
        "generic": []
    },
    {
        "path": "codex-rs/hepta-agentd/src/circuit_on_policy_evaluation_episode.rs",
        "functions": [
            "fn read_episode(",
            "fn probability(",
            "fn observation("
        ],
        "generic": []
    },
    {
        "path": "codex-rs/hepta-agentd/src/circuit_on_policy_evaluation_contract.rs",
        "functions": [
            "fn canonical_digest(",
            "fn validate(",
            "fn push_input_fields(",
            "fn source_input(",
            "fn input_digest(",
            "fn require_input("
        ],
        "generic": [
            "pub(super) const MAX_EPISODES: usize = 64;"
        ]
    },
    {
        "path": "codex-rs/hepta-agentd/src/circuit_on_policy_evaluation_protocol.rs",
        "functions": [
            "fn canonical_digest(",
            "fn candidate_definition(",
            "fn require_original(",
            "fn require_objective(",
            "fn require_publication(",
            "fn commit("
        ],
        "generic": []
    },
    {
        "path": "codex-rs/hepta-agentd/src/circuit_on_policy_evaluation_records.rs",
        "functions": [
            "fn assemble(",
            "fn append_arm(",
            "fn history_digest("
        ],
        "generic": []
    },
    {
        "path": "codex-rs/hepta-agentd/src/circuit_evaluation_cohort_custody.rs",
        "functions": [
            "fn read_current(",
            "fn require_original_member(",
            "fn authenticate_current(",
            "fn original_model_commitment("
        ],
        "generic": []
    },
    {
        "path": "codex-rs/hepta-agentd/src/circuit_task_source_readback.rs",
        "functions": [
            "fn require_original_evaluation_protocol("
        ],
        "generic": []
    },
    {
        "path": "codex-rs/hepta-agentd/src/neuron_cell_evaluation_on_policy.rs",
        "functions": [],
        "generic": [
            "fn freeze_paired_cell_learning_evaluation_plan_v1<"
        ]
    },
    {
        "path": "codex-rs/hepta-agentd/src/neuron_cell_evaluation_on_policy_proofs.rs",
        "functions": [
            "fn contract(",
            "fn holdout(",
            "fn require_pairing("
        ],
        "generic": []
    },
    {
        "path": "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_proofs.rs",
        "functions": [
            "fn execution(",
            "fn cohort(",
            "fn holdout("
        ],
        "generic": []
    },
    {
        "path": "codex-rs/hepta-agentd/src/circuit_original_evaluation_cohort_readback.rs",
        "functions": [
            "fn original_model_commitment("
        ],
        "generic": []
    },
    {
        "path": "codex-rs/hepta-agentd/src/circuit_task_source_policy.rs",
        "functions": [
            "fn read(",
            "fn new(",
            "fn blob(",
            "fn end(",
            "fn checkpoint_before("
        ],
        "generic": []
    },
    {
        "path": "codex-rs/hepta-agentd/src/neuron_cell_evaluation_panel_contract.rs",
        "functions": [
            "fn new(",
            "fn authority("
        ],
        "generic": []
    },
    {
        "path": "codex-rs/hepta-agentd/src/neuron_cell_evaluation_panel_binding.rs",
        "functions": [
            "fn validate_original_members(",
            "fn require_observed_panel(",
            "fn seal_observed_panel("
        ],
        "generic": []
    },
    {
        "path": "codex-rs/hepta-agentd/src/neuron_cell_evaluation_panel_member.rs",
        "functions": [
            "fn read_original(",
            "fn read_cells(",
            "fn authenticate("
        ],
        "generic": []
    },
    {
        "path": "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_export.rs",
        "functions": [
            "fn begin_model_material_transfer(",
            "fn finish_model_material_transfer(",
            "fn read_model_material_export(",
            "fn finish_model_material_export(",
            "fn member("
        ],
        "generic": []
    }
]


def function_body(source, marker):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    if code.count(marker) != 1:
        raise AssertionError(("unique actual function", marker))
    start = code.index(marker)
    opening = code.index("{", start)
    depth = 1
    end = opening + 1
    while end < len(code) and depth:
        depth += (code[end] == "{") - (code[end] == "}")
        end += 1
    if depth:
        raise AssertionError(("complete actual function", marker))
    return start, end, code[start:end]


def require_generic_scope(source, row):
    for sequence in row.get("required_order", []):
        if not sequence[0].startswith("fn "):
            continue
        _, _, body = function_body(source, sequence[0])
        cursor = 0
        for marker in sequence:
            found = body.find(marker, cursor)
            if found < cursor:
                raise AssertionError(("guard outside original generic function", marker))
            cursor = found + len(marker)


def require_literal(source, function, introduction, value):
    start, end = (0, len(source)) if function is None else function_body(source, function)[:2]
    code = PROOF._strip_rust_non_code(source)
    opening, closing = source_marker_span(code, introduction, start, end)
    if not code[opening:closing].strip():
        raise AssertionError("literal declaration is not executable source")
    if re.match(r'\s*b"' + re.escape(value) + r'"', source[closing:end]) is None:
        raise AssertionError(("original comparison domain", value))


class OriginalOnPolicyEvaluationClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        cls.rows = []
        for expected in OWNED_RULES:
            matches = [
                row for row in cls.manifest["protected_file"]
                if row["path"] == expected["path"]
                and [item["function"] for item in row.get("required_function_order", [])]
                == expected["functions"]
                and [item[0] for item in row.get("required_order", [])]
                == expected["generic"]
            ]
            if len(matches) != 1:
                raise AssertionError(("one complete protected record", expected, len(matches)))
            cls.rows.append(matches[0])

    def verifies(self, row, source):
        require_generic_scope(source, row)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / row["path"]
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": [row]})

    def rejects(self, row, source):
        with self.assertRaises((PROOF.VerificationFailure, AssertionError)):
            self.verifies(row, source)

    def test_exact_original_paired_and_closed_cohort_edges(self):
        paths = {row["path"] for row in self.rows}
        for identifier in EXPECTED:
            row = self.boundaries[identifier]
            paths.add(row.definition_path)
            paths.update(row.product_callers)
        sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
            for path in paths
        }
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, tuple(expected))
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, ())
                extra = dict(sources)
                method = row.symbol.rsplit("::", 1)[-1]
                extra[AGENT + "unregistered_paired_owner.rs"] = (
                    f"fn bypass(owner: &mut {row.receiver_type}) {{ owner.{method}(); }}"
                    if row.receiver_type else f"fn bypass() {{ {row.symbol}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_complete_records_preserve_shared_and_paired_guards(self):
        for row in self.rows:
            with self.subTest(path=row["path"]):
                self.verifies(row, (ROOT / row["path"]).read_text())
        # These paths intentionally have separate old and new complete records.
        for name in (
            "circuit_task_source_readback.rs",
            "circuit_original_evaluation_cohort_readback.rs",
        ):
            records = [row for row in self.manifest["protected_file"]
                       if row["path"] == AGENT + name]
            self.assertGreaterEqual(len(records), 2)
            functions = {item["function"] for row in records
                         for item in row.get("required_function_order", [])}
            self.assertIn(
                "fn require_original_input(" if name.startswith("circuit_task_source")
                else "fn read_current_with_clock(", functions
            )

    def test_each_actual_producer_guard_cannot_move_to_a_comment(self):
        for row in self.rows:
            source = (ROOT / row["path"]).read_text()
            for rule in row.get("required_function_order", []):
                start, _, body = function_body(source, rule["function"])
                candidates = [
                    marker for marker in rule["sequence"]
                    if body.count(marker) == 1 and not marker.startswith("fn ")
                    and marker not in ("Ok(())", "Ok(current)")
                ]
                self.assertTrue(candidates, (row["path"], rule["function"]))
                marker = max(candidates, key=len)
                offset = start + body.index(marker)
                with self.subTest(path=row["path"], function=rule["function"]):
                    self.rejects(row, source[:offset] + source[offset + len(marker):]
                                 + "\n/* " + marker + " */\n")

    def test_original_authority_and_outcome_substitutions_are_rejected(self):
        for row in self.rows:
            source = (ROOT / row["path"]).read_text()
            for marker in row["forbidden"]:
                with self.subTest(path=row["path"], forbidden=marker):
                    self.rejects(row, source + "\n" + marker + "\n")

    def test_freeze_guards_stay_inside_the_one_original_generic_function(self):
        row = next(row for row in self.rows
                   if row["path"] == AGENT + "neuron_cell_evaluation_on_policy.rs")
        source = (ROOT / row["path"]).read_text()
        self.verifies(row, source)
        marker = "freeze_paired_on_policy_product_evaluation_plan_v1("
        start, end, body = function_body(source, "fn freeze_paired_cell_learning_evaluation_plan_v1<")
        offset = start + body.index(marker)
        changed = source[:offset] + source[offset + len(marker):]
        changed += "\nfn unrelated() { " + marker + " } }\n"
        self.rejects(row, changed)
        # Keep every ordered marker globally visible, but put the body in an
        # unrelated function. The additional function-scope check must reject.
        opening = source.index("{", start, end)
        moved = source[:opening + 1] + "\n}\nfn unrelated() {\n" + source[opening + 1:]
        self.rejects(row, moved)

    def test_frozen_identity_fresh_empty_and_actual_principal_are_required(self):
        checks = (
            ("circuit_on_policy_evaluation_contract.rs", "fn validate(",
             "self.history.len() + 2 * self.pairs.len() > MAX_EPISODES"),
            ("circuit_on_policy_evaluation_contract.rs", "fn validate(",
             "!runs.insert(&row.candidate.behavior_run_id)"),
            ("circuit_on_policy_evaluation_episode.rs", "fn read_episode(",
             "!policy.checkpoint_before().is_zero()"),
            ("circuit_on_policy_evaluation_records.rs", "fn append_arm(",
             "cluster_id: row.principal.clone()"),
            ("circuit_on_policy_evaluation_records.rs", "fn assemble(",
             "left.source.history_digest() == right.source.history_digest()"),
        )
        cap_row = next(row for row in self.rows
                       if row["path"] == AGENT + "circuit_on_policy_evaluation_contract.rs")
        cap_source = (ROOT / cap_row["path"]).read_text()
        self.rejects(cap_row, cap_source.replace("MAX_EPISODES: usize = 64;",
                                                "MAX_EPISODES: usize = 128;", 1))
        for name, function, marker in checks:
            row = next(row for row in self.rows if row["path"] == AGENT + name)
            source = (ROOT / row["path"]).read_text()
            start, end, _ = function_body(source, function)
            opening, closing = source_marker_span(source, marker, start, end)
            with self.subTest(path=name, marker=marker):
                self.rejects(row, source[:opening] + source[closing:])

    def test_distinct_domains_are_real_code_and_cannot_be_comment_substitutes(self):
        checks = (
            ("circuit_on_policy_evaluation_contract.rs", "fn canonical_digest(",
             "let mut bytes =", r"hepta.circuit.original-on-policy-cohort-rule.v1\0"),
            ("circuit_on_policy_evaluation_protocol.rs", "fn canonical_digest(",
             "let mut bytes =", r"hepta.circuit.original-on-policy-protocol.v1\0"),
            ("circuit_on_policy_evaluation_readback.rs", "fn read_current_with_clock(",
             "let mut bytes =", r"hepta.circuit.original-on-policy-cohort-current.v1\0"),
            ("neuron_cell_evaluation_on_policy.rs", "fn freeze_paired_cell_learning_evaluation_plan_v1<",
             "Digest32::of_parts(&[", r"hepta.agentd.cell-paired-on-policy-estimand.v1\0"),
            ("neuron_cell_evaluation_on_policy_proofs.rs", None,
             "const PLAN: &[u8] =", "hepta.intelligence-eval.product-frozen-paired-on-policy.v1"),
            ("neuron_cell_evaluation_on_policy_proofs.rs", None,
             "const PAIRS: &[u8] =", "hepta.intelligence-eval.on-policy-pair-contract.v1"),
        )
        for name, function, introduction, value in checks:
            source = (ROOT / AGENT / name).read_text()
            with self.subTest(path=name, domain=value):
                require_literal(source, function, introduction, value)
                changed = source.replace(value, value + ".wrong", 1)
                changed += "\n// " + introduction + ' b"' + value + '"\n'
                with self.assertRaises(AssertionError):
                    require_literal(changed, function, introduction, value)

    def test_shared_release_and_cross_mode_current_are_explicitly_closed(self):
        checks = (
            ("circuit_on_policy_evaluation.rs", "fn release_after_consumption(",
             "Err(ProductProviderErrorV1::Rejected)"),
            ("circuit_evaluation_cohort_custody.rs", "fn require_original_member(",
             "_ => return Err(Error::Binding("),
            ("circuit_evaluation_cohort_custody.rs", "fn authenticate_current(",
             "_ => Err(Error::Binding("),
            ("circuit_evaluation_cohort_custody.rs", "fn original_model_commitment(",
             "_ => Err(Error::Binding("),
        )
        for name, function, marker in checks:
            row = next(row for row in self.rows if row["path"] == AGENT + name)
            source = (ROOT / row["path"]).read_text()
            start, end, _ = function_body(source, function)
            opening, closing = source_marker_span(source, marker, start, end)
            with self.subTest(path=name, method=function):
                self.rejects(row, source[:opening] + source[closing:])


if __name__ == "__main__":
    unittest.main()
