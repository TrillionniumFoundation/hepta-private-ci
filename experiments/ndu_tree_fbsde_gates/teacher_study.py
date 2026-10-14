"""Two-process finite-tree -> Head synthetic training study; no production authority."""
from __future__ import annotations
import argparse
import hashlib
import json
import time
from pathlib import Path
from teacher_distillation import (cases,labels,fit,predict,frozen_control_predictions,
                                  fit_cheap_linear,cheap_linear_predictions,_digest)


def dump_new(path,obj):
    with open(path,'x',encoding='utf8') as f:
        json.dump(obj,f,sort_keys=True,indent=2)
        f.write('\n')


def emit(future_file,seal_file):
    study_start=time.process_time_ns()
    train=cases('train',7347,320)
    future=cases('future',7348,160)
    teacher_start=time.process_time_ns()
    train_y=labels(train)
    teacher_cpu_ns=time.process_time_ns()-teacher_start
    candidate=fit(train,train_y,steps=300,seed=19)
    learned=predict(candidate,future)
    linear,linear_cpu=fit_cheap_linear(train,train_y,steps=300,seed=19)
    paths={
        'learned_gate': learned['case_predictions'],
        'frozen_gate': frozen_control_predictions(candidate,future),
        'cheap_linear': cheap_linear_predictions(linear,future),
    }
    seal={
        'schema':'hepta.ndu-tree.teacher-shadow-predictions.v1',
        'train_source_digest':_digest(train),
        'future_source_digest':_digest(future),
        'trained_head_digest':candidate.trained_digest,
        'frozen_initial_head_digest':candidate.initial_digest,
        'train_group_digest':_digest(candidate.train_groups),
        'actual_train_steps_each':300,
        'gated_head_parameters':learned['head_parameters'],
        'gated_parameters_changed':candidate.observed_parameters_changed,
        'cheap_linear_parameters':len(linear),
        'synthetic_teacher_label_cpu_ns':teacher_cpu_ns,
        'whole_producer_cpu_ns_before_publication':time.process_time_ns()-study_start,
        'gated_fit_cpu_ns':candidate.training_cpu_ns,
        'linear_fit_cpu_ns':linear_cpu,
        'predictions':paths,
        'feature_type':'deterministic synthetic rational two-bit public-state encoding',
        'real_pretrained_encoder_executed':False,
        'independent_natural_outcomes_observed':False,
        'global_stochastic_fbsde_solved':False,
        'production_accepted':False,
        'authority':'DENY_ALL',
    }
    # Future source-only records and predictions are create-only; no scoring here.
    dump_new(future_file,list(future))
    dump_new(seal_file,seal)
    print(json.dumps({'seal_path':seal_file,'seal_sha256':hashlib.sha256(Path(seal_file).read_bytes()).hexdigest(),
                      'future_sha256':hashlib.sha256(Path(future_file).read_bytes()).hexdigest(),
                      'model_head_sha256':candidate.trained_digest,'future_rows':len(future)},sort_keys=True))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--future-file',required=True)
    p.add_argument('--seal-file',required=True)
    x=p.parse_args()
    emit(x.future_file,x.seal_file)

if __name__=='__main__':main()
