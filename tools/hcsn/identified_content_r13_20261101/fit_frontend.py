"""Fit and save the shared frontend before any core or confirmation evaluation."""

import argparse
import json
import time

ENTRY_CPU = time.process_time()

from content import fit_frontend

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = fit_frontend(args.archive, args.output)
    print(json.dumps({'dataset': result['dataset'], 'training_iterations': result['training_iterations'],
                      'frontend_cpu_seconds': result['frontend_cpu_seconds'],
                      'entry_to_exit_cpu_seconds': time.process_time()-ENTRY_CPU,
                      'confirmation_encoded': False}), flush=True)
