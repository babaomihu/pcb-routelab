"""Bounded feedback search. Pure serializable policy; no router/model calls.

The committed state and speculative frontier are distinct. Neutral geometry
branches can be explored but never replace the best accepted solution.
"""
from collections import Counter
from copy import deepcopy
import hashlib,itertools,json,os

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()

def geometry_signature(snapshot):
    s=deepcopy(snapshot)
    for t in s['tracks']:t['endpoints_nm']=sorted(t['endpoints_nm'])
    payload={k:sorted(s[k],key=canonical) for k in ('tracks','vias','pads','footprints')}
    payload.update({k:s[k] for k in ('layout_text','outline','design_rules','zone_count','copper_arc_count','copper_layers')})
    payload['net_names']=sorted(s['net_names'].values())
    return digest(payload)

def classification(f):
    if f.get('fatal') or not f.get('input_unchanged',False):return 'infrastructure_or_integrity'
    if f.get('timed_out'):return 'engine_timeout'
    if f.get('returncode',0)!=0:return 'engine_failure'
    if f.get('new_error_types'):return 'original_rule_violation'
    if f.get('protection') and not all(f['protection'].values()):return 'out_of_scope_change'
    if f.get('per_net_nonregression') is False:return 'connectivity_regression'
    if f.get('accepted') and f.get('progress'):return 'safe_progress'
    if not f.get('accepted'):return 'unaccepted_candidate'
    if f.get('reported_blockers'):return 'reported_obstruction'
    return 'safe_no_progress'

def action_key(a):
    return digest({**a,'rip':sorted(a['rip'])})

def atomic_dump(path,obj):
    temp=path.with_name(path.name+'.tmp')
    with temp.open('w') as f:
        f.write(json.dumps(obj,ensure_ascii=False,indent=2)+'\n');f.flush();os.fsync(f.fileno())
    os.replace(temp,path)

