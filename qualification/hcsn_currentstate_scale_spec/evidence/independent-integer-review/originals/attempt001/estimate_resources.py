"""Stdlib symbolic dimensions/event graph only; no numerical state or kernels.

All packet dimensions are affine pairs (a,b) meaning a*n+b. No alpha,
generator, spatial law, floating matrix, semigroup, or quadrature is evaluated.
"""
from collections import Counter
from dataclasses import dataclass, replace
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import struct
import sys

HERE=Path(__file__).resolve().parent
CORE=Path('/workspace/scratch/c06d659c1e72/currentstate-packets/qualification/hcsn_currentstate/packets.py')
EXPECTED='940c40f87a10c8a71d12fd6cb7c8cf7c77b8ec359f863394fd01eedc826a2ccd'
CHANNELS=5
DELAY=F(1,5)

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def val(pair,n):return pair[0]*n+pair[1]
def packet_floats(k,c=CHANNELS):return k*k+(c+1)*k
def physical_floats(n,c=CHANNELS):return c*(2*n+10)
def readout_floats(n,c=CHANNELS):return c*(2*n+16)

@dataclass(frozen=True)
class Support:
    start:F
    end:F
    target:int
    dim:tuple

def summarize(packets):
    return [{'target':target,'dimension_a_n_plus_b':list(dim),'count':count}
            for (target,dim),count in sorted(Counter((p.target,p.dim) for p in packets).items())]

def graph(times,restored=None):
    packets=([Support(F(j,40),F(j+1,40),1,(0,1)) for j in range(8)]
             if restored is None else list(restored[1]))
    now=F(0) if restored is None else restored[0]
    events=[];queries=[];states={}
    for query in times:
        assert now<=query<=F(9,25)
        while now<query:
            right=min(t for t in [query,now+DELAY]+[x for p in packets for x in (p.start,p.end)] if t>now)
            releasing=[p for p in packets if p.start==now]
            assert len(releasing)<=1, 'disjoint-source assumption violated'
            assert all(p.target<=2 for p in releasing)
            source=(sum(p.dim[0] for p in releasing),sum(p.dim[1] for p in releasing))
            # These dimensions follow the output-ancestor graph under an
            # irreducible spatial generator and nonzero lower boundary rate.
            phase_sources=[p for p in releasing if p.target==1]
            first_dim=(1,sum(p.dim[1] for p in phase_sources))
            new=[Support(now+DELAY,right+DELAY,2,first_dim)]
            if now>=DELAY:
                previous=[p for p in releasing if p.target==2]
                second_dim=(1+sum(p.dim[0] for p in previous),sum(p.dim[1] for p in previous))
                new.append(Support(now+DELAY,right+DELAY,3,second_dim))
            future=[]
            for p in packets:
                if p in releasing:
                    if p.end>right:future.append(replace(p,start=right))
                else:future.append(p)
            packets=future+new
            events.append({'left':str(now),'right':str(right),
                           'source_dim_a_n_plus_b':list(source),
                           'C_dim_a_n_plus_b':[source[0]+2,source[1]],
                           'new_packet_dimensions':summarize(new)})
            now=right
        queries.append({'time':str(query),'packets':len(packets),'groups':summarize(packets)})
        states[query]=(now,tuple(packets))
    exps=2*len(events)+2*sum(q['packets'] for q in queries)
    return {'segments':len(events),'advance_expm_calls_structural':2*len(events),
            'observe_expm_calls_structural':2*sum(q['packets'] for q in queries),
            'total_expm_calls_structural':exps,'queries':queries,'events':events,
            'final_packet_groups':summarize(packets)},states

def payload_profile(n,groups):
    p=sum(g['count'] for g in groups)
    count=physical_floats(n)+sum(g['count']*packet_floats(val(g['dimension_a_n_plus_b'],n)) for g in groups)
    arrays=5+3*p
    return {'packet_count':p,'float64_count':count,'float64_array_bytes':8*count,
            'nonempty_hex_array_groups':arrays,
            'hex_contents_lower_bytes_excluding_brackets_metadata':11*count-arrays,
            'hex_arrays_lower_bytes_including_brackets_excluding_metadata':11*count+arrays,
            'hex_contents_upper_bytes_excluding_brackets_metadata':27*count-arrays,
            'CPython_ASCII_strings_plus_list_slots_lower_estimate_bytes':
                count*(sys.getsizeof('0x0.0p+0')+struct.calcsize('P')),
            'exceeds_legacy_900000_byte_cap_by_hex_contents_lower_bound':11*count-arrays>900000}

