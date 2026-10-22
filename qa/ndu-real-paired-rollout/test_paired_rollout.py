"""Execution-contract tests use fake tensors and synthetic PNGs, not capability evidence."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
import unittest

import torch
from PIL import Image

# This fake provides the shape of the trusted frozen backend for unit tests.
V1 = Path(__file__).resolve().parent.parent / 'ndu-grounded-generation'
if V1.exists(): sys.path.insert(0,str(V1))
P2 = Path(__file__).resolve().parent.parent / 'ndu-terminal-portfolio'
if P2.exists(): sys.path.insert(0,str(P2))
fake_backend = ModuleType('backend')
fake_backend.OBSERVATION_FIELDS = frozenset(('task_id','image_path','image_sha256','prompt','target_category'))
fake_backend.MODEL_REVISION = 'fixture-only'
fake_backend.explanation = lambda category, boxes: (
    f'There are {len(boxes)} {category} instances. '
    + ('No largest instance.' if not boxes else 'The largest instance is on the left.'))
sys.modules['backend']=fake_backend

import paired_rollout as pr
from fresh_cohort import combine_exclusions
from evaluate import score_episode
from terminal_risk import ARMS, digest, validate


class Cells:
    def delta(self, hidden, weights, vocabulary_size):
        delta=torch.zeros(vocabulary_size)
        delta[7]=sum((i+1)*float(w) for i,w in enumerate(weights))
        return delta, None


class Backend:
    location_token_ids = list(range(100))
    eos_token_id=101
    def __init__(self):self.seen=[];self.executed=[];self.fail=False
    def encode(self, observation):
        if set(observation)!=fake_backend.OBSERVATION_FIELDS:raise ValueError('reference leak')
        self.seen.append(dict(observation))
        now=time.perf_counter();time.sleep(.003)
        return SimpleNamespace(costs={'encoder_seconds':time.perf_counter()-now})
    def generate(self, encoded, *, modifier, max_new_tokens, checkpoint_stride,
                 max_checkpoints, max_wall_seconds, do_sample, temperature, seed):
        self.executed.append({'seed':seed,'sample':do_sample,'temp':temperature,'modifier':modifier.arm})
        if self.fail: raise RuntimeError('deliberate fixture failure')
        t0=time.perf_counter()
        prefix=[102]
        logits=torch.zeros(102)
        logits[7]=5
        state={'hidden':torch.ones(4),'logits':logits,'token_ids':prefix,'checkpoint':0,
               'step':0,'checkpoint_changed':True,'remaining_seconds':max_wall_seconds}
        update=modifier(state)
        assert update['weights']==[float(i+1==ARMS.index(modifier.arm)) for i in range(4)]
        assert update['action']==ARMS.index(modifier.arm)
        time.sleep(.003)
        # Box is intentionally different per action; scoring is external.
        x=.1 + ARMS.index(modifier.arm)*.05
        return {'boxes':[[x,.1,x+.3,.9]],'controls':[{'argmax_changed':False}],
                'termination':'eos','tokens':[102,101], 'raw_text':'fixture',
                'costs':{'decoder_seconds':.002,'parsing_seconds':0.,
                         'loop_overhead_seconds':max(0.,time.perf_counter()-t0-.002-modifier.seconds),
                         'modifier_seconds':modifier.seconds,'cell_seconds':0.,
                         'decoder_forward_calls':1,'generated_tokens':1,'actual_checkpoints':1}}


class PairedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        image=self.root/'fixture.png'
        Image.new('RGB',(64,32),'white').save(image)
        self.obs={'task_id':'fixture-001','image_path':str(image),
                  'image_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),
                  'prompt':'locate cat','target_category':'cat'}
        self.ref={'task_id':'fixture-001','source_id':'synthetic:fixture001',
                  'image_size':[64,32], 'boxes':[[.1,.1,.4,.9]],
                  'label':'cat','count':1,'largest_side':'left'}
        self.backend=Backend()
        self.cells=Cells()
        self.header={'seeds':[11,29],'split':'train', 'budget_seconds':10., 'model_revision':'fixture-only',
                     'cohort_manifest_sha256':digest('source fixture'),
                     'model_digest':digest('model'), 'objective_digest':digest('objective'),
                     'proposals':{arm:digest('proposal-'+arm) for arm in ARMS}}

    def test_live_modifier_is_preselection_and_zero_arm_uses_same_constraints(self):
        from cells import apply_constraints
        logits=torch.zeros(102)
        logits[100]=5
        fake={'hidden':torch.ones(4), 'logits':logits,'token_ids':[102],
              'checkpoint':0,'checkpoint_changed':True,'step':0,'remaining_seconds':10.}
        zero=pr.FrozenArm('nochange',self.cells,list(range(100)),101,True)(fake)
        one=pr.FrozenArm('semantic',self.cells,list(range(100)),101,True)(fake)
        self.assertTrue(torch.isneginf(zero['logits'][99]))
        self.assertTrue(torch.isneginf(one['logits'][99]))
        self.assertEqual(float(zero['logits'][7]),float(logits[7]))
        self.assertEqual(float(one['logits'][7]),float(logits[7]+1))

    def test_five_arms_two_seeds_and_ledger(self):
        rows=[]
        for seed in self.header['seeds']:
            for arm in ARMS:
                row=pr.run_arm(self.backend,self.cells,self.obs,arm,seed=seed,
                               artifact_root=self.root/'artifacts',budget=10.)
                self.assertEqual(row['termination'],'completed')
                self.assertAlmostEqual(row['ledger_minus_wall_seconds'],0.,places=5)
                self.assertEqual(row['executed_encoder_calls'],1)
                self.assertIsNone(row['failure'])
                score=score_episode(row,self.ref)
                self.assertEqual(score['coverage'],1.0)
                row['plan_digest']=digest(self.header)
                rows.append(row)
        self.assertEqual(len(self.backend.seen),10)
        self.assertEqual(len(self.backend.executed),10)
        self.assertTrue(all('source_id' not in obs and 'boxes' not in obs for obs in self.backend.seen))
        self.assertTrue(all(run['sample'] for run in self.backend.executed))
        paired=pr.to_terminal_batch(self.header,rows,[self.ref],[self.obs])
        self.assertEqual(len(paired['rows']),10)
        self.assertEqual(len(validate(paired,min_source_groups=1)['sources']),1)

    def test_incomplete_exception_is_not_silently_removed(self):
        self.backend.fail=True
        error=pr.run_arm(self.backend,self.cells,self.obs,'semantic',seed=11,
                         artifact_root=self.root/'artifacts',budget=10.)
        self.assertIsNotNone(error['failure'])
        self.assertEqual(error['termination'],'incomplete')
        self.assertAlmostEqual(error['ledger_minus_wall_seconds'],0.,places=5)
        self.assertEqual(score_episode(error,self.ref)['coverage'],0)

    def test_encoder_timeout_is_charged_and_prevents_decoder(self):
        result=pr.run_arm(self.backend,self.cells,self.obs,'semantic',seed=11,
                          artifact_root=self.root/'artifacts',budget=0.0001)
        self.assertEqual(result['termination'],'incomplete')
        self.assertIn('TimeoutError',result['failure'])
        self.assertEqual(len(self.backend.executed),0)
        self.assertEqual(result['executed_encoder_calls'],1)
        self.assertGreater(result['actual_wall_seconds'],result['budget_cap'])
        self.assertAlmostEqual(result['ledger_minus_wall_seconds'],0.,places=5)
        self.assertEqual(score_episode(result,self.ref)['loss'],1.)

    def test_reference_and_roster_cannot_enter_actor(self):
        with self.assertRaisesRegex(ValueError,'actor observation'):
            pr.run_arm(self.backend,self.cells,{**self.obs,'boxes':self.ref['boxes']},'semantic',
                       seed=11,artifact_root=self.root/'artifacts')
        rows=[pr.run_arm(self.backend,self.cells,self.obs,'nochange',seed=11,artifact_root=self.root/'artifacts')]
        with self.assertRaisesRegex(ValueError,'incomplete exact five-arm'):
            pr.to_terminal_batch(self.header,rows,[self.ref],[self.obs])
        with self.assertRaisesRegex(ValueError,'unsupported Cell arm'):
            pr.FrozenArm('untrusted-tool',self.cells,[],101,True)

    def test_resumed_proposals_are_distinct_and_source_id_aligned(self):
        rows=[pr.run_arm(self.backend,self.cells,self.obs,arm,seed=seed,
                         artifact_root=self.root/'artifacts') for seed in (11,29) for arm in ARMS]
        for row in rows:row['plan_digest']=digest(self.header)
        damaged=copy.deepcopy(rows)
        damaged[0]['source_image_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'source image checksum'):
            pr.to_terminal_batch(self.header,damaged,[self.ref],[self.obs])
        damaged=copy.deepcopy(rows)
        damaged[0]['budget_cap']=9
        with self.assertRaisesRegex(ValueError,'budget or method'):
            pr.to_terminal_batch(self.header,damaged,[self.ref],[self.obs])

    def test_original_image_bytes_cannot_drift_before_or_during_encoding(self):
        changed={**self.obs,'image_sha256':'0'*64}
        row=pr.run_arm(self.backend,self.cells,changed,'semantic',seed=11,
                       artifact_root=self.root/'artifacts')
        self.assertEqual(row['termination'],'incomplete')
        self.assertIn('source image bytes differ',row['failure'])
        self.assertEqual(len(self.backend.seen),0)
        self.assertEqual(len(self.backend.executed),0)
        original=self.backend.encode
        def corrupt_after_encode(observation):
            encoded=original(observation)
            Path(observation['image_path']).write_bytes(b'changed mid-episode')
            return encoded
        self.backend.encode=corrupt_after_encode
        row=pr.run_arm(self.backend,self.cells,self.obs,'semantic',seed=11,
                       artifact_root=self.root/'artifacts')
        self.assertEqual(row['termination'],'incomplete')
        self.assertIn('source image bytes changed during encoder',row['failure'])
        self.assertEqual(len(self.backend.executed),0)

    def test_frozen_image_seed_model_policy_and_label_are_checked_at_scoring(self):
        rows=[pr.run_arm(self.backend,self.cells,self.obs,arm,seed=seed,
                         artifact_root=self.root/'artifacts')
              for seed in self.header['seeds'] for arm in ARMS]
        for row in rows: row['plan_digest']=digest(self.header)
        image=Path(self.obs['image_path'])
        original=image.read_bytes()
        image.write_bytes(b'edited after all predictions')
        with self.assertRaisesRegex(ValueError,'source image bytes changed before terminal'):
            pr.to_terminal_batch(self.header,rows,[self.ref],[self.obs])
        image.write_bytes(original)
        for field,value in (
            ('sampling_seed',-1),('model_revision','forged-checkpoint'),
            ('policy_version','other-controller/v1'),('label','wrong-category')
        ):
            altered=copy.deepcopy(rows)
            altered[0][field]=value
            with self.assertRaisesRegex(ValueError,'frozen model, stochastic seed'):
                pr.to_terminal_batch(self.header,altered,[self.ref],[self.obs])

    def test_exclusive_workdir_guard_prevents_parallel_writers(self):
        # Must serialize actual concurrent writers, not only reject duplicate
        # receipts once both already modified the same append-only journal.
        import subprocess
        import sys
        import os
        work=self.root/'durable-five-arm-run'
        if os.name != 'posix':
            with self.assertRaisesRegex(RuntimeError, 'requires POSIX'):
                with pr.exclusive_workdir_lock(work):
                    pass
            return
        with pr.exclusive_workdir_lock(work):
            with self.assertRaisesRegex(RuntimeError,'already active'):
                with pr.exclusive_workdir_lock(work):
                    pass
            child="from pathlib import Path; import paired_rollout as p; " \
                  "p.exclusive_workdir_lock(Path("+repr(str(work))+")).__enter__()"
            env=dict(os.environ)
            env['PYTHONPATH']=str(Path(pr.__file__).resolve().parent)+os.pathsep+env.get('PYTHONPATH','')
            r=subprocess.run([sys.executable,'-c',child],env=env,
                             capture_output=True,text=True,timeout=15)
            self.assertNotEqual(r.returncode,0)
            self.assertIn('already active',r.stderr)
        with pr.exclusive_workdir_lock(work):
            pass
        lock=work/'.hepta-ndu-p3.lock'
        self.assertTrue(lock.exists())
        lock.unlink()
        lock.symlink_to(work/'foreign-target')
        with self.assertRaises((ValueError,OSError)):
            with pr.exclusive_workdir_lock(work):
                pass

    def test_plan_rejects_unverified_cell_checkpoint_before_generating(self):
        from unittest.mock import patch
        model_dir=self.root/'fake-model'
        model_dir.mkdir()
        (model_dir/'model.safetensors').write_bytes(b'fixture checkpoint')
        checkpoint=self.root/'cells.pt'
        checkpoint.write_bytes(b'unsigned untrusted Cell weights')
        cohort=self.root/'new-cohort'
        cohort.mkdir()
        (cohort/'manifest.json').write_text(__import__('json').dumps({
            'schema':'hepta.grounded-cohort.v1','evidence_kind':'real-coco',
            'prior_images_excluded':640}))
        (cohort/'train.references.jsonl').write_text('')
        fake_backend.WEIGHT_SHA256=pr.sha(model_dir/'model.safetensors')
        with self.assertRaisesRegex(ValueError,'does not match the frozen P1'):
            pr.plan_identity(cohort,'train',model_path=model_dir,cells_path=checkpoint,
                             budget=10.,seeds=[11,29],code_dir=Path(pr.__file__).parent,temperature=.7)

    def test_repeated_seed_roster_is_rejected_before_any_asset_load(self):
        """A duplicated seed must not create pseudoreplicated Cell observations."""
        import json
        cohort=self.root/'fresh-cohort'
        cohort.mkdir()
        (cohort/'manifest.json').write_text(json.dumps({
            'evidence_kind':'real-coco',
            'schema':'hepta.grounded-cohort.v1',
            'prior_images_excluded':640,
        }))
        (cohort/'train.references.jsonl').write_text('')
        with self.assertRaisesRegex(ValueError, 'distinct|unique|duplicate'):
            pr.plan_identity(cohort, 'train', model_path=self.root/'no-model',
                             cells_path=self.root/'no-cells', budget=10.,
                             seeds=[11,11,29], code_dir=Path(pr.__file__).parent,
                             temperature=0.7)

    def test_fresh_cohort_exclusion_requires_original_v1_manifest(self):
        historical={'source_sample':{'images':[{'image_id':i, 'image_sha256':digest(f'h-{i}'),
                           'decoded_rgb_sha256':digest(f'r-{i}'),'dhash64':'0'*16} for i in range(384)]}}
        v1={'schema':'hepta.grounded-cohort.v1','splits':{}}
        for n,split in enumerate(('train','dev','calibration','test')):
            start=384+sum((128,32,32,64)[:n]); size=(128,32,32,64)[n]
            v1['splits'][split]={'count':size,'sources':[
                 {'image_id':i,'image_sha256':digest(f'h-{i}'),
                  'decoded_rgb_sha256':digest(f'r-{i}'),'dhash64':'f'*16}
                 for i in range(start,start+size)]}
        (self.root/'prior.json').write_text(__import__('json').dumps(historical))
        (self.root/'v1.json').write_text(__import__('json').dumps(v1))
        with self.assertRaisesRegex(ValueError,'frozen byte digests'):
            combine_exclusions(self.root/'prior.json',self.root/'v1.json',self.root/'both.json')
        result=combine_exclusions(self.root/'prior.json',self.root/'v1.json',self.root/'both.json',require_pinned=False)
        self.assertEqual(len(result['source_sample']['images']),640)
        with self.assertRaises(FileExistsError):
            combine_exclusions(self.root/'prior.json',self.root/'v1.json',self.root/'both.json',require_pinned=False)
        victim=self.root/'uncreated-target.json'
        link=self.root/'preplanted-link.json'
        link.symlink_to(victim)
        with self.assertRaises(FileExistsError):
            combine_exclusions(self.root/'prior.json',self.root/'v1.json',link,require_pinned=False)
        self.assertFalse(victim.exists())


    def test_dev_requires_complete_identical_real_train_receipt(self):
        """A standalone completion-marker must never unlock DEV inference."""
        import json
        with self.assertRaisesRegex(ValueError, 'published and complete'):
            pr.verify_frozen_train(self.root, {'split':'dev'}, {}, min_source_groups=1)
        (self.root/'train.complete.json').write_text('{"status":"completed_no_scientific_claim"}')
        with self.assertRaisesRegex(ValueError, 'TRAIN plan missing'):
            pr.verify_frozen_train(self.root, {'split':'dev'}, {}, min_source_groups=1)
        cohort=self.root/'cohort'
        cohort.mkdir()
        source={'source_id':self.ref['source_id'], 'task_id':self.obs['task_id'],
                'image_sha256':self.obs['image_sha256']}
        manifest={'schema':'hepta.grounded-cohort.v1',
                  'splits':{'train':{'count':1,'sources':[source]}}}
        path=cohort/'manifest.json'
        path.write_text(json.dumps(manifest))
        meta={**manifest,'manifest_path':str(path)}
        proposals={arm:digest(f'proposal:{arm}') for arm in ARMS}
        plan={'schema':'hepta.ndu-real-five-arm-plan.v1','split':'train',
              'cohort_manifest_sha256':pr.sha(path),
              'model_digest':digest('base'),'model_revision':'fixture-only',
              'cell_digest':digest('cells'), 'algorithm_digest':digest('source'),
              'source_code_digests':{'frozen':'fixture'},
              'objective_digest':digest('objective'),'budget_seconds':10.,
              'temperature':.7,'seeds':[11,29],
              'geometry_constraints':'all_arms_including_nochange',
              'proposals':proposals,'scientific_claim':'unverified',
              'promotion':'DENY_ALL'}
        dev={**plan,'split':'dev'}
        work=self.root/'train'
        work.mkdir()
        (work/'plan.json').write_text(json.dumps(plan))
        (cohort/'train.observations.jsonl').write_text(json.dumps(self.obs)+'\n')
        (cohort/'train.references.jsonl').write_text(json.dumps(self.ref)+'\n')
        journal=[]
        for seed in (11,29):
            for arm in ARMS:
                episode=pr.run_arm(self.backend,self.cells,self.obs,arm,seed=seed,
                                   artifact_root=self.root/'generated',budget=10.)
                episode['plan_digest']=digest(plan)
                journal.append(episode)
        terminal=pr.to_terminal_batch(plan,journal,[self.ref],[self.obs])
        (work/'terminal-batch.json').write_text(json.dumps(terminal))
        (work/'episodes.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in journal))
        complete={'status':'completed_no_scientific_claim','source_groups':1,'episodes':10,
                  'plan_sha256':pr.sha(work/'plan.json'),
                  'journal_sha256':pr.sha(work/'episodes.jsonl'),
                  'terminal_batch_sha256':pr.sha(work/'terminal-batch.json')}
        marker=self.root/'train.complete.json'
        marker.write_text(json.dumps(complete))
        receipt=pr.verify_frozen_train(self.root,dev,meta,min_source_groups=1)
        self.assertEqual((receipt['verified'],receipt['sources'],receipt['episodes']),
                         (True,1,10))
        changed={**dev,'temperature':.8}
        with self.assertRaisesRegex(ValueError,'differs from frozen TRAIN'):
            pr.verify_frozen_train(self.root,changed,meta,min_source_groups=1)
        prior=(work/'episodes.jsonl').read_text()
        (work/'episodes.jsonl').write_text(prior+'\n')
        with self.assertRaisesRegex(ValueError,'TRAIN journal missing or digest changed'):
            pr.verify_frozen_train(self.root,dev,meta,min_source_groups=1)
        (work/'episodes.jsonl').write_text(prior)
        # Tampered terminal loss with spoofed updated checksum must also fail
        # under source/seed/arm and original-image custody checks.
        tampered=dict(terminal)
        tampered['rows']=[dict(row) for row in terminal['rows']]
        tampered['rows'][0]['image_digest']=digest('other-image')
        (work/'terminal-batch.json').write_text(json.dumps(tampered))
        complete['terminal_batch_sha256']=pr.sha(work/'terminal-batch.json')
        marker.write_text(json.dumps(complete))
        with self.assertRaisesRegex(ValueError,'multiple image digests|original images'):
            pr.verify_frozen_train(self.root,dev,meta,min_source_groups=1)
        # A valid terminal schema + updated receipt SHA can still fabricate
        # covariance until every terminal score is reconstructed from outputs.
        score_spoof=copy.deepcopy(terminal)
        old=score_spoof['rows'][0]['loss']
        score_spoof['rows'][0]['loss']=0.95 if old!=0.95 else 0.05
        (work/'terminal-batch.json').write_text(json.dumps(score_spoof))
        complete['terminal_batch_sha256']=pr.sha(work/'terminal-batch.json')
        marker.write_text(json.dumps(complete))
        with self.assertRaisesRegex(ValueError,'terminal scores differ'):
            pr.verify_frozen_train(self.root,dev,meta,min_source_groups=1)


    def test_pinned_model_inventory_rejects_tokenizer_config_and_foreign_assets(self):
        """Same weight SHA with changed tokenizer/config cannot start a new rollout."""
        from unittest.mock import patch
        import acquisition
        import backend
        root = self.root / 'pinned-assets'
        root.mkdir()
        data = {'model.safetensors': b'fixed-weights-fixture',
                'tokenizer.json': b'{"eos_token_id": 101}',
                'processor_config.json': b'{"size": 768}',
                'generation_config.json': b'{"max_length": 40}'}
        pins = {}
        for name, payload in data.items():
            (root / name).write_bytes(payload)
            pins[name] = (len(payload), hashlib.sha256(payload).hexdigest())
        with (patch.object(acquisition, 'FILES', pins),
              patch.object(acquisition, 'REVISION', backend.MODEL_REVISION),
              patch.object(backend, 'WEIGHT_SHA256', pins['model.safetensors'][1], create=True)):
            inventory = pr.pinned_model_inventory(root)
            self.assertEqual(set(inventory), set(data))
            original = (root / 'tokenizer.json').read_bytes()
            (root / 'tokenizer.json').write_bytes(b'{"eos_token_id": 102}')
            with self.assertRaisesRegex(ValueError, 'asset pin mismatch: tokenizer.json'):
                pr.pinned_model_inventory(root)
            (root / 'tokenizer.json').write_bytes(original)
            (root / 'processor_config.json').unlink()
            with self.assertRaisesRegex(ValueError, 'asset pin mismatch: processor_config.json'):
                pr.pinned_model_inventory(root)
            (root / 'processor_config.json').write_bytes(data['processor_config.json'])
            (root / 'unexpected_config.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'untracked model directory'):
                pr.pinned_model_inventory(root)
            (root / 'unexpected_config.json').unlink()
            (root / 'generation_config.json').unlink()
            (root / 'generation_config.json').symlink_to(root / 'model.safetensors')
            with self.assertRaisesRegex(ValueError, 'asset pin mismatch: generation_config.json'):
                pr.pinned_model_inventory(root)
            (root / 'generation_config.json').unlink()
            (root / 'generation_config.json').write_bytes(data['generation_config.json'])
            with patch.object(acquisition, 'REVISION', 'different-revision'):
                with self.assertRaisesRegex(ValueError, 'frozen revision'):
                    pr.pinned_model_inventory(root)
            with patch.object(backend, 'WEIGHT_SHA256', hashlib.sha256(b'other-weights').hexdigest(), create=True):
                with self.assertRaisesRegex(ValueError, 'frozen revision'):
                    pr.pinned_model_inventory(root)
            self.assertEqual(pr.pinned_model_inventory(root), inventory)


if __name__=='__main__':unittest.main()
