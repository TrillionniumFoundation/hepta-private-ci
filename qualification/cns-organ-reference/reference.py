#!/usr/bin/env python3
"""Dependency-free deterministic CNS/organ reference."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable

class ValidationError(ValueError): pass
class ConflictError(RuntimeError): pass


def digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

@dataclass(frozen=True)
class ObjectiveSnapshot:
    objective_id: str
    revision: int
    principal_scope: str
    success_predicates: tuple[str, ...]
    hard_constraints: tuple[str, ...]
    legal_action_classes: tuple[str, ...]
    deadline_micros: int
    def semantic_digest(self) -> str:
        if self.revision < 1 or self.deadline_micros <= 0 or not self.success_predicates:
            raise ValidationError("invalid objective")
        return digest(self.__dict__)

@dataclass(frozen=True)
class OrganManifest:
    organ_id: str
    version: int
    organ_class: str
    dependencies: tuple[str, ...] = ()
    fallback_organs: tuple[str, ...] = ()
    essential: bool = False
    local_hot_path: bool = False
    central_rpc_required: bool = False
    effect_boundary: bool = False
    resource_floor: int = 0
    resource_ceiling: int = 100
    def validate(self) -> None:
        if not self.organ_id or self.version < 1 or not self.organ_class:
            raise ValidationError("invalid organ identity")
        if self.resource_floor < 0 or self.resource_ceiling < self.resource_floor:
            raise ValidationError("invalid resource envelope")
        if self.local_hot_path and self.central_rpc_required:
            raise ValidationError("local hot path cannot require central RPC")
        if self.organ_id in self.dependencies or self.organ_id in self.fallback_organs:
            raise ValidationError("self dependency/fallback")

class OrganState(str, Enum):
    PROPOSED="proposed"; BUILT="built"; SIMULATED="simulated"; QUALIFIED="qualified"
    DORMANT="dormant"; CANARY="canary"; ACTIVE="active"; DRAINING="draining"
    QUARANTINED="quarantined"; RETIRED="retired"

TRANSITIONS = {
    OrganState.PROPOSED:{OrganState.BUILT,OrganState.QUARANTINED},
    OrganState.BUILT:{OrganState.SIMULATED,OrganState.QUARANTINED},
    OrganState.SIMULATED:{OrganState.QUALIFIED,OrganState.QUARANTINED},
    OrganState.QUALIFIED:{OrganState.DORMANT,OrganState.CANARY,OrganState.QUARANTINED},
    OrganState.DORMANT:{OrganState.CANARY,OrganState.RETIRED,OrganState.QUARANTINED},
    OrganState.CANARY:{OrganState.ACTIVE,OrganState.DORMANT,OrganState.QUARANTINED},
    OrganState.ACTIVE:{OrganState.DRAINING,OrganState.QUARANTINED},
    OrganState.DRAINING:{OrganState.DORMANT,OrganState.RETIRED,OrganState.QUARANTINED},
    OrganState.QUARANTINED:{OrganState.DORMANT,OrganState.RETIRED},
    OrganState.RETIRED:set(),
}

@dataclass
class OrganInstance:
    manifest: OrganManifest
    state: OrganState = OrganState.PROPOSED
    qualified_artifact: str | None = None
    evaluator_identity: str | None = None
    def transition(self, target: OrganState, *, artifact: str|None=None, generator: str|None=None, evaluator: str|None=None) -> None:
        if target not in TRANSITIONS[self.state]: raise ValidationError(f"invalid transition {self.state}->{target}")
        if target is OrganState.QUALIFIED:
            if not artifact or not generator or not evaluator or generator == evaluator:
                raise ValidationError("qualification requires artifact and independent evaluator")
            self.qualified_artifact, self.evaluator_identity = artifact, evaluator
        if target in {OrganState.CANARY,OrganState.ACTIVE} and not self.qualified_artifact:
            raise ValidationError("activation requires qualification")
        self.state = target

@dataclass(frozen=True)
class BodyGraph:
    generation: int
    organs: tuple[OrganManifest, ...]
    def validate(self) -> tuple[str, ...]:
        if self.generation < 1 or not 1 <= len(self.organs) <= 256: raise ValidationError("invalid body graph")
        by_id={o.organ_id:o for o in self.organs}
        if len(by_id)!=len(self.organs): raise ValidationError("duplicate organ")
        for o in self.organs:
            o.validate()
            if set(o.dependencies)-set(by_id) or set(o.fallback_organs)-set(by_id): raise ValidationError("unknown graph reference")
            if o.essential and not o.fallback_organs and o.organ_class not in {"constitutional_kernel","human_override"}:
                raise ValidationError(f"essential organ {o.organ_id} requires fallback")
        indeg={k:0 for k in by_id}; out={k:[] for k in by_id}
        for o in self.organs:
            for dep in o.dependencies: out[dep].append(o.organ_id); indeg[o.organ_id]+=1
        ready=sorted(k for k,v in indeg.items() if v==0); order=[]
        while ready:
            n=ready.pop(0); order.append(n)
            for x in sorted(out[n]):
                indeg[x]-=1
                if indeg[x]==0: ready.append(x); ready.sort()
        if len(order)!=len(by_id): raise ValidationError("body graph cycle")
        # Dependencies and fallbacks are distinct graphs. Neither a fallback
        # cycle nor a fallback that needs the failed organ is a safe recovery.
        dependency_closure: dict[str, set[str]] = {}
        for organ_id in order:
            closure = set(by_id[organ_id].dependencies)
            for dependency in by_id[organ_id].dependencies:
                closure.update(dependency_closure[dependency])
            dependency_closure[organ_id] = closure
        for organ in self.organs:
            if len(set(organ.dependencies)) != len(organ.dependencies) or len(set(organ.fallback_organs)) != len(organ.fallback_organs):
                raise ValidationError("duplicate graph edge")
            for fallback in organ.fallback_organs:
                if organ.organ_id in dependency_closure[fallback]:
                    raise ValidationError("fallback depends on failed organ")
        fallback_degree = {organ_id: 0 for organ_id in by_id}
        for organ in self.organs:
            for fallback in organ.fallback_organs:
                fallback_degree[fallback] += 1
        pending = [organ_id for organ_id, degree in fallback_degree.items() if degree == 0]
        visited = 0
        while pending:
            current = pending.pop()
            visited += 1
            for fallback in by_id[current].fallback_organs:
                fallback_degree[fallback] -= 1
                if fallback_degree[fallback] == 0:
                    pending.append(fallback)
        if visited != len(by_id):
            raise ValidationError("fallback cycle")
        return tuple(order)

@dataclass(frozen=True)
class ResourceRequest:
    organ_id: str; floor: int; desired: int; priority: int

class HomeostasisController:
    @staticmethod
    def allocate(total: int, requests: Iterable[ResourceRequest]) -> dict[str,int]:
        req=sorted(requests,key=lambda r:(-r.priority,r.organ_id))
        if total < 0 or any(r.floor<0 or r.desired<r.floor for r in req): raise ValidationError("bad resource request")
        if len({r.organ_id for r in req}) != len(req): raise ValidationError("duplicate resource organ")
        floors=sum(r.floor for r in req)
        if floors>total: raise ValidationError("essential floors exceed endowment")
        out={r.organ_id:r.floor for r in req}; remaining=total-floors
        for r in req:
            add=min(remaining,r.desired-r.floor); out[r.organ_id]+=add; remaining-=add
        if sum(out.values())>total: raise AssertionError("allocation overflow")
        return out

@dataclass(frozen=True)
class SensorObservation:
    observation_id:str; sensor_id:str; monotonic_micros:int; calibration_generation:int
    body_generation:int; payload_digest:str; uncertainty_ppm:int; principal_scope:str
    def validate(self, *, now_micros:int, maximum_age_micros:int, calibration_generation:int, body_generation:int, scope:str) -> None:
        if self.sensor_id=="" or len(self.payload_digest)!=64: raise ValidationError("sensor identity/digest")
        if self.monotonic_micros>now_micros or now_micros-self.monotonic_micros>maximum_age_micros: raise ValidationError("stale/future sensor")
        if self.calibration_generation!=calibration_generation: raise ValidationError("calibration mismatch")
        if self.body_generation!=body_generation: raise ValidationError("body generation mismatch")
        if self.principal_scope!=scope or not 0<=self.uncertainty_ppm<=1_000_000: raise ValidationError("sensor scope/uncertainty")

@dataclass(frozen=True)
class BodyStateEstimate:
    generation:int; observed_through:int; integrity_ppm:int; uncertainty_ppm:int; source_digest:str

@dataclass(frozen=True)
class ActuationIntent:
    intent_id:str; objective_digest:str; body_generation:int; actuator_id:str
    final_payload_digest:str; deadline_micros:int; idempotency_key:str; authority_witness:str
    def semantic_digest(self)->str:
        if any(len(x)!=64 for x in (self.objective_digest,self.final_payload_digest,self.authority_witness)):
            raise ValidationError("intent digest")
        return digest(self.__dict__)

@dataclass(frozen=True)
class ReflexDecision:
    veto:bool; reason:str

class ReflexController:
    @staticmethod
    def evaluate(
        intent: ActuationIntent,
        body: BodyStateEstimate,
        *,
        now_micros: int,
        maximum_state_age_micros: int,
        minimum_integrity_ppm: int,
        maximum_uncertainty_ppm: int,
        human_stop: bool = False,
    ) -> ReflexDecision:
        """Revalidate the current fused state at dispatch, not only at ingress.

        All timestamps must belong to the same monotonic clock domain. A zero
        age budget permits only a state observed at this exact boundary. This
        deterministic reference does not verify physical calibration or tokens.
        """
        if human_stop is True:
            return ReflexDecision(True, "human_stop")
        profile = (now_micros, maximum_state_age_micros, minimum_integrity_ppm, maximum_uncertainty_ppm)
        if type(human_stop) is not bool or any(type(value) is not int or value < 0 for value in profile):
            return ReflexDecision(True, "invalid_safety_profile")
        if minimum_integrity_ppm > 1_000_000 or maximum_uncertainty_ppm > 1_000_000:
            return ReflexDecision(True, "invalid_safety_profile")
        state = (body.generation, intent.body_generation, body.observed_through, intent.deadline_micros, body.integrity_ppm, body.uncertainty_ppm)
        if any(type(value) is not int or value < 0 for value in state):
            return ReflexDecision(True, "invalid_body_state")
        if body.generation == 0 or intent.body_generation == 0 or body.integrity_ppm > 1_000_000 or body.uncertainty_ppm > 1_000_000:
            return ReflexDecision(True, "invalid_body_state")
        if intent.body_generation != body.generation:
            return ReflexDecision(True, "stale_body_generation")
        if now_micros >= intent.deadline_micros:
            return ReflexDecision(True, "deadline_expired")
        if body.observed_through > now_micros:
            return ReflexDecision(True, "future_body_state")
        if now_micros - body.observed_through > maximum_state_age_micros:
            return ReflexDecision(True, "stale_body_state")
        if body.integrity_ppm < minimum_integrity_ppm:
            return ReflexDecision(True, "integrity_floor")
        if body.uncertainty_ppm > maximum_uncertainty_ppm:
            return ReflexDecision(True, "uncertainty_ceiling")
        return ReflexDecision(False, "clear")

class EffectState(str,Enum):
    ACCEPTED="accepted"; DISPATCHED="dispatched"; INDETERMINATE="indeterminate"
    APPLIED="applied"; NOT_APPLIED="not_applied"; QUARANTINED="quarantined"

@dataclass
class ActuationLedger:
    intents:dict[str,tuple[str,EffectState]]=field(default_factory=dict)
    def accept(self,intent:ActuationIntent)->EffectState:
        d=intent.semantic_digest(); prior=self.intents.get(intent.idempotency_key)
        if prior and prior[0]!=d: raise ConflictError("idempotency semantic conflict")
        if prior:return prior[1]
        self.intents[intent.idempotency_key]=(d,EffectState.ACCEPTED); return EffectState.ACCEPTED
    def dispatch(self,key:str)->EffectState:
        d,s=self.intents[key]
        if s is not EffectState.ACCEPTED: raise ValidationError("dispatch transition")
        self.intents[key]=(d,EffectState.DISPATCHED); return EffectState.DISPATCHED
    def acknowledgement_lost(self,key:str)->EffectState:
        d,s=self.intents[key]
        if s is not EffectState.DISPATCHED: raise ValidationError("ack transition")
        self.intents[key]=(d,EffectState.INDETERMINATE); return EffectState.INDETERMINATE
    def observe_terminal(self,key:str,state:EffectState)->EffectState:
        if state not in {EffectState.APPLIED,EffectState.NOT_APPLIED,EffectState.QUARANTINED}: raise ValidationError("not terminal")
        d,s=self.intents[key]
        if s not in {EffectState.DISPATCHED,EffectState.INDETERMINATE}: raise ValidationError("terminal transition")
        self.intents[key]=(d,state); return state

@dataclass(frozen=True)
class PlanCandidate:
    candidate_id:str; expected_utility:int; resource_cost:int; hard_vetoes:tuple[str,...]=()

class CNSController:
    @staticmethod
    def select(candidates:Iterable[PlanCandidate], budget:int)->PlanCandidate:
        rows=list(candidates)
        if not rows: raise ValidationError("empty candidate set")
        feasible=[c for c in rows if not c.hard_vetoes and c.resource_cost<=budget]
        if not feasible: raise ValidationError("no feasible candidate")
        return sorted(feasible,key=lambda c:(-c.expected_utility,c.resource_cost,c.candidate_id))[0]

@dataclass(frozen=True)
class TopologyProposal:
    proposal_id:str; predecessor_generation:int; next_generation:int; operation:str
    generator_identity:str; evaluator_identity:str|None=None; selected:bool=False
    def validate(self,current_generation:int)->None:
        if self.predecessor_generation!=current_generation or self.next_generation!=current_generation+1: raise ValidationError("topology generation")
        if self.operation not in {"add","split","merge","rewire","retire"}: raise ValidationError("topology operation")
        if self.selected: raise ValidationError("proposal cannot self-select")
        if self.evaluator_identity and self.evaluator_identity==self.generator_identity: raise ValidationError("evaluator collision")

@dataclass(frozen=True)
class EpisodeRow:
    row_id:str; revoked:bool; utility:int

def consolidation_candidate(rows:Iterable[EpisodeRow])->tuple[str,...]:
    return tuple(sorted(r.row_id for r in rows if not r.revoked))

def default_reference_organs() -> tuple[OrganManifest, ...]:
    """Load the full registered anatomy; do not maintain a second toy graph.

    This loader is for repository qualification only. Runtime activation still
    requires its separately signed manifest and authority boundary.
    """
    path = Path(__file__).resolve().parents[2] / "docs/cns/CNS_ARCHITECTURE.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    rows = registry["organs"]
    if [row["id"] for row in rows] != registry["requiredOrganRoles"]:
        raise ValidationError("registered organ coverage mismatch")
    return tuple(
        OrganManifest(
            organ_id=row["id"],
            version=registry["schemaVersion"],
            organ_class=row["organClass"],
            dependencies=tuple(row["dependencies"]),
            fallback_organs=tuple(row["fallbackOrgans"]),
            essential=row["essential"],
            local_hot_path=row["localHotPath"],
            central_rpc_required=registry["organDefaults"]["centralSynchronousRpcAllowed"],
            effect_boundary=row["effectBoundary"],
        )
        for row in rows
    )
