"""Deterministic resource-envelope reference for P0.8C qualification."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Resources:
    cpu_millis: int
    memory_bytes: int
    disk_bytes: int
    network_bytes: int
    energy_millijoules: int
    risk_ppm: int

    def __post_init__(self) -> None:
        if min(self.values()) < 0:
            raise ValueError("resource values must be non-negative")
        if self.risk_ppm > 1_000_000:
            raise ValueError("risk_ppm exceeds one million")

    def values(self) -> tuple[int, ...]:
        return (
            self.cpu_millis,
            self.memory_bytes,
            self.disk_bytes,
            self.network_bytes,
            self.energy_millijoules,
            self.risk_ppm,
        )

    def plus(self, other: "Resources") -> "Resources":
        return Resources(*(left + right for left, right in zip(self.values(), other.values())))

    def minus(self, other: "Resources") -> "Resources":
        values = tuple(left - right for left, right in zip(self.values(), other.values()))
        if min(values) < 0:
            raise ValueError("resource release exceeds reservation")
        return Resources(*values)

    def fits(self, ceiling: "Resources") -> bool:
        return all(value <= limit for value, limit in zip(self.values(), ceiling.values()))


@dataclass(frozen=True)
class BudgetProfile:
    ceiling: Resources
    essential_floor: Resources
    maximum_active_reservations: int

    def __post_init__(self) -> None:
        if not self.essential_floor.fits(self.ceiling):
            raise ValueError("essential floor exceeds ceiling")
        if self.maximum_active_reservations <= 0:
            raise ValueError("reservation capacity must be positive")


class BudgetLedger:
    """Fail-closed reservation model; it never borrows from essential floors."""

    def __init__(self, profile: BudgetProfile) -> None:
        self.profile = profile
        self.used = profile.essential_floor
        self.reservations: dict[str, Resources] = {}

    def reserve(self, reservation_id: str, requested: Resources) -> bool:
        if not reservation_id or requested.risk_ppm == 0 and all(
            value == 0 for value in requested.values()[:-1]
        ):
            raise ValueError("reservation identity and non-zero request are required")
        existing = self.reservations.get(reservation_id)
        if existing is not None:
            if existing != requested:
                raise ValueError("reservation identity conflict")
            return True
        if len(self.reservations) >= self.profile.maximum_active_reservations:
            return False
        candidate_values = tuple(
            left + right for left, right in zip(self.used.values(), requested.values())
        )
        if not all(
            value <= limit
            for value, limit in zip(candidate_values, self.profile.ceiling.values())
        ):
            return False
        candidate = Resources(*candidate_values)
        self.reservations[reservation_id] = requested
        self.used = candidate
        return True

    def release(self, reservation_id: str) -> None:
        reservation = self.reservations.pop(reservation_id)
        self.used = self.used.minus(reservation)
        if not self.profile.essential_floor.fits(self.used):
            raise AssertionError("essential floor was borrowed")

    def degradation_mode(self) -> str:
        values = self.used.values()
        ceilings = self.profile.ceiling.values()
        peak = max(value / limit if limit else 1.0 for value, limit in zip(values, ceilings))
        if peak >= 0.95:
            return "critical_shed_optional"
        if peak >= 0.80:
            return "degraded_no_exploration"
        return "normal"
