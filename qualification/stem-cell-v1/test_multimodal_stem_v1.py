"""Standalone source-only and adversarial tests: NOT pretrained efficacy tests."""
import dataclasses
import hashlib
import unittest

from multimodal_stem_v1 import (
    AdmissionError, CellHead, FeatureEnvelope, ReuseLedger,
    WIDTH, admit_features, audit_split, select_cells,
)

def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def envelope(raw=b"real feature bytes", modality="text"):
    return FeatureEnvelope(
        modality=modality, original_sha256=sha(b"original"), feature_sha256=sha(raw),
        encoder_sha256=sha(b"encoder"), tokenizer_sha256=sha(b"tokenizer"),
        preprocessor_sha256=sha(b"preproc"), quantization_sha256=sha(b"quant"),
        projection_sha256=sha(b"projection"), principal="p1", purpose="retrieval",
        generation=1, epoch=0, slot_count=1, width=WIDTH,
        timestamps=(10,) if modality in ("audio","video") else (),
        regions=((0,0,1,1),) if modality == "image" else (),
        source_kind="original", reviewed=True,
    )

class StemBoundaryTests(unittest.TestCase):
    def test_admits_exact_bytes(self):
        self.assertEqual(len(admit_features(envelope(), b"real feature bytes")), 64)

    def test_feature_tamper_denied(self):
        with self.assertRaises(AdmissionError):
            admit_features(envelope(), b"tampered")

    def test_unreviewed_denied(self):
        with self.assertRaises(AdmissionError):
            admit_features(dataclasses.replace(envelope(), reviewed=False), b"real feature bytes")

    def test_all_modality_shape(self):
        for m in ("text","image","audio","video"):
            with self.subTest(m=m):
                self.assertEqual(len(envelope(modality=m).key()), 64)

    def test_temporal_missing_denied(self):
        for m in ("video","audio"):
            with self.assertRaises(AdmissionError):
                envelope(modality=m).__class__(**{
                    **envelope(modality=m).__dict__, "timestamps": ()
                }).validate()

    def test_image_missing_regions_denied(self):
        with self.assertRaises(AdmissionError):
            dataclasses.replace(envelope(modality="image"), regions=()).validate()

    def test_scope_and_provenance_not_reused(self):
        base=envelope()
        ledger=ReuseLedger()
        raw=b"real feature bytes"
        self.assertFalse(ledger.access(base,raw))
        self.assertTrue(ledger.access(base,raw))
        changes={"principal":"p2","purpose":"other","generation":2,"epoch":1,
                 "modality":"video","encoder_sha256":sha(b"e2"),
                 "original_sha256":sha(b"new"),"projection_sha256":sha(b"newp")}
        for name,val in changes.items():
            e=dataclasses.replace(base, **{name:val})
            if name=="modality":
                e=dataclasses.replace(e,timestamps=(1,))
            self.assertFalse(ledger.access(e,raw))
        self.assertEqual(ledger.reused_requests,1)

    def test_invalid_metadata(self):
        base=envelope()
        for change in ({"slot_count":0},{"slot_count":257},{"width":383},
                       {"generation":0},{"principal":""},
                       {"encoder_sha256":"ABC"},{"source_kind":"fake"}):
            with self.subTest(change=change), self.assertRaises(AdmissionError):
                dataclasses.replace(base,**change).validate()

    def test_deterministic_head_routing(self):
        rows=[[0.5]*WIDTH]
        heads=[CellHead("b",(0.0,)*WIDTH,1.0),
               CellHead("a",(0.0,)*WIDTH,1.0),
               CellHead("c",(0.0,)*WIDTH,-1.0)]
        self.assertEqual(tuple(x[0] for x in select_cells(heads,rows,2)),("a","b"))

    def test_duplicate_cell_denied(self):
        h=CellHead("a",(0.0,)*WIDTH,0.0)
        with self.assertRaises(AdmissionError):
            select_cells([h,h],[[0.0]*WIDTH])

    def test_nan_or_wrong_shape_denied(self):
        for row in ([[float("nan")]*WIDTH],[[1.0]*383],[[9.0]*WIDTH]):
            with self.assertRaises(AdmissionError):
                select_cells([CellHead("a",(0.0,)*WIDTH,0.0)],row)

    def test_unique_admission_is_not_a_physical_forward(self):
        ledger = ReuseLedger()
        raw = b"real feature bytes"
        self.assertFalse(ledger.access(envelope(), raw))
        self.assertTrue(ledger.access(envelope(), raw))
        self.assertEqual(ledger.unique_feature_admissions, 1)
        self.assertEqual(ledger.reused_requests, 1)
        self.assertFalse(hasattr(ledger, "physical_forward_claims"))

    def test_boolean_generations_and_coordinates_denied(self):
        for fields in ({"generation": True}, {"epoch": False},
                       {"timestamps": (True,)},
                       {"regions": ((0, 0, True, 1),)}):
            base = envelope(modality="image" if "regions" in fields else "video")
            with self.subTest(fields=fields), self.assertRaises(AdmissionError):
                dataclasses.replace(base, **fields).validate()

    def test_nonfinite_final_head_scores_denied(self):
        huge = CellHead("unsafe", (1e308,) * WIDTH, 0)
        with self.assertRaises(AdmissionError):
            select_cells([huge], [[8.0] * WIDTH])

    def test_empty_cell_fleet_denied(self):
        with self.assertRaises(AdmissionError):
            select_cells([], [[0.0] * WIDTH])

    def test_split_cannot_self_authorize(self):
        r=audit_split([0]*200,[1]*200,[1]*200,1.2)
        self.assertEqual(r["delta_future"],1.0)
        self.assertEqual(r["authority"],"DENY_ALL")
        self.assertFalse(r["split_authorized"])
        self.assertFalse(r["quality_attested"])

    def test_split_insufficient_groups_denied(self):
        with self.assertRaises(AdmissionError):
            audit_split([0]*199,[1]*199,[1]*199,0.0)

if __name__ == "__main__":
    unittest.main()
