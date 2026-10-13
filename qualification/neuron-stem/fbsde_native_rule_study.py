"""Execute native composition on real files; negative outcomes remain evidence.

One already-known finite rule is a CPU driver fixture, not a new identification
or efficacy experiment. Every native key is research-only and role-separated.
"""
import argparse
import json
from pathlib import Path
import resource
import threading
import time

from four_gate_common import digest, require
from fbsde_checkpoint_audit import validate_rows
from fbsde_durable_rule import DurableRuleSlot
from fbsde_native_rule import NativeRulePort, NativeRuleSlotConsumer, canonical
from fbsde_rule_checkpoint import RuleCheckpoint
from fbsde_transfer import TransferProblem, TransferTable, OPS

PUBLIC = dict(source_id='native-rule-research-fixture', names=['Alice', 'Bob', 'Cara'],
    event='Alice, Bob and Cara execute the registered operation.')
CONTEXT = dict(scope='native-rule-research', generation=1, environment='finite-reset-fixture')


def create(directory):
    problem = TransferProblem.build(PUBLIC, CONTEXT)
    history = tuple(enumerate(problem.table[1]))
    table = TransferTable.from_support(problem, history, dict(binding=problem.binding, **CONTEXT))
    return DurableRuleSlot(RuleCheckpoint(directory, create=True), PUBLIC, CONTEXT, history, table.snapshot())


def reveal(request):
    problem = TransferProblem.build(PUBLIC, CONTEXT)
    return dict(request_sha256=digest(request), effect=OPS[problem.table[1][OPS.index(tuple(request['state']))]])


class ConfiguredPort(NativeRulePort):
    def __init__(self, *args, config=None, **kwargs):
        self.config = config or {}
        self.transcript = []
        super().__init__(*args, **kwargs)

    def call(self, value):
        value = dict(value, **self.config.get(value['command'], {}))
        result = super().call(value)
        self.transcript.append(dict(request=value, response=result))
        return result


