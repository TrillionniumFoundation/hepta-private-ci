"""Use independent results to qualify each policy, without changing any model."""

import argparse
import json
from pathlib import Path
import time

from .common import sha, write


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    original = json.loads(args.template.read_text())
    qualification = json.loads(args.qualification.read_text())
    protocol = json.loads(args.protocol.read_text())
    templates, decisions = {}, {}
    for policy in ('dynamic', 'fixed_late'):
        result = qualification['summary'][policy]
        if result['ID_actual_requests'] != 160 or result['all_missing_actual_requests'] != 600:
            raise ValueError('The complete registered source census was not executed')
        template = json.loads(json.dumps(original))
        template['policy'] = policy
        if result['study_qualified']:
            verification = {**result, 'schema': 'hepta.advance.semantic-owner-verification.v1',
                'qualification_protocol_sha256': original['pins']['protocol'],
                'calibration_sha256': original['pins']['calibration'], 'weights_sha256': original['pins']['weights'],
                'native_measured_ece_ppm': round(max(result['selected_initial_operation_ECE'],
                    result['pooled_fixed_endpoint_counterfactual_code_ECE']) * 1e6),
                'native_measured_false_acceptance_ppm': round(result['all_missing_false_acceptances'] / 600 * 1e6),
                'nonempty_definition': 'fraction_of_ID_requests_with_at_least_one_admitted_action',
                'minimum_confidence_ppm': 750000, 'maximum_ece_ppm': 30000, 'maximum_false_acceptance_ppm': 4999,
                'independent_result_sha256': sha(args.qualification)}
            path = args.output / (policy + '-verification.json')
            write(path, verification)
            template['verification_path'] = str(path)
            template['pins'].update(verification=sha(path), measured_ece_ppm=verification['native_measured_ece_ppm'],
                                   measured_false_acceptance_ppm=verification['native_measured_false_acceptance_ppm'])
            template['mode'] = 'qualified'
        else:
            # Preserve the failed independent report. The original development
            # profile permits research diagnosis; it is never relabelled PASS.
            template['mode'] = 'qualification_collection'
        destination = args.output / (policy + '-template.json')
        write(destination, template)
        templates[policy] = str(destination)
        decisions[policy] = {'mode': template['mode'], 'independent_gates': result['gates'],
            'failed_independent_result_preserved': not result['study_qualified']}
    write(args.output / 'TEMPLATES.json', templates)
    protocol['phase'] = 'confirmation'
    protocol['source_roles'] = ['confirmation']
    protocol['frozen_unix_ns'] = time.time_ns()
    protocol['qualification_sha256'] = sha(args.qualification)
    protocol['policy_modes'] = decisions
    for path in list(args.output.glob('*.json')) + [args.qualification]:
        protocol['frozen_candidate_sha256'][str(path.resolve())] = sha(path)
    write(args.output / 'CONFIRMATION_SPEC.json', protocol)
    write(args.output / 'PROMOTION.json', {'schema': 'hepta.advance.native-policy-qualification-decision.v1',
        'policy_decisions': decisions, 'model_weights_changed': False, 'calibration_changed': False,
        'full_registered_research_continues_even_if_policy_not_qualified': True,
        'qualification_sha256': sha(args.qualification), 'confirmation_spec_sha256': sha(args.output / 'CONFIRMATION_SPEC.json')})
    print(json.dumps(decisions))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('template', 'qualification', 'protocol', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    run(p.parse_args())
