"""Actual CPU autograd/Adam and source-bound Bridge CellSplit shadow tests.

The synthetic-feature mechanism tests never claim original Granite token parity.
Set HEPTA_ORIGINAL_V6_ZIP to enable the authentic original 3-seed checkpoints.
"""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

import torch

from bridge_reader import build_reader
from bridge_split_cell_v77 import (SplitBridgeCell, RouteEvidence, GatedNewHead,
    FrozenNewTaskCache, OLD_TASK, NEW_TASK, ROUTE_SCHEMA,
    PARAMETERS_PER_CELL, collect_new_task_cache, digest_parameters,
    feature_digest, fit_new_task_head, physical_weight_budget)

SEEDS=(41,47,53)
ORIGINAL="197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a"
PATH=Path(os.environ.get("HEPTA_ORIGINAL_V6_ZIP","/mnt/data/hepta_research_material/hepta_bridge_learning_v6_20261015.zip"))
DUMMY="1"*64

def fixture_features(seed=11, size=16):
    generator=torch.Generator().manual_seed(seed)
    return (torch.randn(size,3,4,384,generator=generator),
            torch.randn(size,2,384,generator=generator),
            torch.randn(size,2,384,generator=generator),
            torch.ones(size,3,4,dtype=torch.bool),
            torch.ones(size,2,dtype=torch.bool),
            torch.ones(size,2,dtype=torch.bool))

def make_evidence(features,parent_digest,task=OLD_TASK,seq=0):
    n=features[0].shape[0]
    return RouteEvidence(task,tuple(f"synthetic-public-case/{seq}/{i}" for i in range(n)),
      tuple(hashlib.sha256(f"synthetic-source/{seq}/{i//4}".encode()).hexdigest()
            for i in range(n)), feature_digest(features),parent_digest,DUMMY,DUMMY,DUMMY)

def fresh_cell(seed=41):
    old=build_reader('bridge',seed).eval().requires_grad_(False)
    return SplitBridgeCell(old,expected_parent_sha256=digest_parameters(old),new_head_seed=seed)


class FrozenRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_exact_original_route_bitwise(self):
        cell=fresh_cell()
        f=fixture_features()
        control=cell.parent(*f,steps=3)
        old=cell.route(f,make_evidence(f,cell.original_sha256))
        self.assertTrue(torch.equal(control,old))
        self.assertEqual(cell.parent_forward_calls,1)

    def test_new_head_initial_zero_residual(self):
        cell=fresh_cell()
        f=fixture_features()
        old=cell.route(f,make_evidence(f,cell.original_sha256))
        new=cell.route(f,make_evidence(f,cell.original_sha256,NEW_TASK))
        self.assertTrue(torch.equal(old,new))
        self.assertEqual(sum(p.numel() for p in cell.new_head.parameters()),1700)

    def test_multiple_cells_share_exact_physical_weight_tensor(self):
        parent=build_reader('bridge',41).eval().requires_grad_(False)
        sha=digest_parameters(parent)
        cells=[SplitBridgeCell(parent,expected_parent_sha256=sha,new_head_seed=41+i) for i in range(5)]
        self.assertTrue(all(c.parent is parent for c in cells))
        self.assertEqual(len({c.parent.project.weight.data_ptr() for c in cells}),1)
        self.assertEqual(len({c.new_head.input.weight.data_ptr() for c in cells}),5)
        self.assertIs(cells[0]._forward_lock,cells[-1]._forward_lock)

    def test_owner_ticket_digest_bound_and_no_production(self):
        cell=fresh_cell()
        f=fixture_features()
        ticket=make_evidence(f,cell.original_sha256)
        for changed in (replace(ticket,task_family='unregistered'),
                        replace(ticket,production_authorized=True),
                        replace(ticket,feature_sha256=DUMMY),
                        replace(ticket,frozen_model_sha256=DUMMY),
                        replace(ticket,source_scope='future'),
                        replace(ticket,schema='unknown'),
                        replace(ticket,case_ids=(ticket.case_ids[0],)*16),
                        replace(ticket,generation=0)):
            with self.subTest(ticket=changed):
                with self.assertRaises(ValueError):cell.route(f,changed)

    def test_modified_feature_bytes_refused(self):
        cell=fresh_cell()
        f=fixture_features()
        ticket=make_evidence(f,cell.original_sha256)
        arr=list(f)
        arr[0]=arr[0].clone(); arr[0][0,0,0,0]+=0.1
        with self.assertRaisesRegex(ValueError,'routed feature'):
            cell.route(tuple(arr),ticket)

    def test_reject_tampered_shared_parent(self):
        cell=fresh_cell()
        with torch.no_grad():cell.parent.project.weight[0,0]+=0.25
        with self.assertRaisesRegex(ValueError,'mutated'):
            cell.check_frozen()

    def test_init_does_not_advance_rng(self):
        parent=build_reader('bridge',41).eval().requires_grad_(False)
        before=torch.random.get_rng_state().clone()
        SplitBridgeCell(parent,expected_parent_sha256=digest_parameters(parent),new_head_seed=72)
        self.assertTrue(torch.equal(before,torch.random.get_rng_state()))

    def test_shared_reader_head_hooks_are_serialized_across_cells(self):
        parent=build_reader('bridge',41).eval().requires_grad_(False)
        digest=digest_parameters(parent)
        cells=[SplitBridgeCell(parent,expected_parent_sha256=digest,
                               new_head_seed=130+i) for i in range(4)]
        f=fixture_features()
        baseline=parent(*f,steps=3)
        def execute(cell):
            return cell.route(f,make_evidence(f,digest))
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(execute,cells*3))
        self.assertTrue(all(torch.equal(x,baseline) for x in results))
        self.assertEqual(len(parent.head[0]._forward_pre_hooks),0)

    def test_shadow_only_synthetic_unseen_route(self):
        cell=fresh_cell()
        features=fixture_features()
        evidence=replace(make_evidence(features,cell.original_sha256,NEW_TASK),
                         source_scope='synthetic_unseen_source')
        self.assertEqual(cell.route(features,evidence).shape,(16,2))
        with self.assertRaises(ValueError):
            cell.route(features,replace(evidence,source_scope='production'))

    def test_train_mode_never_enables_parent_training(self):
        cell=fresh_cell()
        cell.train(True)
        self.assertTrue(cell.new_head.training)
        self.assertFalse(cell.parent.training)
        cell.check_frozen()

    def test_fixed_head_and_weight_storage_math(self):
        a=physical_weight_budget(64)
        b=physical_weight_budget(4096)
        self.assertEqual(a['physical_parameter_bytes'],(42562+1700*64)*4)
        self.assertEqual(b['each_head_bytes'],6800)
        self.assertLess(a['physical_parameter_bytes'],a['dense_replica_baseline_bytes'])
        self.assertTrue(b['pretrained_encoder_not_included'])
        for n in (0,4097,1.5,True):
            with self.assertRaises(ValueError):physical_weight_budget(n)

    def test_head_trainable_gradient_path(self):
        head=GatedNewHead(41)
        x=torch.randn(64,97)
        base=torch.randn(64,2)
        labels=torch.randint(0,2,(64,))
        optimizer=torch.optim.Adam(head.parameters(),lr=0.1)
        for i in range(4):
            optimizer.zero_grad()
            torch.nn.functional.cross_entropy(head(x,base),labels).backward()
            self.assertTrue(all(p.grad is not None for p in head.parameters()))
            optimizer.step()
        self.assertTrue(torch.isfinite(head(x,base)).all())

    def test_feature_tensor_geometry_and_finiteness_denied(self):
        f=fixture_features()
        for corrupt in (('nan',torch.full_like(f[0],float('nan'))),('type',f[0].double()),('batch',f[0][:15])):
            v=list(f);v[0]=corrupt[1]
            with self.subTest(error=corrupt[0]):
                with self.assertRaises(ValueError):feature_digest(tuple(v))


class CachedHeadTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):torch.set_num_threads(1)
    def build_cache(self,cell,*,n=64):
        batches=[]
        for start in range(0,n,16):
            f=fixture_features(seed=1000+start,size=16)
            batches.append((f,make_evidence(f,cell.original_sha256,NEW_TASK,seq=start)))
        return collect_new_task_cache(cell,batches)

    def test_actual_adam_updates_only_new_head(self):
        cell=fresh_cell()
        cache=self.build_cache(cell)
        before=digest_parameters(cell.parent)
        # A deliberately synthetic teacher over a *frozen original latent*;
        # NOT natural-language ground truth or real Granite features.
        target=(cache.hidden[:,1]-cache.hidden[:,3] >
                (cache.hidden[:,1]-cache.hidden[:,3]).median()).long()
        receipt=fit_new_task_head(cell,cache,target,updates=180,batch_size=16,
                                  learning_rate=0.025)
        self.assertEqual(receipt['accepted_optimizer_updates'],180)
        self.assertEqual(receipt['new_head_parameter_count'],1700)
        self.assertEqual(receipt['original_trunk_training_updates'],0)
        self.assertEqual(receipt['actual_frozen_reader_calls_to_build_cache'],4)
        self.assertTrue(cell.candidate_fitted)
        self.assertEqual(digest_parameters(cell.parent),before)
        self.assertTrue(all(p.grad is None for p in cell.parent.parameters()))
        self.assertFalse(receipt['production_authorized'])
        f=fixture_features(seed=999)
        self.assertTrue(torch.equal(cell.parent(*f,steps=3),
                         cell.route(f,make_evidence(f,cell.original_sha256))))
        with self.assertRaisesRegex(ValueError,'untrained registered'):
            fit_new_task_head(cell,cache,target,updates=1,learning_rate=0.01)

    def test_cache_rejects_old_source_overlap(self):
        cell=fresh_cell()
        f=fixture_features()
        ticket=make_evidence(f,cell.original_sha256,NEW_TASK)
        with self.assertRaisesRegex(ValueError,'source disjoint'):
            collect_new_task_cache(cell,[(f,ticket)],forbidden_old_sources=ticket.source_hashes)

    def test_cache_rejects_duplicate_case_ids_across_batches(self):
        cell=fresh_cell()
        f=fixture_features()
        ticket=make_evidence(f,cell.original_sha256,NEW_TASK)
        with self.assertRaisesRegex(ValueError,'unique bounded'):
            collect_new_task_cache(cell,[(f,ticket),(f,ticket)])

    def test_train_labels_must_not_enter_feature_cache(self):
        cell=fresh_cell()
        cache=self.build_cache(cell)
        self.assertFalse(hasattr(cache,'labels'))
        with self.assertRaisesRegex(ValueError,'aligned binary'):
            fit_new_task_head(cell,cache,torch.zeros(64,dtype=torch.float32),updates=1,learning_rate=.01)
        with self.assertRaisesRegex(ValueError,'aligned binary'):
            fit_new_task_head(cell,cache,torch.full((64,),2,dtype=torch.long),updates=1,learning_rate=.01)

    def test_cached_tensor_tampering_rejected_before_training(self):
        cell=fresh_cell()
        cache=self.build_cache(cell)
        mutated_hidden=cache.hidden.clone()
        mutated_hidden[0,2]+=0.2
        with self.assertRaisesRegex(ValueError,'cache.*tensor bytes'):
            fit_new_task_head(cell,replace(cache,hidden=mutated_hidden),
                torch.zeros(64,dtype=torch.long),updates=1,learning_rate=.01)
        mutated_logits=cache.original_logits.clone()
        mutated_logits[0,1]+=0.2
        with self.assertRaisesRegex(ValueError,'cache.*tensor bytes'):
            fit_new_task_head(cell,replace(cache,original_logits=mutated_logits),
                torch.zeros(64,dtype=torch.long),updates=1,learning_rate=.01)

    def test_input_batch_roster_tampering_rejected(self):
        cell=fresh_cell()
        cache=self.build_cache(cell)
        with self.assertRaisesRegex(ValueError,'cache.*tensor bytes'):
            replace(cache,input_batch_sha256s=(DUMMY,)*len(cache.input_batch_sha256s)).validate()

    def test_wrong_parent_cache_refused(self):
        cell=fresh_cell()
        cache=self.build_cache(cell)
        with self.assertRaisesRegex(ValueError,'cache'):
            fit_new_task_head(cell,replace(cache,frozen_model_sha256=DUMMY),
                              torch.zeros(64,dtype=torch.long),updates=1,learning_rate=.01)

    def test_new_cell_fitting_cannot_damage_another_cells_parent(self):
        parent=build_reader('bridge',41).eval().requires_grad_(False)
        digest=digest_parameters(parent)
        c1=SplitBridgeCell(parent,expected_parent_sha256=digest,new_head_seed=41)
        c2=SplitBridgeCell(parent,expected_parent_sha256=digest,new_head_seed=47)
        f=fixture_features()
        old_before=c1.route(f,make_evidence(f,digest))
        cache=self.build_cache(c2)
        labels=(cache.hidden[:,0]>cache.hidden[:,0].median()).long()
        fit_new_task_head(c2,cache,labels,updates=20,learning_rate=.01)
        old_after=c1.route(f,make_evidence(f,digest))
        self.assertTrue(torch.equal(old_before,old_after))
        self.assertIs(c1.parent,c2.parent)

