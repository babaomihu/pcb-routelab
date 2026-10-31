"""Process-local history hook, installed before route imports; no engine edits."""
import argparse
import hashlib
import importlib.util
import json
import runpy
import sys
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('discovery_common',ROOT/'common-2026-10-09.py')
C=importlib.util.module_from_spec(spec);spec.loader.exec_module(C)

def main():
    p=argparse.ArgumentParser();p.add_argument('--policy',required=True);p.add_argument('--trace',required=True)
    p.add_argument('route_args',nargs=argparse.REMAINDER);args=p.parse_args()
    policy_data=C.load(Path(args.policy))
    sys.path.insert(0,str(C.ENGINE))
    import history_congestion as H
    K=C.module('congestion_policy_contract',ROOT/'policy-contract-2026-10-09.py')
    policy=K.Policy(policy_data['expression'])
    if H.history_knobs()['escalate']!=0:raise ValueError('v1 expression contract fixes native escalate=0')
    trace={'policy':policy_data,'policy_sha256':C.sha(Path(args.policy)), 'knobs':H.history_knobs(),
           'events':[],'consumption':[],'exception':None}
    context=[]
    for name,event in [('record_rip','rip'),('record_contested','contest'),('record_blocked_frontier','frontier')]:
        original=getattr(H,name)
        def wrapper(*a,_original=original,_event=event,**kw):
            context.append(_event)
            try:return _original(*a,**kw)
            finally:context.pop()
        setattr(H,name,wrapper)
    def accumulate(field,cells,inc):
        item=K.update(field,cells,inc,policy,context[-1] if context else 'unknown',H.env_knobs.HISTORY)
        if item:trace['events'].append(item)
    H.HistoryField.accumulate=accumulate
    original_source=H.add_history_source
    def add_source(ghost_costs,config):
        result=original_source(ghost_costs,config)
        if result is not None and H.HISTORY_SOURCE_KEY in result:
            rows=result[H.HISTORY_SOURCE_KEY]
            trace['consumption'].append({'rows':int(len(rows)), 'sha256':hashlib.sha256(rows.tobytes()).hexdigest(),
                                          'max_cost':int(rows[:,3].max()) if len(rows) else 0})
        return result
    H.add_history_source=add_source
    route_args=args.route_args[1:] if args.route_args[:1]==['--'] else args.route_args
    sys.argv=[str(C.ENGINE/'route.py'),*route_args]
    try:runpy.run_path(str(C.ENGINE/'route.py'),run_name='__main__')
    except BaseException as exc:
        if not isinstance(exc,SystemExit) or exc.code not in (0,None):trace['exception']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        trace['updated_cells']=sum(e['cells'] for e in trace['events'])
        trace['changed_charges']=sum(e['changed_charges'] for e in trace['events'])
        trace['consumption_calls']=len(trace['consumption'])
        C.save(Path(args.trace),trace)

if __name__=='__main__':main()
