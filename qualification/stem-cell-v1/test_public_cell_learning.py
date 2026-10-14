import copy
import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

from banking77_material import INTENTS, prepare, acquire, text_key
from matrix_materials import file_sha256
from next_round_matrix import _digest
from public_cell_learning import execute_learning, freeze_plan, score_sealed, validate_inputs


def csv_bytes(split, per_class=20):
    stream=io.StringIO(); writer=csv.writer(stream); writer.writerow(['text','category'])
    for category in INTENTS:
        for i in range(per_class):
            writer.writerow([f'{split} sample {category} {i}',category])
    return stream.getvalue().encode()


def fixture_inputs():
    inputs, labels, _=prepare(csv_bytes('fit'),csv_bytes('heldout'))
    # Small explicit fixture; not passed off as the fixed public subset.
    inputs['fit']=[r for i,r in enumerate(inputs['fit']) if i%16<2]
    inputs['heldout']=[r for i,r in enumerate(inputs['heldout']) if i%8<2]
    inputs['input_id']=_digest({k:v for k,v in inputs.items() if k!='input_id'})
    labels['rows']=[r for i,r in enumerate(labels['rows']) if i%8<2]
    labels['input_id']=inputs['input_id']
    return inputs,labels


class FeatureFixture:
    dimension=4
    receipt={'kind':'explicit_synthetic_fixture','pretrained':False}
    def __init__(self): self.seen=[]; self.verified=False
    def encode(self,row):
        self.seen.append(copy.deepcopy(row))
        raw=hashlib.sha256(row['state'].encode()).digest()
        return torch.tensor([v/255 for v in raw[:4]]),8
    def reverify(self): self.verified=True


class BankingMaterialTests(unittest.TestCase):
    def test_fixed_size_balanced_no_heldout_labels_and_source_identity(self):
        inputs,labels,selection=prepare(csv_bytes('fit'),csv_bytes('heldout'))
        validate_inputs(inputs)
        self.assertEqual([len(inputs[s]) for s in ('fit','heldout')],[64,32])
        self.assertEqual([sum(r['label']==c for r in inputs['fit']) for c in range(4)],[16]*4)
        self.assertTrue(all(set(r)=={'id','text'} for r in inputs['heldout']))
        self.assertEqual(labels['input_id'],inputs['input_id'])
        self.assertEqual(selection['input_id'],inputs['input_id'])

    def test_row_reordering_does_not_change_subset(self):
        original=csv_bytes('fit').decode().splitlines()
        reversed_bytes=('\n'.join(original[:1]+original[1:][::-1])+'\n').encode()
        a=prepare(csv_bytes('fit'),csv_bytes('heldout'))[0]
        b=prepare(reversed_bytes,csv_bytes('heldout'))[0]
        self.assertEqual(a,b)

    def test_overlap_is_excluded_before_sampling_and_not_renamed(self):
        data=csv_bytes('heldout')+csv_bytes('fit').split(b'\n',1)[1]
        inputs,_,selection=prepare(csv_bytes('fit'),data)
        self.assertEqual(selection['excluded_test_overlap'],80)
        self.assertEqual(len(inputs['heldout']),32)
        self.assertFalse({text_key(r['text']) for r in inputs['fit']} & {text_key(r['text']) for r in inputs['heldout']})

    def test_insufficient_or_conflicting_rows_reject(self):
        with self.assertRaisesRegex(ValueError,'insufficient'):
            prepare(csv_bytes('fit',3),csv_bytes('heldout'))
        conflict=csv_bytes('fit')+f'fit sample {INTENTS[0]} 0,{INTENTS[1]}\n'.encode()
        with self.assertRaisesRegex(ValueError,'conflicting'):
            prepare(conflict,csv_bytes('heldout'))

    def test_bad_csv_and_injected_heldout_labels_reject(self):
        for data in (b'text,label\na,1\n',b'text,category\n,card_arrival\n'):
            with self.assertRaises(ValueError): prepare(data,csv_bytes('heldout'))
        inputs,_=fixture_inputs(); inputs['heldout'][0]['label']=0
        inputs['input_id']=_digest({k:v for k,v in inputs.items() if k!='input_id'})
        with self.assertRaisesRegex(ValueError,'heldout labels'): validate_inputs(inputs)

    def test_acquisition_checks_actual_bytes_and_never_overwrites(self):
        payload=b'fixed CSV bytes'; sha=hashlib.sha1(b'blob '+str(len(payload)).encode()+b'\0'+payload).hexdigest()
        class Response(io.BytesIO):
            def geturl(self): return 'https://fixture/train.csv'
        with tempfile.TemporaryDirectory() as td, patch('banking77_material.ORIGIN','https://fixture/'), \
                patch('banking77_material.BLOBS',{'train.csv':sha}), \
                patch('urllib.request.urlopen',side_effect=lambda *a,**k: Response(payload)):
            root=Path(td)/'ok'; acquire(root)
            self.assertEqual((root/'train.csv').read_bytes(),payload)
            with self.assertRaises(FileExistsError): acquire(root)
            with patch('banking77_material.BLOBS',{'train.csv':'0'*40}):
                with self.assertRaises(ValueError): acquire(Path(td)/'bad')
            self.assertTrue((Path(td)/'bad'/'FAILED.json').exists())
            self.assertFalse((Path(td)/'bad'/'MATERIAL.json').exists())


class PublicCellLearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temp.cleanup)
        cls.root=Path(cls.temp.name)/'trial'; cls.inputs,cls.labels=fixture_inputs()
        cls.plan=freeze_plan(cls.inputs,'a'*64,steps=3,width_units=2,batch_size=4)
        cls.backend=FeatureFixture()
        cls.terminal=execute_learning(cls.inputs,cls.plan,cls.backend,cls.root)

    def copied(self):
        import shutil
        td=tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        root=Path(td.name)/'trial'; shutil.copytree(self.root,root); return root

    def test_actual_training_parameter_match_and_single_shared_encoding(self):
        report=score_sealed(self.root,self.terminal['run_id'],self.inputs,self.labels)
        self.assertTrue(report['all_arms_completed'])
        records=[v['execution'] for v in report['scores'].values()]
        self.assertEqual(records[0]['initial_sha256'],records[1]['initial_sha256'])
        self.assertEqual(records[0]['inventory']['parameters'],records[1]['inventory']['parameters'])
        self.assertTrue(all(v['initial_sha256']!=v['trained_sha256'] for v in records))
        self.assertEqual(len(self.backend.seen),len(self.inputs['fit'])+len(self.inputs['heldout']))
        self.assertTrue(all(set(r)=={'state','question','options'} for r in self.backend.seen))
        self.assertTrue(self.backend.verified)
        self.assertFalse(report['efficacy_established'])

    def test_sparse_graph_really_uses_fewer_heads_but_is_not_equal_compute(self):
        report=score_sealed(self.root,self.terminal['run_id'],self.inputs,self.labels)
        dense=report['scores']['dense16']['execution']; sparse=report['scores']['sparse16_top2']['execution']
        self.assertEqual(sum(dense['inventory']['executed_rows']),8*sum(sparse['inventory']['executed_rows']))
        self.assertGreater(dense['work_observation']['phase_flops']['inference'],sparse['work_observation']['phase_flops']['inference'])
        self.assertTrue(report['fixed_steps_not_matched_compute'])

    def test_safetensors_saved_for_both_and_match_trained_state(self):
        from safetensors.torch import load_file
        from matrix_bank import CellBank,state_digest
        for name,active in (('dense16',16),('sparse16_top2',2)):
            profile=dict(logical_cells=16,initial_logical_cells=16,split=False,ndu=False,resident_stem_copies=1,
                         active_cells_per_round_cap=active,cell_head_budget_params=2_000_000,total_head_budget_params=32_000_000)
            bank=CellBank(4,4,profile,2); bank.load_state_dict(load_file(str(self.root/name/'bank.safetensors')))
            ex=json.loads((self.root/name/'execution.json').read_text())
            self.assertEqual(state_digest(bank),ex['trained_sha256'])

    def test_changed_labels_cannot_train_or_modify_sealed_weights(self):
        path=self.root/'dense16'/'bank.safetensors'; before=file_sha256(path)
        altered=copy.deepcopy(self.labels); altered['rows'][0]['label']=(altered['rows'][0]['label']+1)%4
        with patch('matrix_bank.train_bank',side_effect=AssertionError('must not train')):
            original=score_sealed(self.root,self.terminal['run_id'],self.inputs,self.labels)
            changed=score_sealed(self.root,self.terminal['run_id'],self.inputs,altered)
        self.assertNotEqual(original['labels_sha256'],changed['labels_sha256'])
        self.assertEqual(file_sha256(path),before)

    def test_tampered_weights_or_missing_terminal_reject(self):
        root=self.copied(); path=root/'dense16'/'bank.safetensors'; path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaises(ValueError): score_sealed(root,self.terminal['run_id'],self.inputs,self.labels)
        root=self.copied(); (root/'COMMITTED.json').unlink()
        with self.assertRaises(FileNotFoundError): score_sealed(root,self.terminal['run_id'],self.inputs,self.labels)

    def test_wrong_heldout_order_and_boolean_label_reject(self):
        for how in ('reverse','boolean','missing'):
            labels=copy.deepcopy(self.labels)
            if how=='reverse': labels['rows'].reverse()
            elif how=='boolean': labels['rows'][0]['label']=True
            else: labels['rows'].pop()
            with self.subTest(how=how),self.assertRaises(ValueError):
                score_sealed(self.root,self.terminal['run_id'],self.inputs,labels)

    def test_failed_training_is_retained_and_no_successful_weight_seal(self):
        with tempfile.TemporaryDirectory() as td,patch('matrix_bank.train_bank',side_effect=RuntimeError('failed optimizer')):
            root=Path(td)/'trial'; terminal=execute_learning(self.inputs,self.plan,FeatureFixture(),root)
            result=score_sealed(root,terminal['run_id'],self.inputs,self.labels)
        self.assertFalse(result['all_arms_completed'])
        self.assertTrue(all(v['status']=='failed' and v['task_opportunities']==8 for v in result['scores'].values()))

    def test_changed_plan_or_duplicate_input_rejects_before_encoder(self):
        plan=copy.deepcopy(self.plan); plan['train_steps']+=1
        encoder=FeatureFixture()
        with tempfile.TemporaryDirectory() as td,self.assertRaises(ValueError):
            execute_learning(self.inputs,plan,encoder,Path(td)/'never')
        self.assertEqual(encoder.seen,[])
        bad=copy.deepcopy(self.inputs); bad['heldout'][0]['text']=bad['fit'][0]['text']
        bad['input_id']=_digest({k:v for k,v in bad.items() if k!='input_id'})
        with self.assertRaises(ValueError): validate_inputs(bad)

    def test_encoder_revalidation_failure_prevents_scoring(self):
        backend=FeatureFixture(); backend.reverify=lambda: (_ for _ in ()).throw(ValueError('mutated weights'))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'trial'
            with self.assertRaises(ValueError): execute_learning(self.inputs,self.plan,backend,root)
            self.assertTrue((root/'FAILED.json').exists())
            self.assertFalse((root/'COMMITTED.json').exists())


if __name__=='__main__': unittest.main()