class Planner:
    def __init__(self,initial,mode='full',max_actions=12,max_engine_seconds=240.,max_depth=2,max_branch_entries=4):
        if mode not in ('full','no_memory'):raise ValueError('Unknown policy mode')
        self.data={'version':'0.3-memory1','mode':mode,'limits':{'actions':max_actions,'engine_seconds':max_engine_seconds,'depth':max_depth,'branch_entries':max_branch_entries},
            'best':deepcopy(initial),'stack':[{'state':deepcopy(initial),'depth':0}],
            'attempts':[],'pending':None,'events':[],'visited':[initial['geometry']],
            'branch_entries':0,'stop':None}

    @classmethod
    def restore(cls,data):
        if data['version']!='0.3-memory1':raise ValueError('Unsupported checkpoint version')
        obj=cls.__new__(cls);obj.data=deepcopy(data);return obj

    @property
    def spent(self):return sum(a['feedback'].get('engine_seconds',0.) for a in self.data['attempts'])

    def stop(self,reason):
        d=self.data
        if not d['stop']:
            # Abandon every speculative branch; report only committed state.
            if len(d['stack'])>1:d['events'].append({'event':'backtrack','reason':reason,'to':d['best']['geometry']})
            d['stack']=[{'state':deepcopy(d['best']),'depth':0}]
            d['stop']={'decision':'stop','reason':reason,'best_geometry':d['best']['geometry'],'remaining':d['best']['remaining']}
            d['events'].append({'event':'stop',**d['stop']})
        return d['stop']

    def next(self):
        d=self.data
        if d['stop']:return d['stop']
        if d['pending']:raise RuntimeError('Pending action must be reconciled first')
        if any(a['classification']=='infrastructure_or_integrity' for a in d['attempts']):return self.stop('infrastructure_or_integrity')
        if sum(d['best']['remaining'].values())==0:return self.stop('complete')
        if len(d['attempts'])>=d['limits']['actions']:return self.stop('action_budget')
        if self.spent>=d['limits']['engine_seconds']:return self.stop('engine_budget')
        while d['stack']:
            node=d['stack'][-1];s=node['state']
            # Latest-feedback ablation retains the tried-action ledger solely
            # for deterministic scheduling and bounded execution.
            history=[h for h in d['attempts'] if h['input']['geometry']==s['geometry']]
            tried={action_key(h['action']) for h in history}
            for target in sorted(s['remaining'],key=lambda n:(s['remaining'][n],n)):
                if s['remaining'][target]<=0:continue
                hs=[h for h in history if h['action']['target']==target]
                base={'target':target,'rip':[],'force':False,'options':{}}
                proposals=[('continue',base,'target_only',[])]
                usable=hs if d['mode']=='full' else hs[-1:]
                evidence={}
                for h in usable:
                    for n in set(h['feedback'].get('reported_blockers',[])):
                        if n!=target and n in s['net_cost']:evidence.setdefault(n,[]).append(h['id'])
                # Repeated blocker reports are a heuristic signal, not causal proof.
                ranked=sorted(evidence,key=lambda n:(-len(evidence[n]) if d['mode']=='full' else 0,s['net_cost'][n]['length_mm'],s['net_cost'][n]['vias'],n))[:5]
                singleton_attempts=sum(bool(h['action']['rip']) and len(h['action']['rip'])==1 for h in hs)
                singles=[[n] for n in ranked]
                combos=[list(c) for k in (2,3) for c in itertools.combinations(ranked,k)]
                subsets=combos+singles if singleton_attempts>=2 else singles+combos
                for rip in subsets:
                    proposals.append(('expand',{**base,'rip':rip},'current_state_blocker_evidence',sorted({i for n in rip for i in evidence[n]})))
                if any(h['feedback'].get('engine_native_disagreement') for h in usable):
                    proposals.append(('continue',{**base,'force':True},'native_engine_disagreement',[h['id'] for h in usable if h['feedback'].get('engine_native_disagreement')]))
                if any(h['feedback'].get('static_obstacle_hint') for h in usable):
                    proposals.append(('continue',{**base,'options':{'grid_step':.05}},'static_obstacle_finer_grid',[h['id'] for h in usable if h['feedback'].get('static_obstacle_hint')]))
                for kind,action,reason,evidence_ids in proposals:
                    if action_key(action) in tried:continue
                    item={'id':f'a{len(d["attempts"])+1:03d}','decision':kind,'action':action,'reason':reason,
                        'evidence_actions':evidence_ids,'input':deepcopy(s),'depth':node['depth'],
                        'checkpoint':s['sha256'],'timeout_seconds':min(60.,d['limits']['engine_seconds']-self.spent)}
                    d['pending']=item;d['events'].append({'event':kind,**deepcopy(item)});return item
            if len(d['stack'])==1:return self.stop('supported_actions_exhausted')
            d['stack'].pop();d['events'].append({'event':'backtrack','reason':'branch_exhausted','from':s['geometry'],'to':d['stack'][-1]['state']['geometry']})
        return self.stop('supported_actions_exhausted')

    def observe(self,feedback,candidate=None):
        d=self.data;p=d['pending']
        if not p:raise RuntimeError('No pending action')
        f=deepcopy(feedback);kind=classification(f);before=p['input'];result='rollback';reason=kind
        safe=bool(f.get('accepted') and kind not in ('infrastructure_or_integrity','engine_timeout','engine_failure','original_rule_violation','out_of_scope_change','connectivity_regression'))
        if safe:
            if candidate is None:raise ValueError('Safe outcome needs measured candidate state')
            old,new=before['remaining'],candidate['remaining']
            if any(new.get(n,0)>old.get(n,0) for n in set(old)|set(new)):
                raise ValueError('Safe outcome contradicts per-net nonregression')
            if f.get('candidate_U')!=sum(new.values()):raise ValueError('Candidate U mismatch')
            if bool(f.get('progress'))!=(sum(new.values())<sum(old.values())):raise ValueError('Progress flag mismatch')
            duplicate=candidate['geometry'] in d['visited']
            f['equivalent_result_actions']=[h['id'] for h in d['attempts'] if h.get('candidate_geometry')==candidate['geometry']] if d['mode']=='full' else []
            if sum(new.values())<sum(d['best']['remaining'].values()):
                d['best']=deepcopy(candidate);d['stack']=[{'state':deepcopy(candidate),'depth':0}]
                result='commit';reason='safe_connectivity_progress'
            elif candidate['geometry']==before['geometry']:
                reason='unchanged_geometry'
            elif d['mode']=='full' and duplicate:
                reason='previously_seen_geometry'
            elif p['depth']>=d['limits']['depth'] or d['branch_entries']>=d['limits']['branch_entries']:
                reason='branch_budget'
            else:
                d['stack'].append({'state':deepcopy(candidate),'depth':p['depth']+1});d['branch_entries']+=1
                result='branch';reason='safe_neutral_geometry'
            if not duplicate:d['visited'].append(candidate['geometry'])
        entry={**deepcopy(p),'feedback':f,'classification':kind,'candidate_geometry':candidate['geometry'] if candidate else None,
            'outcome':result,'outcome_reason':reason,'best_geometry':d['best']['geometry']}
        d['attempts'].append(entry);d['pending']=None
        d['events'].append({'event':result,'action_id':p['id'],'reason':reason,'best_geometry':d['best']['geometry']})
        return result
