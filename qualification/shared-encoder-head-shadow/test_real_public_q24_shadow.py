"""Negative controls for a physically saved public Encoder Feature Snapshot."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from hepta_shared_encoder_shadow import audited_inputs, run

ARTIFACT = Path(__file__).with_name('stem-real-public-q24-feature-snapshot.zip')
ROOT = 'public-q24-feature-snapshot/'


def build_mutated(member, mutator):
    with zipfile.ZipFile(ARTIFACT) as source:
        entries={i.filename:source.read(i.filename) for i in source.infolist()}
    entries[member] = mutator(entries[member])
    # Raw checksum fields are not signatures; recompute them to test semantic gates.
    if member in (ROOT+'case-registry.json', ROOT+'feature-q24.safetensors'):
        sealed=json.loads(entries[ROOT+'SEALED.json'])
        item=member[len(ROOT):]
        sealed['files'][item]['sha256']=hashlib.sha256(entries[member]).hexdigest()
        sealed['files'][item]['bytes']=len(entries[member])
        entries[ROOT+'SEALED.json']=json.dumps(sealed,separators=(',',':')).encode()
    if member==ROOT+'SEALED.json' or member in (ROOT+'case-registry.json', ROOT+'feature-q24.safetensors'):
        verdict=json.loads(entries['public-q24-independent-verdict.json'])
        verdict['sealed_sha256']=hashlib.sha256(entries[ROOT+'SEALED.json']).hexdigest()
        entries['public-q24-independent-verdict.json']=json.dumps(verdict,separators=(',',':')).encode()
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED) as dest:
        for filename,data in entries.items():dest.writestr(filename,data)
    return buf.getvalue()


class ShadowTests(unittest.TestCase):
    def test_exact_archived_model_features_and_predictions(self):
        d=run(ARTIFACT)
        self.assertEqual(d['training_n'],64)
        self.assertEqual(d['unscored_official_test_n'],32)
        self.assertEqual(d['model_costs']['linear']['trainable_parameters'],132)
        self.assertEqual(d['model_costs']['gated_rank4']['trainable_parameters'],1288)
        self.assertFalse(d['future_window_or_ndu_verified'])

    def test_rejects_heldout_label_even_with_unsigned_hashes_recomputed(self):
        def contaminate(raw):
            d=json.loads(raw)
            d['heldout'][0]['label']=3
            return json.dumps(d,separators=(',',':')).encode()
        payload=build_mutated(ROOT+'case-registry.json',contaminate)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'mutated.zip';p.write_bytes(payload)
            with self.assertRaisesRegex(ValueError,'case leakage/shape'):
                audited_inputs(p)

    def test_rejects_production_authority_even_with_unsigned_verdict_recomputed(self):
        def escalate(raw):
            d=json.loads(raw)
            d['production_qualification']=True
            return json.dumps(d,separators=(',',':')).encode()
        payload=build_mutated(ROOT+'SEALED.json',escalate)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'mutated.zip';p.write_bytes(payload)
            with self.assertRaisesRegex(ValueError,'overstated source authority'):
                audited_inputs(p)

    def test_rejects_corrupt_q24_even_with_unsigned_hashes_recomputed(self):
        def corrupt(raw):
            return raw[:-1]+bytes([raw[-1]^255])
        payload=build_mutated(ROOT+'feature-q24.safetensors',corrupt)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'mutated.zip';p.write_bytes(payload)
            with self.assertRaises(Exception):
                audited_inputs(p)

if __name__=='__main__':unittest.main()
