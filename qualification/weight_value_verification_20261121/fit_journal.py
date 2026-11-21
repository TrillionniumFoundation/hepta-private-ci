"""Persist complete fit checks at unchanged original-reader control-flow boundaries."""
from pathlib import Path
import time

from stage_contract import FITS, require, save_new, utc, verify_pin


class FitJournal:
    """A pending fit becomes durable only after the original CONF tail checks."""

    def __init__(self, reader, original, contract, contract_pin, output):
        self.reader, self.original = reader, original
        self.contract, self.contract_pin = contract, contract_pin
        self.output = Path(output)
        self.current, self.pending = None, None
        self.receipts = []
        self.primary_completed = False

    def main_fit(self, *args, **kwargs):
        self.flush('next_fit_entry_after_original_CONF_tail')
        fit = args[1]
        require(self.current is None and fit == FITS[len(self.receipts)], 'fit order or incomplete prior fit')
        self.current = dict(fit=fit, started_utc=utc(), start_CPU=time.process_time(),
                            start_wall=time.perf_counter(), before=dict(self.reader.COUNTS),
                            input_spec=args[0]['input_specs'][str(fit)], main_row=args[2])
        result = self.original['main_fit_check'](*args, **kwargs)
        self.current['main_result'] = result
        return result

    def confirmation_fit(self, *args, **kwargs):
        require(self.current is not None and self.current['fit'] == args[1] and
                'main_result' in self.current and self.pending is None, 'MAIN must complete before CONF')
        result = self.original['confirmation_fit_check'](*args, **kwargs)
        self.current['confirmation_row'] = args[3]
        self.current['confirmation_result'] = result
        self.pending = self.current
        # No receipt here: the original main still checks both domain completion times.
        return result

    def flush(self, boundary):
        if self.pending is None:
            return
        require(boundary in ('next_fit_entry_after_original_CONF_tail',
                             'budget_after_original_CONF_tail', 'primary_after_original_CONF_tail'),
                'unknown persistence boundary')
        item = self.pending
        fit = item['fit']
        require(len(self.receipts) < len(FITS) and fit == FITS[len(self.receipts)], 'duplicate fit')
        delta = {key: value - item['before'][key] for key, value in self.reader.COUNTS.items()}
        require(delta['own_graphs'] == 80 and delta['original_recursive_worlds'] == 16 and
                delta['TRAIN_hidden_calls'] == 1 and delta['CONF_hidden_calls'] == 16,
                'complete per-fit graph, feature and recursive queue')
        identities, main_summary = item['main_result']
        conf_summary, recursive = item['confirmation_result']
        require(set(conf_summary) == {'iid', 'ood'} and
                all(len(recursive[d]) == 8 for d in ('iid', 'ood')), 'complete per-fit domains')
        (self.output / 'fits').mkdir(exist_ok=True)
        record = dict(schema='hepta-verification-fit-complete-v1', status='FIT_COMPLETE',
            fit=fit, created_utc=utc(), stage_contract_pin=self.contract_pin,
            original_protocol_pin=self.contract['original']['protocol'],
            original_failed_reader=self.contract['original']['prior_failure'],
            new_source_pins=self.contract['source_pins'],
            input_spec=item['input_spec'], main_row=item['main_row'],
            confirmation_row=item['confirmation_row'], verified_model_identities=identities,
            old_TRAIN_summaries=main_summary, confirmation_summaries=conf_summary,
            original_recursive=recursive, counts_delta=delta, counts_cumulative=dict(self.reader.COUNTS),
            started_utc=item['started_utc'], CPU_seconds_since_fit_entry=time.process_time()-item['start_CPU'],
            wall_seconds_since_fit_entry=time.perf_counter()-item['start_wall'],
            persistence_boundary=boundary, original_CONF_tail_checks_completed=True,
            global_primary_and_final_source_checks_still_required=True,
            parent_process_completion_required=True, production_admission=False)
        identity = save_new(self.output / 'fits' / ('fit_' + str(fit) + '.json'), record)
        self.receipts.append(identity)
        self.pending = self.current = None

    def primary(self, *args, **kwargs):
        self.flush('primary_after_original_CONF_tail')
        require(len(self.receipts) == len(FITS) and self.current is None, 'five completed fits required')
        result = self.original['primary_check'](*args, **kwargs)
        self.primary_completed = True
        return result

    def finish(self, raw_result):
        require(self.pending is None and self.current is None and self.primary_completed and
                len(self.receipts) == len(FITS), 'all fit receipts and original primary checks required')
        require(raw_result['status'] == 'PASS' and raw_result['acceptance_requires_parent_process_COMPLETED'] is True,
                'original full reader completion required')
        require(raw_result['counts']['own_graphs'] == 400 and
                raw_result['counts']['original_recursive_worlds'] == 80, 'complete original work totals')
        for fit, identity in zip(FITS, self.receipts, strict=True):
            verify_pin(identity)
            require(Path(identity['path']).name == 'fit_' + str(fit) + '.json', 'fit receipt identity')
        return list(self.receipts)
