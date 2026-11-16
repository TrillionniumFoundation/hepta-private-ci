"""Use the closed finite-window loss field in the same certified terminal problem."""

import time

from cell_field_observable_v6 import build_field
from cell_field_planner_v5 import make_plan as reference_plan, solve_terminal


def make_plan(state,split,old_anchor,*,method,horizon,dt=.02,effort_price=.1,
              action_bound=1.,old_weight=0.,hard_retention=True):
    options={"horizon":horizon,"dt":dt,"effort_price":effort_price,
             "action_bound":action_bound,"old_weight":old_weight,"hard_retention":hard_retention}
    if method != "future_field":
        return reference_plan(state,split,old_anchor,method=method,**options)
    cpu,wall=time.process_time_ns(),time.perf_counter_ns()
    response,field=build_field(state,split,horizon=horizon,dt=dt)
    maps=field.terminal_maps()
    result=solve_terminal(maps,response.observations[-1],old_anchor,
        **{key:value for key,value in options.items() if key!="horizon"})
    arrays=field.arrays()
    if result["actions"] is not None:
        arrays["planned_loss_path"]=response.observations+field.forecast(result["actions"])["losses"]
    result.update(maps=maps,reference_states=response.states,reference_observations=response.observations,
                  field_arrays=arrays,cpu_ns=time.process_time_ns()-cpu,wall_ns=time.perf_counter_ns()-wall)
    result["record"].update(method=method,reference_cpu_ns=response.cpu_ns,
        complete_optimizer_dimension=3*state.parameter_count,field_dimensions=[len(x) for x in field.observations],
        field_coefficient_bytes=sum(x.nbytes for x in (*field.observations,*field.inputs)),
        field_scope="closed local finite-window loss outputs; coefficients from full known reference, not autonomous nonlinear observer")
    return result
