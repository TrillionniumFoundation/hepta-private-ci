import copy
import hashlib
import unittest

from windows_directory_probe import MODES, capability


def native_facts():
    digest = hashlib.sha256(bytes([1, 2, 3])).hexdigest()
    return {
        "fileIdQuery": {"ok": True},
        "volumeSerialNumber": 7,
        "fileId128": list(range(16)),
        "descriptorRead": {"ok": True},
        "descriptorBytes": [1, 2, 3],
        "descriptorSha256": digest,
        "statePrivateSecurity": {"ok": True, "sha256": digest},
        "stateFullSnapshotAccepted": True,
    }


def collector_trace():
    facts = native_facts()
    mode = {
        "open": {"ok": True},
        "before": facts,
        "after": facts,
        "sameRetainedDirectoryBefore": True,
        "sameRetainedDirectoryAfter": True,
        "rustSyncAll": {"ok": True},
        "flushFileBuffers": {"ok": True, "rawReturn": 1, "rawWin32Error": None},
    }
    return {
        "schema": "hepta.windows-directory-native-probe.v1",
        "diagnosticCollectionCompleted": True,
        "productQualification": False,
        "originalOperator26OrShadow31Executed": False,
        "physicalPowerLossQualified": False,
        "ownedScratchCleanup": {"ok": True},
        "retainedFull128IdentityAndDaclUnchanged": True,
        "retainedBefore": facts,
        "retainedAfter": facts,
        "modes": [{**copy.deepcopy(mode), "mode": name} for name in MODES],
        "unchangedStateDirectorySync": {"ok": True},
    }


class NativeCapabilityAssessmentTests(unittest.TestCase):
    def test_collector_success_does_not_mask_native_failures(self):
        for key in ("open", "rustSyncAll", "flushFileBuffers"):
            trace = collector_trace()
            trace["modes"][-1][key] = {"ok": False, "rawReturn": 0, "rawWin32Error": 5}
            modes, supported = capability(trace)
            self.assertFalse(supported)
            self.assertFalse(modes[-1]["retainedDirectoryFlushSupported"])

    def test_full_128bit_identity_and_exact_dacl_are_required(self):
        for mutation in ("high-byte", "short-id", "dacl", "privacy"):
            trace = collector_trace()
            facts = copy.deepcopy(trace["modes"][-1]["after"])
            if mutation == "high-byte":
                facts["fileId128"][-1] ^= 1
            if mutation == "short-id":
                facts["fileId128"] = facts["fileId128"][:8]
            if mutation == "dacl":
                facts["descriptorBytes"] = [9, 9, 9]
            if mutation == "privacy":
                facts["statePrivateSecurity"]["ok"] = False
            trace["modes"][-1]["after"] = facts
            self.assertFalse(capability(trace)[1])

    def test_missing_duplicate_mode_or_retained_identity_fails_collection(self):
        for mutation in ("missing", "duplicate", "retained"):
            trace = collector_trace()
            if mutation == "missing":
                trace["modes"].pop()
            if mutation == "duplicate":
                trace["modes"][-1]["mode"] = MODES[0]
            if mutation == "retained":
                trace["retainedAfter"] = {}
            with self.assertRaises(ValueError):
                capability(trace)

    def test_real_mode_and_original_state_primitive_are_both_required(self):
        self.assertTrue(capability(collector_trace())[1])
        trace = collector_trace()
        trace["unchangedStateDirectorySync"]["ok"] = False
        self.assertFalse(capability(trace)[1])
