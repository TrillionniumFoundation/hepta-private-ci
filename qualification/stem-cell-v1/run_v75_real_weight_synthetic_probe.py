"""Executed-mechanism-only receipt: REAL V6 weights, SYNTHETIC tokens, 9 slots."""
from pathlib import Path
import json
import tempfile
import numpy as np
from hashlib import sha256

from test_bridge_candidate_v75 import OriginalWeightsSyntheticFeatures,synthetic_batches
from bridge_candidate_v75 import seal_features,seal_logits,seal_scope_receipt,_digest,_json
from bridge_candidate_v75_review import audit_one
from bridge_numpy_forward import weights_from_checkpoint
from bridge_numpy_reference_torch import reference


def run(output):
    OriginalWeightsSyntheticFeatures.setUpClass()
    fixture=OriginalWeightsSyntheticFeatures
    with tempfile.TemporaryDirectory(prefix='hepta-v75-realweights-synthetictokens-') as temp:
        root=Path(temp)
        source=root/'features'
        seal_features(source,fixture.rows,synthetic_batches(),
            model_sha='a'*64,tokenizer_sha='b'*64,preprocess_sha='c'*64,
            principal_sha='d'*64,purpose_sha='e'*64,origin='synthetic_test_only')
        result={}
        for seed in (41,47,53):
            candidate=root/f'original-v6-seed-{seed}.pt'
            candidate.write_bytes(fixture.checkpoints[seed])
            weights,_=weights_from_checkpoint(fixture.checkpoints[seed])
            def torch_forward(arrays):
                x=tuple(arrays[k] for k in ('facts','question','candidate'))
                m=tuple(arrays[k] for k in ('fact_mask','question_mask','candidate_mask'))
                return reference(weights,x,m,steps=3)[-1][1]
            for arm in ('joint','protect_old','protect_old_guarded'):
                folder=root/'predictions'/f'seed-{seed}'/arm
                folder.parent.mkdir(parents=True,exist_ok=True)
                seal_logits(source,folder,seed=seed,arm=arm,
                            checkpoint=candidate,torch_predict=torch_forward)
                probs=[]
                for i in range(8):
                    row=json.loads((folder/f'batch-{i:03d}.json').read_text())
                    arr=np.array(row['logits'],dtype=np.float64)
                    probs.extend(np.exp(arr[:,1]-np.logaddexp(arr[:,0],arr[:,1])).tolist())
                verified=audit_one(source,folder,candidate,fixture.rows,probs,
                                   seed=seed,arm=arm,allow_synthetic=True)
                result[f'{seed}/{arm}']=dict(original_warmup_checkpoint_sha256=verified['checkpoint_sha256'],
                    synthetic_case_rows=verified['case_count'],
                    max_abs_torch_numpy_logit_error=verified['max_abs_torch_numpy_logit_error'],
                    historical_old_task_training_score_not_measured=True,
                    synthetic_input_probe_correct=verified['old_binding_train_score']['original_candidate_correct'],
                    synthetic_probe_pair_correct=verified['old_binding_train_score']['original_world_pair_correct'],
                    synthetic_label_score_not_semantic_accuracy=True)
        assembly=seal_scope_receipt(source,root/'predictions',output=root/'assembly.json',
                       original_rows=fixture.rows,allow_synthetic=True)
        assert len(result)==9 and assembly['synthetic_test_only'] is True
        report=dict(schema='hepta.bridge.v75.synthetic-input-actual-v6-weights.mechanism.v1',
            status='MECHANISM_NUMERIC_PASS_NOT_PRETRAINED_TASK_QUALITY',
            input_origin='explicit_synthetic_fp32_features',
            original_v6_weight_source_sha256='197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a',
            original_model_pretrained_weight_checkpoints=3,
            logical_slots=9,unique_test_source_cases=128,
            repeated_arm_source_rows=9*128,
            historical_checkpoint_as_untrained_v75_candidate=True,
            genuine_granite_encoder_forward_count=0,
            authentic_v75_train_optimizer_updates=0,
            actual_v75_real_pretrained_9_arm_training_performed=False,
            peak_numeric_abs_error=max(r['max_abs_torch_numpy_logit_error'] for r in result.values()),
            synthetic_feature_acceptance_for_real_experiments=False,
            original_archive_real_source_case_ids_used=True,
            old_future_retention_verified=False,independent_natural_task_gain_verified=False,
            cell_split_authorized=False,ndu_selection_authorized=False,
            model_selection_authorized=False,production_authorized=False,
            results=result)
        Path(output).write_bytes(_json(report))
        return report

if __name__=='__main__':
    a=run(Path(__file__).with_name('V75_REAL_WEIGHTS_SYNTHETIC_INPUT_20261015.json'))
    print(json.dumps(dict(slots=a['logical_slots'],max_error=a['peak_numeric_abs_error'],
                          pretrained_execution=a['actual_v75_real_pretrained_9_arm_training_performed'])))