def main():
    before=digest(CORE);assert before==EXPECTED
    minimal,_=graph((F(9,25),))
    warm_times=tuple(F(x) for x in ('0','.001','.02','.16','.2','.201','.28','.36'))
    warm,states=graph(warm_times)
    coarse,_=graph((F(0),F(1,5),F(9,25)))
    cold,_=graph((F(201,1000),F(7,25),F(9,25)),restored=states[F(201,1000)])
    assert minimal['segments']==15 and minimal['queries'][-1]['packets']==16
    assert (warm['segments'],coarse['segments'],cold['segments'])==(21,15,9)
    assert [x['packets'] for x in warm['queries']]==[8,9,10,11,11,12,18,22]
    assert (warm['total_expm_calls_structural'],coarse['total_expm_calls_structural'],cold['total_expm_calls_structural'])==(244,94,122)
    profiles=[]
    for intervals in (128,256,512):
        n=intervals-1;c=CHANNELS
        packets=[]
        for label,k in [('first_hit_without_phase_source',n),('first_hit_with_scalar_phase_source',n+1),('second_hit_after_first_packet_release',2*n+1)]:
            f=packet_floats(k,c)
            packets.append({'kind':label,'dimension':k,'generator_float64_bytes':8*k*k,
                            'all_packet_array_float64_count':f,'all_packet_array_float64_bytes':8*f,
                            'hex_contents_lower_bytes':11*f-3})
        dimensions=[]
        for label,s in [('no_releasing_packet',0),('original_scalar_phase_release',1),('one_first_hit_packet_release',n+1)]:
            m=2*n+s;d=m+8
            # Visible dense arrays held before/during the second integral's
            # matrix multiplication, excluding backend-internal workspaces.
            visible=m*m+(m+3)**2+(m+5)**2+2*(m+8)**2
            dimensions.append({'case':label,'releasing_source_dim':s,'C_dim':m,
                               'first_advance_expm_dim':m+5,'second_advance_expm_dim':d,
                               'one_largest_dense_float64_matrix_bytes':8*d*d,
                               'two_visible_argument_matrices_float64_bytes':16*d*d,
                               'visible_C_extended_first_result_second_z_and_argument_bytes':8*visible,
                               'dimension_cube_scaling_unit':d**3})
        profiles.append({'intervals_N':intervals,'interior_n':n,'channels_C':c,
                         'physical_state_float64_count':physical_floats(n,c),
                         'readout_scalar_denominator_per_query':readout_floats(n,c),
                         'planned_14_readouts_scalar_denominator':14*readout_floats(n,c),
                         'planned_8_unique_reference_scalar_denominator':8*readout_floats(n,c),
                         'external_physics_float64_count_including_discount':n*n+3*n+1,
                         'dimension_cases':dimensions,'packet_cases':packets,
                         'minimal_single_advance_final':payload_profile(n,minimal['final_packet_groups']),
                         'planned_warm_final':payload_profile(n,warm['final_packet_groups']),
                         'planned_coarse_final':payload_profile(n,coarse['final_packet_groups']),
                         'planned_resume_0_201':payload_profile(n,warm['queries'][5]['groups']),
                         'existing_operator_refusals':{
                            'Physics_n_not_1_or_2':n not in (1,2),'channels_not_three':c!=3,
                            'no_source_C_exceeds_64':2*n>64,'no_source_largest_expm_exceeds_128':2*n+8>128,
                            'first_phase_packet_exceeds_64':n+1>64,
                            'active_array_axis_exceeds_128':n>128,
                            'second_packet_array_axis_exceeds_128':2*n+1>128,
                            'planned_warm_segments_exceed_20':warm['segments']>20,
                            'planned_warm_expm_exceed_resume_ledger_100':warm['total_expm_calls_structural']>100,
                            'planned_cold_expm_exceed_resume_ledger_100':cold['total_expm_calls_structural']>100}})
    after=digest(CORE);assert before==after
    pergrid=sum(x['total_expm_calls_structural'] for x in (warm,coarse,cold))
    pergridsegments=sum(x['segments'] for x in (warm,coarse,cold))
    result={
      'identity':'currentstate-largegrid-stdlib-static-cost-v1',
      'reviewed_core_source':str(CORE),'reviewed_core_source_freeze':'de3d9372d8bd53bb4c523c6f1a43e3e213d33790',
      'core_sha256_before':before,'core_sha256_after':after,
      'input_binding_status':'parent-supplied intended binding; no NPZ or actual selected law loaded by this reviewer',
      'binding':{'intervals_N':[128,256,512],'interior_n':'N-1','channels':5,'signed_channels':4,
                 'L':'8','graded_stretch':'6','reset_point_decimal':'0.3131468965881033',
                 'phase_supports':'[j/40,(j+1)/40], j=0,...,7','delay':'1/5','max_time':'9/25',
                 'upper_state':'permanently active and nonreturning',
                 'N128_N512_inputs':'parent reports original NPZ+JSON persisted in #6234 archive; not loaded here',
                 'N256_inputs':'missing export: hard input gate; no regeneration performed'},
      'assumptions':['Direct extension preserves dense arrays, two active generations, three upper origins and exact-support packets.',
                     'Spatial generator is irreducible with a nonzero lower-hit selector; reset couples the incoming source to it.',
                     'All eight initial phase packets are represented; supports are disjoint. No floating coefficient threshold pruning.',
                     'No new input/physics/reset changes during the episode; T<=.36<2d.',
                     'Event graph counts source/active ancestor dimensions, not any numerical semigroup or hit probability.'],
      'formulas':{'C_dimension':'m=2n+s, s=sum dimensions of simultaneously releasing continuous packets',
                  'advance_expm_dimensions':['m+5','m+8'],'observe_expm_dimension':'k+1, twice per flux packet per readout',
                  'packet_float64_count':'k^2+(C+1)k','physical_state_float64_count':'C(2n+10)',
                  'readout_scalar_count':'C(2n+16)','minimal_final_F_C5':'37n^2+180n+113',
                  'planned_warm_final_F_C5':'52n^2+246n+134','array_group_count':'A=5+3P',
                  'hex_contents_lower':'11F-A; exclude [] and all metadata',
                  'hex_arrays_lower':'11F+A; include [] but exclude dictionary/shape/support/hash metadata',
                  'hex_contents_upper':'27F-A for finite binary64 only; metadata has no universal bound for arbitrary Fraction denominators'},
      'minimal_graph':minimal,'planned_warm_graph':warm,'planned_coarse_graph':coarse,'planned_cold_graph':cold,
      'profiles':profiles,
      'planned_all_three_grids':{'readouts':42,'capsules':42,'warm_cold_raw_pairs':9,
                                'structural_expm_calls':3*pergrid,'structural_segments':3*pergridsegments,
                                'observation_scalar_denominator':sum(p['planned_14_readouts_scalar_denominator'] for p in profiles),
                                'unique_reference_scalar_denominator':sum(p['planned_8_unique_reference_scalar_denominator'] for p in profiles)},
      'memory_qualifications':['All array byte figures are estimates or strict representation lower bounds, never measured peak RSS.',
                              'Visible dense matrix count excludes scipy workspace, expression temporaries, Python/numpy headers and old states.',
                              'CPython payload estimate assumes independently allocated compact ASCII hex strings, at least57 bytes each plus8-byte list slots on this interpreter; not a portable RSS certificate.',
                              'No generic JSON metadata upper bound exists without a bound on rational numerator/denominator bit lengths. The worked schedules use denominators dividing1000.'],
      'new_candidate_calls':0,'new_reference_calls':0,'new_expm_calls':0,'new_quadratures':0,
      'numpy_imports':0,'scipy_imports':0,'core_imports':0,'model_runs':0,'NPZ_loads':0,
      'integer_event_graph_only':True,'N256_hard_input_gate':True,
      'dynamic_admission':'REJECTED_BY_EXISTING_CAPS_AND_NOT_EXECUTED','admission':'HOLD_NO_GO','all_closed':False,
      'reviewer_source_sha256':digest(Path(__file__))
    }
    raw=(json.dumps(result,indent=2)+'\n').encode();(HERE/'STATIC_COST.json').write_bytes(raw)
    print(json.dumps({'static_only':True,'core_sha256':before,'new_expm':0,'new_model':0,
                      'warm_segments':warm['segments'],'coarse_segments':coarse['segments'],'cold_segments':cold['segments'],
                      'warm_expm_structural':244,'coarse_expm_structural':94,'cold_expm_structural':122,
                      'all_three_grids_expm_structural':3*pergrid,
                      'output_sha256':hashlib.sha256(raw).hexdigest()}))

if __name__=='__main__':main()
