"""Measured model-owner settlement into the shared hard reservation ledger.

Storage byte-time and logical I/O are explicitly incomplete, not zero resource
claims. OS block I/O, clocks, model work and retained inventories have independent
receipts. Dependency allocations never masquerade as repeated physical runs.
"""

from pathlib import Path
import resource
import sys
import time

from evolution_common import digest, retain, require


class EffectFailure(RuntimeError):
    """An infrastructure/budget failure must stop the experimental arm."""


def usage():
    owner, child = (
        resource.getrusage(resource.RUSAGE_SELF),
        resource.getrusage(resource.RUSAGE_CHILDREN),
    )
    return dict(
        cpu_ns=int(
            round(
                (owner.ru_utime + owner.ru_stime + child.ru_utime + child.ru_stime)
                * 1e9
            )
        ),
        read_bytes=(owner.ru_inblock + child.ru_inblock) * 512,
        write_bytes=(owner.ru_oublock + child.ru_oublock) * 512,
        rss_upper_bytes=(owner.ru_maxrss + child.ru_maxrss) * 1024,
    )


class ModelBudget:
    def __init__(self, output, budget_scripts, protocol_sha256):
        sys.path.insert(0, str(Path(budget_scripts).resolve()))
        from budget_ledger import BudgetLedger, METERS

        require(
            Path(sys.modules["budget_ledger"].__file__).resolve()
            == Path(budget_scripts).resolve() / "budget_ledger.py",
            "unbound budget ledger import",
        )
        self.budget_scripts = Path(budget_scripts).resolve()
        self.output, self.meters = Path(output), METERS
        limits = {k: 0 for k in METERS}
        limits.update(
            wall_ns=900_000_000_000,
            cpu_ns=1_800_000_000_000,
            decoder_updates=1024,
            router_updates=400,
            train_tokens=262144,
            decoder_queries=122,
            input_tokens=31232,
            output_tokens=1952,
            read_bytes=8 * 1024**3,
            write_bytes=1024**3,
        )
        prices = {
            k: 1
            if k
            in (
                "wall_ns",
                "cpu_ns",
                "decoder_updates",
                "router_updates",
                "train_tokens",
                "decoder_queries",
                "input_tokens",
                "output_tokens",
            )
            else 0
            for k in METERS
        }
        gauges = dict(
            retained_bytes=256 * 1024**2,
            private_bytes=128 * 1024**2,
            peak_rss_bytes=1536 * 1024**2,
        )
        self.ledger = BudgetLedger(
            self.output / "budget.sqlite",
            arm="physical_execution",
            protocol_sha256=protocol_sha256,
            limits=limits,
            gauges=gauges,
            prices=prices,
            cost_limit=3_000_000_000_000,
        )
        self.events, self.counter = [], 0

    def effect(
        self,
        phase,
        request,
        callback,
        counters,
        *,
        updates=0,
        queries=0,
        router_updates=0,
    ):
        event = f"effect-{self.counter:04d}"
        self.counter += 1
        upper = dict(
            wall_ns=121_000_000_000,
            cpu_ns=240_000_000_000,
            read_bytes=2 * 1024**3,
            write_bytes=128 * 1024**2,
            decoder_updates=updates,
            router_updates=router_updates,
            train_tokens=updates * 256,
            decoder_queries=queries,
            input_tokens=queries * 256,
            output_tokens=queries * 16,
        )
        try:
            lease = self.ledger.reserve(
                event, phase, upper, request_sha256=digest(request)
            )
            require(
                lease["state"] == "reserved",
                "effects cannot replay a settled reservation",
            )
        except BaseException as error:
            raise EffectFailure("effect reservation rejected: " + str(error)) from error
        before, started = usage(), time.monotonic_ns()
        try:
            value = callback()
            after, elapsed = usage(), time.monotonic_ns() - started
            work = counters(value)
            require(set(work) <= set(self.meters), "unregistered measured work field")
            measured = {
                k: after[k] - before[k] for k in ("cpu_ns", "read_bytes", "write_bytes")
            }
            measured.update(wall_ns=elapsed, **work)
            record = dict(
                schema="hepta.edge-model-budget-receipt.v1",
                event_id=event,
                phase=phase,
                request_sha256=digest(request),
                measured=measured,
                rss_sum_of_peaks_upper_bytes=after["rss_upper_bytes"],
                io_scope="Linux rusage block IO; not all logical file reads",
                storage_byte_time_measured=False,
                physical_execution=True,
            )
            retain(self.output / "budget-events" / (event + ".json"), record)
            self.ledger.settle(event, measured, receipt_sha256=digest(record))
            self.events.append(record)
            if (
                after["rss_upper_bytes"]
                > self.ledger.config["gauges"]["peak_rss_bytes"]
            ):
                previous = self.ledger.snapshot()["inventory"]["gauges"]
                self.ledger.observe_inventory(
                    previous | {"peak_rss_bytes": after["rss_upper_bytes"]},
                    inventory_sha256=digest(record),
                )
            return value
        except BaseException as error:
            self.ledger.abandon(
                event,
                reason=f"unsettled/failed effect: {type(error).__name__}: {error}",
            )
            raise EffectFailure("measured effect failed: " + str(error)) from error

    def inventory(self, components):
        from artifact_inventory import measure

        require(
            Path(sys.modules["artifact_inventory"].__file__).resolve()
            == self.budget_scripts / "artifact_inventory.py",
            "unbound inventory import",
        )
        value = measure(components)
        record = self.output / "inventories" / (str(time.monotonic_ns()) + ".json")
        retain(record, value)
        self.ledger.observe_inventory(
            dict(
                retained_bytes=value["logical_bytes"],
                private_bytes=value["private_bytes"],
                peak_rss_bytes=usage()["rss_upper_bytes"],
            ),
            inventory_sha256=value["inventory_sha256"],
        )
        return value

    def report(self):
        return dict(
            ledger=self.ledger.snapshot(),
            explicitly_unmeasured=[
                "transient_storage_byte_ns",
                "complete_logical_io",
                "shared_runtime_and_os_storage",
                "energy",
            ],
            observer_overhead_outside_leaf_effects=True,
            complete_total_cost_qualified=False,
            equal_total_cost_established=False,
        )
