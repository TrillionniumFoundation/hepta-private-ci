import unittest

from control_engineering_v2.status_projection import status_projection


class StatusProjectionTests(unittest.TestCase):
    def test_projection_keeps_every_external_and_authority_gate_false(self):
        value = status_projection(
            {
                "sourceRootPresent": True,
                "productCallerState": "defined",
                "productionWriterState": "defined",
                "observedAtHead": {"commit": "a" * 40, "tree": "b" * 40},
                "sourceObjects": [],
                "claimBoundary": {
                    "nativeSourceMappingComplete": True,
                    "productionImplementation": True,
                    "productExecutionProved": True,
                    "independentAcceptance": True,
                    "activation": True,
                    "release": True,
                },
            }
        )
        self.assertFalse(value["productionImplementation"])
        self.assertFalse(value["claimBoundary"]["independentAcceptance"])
        self.assertFalse(value["claimBoundary"]["activation"])
        self.assertFalse(value["claimBoundary"]["release"])
        self.assertFalse(any(value["externalProductionGates"].values()))
        self.assertFalse(value["runtimeAuthority"])
        self.assertFalse(value["releaseAuthority"])


if __name__ == "__main__":
    unittest.main()
