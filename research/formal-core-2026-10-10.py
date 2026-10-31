import ast
from pcb_routelab import runtime as C
K=C.module('research_contract',C.assets()/'congestion/policy-contract-2026-10-09.py')
A=C.module('research_model',__import__('pathlib').Path(__file__).parent/'model-policy-r2-2026-10-11.py')

def classify(expression):
    import numpy as np
    p=K.Policy(expression);out={}
    for e,inc in [('contest',.1),('rip',.1),('frontier',.025)]:
        out[e]=p.charge(np.array([0.,.001,.025,.1,.2,.5,1,2,10,100,1000]),inc,e).tolist()
    return {'syntactic_names':sorted({n.id for n in ast.walk(p.tree) if isinstance(n,ast.Name) and n.id in K.NAMES}),
      'old_dependence_observed_on_probe_grid':any(len(set(v))>1 for v in out.values()),
      'probe_values':out,'probe_is_not_global_symbolic_proof':True}

def feedback(rows):
    return {'columns':['family','context','safe','legal_complete','U','raw_error_count','vias','length_mm',
                        'events[contest,rip,frontier]:[count,cell_updates,repeat_updates]'],
      'rows':[[r['case'],r['context'],r.get('safe',False),r.get('clean_pass',False),r.get('U'),r.get('new_errors'),
       (r.get('geometry') or {}).get('vias'),(r.get('geometry') or {}).get('straight_track_length_mm'),
       [r['event_feedback'][k] for k in ('contest','rip','frontier')] if 'event_feedback' in r else None] for r in rows]}
