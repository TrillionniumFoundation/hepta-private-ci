"""Enter only the frozen supplement through the scoped execution06 producer API."""

import argparse
import importlib
from pathlib import Path
import sys

SOURCE=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(SOURCE))
from operational.parameter_field_recovery06.postseal import prepare_plan as layout
from operational.parameter_field_recovery06.producer_adapter import ProducerAdapter


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,add_help=False)
    parser.add_argument('--producer-config',required=True)
    parser.add_argument('--expected-producer-config-sha256',required=True)
    parsed,remaining=parser.parse_known_args(argv)
    item=layout.descriptor(Path(parsed.producer_config).absolute())
    layout.need(item['sha256']==parsed.expected_producer_config_sha256,'External producer configuration pin differs')
    def option(name):
        layout.need(remaining.count(name)==1,'Missing/duplicate original argument: '+name)
        position=remaining.index(name)
        layout.need(position+1<len(remaining),'Missing original argument value')
        return remaining[position+1]
    plan_item=layout.descriptor(Path(option('--plan')).absolute())
    layout.need(plan_item['sha256']==option('--expected-plan-sha256'),'External plan pin differs')
    plan=layout.bound(plan_item)
    producer=layout.validate_plan(plan,item,plan['registered_source_commit'])
    module=importlib.import_module('supplements.parameter_field_fullstudy_20261030.postseal_supplement')
    layout.need(layout.descriptor(Path(module.__file__).resolve())['sha256']==layout.SUPPLEMENT_SHA,'Original supplement source changed')
    factory=ProducerAdapter(producer['producer_map'],producer['import_receipt'],producer['fresh_registration']).for_postseal(module)
    previous=sys.argv
    try:
        sys.argv=[str(Path(module.__file__).resolve()),*remaining]
        return factory.main()
    finally:
        sys.argv=previous


if __name__=='__main__':
    raise SystemExit(main())
