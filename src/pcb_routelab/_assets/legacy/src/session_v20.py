from release_runtime import WORK, CODE, ENGINE, ENGINE_PYTHON, KICAD_PYTHON, KICAD_CLI
"""V14 model evidence/decision layer, over an unchanged native executor."""
import fcntl,json,os,time
from pathlib import Path
from session_legacy_v20 import Session as LegacySession,ROOT,save,load
from evidence_v20 import local_geometry,diagnose,effects

GUIDANCE='Use observed geometry, original rules and engine evidence to form a hypothesis. Nearness alone does not prove blocking. Fine grid may help fine-pitch searches but costs compute; layers/waypoints may help a diagnosed conflict but need actual-geometry validation. Preserve original widths/clearance/layout. Do not assume diff-pair intent from names. Default all-net can be appropriate; do not force local actions. If a tested hypothesis fails, explain what new evidence motivates a different attempt. These are authored domain hints, not model discoveries.'

class Session(LegacySession):
 @classmethod
 def create(cls,*args):
  self=super().create(*args);s=self.read();s['method']='enhanced';self.write(s);return self
 def inspect_region(self,run_id,nets,bbox,layers,offset):
  s=self.read();rid=s['current'] if run_id=='current' else run_id
  if rid!='initial' and not any(h.get('id')==rid for h in s['history']):raise ValueError('Unknown snapshot')
  file=self.path/('initial_audit' if rid=='initial' else rid+'/audit')/'candidate_snapshot.json'
  if not file.exists():raise ValueError('No audited geometry for this run')
  return {'state_token':s['state_token'],'snapshot':rid,'current_snapshot':s['current'],**local_geometry(load(file),nets,bbox,layers,offset)}
 def diagnose(self,run_id,net='',offset=0):
  s=self.read();rid=s['current'] if run_id=='current' else run_id
  return {'state_token':s['state_token'],'current_snapshot':s['current'],**diagnose(self.path,rid,net,offset)}
 def feedback(self):
  s=self.read();denials=[];log=ROOT/'runs/v20/harness'/self.path.name/'call_log.jsonl'
  if log.exists():
   for line in log.read_text().splitlines():
    try:r=json.loads(line)
    except ValueError:continue
    if r.get('error'):denials.append({'tool':r['name'],'error':r['error'],'response_number':r.get('response_number')})
  return {'state_token':s['state_token'],'actions':effects(self.path,s),'recent_tool_rejections':denials[-6:],'interventions':s.get('interventions',[])[-4:],'interpretation':'Measurements and model hypotheses are separate. No repair action is automatically chosen.'}
 def observe(self):
  r=super().observe();s=self.read();r['method']='enhanced';r['decision_support']={'domain_hints':GUIDANCE,'diagnosis_tool':'diagnose(run_id, net, offset)','region_tool':'inspect_region(run_id, nets, bbox, layers, offset); includes other-net neighbors','memory':effects(self.path,s)[-4:],'active_intervention':s.get('active_intervention'),'delivery':'commit_result explicitly selects safe candidate and finishes in one tool call; offline recovery never counts an unselected board as model success.'};return r
 def propose_intervention(self,plan,expected_state):
  with (self.path/'session.lock').open('a+') as f:
   fcntl.flock(f,fcntl.LOCK_EX);s=self.read();self.check_active(s,expected_state)
   if s['arm']!='model':raise ValueError('Model-only intervention')
   required={'problem','evidence_run','evidence_ids','hypothesis','action','nets','expected_effect','verification','on_failure'}
   if not isinstance(plan,dict) or set(plan)!=required:raise ValueError('Complete intervention required')
   if plan['action'] not in ['route_nets','route_guided']:raise ValueError('Unsupported action')
   valid={v for v in self.snapshot(s)['net_names'].values() if v}
   if not isinstance(plan['nets'],list) or len(plan['nets'])>100 or any(n not in valid for n in plan['nets']):raise ValueError('Unknown target net')
   if plan['action']=='route_guided' and len(plan['nets'])!=1:raise ValueError('Guidance requires one net')
   for k in ['problem','hypothesis','expected_effect','verification','on_failure']:
    if not isinstance(plan[k],str) or not 8<=len(plan[k])<=1200:raise ValueError('Invalid '+k)
   ev=[];offset=0
   while True:
    page=self.diagnose(plan['evidence_run'],'',offset);ev.extend(x['id'] for x in page['items'])
    if page['next_offset'] is None:break
    offset=page['next_offset']
   if not isinstance(plan['evidence_ids'],list) or len(plan['evidence_ids'])>20 or any(e not in ev for e in plan['evidence_ids']):raise ValueError('Evidence ID not in cited audit/log')
   if s['runs_used'] and not plan['evidence_ids']:raise ValueError('Post-run intervention requires actual diagnostic evidence IDs')
   record={'id':len(s.get('interventions',[]))+1,'origin':'model','from_snapshot':s['current'],'before_run_count':s['runs_used'],'plan':plan}
   s.setdefault('interventions',[]).append(record);s['active_intervention']=record;s['history'].append({'action':'propose_intervention','intervention':record});self.write(s);save(self.path/f'intervention_{record["id"]}.json',record)
   return {'state_token':s['state_token'],'intervention':record,'copper_changed':False}
 def _require_intervention(self,name,nets):
  s=self.read();p=s.get('active_intervention')
  if not p or p['before_run_count']!=s['runs_used'] or p['from_snapshot']!=s['current']:raise ValueError('Submit a fresh intervention for current snapshot before each engine action')
  if p['plan']['action']!=name or sorted(p['plan']['nets'])!=sorted(nets):raise ValueError('Action/net scope differs from model intervention')
 def route(self,nets,rip_existing,options,expected_state,plan=None):
  if self.read()['arm']=='model':self._require_intervention('route_nets',nets)
  r=super().route(nets,rip_existing,options,expected_state,plan);r['effect_feedback']=self.feedback()['actions'][-1:];return r
 def route_guided(self,net,guidance,options,plan,expected_state):
  self._require_intervention('route_guided',[net]);r=super().route_guided(net,guidance,options,plan,expected_state);r['effect_feedback']=self.feedback()['actions'][-1:];return r
 def commit_result(self,snapshot,expected_state,reason):
  # A dedicated lock serializes the multi-file delivery; intent survives interruption.
  with (self.path/'delivery.lock').open('a+') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX);s=self.read();self.check_active(s,expected_state)
   if snapshot not in s['candidates']:raise ValueError('No verified safe candidate')
   save(self.path/'commit_intent.json',{'origin':'model','snapshot':snapshot,'state_token':expected_state,'reason':reason,'requested_at':time.time()})
   self.select(snapshot,expected_state)
   result=self.finish(reason);save(self.path/'commit_receipt.json',{'origin':'model','selected':snapshot,'result':result});return result
