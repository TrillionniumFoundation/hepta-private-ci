"""Small source fixtures only; no N256 numerical implementation is invoked."""

import copy
import json
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_reference_provider_hold import method_hold


ROOT = Path(__file__).parent


def future_record():
    record = {name: "a" * 64 for name in method_hold.REQUIRED_METHOD_SHA_FIELDS}
    record.update(
        {
            "method_id": "certified_sparse_uniformization_v1",
            "imports_candidate_or_oracle": False,
            "uses_scipy_expm_multiply": False,
            "shared_numeric_kernel": False,
            "coordinate_denominator": method_hold.EXPECTED_DENOMINATOR,
            "capsules": method_hold.EXPECTED_CAPSULES,
            "lane_capsules": method_hold.EXPECTED_LANE_CAPSULES,
        }
    )
    record.update({name: True for name in method_hold.REQUIRED_CERTIFICATIONS})
    return record


class ReferenceProviderHoldTest(unittest.TestCase):
    def test_request_is_truthful_hold_and_rejects_execution(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        self.assertEqual(method_hold.validate_source_request(request), request)
        with self.assertRaises(method_hold.AdmissionRequired):
            method_hold.require_provider_admission(ROOT / "REQUEST.json", None)

    def test_shared_scipy_kernel_is_detected(self):
        source = "from scipy.sparse.linalg import expm_multiply\n"
        assessment = method_hold.assess_frozen_numeric_kernels(source, source)
        self.assertEqual(
            assessment,
            method_hold.KernelAssessment(True, True, True),
        )

    def test_distinct_small_fixture_is_not_mislabeled_as_shared(self):
        candidate = "from scipy.sparse.linalg import expm_multiply\n"
        independent = "def uniformize(operator, time):\n    return operator, time\n"
        assessment = method_hold.assess_frozen_numeric_kernels(candidate, independent)
        self.assertEqual(
            assessment,
            method_hold.KernelAssessment(True, False, False),
        )

    def test_future_record_requires_independent_method_and_every_certificate(self):
        record = future_record()
        self.assertEqual(method_hold.validate_future_method_record(record), record)
        shared = copy.deepcopy(record)
        shared["uses_scipy_expm_multiply"] = True
        with self.assertRaisesRegex(ValueError, "may not share"):
            method_hold.validate_future_method_record(shared)
        missing = copy.deepcopy(record)
        missing["certifies_signed_l1_tail"] = False
        with self.assertRaisesRegex(ValueError, "signed_l1_tail"):
            method_hold.validate_future_method_record(missing)

    def test_future_record_rejects_reused_source_and_denominator_change(self):
        record = future_record()
        record["provider_source_sha256"] = method_hold.ORACLE_SOURCE_SHA256
        with self.assertRaisesRegex(ValueError, "not independent"):
            method_hold.validate_future_method_record(record)
        record = future_record()
        record["coordinate_denominator"] -= 1
        with self.assertRaisesRegex(ValueError, "denominator mismatch"):
            method_hold.validate_future_method_record(record)


if __name__ == "__main__":
    unittest.main()
