"""V29 research-only physical DINO execution through an exact minimal text route.

The full V27 precomputed image-class plan is forbidden by this entry point.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import v28_physical_lazy_vision as physical
import v29_route_only as route


def run(args):
    response=physical.run(args,route_loader=route.validate_model_plan)
    physical.require(response['frozen_route_plan_sha256']==route.MINIMAL_SHA256
                     and response['route_model_inputs_restricted_to_source_and_trigger'] is True,
                     'model-visible source-only plan identity mismatch')
    physical.require(response['actual_pretrained_vision_forward'] is True
                     and response['real_test_labels_opened'] is False
                     and response['new_training_updates']==0
                     and response['physical_end_to_end_savings_proven'] is False
                     and response['authority']=='DENY_ALL',
                     'physical observation/authority incompatible with V29')
    return response


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--source-dir',type=Path,required=True)
    parser.add_argument('--weights-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    result=run(parser.parse_args())
    print(json.dumps({'authority':'DENY_ALL',
         'actual_pretrained_vision_forward':result['actual_pretrained_vision_forward'],
         'original_route_minimized':True,
         'items_by_arm':[arm['items'] for arm in result['arm_traces']],
         'physical_end_to_end_savings_proven':False},sort_keys=True))
