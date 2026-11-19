"""Synthetic receipt-boundary tests only; no historical inputs, gzip or science."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

fixed=load('receipt_fixed',ROOT/'restore_historical_run_assets.py')

class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.source=Path(self.tmp.name)/'source';self.source.mkdir()
        self.output=Path(self.tmp.name)/'output';self.output.mkdir()
        descriptor=self.source/fixed.DESCRIPTOR;descriptor.parent.mkdir(parents=True);descriptor.write_bytes(b'{}\n')
        assets={p:(b'{}\n' if p.endswith('.json') else b'opaque-test-bytes') for p in fixed.ASSET_PATHS}
        markers={p:b'{}\n' for p in fixed.MARKER_PATHS}
        self.prepared={'assets':assets,'metadata_raw':markers,'metadata_json':{},'maps':{'assets':{p:{'original_bytes':len(b),'original_sha256':fixed.H(b)} for p,b in assets.items()},'markers':{p:{'bytes':len(b),'sha256':fixed.H(b)} for p,b in markers.items()}}}
        # Deliberately isolate receipt binding. Historical relation correctness is
        # not exercised or claimed by these synthetic fixtures.
        self.checks=['synthetic-relation-only']
        for module in [fixed]:
            original=module.relations;module.relations=lambda *args:self.checks
            self.addCleanup(setattr,module,'relations',original)
        for p,b in {**assets,**markers,fixed.NOTE_PATH:fixed.NOTE}.items():
            dest=self.output/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b)
        self.receipt=fixed.completion_receipt(self.source,self.output,self.prepared,self.checks)
    def write(self,receipt):
        (self.output/fixed.RECEIPT_PATH).write_bytes(fixed.canonical(receipt))
    def inspect(self,module=fixed):return module.inspect_output(self.source,self.output,self.prepared)
    def test_precompletion_no_receipt(self):self.assertEqual(self.inspect(),self.checks)
    def test_exact_receipt_accepted(self):self.write(self.receipt);self.assertEqual(self.inspect(),self.checks)
    def test_reordered_receipt_json_accepted(self):
        text=json.dumps(dict(reversed(list(self.receipt.items()))),indent=4)
        (self.output/fixed.RECEIPT_PATH).write_text(text)
        self.assertEqual(self.inspect(),self.checks)
    def test_relocated_output_requires_new_receipt(self):
        self.write(self.receipt)
        moved=self.output.with_name('moved-output');self.output.rename(moved);self.output=moved
        with self.assertRaisesRegex(fixed.ContractError,'inspection-receipt'):self.inspect()
    def test_relocated_source_requires_new_receipt(self):
        self.write(self.receipt)
        moved=self.source.with_name('moved-source');self.source.rename(moved);self.source=moved
        with self.assertRaisesRegex(fixed.ContractError,'inspection-receipt'):self.inspect()
    def test_synthetic_misbound_receipt_rejected(self):
        bad=copy.deepcopy(self.receipt);bad['descriptor_sha256']='0'*64;self.write(bad)
        with self.assertRaisesRegex(fixed.ContractError,'inspection-receipt'):self.inspect()
    def test_each_top_level_metadata_mutation_rejected(self):
        for key in self.receipt:
            with self.subTest(key=key):
                bad=copy.deepcopy(self.receipt);bad[key]='wrong';self.write(bad)
                with self.assertRaisesRegex(fixed.ContractError,'inspection-receipt'):self.inspect()
    def test_missing_extra_fields_rejected(self):
        for mode in ['missing','extra']:
            bad=copy.deepcopy(self.receipt)
            if mode=='missing':bad.pop('files')
            else:bad['unexpected']=True
            self.write(bad)
            with self.assertRaisesRegex(fixed.ContractError,'inspection-receipt'):self.inspect()
    def test_nested_file_metadata_rejected(self):
        first=fixed.ASSET_PATHS[0]
        for value in [0,True,999]:
            bad=copy.deepcopy(self.receipt);bad['files'][first]['bytes']=value;self.write(bad)
            with self.assertRaisesRegex(fixed.ContractError,'inspection-receipt'):self.inspect()
    def test_existing_receipt_never_excuses_missing_target(self):
        self.write(self.receipt);(self.output/fixed.ASSET_PATHS[0]).unlink()
        with self.assertRaises(FileNotFoundError):self.inspect()
    def test_descriptor_drift_rejected(self):
        self.write(self.receipt);(self.source/fixed.DESCRIPTOR).write_bytes(b'{"changed":true}\n')
        with self.assertRaisesRegex(fixed.ContractError,'inspection-receipt'):self.inspect()

if __name__=='__main__':unittest.main()