def run(executable, output):
    require(not output.exists(), 'create-only native evidence output')
    output.mkdir(parents=True, mode=0o700)
    started_cpu, started_wall = time.process_time_ns(), time.perf_counter_ns()
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    cases = []
    names = ('successful', 'concurrent_finish', 'finaluse_revoked_after_claim', 'finaluse_revoked_restart', 'rule_revoked', 'signed_current_corrupt',
        'selection_expired', 'late_inference', 'driver_unknown', 'driver_panic', 'local_finish_unknown', 'native_restart',
        'rule_restart', 'recovery_new_selection', 'unverified_source')
    for name in names:
        root = output / name
        root.mkdir(mode=0o700)
        local, native = root / 'rule', root / 'native'
        local.mkdir(mode=0o700); native.mkdir(mode=0o700)
        config = {}
        if name == 'selection_expired': config['init'] = dict(selection_lifetime_s=1)
        if name == 'finaluse_revoked_after_claim': config['execute'] = dict(revoke_after_claim=True)
        if name == 'late_inference': config['execute'] = dict(timeout_ms=100, driver_delay_ms=250)
        if name == 'driver_unknown': config['execute'] = dict(driver_fail=True)
        if name == 'driver_panic': config['execute'] = dict(driver_panic=True)
        slot, port, consumer = None, None, None
        case = dict(name=name, returned=[], refusals=[], expected_refusal=name not in ('successful','concurrent_finish','recovery_new_selection'),
                    production_qualified=False)
        before_cpu, before_wall = time.process_time_ns(), time.perf_counter_ns()
        try:
            slot = create(local)
            port = ConfiguredPort(executable, native, config=config)
            consumer = NativeRuleSlotConsumer(slot, port)
            if name == 'recovery_new_selection':
                old_ticket = slot.begin(PUBLIC['event'], PUBLIC['names'], OPS[0])
                require(consumer.verify(old_ticket, reveal), 'initial current source verification')
                case['returned'].append(list(consumer.finish(old_ticket)))
                floor = slot.checkpoint_anchor(); slot.close()
                slot = DurableRuleSlot.reopen(RuleCheckpoint(local, anchor=floor), dict(CONTEXT, generation=2))
                consumer.slot = slot
                try: consumer.finish(old_ticket)
                except ValueError as error:
                    case['refusals'].append(dict(type=type(error).__name__, reason=str(error)))
                require(slot.status()['state'] == 'quarantined', 'old native candidate revived restarted rule')
                recovery_calls = []
                def paid_reveal(request):
                    recovery_calls.append(dict(request))
                    return reveal(request)
                require(slot.relearn(paid_reveal), 'paid fresh source recovery')
                case['recovery'] = dict(calls=recovery_calls, status=slot.status())
                case['prior_wrapper_costs'] = consumer.costs
                port.config['init'] = dict(command='install_revision')
                consumer = NativeRuleSlotConsumer(slot, port)
                require(port.call(dict(command='restart'))['ok'], 'restart exact fresh native selection')
            if name == 'rule_revoked': slot.advance_generation(2)
            if name == 'signed_current_corrupt': require(port.call(dict(command='corrupt_current'))['ok'], 'current mutation failed')
            if name == 'selection_expired': require(port.call(dict(command='expire_selection'))['ok'], 'expiry wait failed')
            if name == 'native_restart': require(port.call(dict(command='restart'))['ok'], 'native restart failed')
            if name == 'finaluse_revoked_restart':
                require(port.call(dict(command='revoke_finaluse', sequence=1))['ok'], 'persist finaluse revocation')
                require(port.call(dict(command='restart'))['ok'], 'restart revoked native authority')
            if name == 'rule_restart':
                floor = slot.checkpoint_anchor(); slot.close()
                slot = DurableRuleSlot.reopen(RuleCheckpoint(local, anchor=floor), CONTEXT)
                consumer.slot = slot
            states = OPS if name == 'successful' else (OPS[0],)
            for state in states:
                try:
                    ticket = slot.begin(PUBLIC['event'], PUBLIC['names'], state)
                    if name != 'unverified_source': require(consumer.verify(ticket, reveal), 'source verification failed')
                    case['last_acknowledged_anchor'] = slot.checkpoint_anchor()
                    if name == 'native_restart':
                        # One persisted native execution is reconciled, never repeated.
                        command = dict(command='execute', **consumer.descriptor, sequence=ticket.sequence,
                            input_state=list(state), expected_prediction_q24=[x*(1 << 24) for x in OPS[1]],
                            checkpoint_anchor=slot.checkpoint_anchor())
                        require(port.call(command)['ok'], 'initial native completion before restart')
                        require(port.call(dict(command='restart'))['ok'], 'second native restart failed')
                    if name == 'local_finish_unknown':
                        def fault(stage, event):
                            if stage == 'after_commit' and event == 'finish': raise OSError('lost SQLite finish reply')
                        slot._store._fault = fault
                    if name == 'concurrent_finish':
                        rendezvous = threading.Barrier(3)
                        def finish_once():
                            rendezvous.wait()
                            try: case['returned'].append(list(consumer.finish(ticket)))
                            except Exception as error:
                                case['refusals'].append(dict(type=type(error).__name__, reason=str(error)))
                        threads = [threading.Thread(target=finish_once) for _ in range(2)]
                        for thread in threads: thread.start()
                        rendezvous.wait()
                        for thread in threads: thread.join(30)
                        require(not any(thread.is_alive() for thread in threads), 'bounded concurrent use')
                    else: case['returned'].append(list(consumer.finish(ticket)))
                except Exception as error:
                    case['refusals'].append(dict(type=type(error).__name__, reason=str(error)))
            if name == 'successful':
                require(len(case['returned']) == 6 and not case['refusals'], 'successful native domain use')
            elif name == 'concurrent_finish':
                require(len(case['returned']) == len(case['refusals']) == 1, 'one concurrent native delivery')
            elif name == 'recovery_new_selection':
                require(len(case['returned']) == 2 and len(case['refusals']) == 1, 'fresh selection recovery deliveries')
            else:
                require(not case['returned'] and case['refusals'], 'negative case must not deliver')
            case['slot_status'] = slot.status()
            case['wrapper_costs'] = consumer.costs
            case['transport_costs'] = port.calls
            case['native_transcript'] = port.transcript
            # A poisoned handle cannot expose a new floor. Retain raw SQLite
            # bytes and its prior independent acknowledgement for reconciliation.
            if not slot._dead:
                case['checkpoint_anchor'] = slot.checkpoint_anchor()
                validate_rows(slot._store.rows())
            case['passed_contract'] = True
        except Exception as error:
            case.update(passed_contract=False, failure=dict(type=type(error).__name__, reason=str(error)))
        finally:
            if consumer: case['wrapper_costs'] = consumer.costs
            if port:
                case['transport_costs'] = port.calls
                case['native_transcript'] = port.transcript
            if consumer: consumer.close()
            elif port: port.close()
            if port: case['native_exit_code'] = port._process.returncode
            if slot: slot.close()
        case.update(parent_cpu_ns=time.process_time_ns()-before_cpu,
            wall_ns=time.perf_counter_ns()-before_wall,
            file_bytes=sum(path.stat().st_size for path in root.rglob('*') if path.is_file()))
        (root / 'case.json').write_bytes(canonical(case))
        cases.append(case)
    children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    summary = dict(schema='hepta.native-rule-composition-study.v1', cases=cases,
        passed_contracts=sum(case['passed_contract'] for case in cases), total=len(cases),
        parent_cpu_ns=time.process_time_ns()-started_cpu, wall_ns=time.perf_counter_ns()-started_wall,
        native_children_user_cpu_s=children_after.ru_utime-children_before.ru_utime,
        native_children_system_cpu_s=children_after.ru_stime-children_before.ru_stime,
        production_qualified=False, four_gate_changed=False,
        limits=['CPU finite permutation fixture; no pretrained weights or future Hepta efficacy',
            'named artifact owner durable Revoke/Quarantine publication remains unavailable; native signed revoked-view tests use its read-only verifier proxy',
            'process/file durability, not hardware power-loss qualification',
            'native execution then local durable finish is fail-closed, not distributed exactly-once',
            'raw completed inference observation can coexist with refused late RuleSlot delivery',
            'fresh recovery repeats the same known finite mechanism, not independent semantic learning'])
    (output / 'summary.json').write_bytes(canonical(summary))
    print(json.dumps({key: summary[key] for key in ('passed_contracts','total','wall_ns','parent_cpu_ns',
        'native_children_user_cpu_s','native_children_system_cpu_s','production_qualified')}))
    require(summary['passed_contracts'] == summary['total'], 'native composition study failed; evidence retained')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.executable, args.output)