@unittest.skipUnless(PATH.is_file(), 'requires original V6 artifact; no test fixture substituted')
class OriginalArchivedBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        blob=PATH.read_bytes()
        assert hashlib.sha256(blob).hexdigest()==ORIGINAL
        cls.z=zipfile.ZipFile(io.BytesIO(blob))

    def original_cell(self,seed):
        prefix=f'reader-v6-bridge/seed-{seed}/bridge/'
        info=json.loads(self.z.read(prefix+'warmup-model.json'))
        source=self.z.read(prefix+'warmup.pt')
        self.assertEqual(hashlib.sha256(source).hexdigest(),info['file_sha256'])
        parent=build_reader('bridge',seed).eval().requires_grad_(False)
        parent.load_state_dict(torch.load(io.BytesIO(source),weights_only=True,map_location='cpu'),strict=True)
        return SplitBridgeCell(parent,expected_parent_sha256=info['training_parameter_sha256'],new_head_seed=seed)

    def test_all_3_actual_pretrained_bridge_old_route_exact(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                cell=self.original_cell(seed)
                f=fixture_features(seed=seed)
                expected=cell.parent(*f,steps=3)
                found=cell.route(f,make_evidence(f,cell.original_sha256))
                self.assertTrue(torch.equal(found,expected))
                cell.check_frozen()

    def test_actual_pretrained_parent_training_is_immutable(self):
        cell=self.original_cell(41)
        f=fixture_features(seed=41)
        original=cell.parent(*f,steps=3)
        parts=[]
        for i in range(0,64,16):
            ff=fixture_features(seed=9000+i)
            parts.append((ff,make_evidence(ff,cell.original_sha256,NEW_TASK,seq=i)))
        cache=collect_new_task_cache(cell,parts)
        labels=(cache.hidden[:,0]>cache.hidden[:,0].median()).long()
        receipt=fit_new_task_head(cell,cache,labels,updates=40,learning_rate=0.02)
        self.assertEqual(receipt['original_trunk_training_updates'],0)
        self.assertEqual(receipt['accepted_optimizer_updates'],40)
        self.assertTrue(torch.equal(original,cell.route(f,make_evidence(f,cell.original_sha256))))
        cell.check_frozen()

    def test_all_3_actual_pretrained_bridge_new_route_zero_before_training(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                cell=self.original_cell(seed)
                f=fixture_features(seed=seed)
                self.assertTrue(torch.equal(cell.route(f,make_evidence(f,cell.original_sha256)),
                                 cell.route(f,make_evidence(f,cell.original_sha256,NEW_TASK))))

if __name__=='__main__':unittest.main()
