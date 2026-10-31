from release_runtime import WORK, CODE, ENGINE, ENGINE_PYTHON, KICAD_PYTHON, KICAD_CLI
"""Model-facing compact observations; inherited stock execution is unchanged."""
import collections,json,re
from session_core_v20 import Session as Core,ROOT,save
from audit_board_v6 import load

def summary(check):
 if not check:return None
 errors=check.get('new_drc_errors') or []
 return {**{k:check.get(k) for k in ['status','safe','task_success','final_unconnected','remaining_by_net_name','final_geometry','error']},'new_error_count':len(errors),'new_error_types':dict(collections.Counter(x['type'] for x in errors)),'failed_preservation_checks':[k for k,v in (check.get('geometry') or {}).items() if not v],'details':'inspect_details(drc) has every error; full raw checks are retained'}

class Session(Core):
 def observe(self):
  s=self.read();snap=self.snapshot(s);base=super().observe()
  # Full independent evidence stays on disk; no repeated raw DRC arrays or transcripts.
  base['current_check']=summary(base['current_check'])
  base['available_snapshots']={k:summary(v) for k,v in base['available_snapshots'].items()}
  base['history']=[{'id':h.get('id'),'action':h.get('action'),'from':h.get('from'),'to':h.get('to'),'nets':h.get('nets'),'options':h.get('options'),'check':summary(h.get('check')),'error':h.get('error')} for h in s['history']]
  for p,raw in zip(base['pads'],snap['pads']):
   p['layers']=[x for x in p['layers'] if x in ('F.Cu','B.Cu') or (snap['copper_layers']>2 and x.startswith('In'))];p['rotation_degrees']=raw['GetOrientationDegrees'];p['drill_mm']=[v/1e6 for v in raw['GetDrillSize']]
  native=snap['design_rules'];groups={}
  for net,r in native['effective_netclasses'].items():groups.setdefault(json.dumps(r,sort_keys=True),[]).append(net)
  base['rules']={'native_board_rules':{k:v for k,v in native.items() if k!='effective_netclasses'},'effective_netclasses':[{'nets':ns,'rules':json.loads(k)} for k,ns in groups.items()],'native_distance_units':'nanometres (1 mm = 1000000 nm)','full_project_files':'inspect_details(kind=rules, run_id=current, offset=0), then next_offset; no rule changes allowed'}
  base['quality_policy']='After safe full completion, minimize vias while holding length within 1% of a good complete snapshot; also report length separately. Use limited justified improvement attempts and retain completed snapshots. Decisions and selection belong to the model.'
  return base
 def select(self,snapshot,expected_state):
  result=super().select(snapshot,expected_state)
  # Static pads/rules/outline are already in the initial observation and remain protected.
  return {k:result[k] for k in ['state_token','current_snapshot','status','current_check','geometry_summary','nets','available_snapshots','history','budget']}|{'static_fields':'Unchanged and omitted from this delta; observe or inspect_details(rules) retrieves them.'}
 def route(self,nets,rip_existing,options,expected_state):
  r=super().route(nets,rip_existing,options,expected_state)
  return {k:r.get(k) for k in ['run_id','from_snapshot','error','state_token','requires_explicit_select','current_snapshot','engine_seconds']}|{'check':summary(r.get('check')),'native_scopes':[{'scope':x.get('scope'),'successful':x.get('successful'),'failed':x.get('failed')} for x in r.get('native_summaries',[])],'engine_warnings':[x[:400] for x in (self.path/r['run_id']/'engine.log').read_text(errors='replace').splitlines() if x.startswith(('WARNING:','--force-reroute:','All nets are already'))][:6],'details':'All DRC errors and engine text available with inspect_details; no evidence discarded.'}
 def inspect_details(self,run_id,kind,offset):
  if type(offset)is not int or offset<0:raise ValueError('offset must be nonnegative integer')
  s=self.read()
  if run_id=='current':run_id=s['current']
  if run_id!='initial' and not re.fullmatch(r'run[1-8]',run_id):raise ValueError('Invalid run id')
  if run_id=='initial':audit_path=self.path/'initial_audit';board=self.path/'initial/board.kicad_pcb'
  else:
   if not any(x.get('id')==run_id for x in s['history']):raise ValueError('Unknown run')
   audit_path=self.path/run_id/'audit';board=self.path/run_id/'candidate/board.kicad_pcb'
  common={'state_token':s['state_token'],'run_id':run_id,'kind':kind,'offset':offset}
  if kind=='drc':
   a=load(audit_path/'result.json');errors=a.get('new_drc_errors',[])
   # Rows remain exact; bounded character pagination covers even a huge single violation.
   text=json.dumps({'new_errors':errors,'native_delta':{k:v for k,v in a.get('native_delta',{}).items() if k not in ['new_errors','removed_errors']},'geometry':a.get('geometry'),'error':a.get('error')},ensure_ascii=False)
  elif kind=='engine':
   if run_id=='initial':text='No engine run on initial snapshot.'
   else:text=(self.path/run_id/'engine.log').read_text(errors='replace')
  elif kind=='rules':
   task=load(self.path/'task.json');original=ROOT/task['board'];files={ext:original.with_suffix(ext).read_text(errors='replace') for ext in ['.kicad_pro','.kicad_dru','.pro'] if original.with_suffix(ext).exists()};files['native_effective_rules']=self.snapshot(s)['design_rules'];text=json.dumps(files,ensure_ascii=False)
  else:raise ValueError('Unknown detail kind')
  return common|{'text':text[offset:offset+5000],'total_characters':len(text),'next_offset':offset+5000 if len(text)>offset+5000 else None,'pagination_unit':'unicode characters; concatenate pages for exact full content'}
 def finish(self,reason):
  r=super().finish(reason)
  return {k:v for k,v in r.items() if k!='check'}|{'check':summary(r.get('check'))}

# CLI values verified from immutable stock routing_defaults.py; not guessed from
# the route() Python signature, which differs from command-line defaults.
TOOL_SEMANTICS={
 'grid_step':{'default':0.1,'unit':'mm','effect':'search grid spacing; finer grids cost more compute'},
 'via_cost':{'default':75,'unit':'0.1-mm-grid-step equivalent path penalty (75 = 7.5 mm)','effect':'lower values make vias cheaper, potentially increasing via count; not via geometry'},
 'heuristic_weight':{'default':2.3,'unit':'dimensionless A* heuristic weight','effect':'speed/path-search tradeoff, not a physical rule'},
 'max_ripup':{'default':3,'unit':'stock rip-up attempt limit','effect':'existing internal rip-up control'},
 'force_reroute':{'default':False,'effect':'actively reroute selected completed nets'},
 'track_width':{'effect':'V19 size option, mm; audit unchanged'},
 'via_size':{'effect':'V19 size option, mm'},
 'via_drill':{'effect':'V19 size option, mm; below via_size'},
 'empty_options':'{} inherits ALL stock CLI defaults. Do not populate optional keys merely because schema lists them.'}

CompactSession=Session
class Session(CompactSession):
 def bootstrap(self):
  s=self.read()
  if s['arm']!='model' or s['runs_used']!=0:raise ValueError('Bootstrap only once before model actions')
  # The normal stock call is host orchestration, never a model contribution.
  outcome=super().route([],[],{},s['state_token']);s=self.read()
  if 'run1' in s['candidates']:super().select('run1',s['state_token'])
  s=self.read();s['bootstrap']={'origin':'host','run_id':'run1','selected':s['current'],'is_model_decision':False}
  if s['candidates'][s['current']]['check']['task_success']:s['quality_reference']=s['current']
  self.write(s);save(self.path/'bootstrap.json',s['bootstrap']);return self.observe()
 def observe(self):
  o=super().observe();s=self.read();o['tool_semantics']=TOOL_SEMANTICS;o['bootstrap']=s.get('bootstrap')
  ref=s.get('quality_reference');o['quality_reference']={'snapshot':ref,'check':summary(s['candidates'][ref]['check'])}if ref else None
  o['quality_policy']='Keep safe completed current board. Selection must not increase current vias and must hold length <=1.01 times first complete reference. Incomplete safe rollback allowed only before current completion. Defaults and host preservation are not model contributions.'
  return o
 def route(self,nets,rip_existing,options,expected_state,plan=None):
  s=self.read()
  if s['arm']=='model':
   if not s.get('bootstrap'):raise ValueError('Session initial observation must be initialized before model decisions')
   if not isinstance(plan,dict) or set(plan)!={'objective','evidence_run','diagnosis','expected_effect'}:raise ValueError('Provide complete evidence plan')
   if plan['objective'] not in ['initial','continue','repair','quality']:raise ValueError('Invalid objective')
   current=s['candidates'][s['current']]['check']
   if (plan['objective']=='quality')!=bool(current['task_success']):raise ValueError('Objective must match current completion state')
   if plan['objective']=='initial' and s['runs_used']!=0:raise ValueError('Initial action only before any engine run')
   if plan['evidence_run']!='initial' and not any(h.get('id')==plan['evidence_run'] for h in s['history']):raise ValueError('Evidence must reference initial PCB or a real executed run')
   if any(not isinstance(plan[k],str) or not 12<=len(plan[k])<=1800 for k in ['diagnosis','expected_effect']):raise ValueError('Diagnosis and expected effect need 12..1800 characters')
   # Save intent before execution, even a later failed/denied engine attempt.
   save(self.path/f'plan_{s["runs_used"]+1}.json',{'origin':'model','plan':plan,'state_token':expected_state})
  result=super().route(nets,rip_existing,options,expected_state)
  if plan is not None:
   s=self.read();s['history'][-1]['plan']=plan;self.write(s);result['state_token']=s['state_token'];save(self.path/result['run_id']/'plan.json',plan)
  return result
 def select(self,snapshot,expected_state):
  s=self.read();self.check_active(s,expected_state)
  if snapshot not in s['candidates']:raise ValueError('Not a safe candidate')
  if s['arm']=='model' and s.get('bootstrap'):
   old=s['candidates'][s['current']]['check'];new=s['candidates'][snapshot]['check']
   if old['task_success']:
    ref=s['candidates'][s.get('quality_reference',s['current'])]['check']['final_geometry'];g=new.get('final_geometry')or{}
    if not new['task_success'] or g.get('vias',float('inf'))>old['final_geometry']['vias'] or g.get('straight_track_length_mm',float('inf'))>1.01*ref['straight_track_length_mm']:
     raise ValueError('Quality guard: preserve complete board, no more vias, length <=1.01 of first complete reference; candidate remains evidence')
  result=super().select(snapshot,expected_state);s=self.read()
  if s['arm']=='model' and not s.get('quality_reference') and s['candidates'][s['current']]['check']['task_success']:
   s['quality_reference']=s['current'];self.write(s);result['state_token']=s['state_token']
  return result

GeometryBase=Session
class Session(GeometryBase):
 def bootstrap(self):
  task=load(self.path/'task.json')
  if task.get('workflow')=='geometric':
   s=self.read();s['bootstrap']={'origin':'none','is_model_decision':False,'selected':'initial','reason':'Predeclared geometric task starts original board, no default route or quality-optimization comparison'};self.write(s);return self.observe()
  return super().bootstrap()
 def observe(self):
  o=super().observe();task=load(self.path/'task.json');o['workflow']=task.get('workflow','default_quality');o['geometry_goal']=task.get('geometry_goal');o['allowed_geometry_backends']=task.get('allowed_geometry_backends',['krt','pcbworld'])
  o['geometry_tools']={'route_guided':'Single net: soft KRT waypoints, explicit copper restrictions/costs, convex keepouts. Returns measured actual geometry; never assume every guide point followed.','scope':'Two copper layers; other-net current copper must stay exactly unchanged; all original rules audited.'}
  if task.get('geometry_goal'):
   from geometry_v9 import geometry_feedback
   goal=task['geometry_goal'];o['geometry_goal_check']=geometry_feedback(self.snapshot(self.read()),goal['net'],goal.get('guidance',{}),goal.get('via_points',[]));o['current_check']['native_routing_complete']=o['current_check']['task_success'];o['current_check']['task_success']=o['current_check']['task_success']and o['geometry_goal_check']['hard_constraints_satisfied']
  if o['workflow']=='geometric':o['quality_policy']='Predeclared geometry requirement task: extra length/vias allowed for required path. Original DRC/layout/connectivity protection unchanged. Not V8 quality optimization efficacy.'
  return o
 def select(self,snapshot,expected_state):
  if load(self.path/'task.json').get('workflow')=='geometric':return CompactSession.select(self,snapshot,expected_state)
  return super().select(snapshot,expected_state)
 def route_guided(self,net,guidance,options,plan,expected_state):return self._geometry('krt',net,guidance,[],options,plan,expected_state)
 def edit_copper(self,*args,**kwargs):raise NotImplementedError('PCBWorld experimental backend is not bundled')
 def _geometry(self,backend,net,guidance,actions,options,plan,expected_state):
  if backend != 'krt':raise ValueError('Only bundled KRT backend is available')
  import fcntl,time,shutil
  from geometry_v9 import validate_guidance,point,overlay,clean_overlay,geometry_feedback,other_copper_preserved
  from session_core_v20 import command,invoke,brief,KRT_PYTHON
  from audit_board_v6 import copy_board,audit,sha,rules,native_snapshot
  if backend not in load(self.path/'task.json').get('allowed_geometry_backends',['krt','pcbworld']):raise ValueError('Backend not allowed in this predeclared task')
  validate_guidance(guidance)
  if not isinstance(plan,str)or not 12<=len(plan)<=1800:raise ValueError('Explain geometry intent/evidence in 12..1800 characters')
  if not isinstance(net,str):raise ValueError('Exact single network name required')
  if not isinstance(actions,list)or len(actions)>16 or (backend=='pcbworld'and not actions):raise ValueError('1..16 coordinate actions required')
  for a in actions:
   if not isinstance(a,dict):raise ValueError('Invalid action')
   op=a.get('op');fields={'start':{'op','xy','layer'},'line':{'op','xy'},'via':{'op','xy'},'delete_track':{'op','start','end','layer'},'delete_via':{'op','xy'}}
   if op not in fields or set(a)!=fields[op]:raise ValueError('Wrong action fields')
   for k in ['xy','start','end']:
    if k in a:point(a[k])
   if 'layer'in a and a['layer']not in ['F.Cu','B.Cu']:raise ValueError('Unsupported copper layer')
  with (self.path/'session.lock').open('a+')as lock:
   fcntl.flock(lock,fcntl.LOCK_EX);s=self.read();self.check_active(s,expected_state)
   if s['arm']!='model':raise ValueError('Geometry tools are model-side only; native group unchanged')
   before=self.snapshot(s);names={v:int(k)for k,v in before['net_names'].items()}
   if before['copper_layers']!=2 or net not in names or not names[net]:raise ValueError('Known named net and two-layer board required')
   if net not in {self.snapshot(s,'initial')['net_names'].get(str(n)) for n in load(self.path/'task.json')['allowed_nets']}:raise ValueError('Task does not allow this network')
   from session_core_v20 import action_cap
   if s['runs_used']>=action_cap(s):raise ValueError('Action budget exhausted')
   timeout=min(120,600-s['engine_seconds'],1800-(time.time()-s['started_at']))
   if timeout<1:raise ValueError('Time budget exhausted')
   run_id=f'run{s["runs_used"]+1}';out=self.path/run_id;source=self.path/s['candidates'][s['current']]['board'];command(source,source,[net],[],options) # pure options validation
   out.mkdir();copy_board(source,out/'input/board.kicad_pcb');(out/'raw').mkdir()
   record={'id':run_id,'from':s['current'],'backend':backend,'nets':[net],'rip_existing':[],'options':options,'guidance':guidance,'actions':actions,'geometry_plan':plan,'status':'reserved','reserved_at':time.time(),'timeout_seconds':timeout}
   s['runs_used']+=1;s['history'].append(record);self.write(s);save(out/'reservation.json',record)
   try:
    raw=out/'raw/board.kicad_pcb';ids=[];invocation_started=False
    if backend=='krt':
     working=out/'engine/board.kicad_pcb';copy_board(source,working);ids=overlay(source,working,guidance);save(out/'overlay.json',{'uuids':ids,'guidance':guidance})
     argv=command(working,raw,[net],[],options)
     if guidance.get('waypoints'):argv+=['--guide-corridor','--guide-corridor-layer','User.1','--guide-corridor-spacing','0']
     if guidance.get('keepouts'):argv+=['--keepout','--keepout-layer','User.2']
     if guidance.get('layers'):argv+=['--layers']+guidance['layers']
     if guidance.get('layer_costs'):argv+=['--layer-costs']+list(map(str,guidance['layer_costs']))
    else:
     save(out/'worker_request.json',{'input':str(out/'input/board.kicad_pcb'),'output':str(raw),'net_code':names[net],'actions':actions})
     argv=[ENGINE_PYTHON,CODE/'scripts/pcbworld_geometry_worker_v9.py',out/'worker_request.json',out/'worker_result.json']
    invocation_started=True;ex=invoke(argv,out,timeout);record['execution']=ex;s['engine_seconds']+=ex['seconds'];record['status']='executed'
    if raw.exists()and ex['status']=='completed'and ex['returncode']==0:
     candidate=out/'candidate/board.kicad_pcb';copy_board(raw,candidate)
     if backend=='krt':clean_overlay(raw,candidate,source,ids)
     else:
      from packaging_v9_3 import preserve_unused_nets
      record['restored_unused_net_declarations']=preserve_unused_nets(source,candidate)
     task=load(self.path/'task.json');original=ROOT/task['board']
     for ext in ['.kicad_pro','.kicad_dru','.pro']:
      src=original.with_suffix(ext);dst=candidate.with_suffix(ext)
      if src.exists():shutil.copy2(src,dst)
      elif dst.exists():dst.unlink()
     checked=audit(original,candidate,task,out/'audit');after=load(out/'audit/candidate_snapshot.json');feedback=geometry_feedback(after,net,guidance if backend=='krt'else {'waypoints':[a['xy']for a in actions if a['op']=='line'],'require_waypoints':True},[a['xy']for a in actions if a['op']=='via'],endpoint_mode=backend=='pcbworld')
     feedback['other_current_networks_unchanged']=other_copper_preserved(before,after,net);feedback['deletion_connectivity_preserved']=not any(a['op'].startswith('delete')for a in actions)or after.get('remaining_by_net_name',{}).get(net,0)<=before.get('remaining_by_net_name',{}).get(net,0);record['check']=brief(checked);record['geometry_feedback']=feedback
     if task.get('geometry_goal'):
      goal=task['geometry_goal'];record['task_goal_check']=geometry_feedback(after,goal['net'],goal.get('guidance',{}),goal.get('via_points',[]))
     # Raw copper is not edited when temporary drawings and original rule sidecars are restored.
     raw_snap=native_snapshot(raw);record['packaging_copper_identical']=all(raw_snap[k]==after[k]for k in ['tracks','vias']);assert record['packaging_copper_identical']
     admissible=checked['safe']and feedback['hard_constraints_satisfied']and feedback['other_current_networks_unchanged']and feedback['deletion_connectivity_preserved'];record['eligible_for_selection']=admissible
     if admissible:s['candidates'][run_id]={'board':str(candidate.relative_to(self.path)),'audit':str((out/'audit').relative_to(self.path)),'check':brief(checked),'geometry_feedback':feedback}
    else:
     record.update(check={'safe':False,'task_success':False,'status':'engine_failed'},eligible_for_selection=False)
     if (out/'worker_result.json').exists():record['error']=json.dumps(load(out/'worker_result.json'),ensure_ascii=False)
   except Exception as e:
    record.update(status='adapter_error',error=type(e).__name__+': '+str(e),eligible_for_selection=False)
    if 'execution'not in record:
     if invocation_started:s['engine_time_unknown']=True;s['engine_seconds']=600
     else:record['execution']={'status':'not_started','returncode':None,'seconds':0}
   finally:self.write(s);save(out/'result.json',record)
   return {'run_id':run_id,'state_token':s['state_token'],'current_snapshot':s['current'],'check':summary(record.get('check')),'geometry_feedback':record.get('geometry_feedback'),'task_goal_check':record.get('task_goal_check'),'eligible_for_selection':record.get('eligible_for_selection',False),'error':record.get('error'),'backend':backend,'details':'Full original audit and engine log available; actual geometry via select/inspect. Explicit select required.'}
 def finish(self,reason):
  from geometry_v9 import geometry_feedback
  task=load(self.path/'task.json');r=super().finish(reason)
  if task.get('geometry_goal'):
   goal=task['geometry_goal'];snap=self.snapshot(self.read());feedback=geometry_feedback(snap,goal['net'],goal.get('guidance',{}),goal.get('via_points',[]))
   full=load(self.path/'result.json');full['native_routing_complete']=full.get('native_routing_complete',full['task_success']);full['geometry_goal_check']=feedback;full['geometry_goal_met']=feedback['hard_constraints_satisfied'];full['task_success']=full['native_routing_complete']and full['geometry_goal_met'];save(self.path/'result.json',full);r={k:v for k,v in full.items()if k!='check'}|{'check':summary(full.get('check'))}
  return r


ProfileBase=Session
class Session(ProfileBase):
 def observe(self):
  o=super().observe();s=self.read();o['tool_profile']=s.get('tool_profile','geometry')
  from input_gate_v12 import check_qualification
  o['input_diagnostics']=check_qualification(self.path/'initial_audit')
  if o['tool_profile']=='parameters':
   o['geometry_tools']={};o['allowed_geometry_backends']=[]
  return o
 def _geometry(self,*args,**kwargs):
  if self.read().get('tool_profile')=='parameters':raise ValueError('Geometry actions are disabled in parameter-only ablation')
  return super()._geometry(*args,**kwargs)


AutonomyBase=Session
class Session(AutonomyBase):
 def bootstrap(self):
  s=self.read()
  if s.get('start_policy')!='autonomous':return super().bootstrap()
  if s['arm']!='model' or s['runs_used'] or s.get('bootstrap'):raise ValueError('Initial observation only once')
  s['bootstrap']={'origin':'none','start_policy':'autonomous','selected':'initial','is_model_decision':False,'engine_runs':0,'reason':'Model receives original board before choosing any routing operation'}
  if s['candidates']['initial']['check']['task_success']:s['quality_reference']='initial'
  self.write(s);save(self.path/'bootstrap.json',s['bootstrap'])
  return self.observe()

 def observe(self):
  o=super().observe();s=self.read()
  o['start_policy']=s.get('start_policy');o['board_plan']=s.get('board_plan');o['plan_revisions']=len(s.get('plans',[]))
  o['planning_semantics']='Model decides strategy; no routing is performed by plan_board. priority_nets express intended cross-call order, not native internal solver ordering. Initial PCB is valid evidence.'
  return o

 def plan_board(self,plan,expected_state):
  import fcntl,time
  with (self.path/'session.lock').open('a+') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX);s=self.read();self.check_active(s,expected_state)
   if s['arm']!='model' or not s.get('bootstrap'):raise ValueError('Only initialized model session may plan')
   fields={'approach','priority_nets','rationale','steps','revision_reason'}
   if not isinstance(plan,dict) or set(plan)!=fields:raise ValueError('Complete structured board plan required')
   if plan['approach'] not in ['default_all','ordered_networks','geometric_first','adaptive']:raise ValueError('Unknown approach')
   valid={n for n in self.snapshot(s)['net_names'].values() if n}
   if not isinstance(plan['priority_nets'],list) or len(plan['priority_nets'])>100 or any(not isinstance(n,str) or n not in valid for n in plan['priority_nets']):raise ValueError('Priority nets must be actual named nets')
   if len(set(plan['priority_nets']))!=len(plan['priority_nets']):raise ValueError('Do not duplicate priority nets')
   for k,low,high in [('rationale',12,2400),('revision_reason',8,1200)]:
    if not isinstance(plan[k],str) or not low<=len(plan[k])<=high:raise ValueError('Invalid '+k)
   if not isinstance(plan['steps'],list) or not 1<=len(plan['steps'])<=8 or any(not isinstance(x,str) or not 8<=len(x)<=500 for x in plan['steps']):raise ValueError('Provide 1..8 bounded plan steps')
   revision=len(s.get('plans',[]))+1
   record={'revision':revision,'origin':'model','snapshot':s['current'],'engine_runs_before':s['runs_used'],'recorded_at':time.time(),'plan':plan}
   s.setdefault('plans',[]).append(record);s['board_plan']=record;s['history'].append({'action':'plan_board',**record});self.write(s)
   save(self.path/f'board_plan_{revision}.json',record)
  return {'state_token':s['state_token'],'board_plan':record,'current_snapshot':s['current'],'engine_runs':s['runs_used'],'copper_changed':False}

 def _link_decision(self,result,before):
  # Measurements only; never generates paths or modifies engine candidates.
  from audit_board_v6 import key
  rid=result.get('run_id')
  if not rid:return result
  s=self.read();record=next(x for x in s['history'] if x.get('id')==rid)
  after_path=self.path/rid/'audit/candidate_snapshot.json';changes=None
  if after_path.exists():
   after=load(after_path);names={x['net_name'] for k in ['tracks','vias'] for snap in [before,after] for x in snap[k]}
   changes=[]
   for net in sorted(names):
    delta={}
    for k in ['tracks','vias']:
     left=collections.Counter(key(x) for x in before[k] if x['net_name']==net);right=collections.Counter(key(x) for x in after[k] if x['net_name']==net)
     delta[k+'_added']=sum((right-left).values());delta[k+'_removed']=sum((left-right).values())
    if any(delta.values()):changes.append({'net':net,**delta})
  link={'origin':'model','plan_revision':s['board_plan']['revision'],'requested_nets':record.get('nets'),'actual_copper_changes':changes,'interpretation':'Actual before/after copper changes; not a claim about internal solver order'}
  record['decision_link']=link;self.write(s);save(self.path/rid/'decision_link.json',link)
  result.update(state_token=s['state_token'],decision_link=link)
  return result

 def route(self,nets,rip_existing,options,expected_state,plan=None):
  s=self.read()
  if s['arm']=='native':return super().route(nets,rip_existing,options,expected_state,plan)
  self.check_active(s,expected_state)
  if not s.get('board_plan'):raise ValueError('Submit your whole-board plan before first engine action')
  before=self.snapshot(s)
  return self._link_decision(super().route(nets,rip_existing,options,expected_state,plan),before)

 def _geometry(self,*args,**kwargs):
  s=self.read()
  if not s.get('board_plan'):raise ValueError('Submit your whole-board plan before first engine action')
  before=self.snapshot(s)
  return self._link_decision(super()._geometry(*args,**kwargs),before)

# Shared transport views: no engine, strategy, validation, or selection changes.
ContextBase=Session
class Session(ContextBase):
 def _full_observe(self):return super().observe()
 def observe(self):
  from context_v20 import compact_observation
  return compact_observation(self._full_observe(),ROOT/'runs/v20/harness'/self.path.name/'context_payloads')
 def inspect_pads(self,nets,bbox,offset):
  if type(offset)is not int or offset<0:raise ValueError('Invalid offset')
  if bbox and (len(bbox)!=4 or bbox[0]>bbox[2] or bbox[1]>bbox[3]):raise ValueError('Invalid bbox')
  o=self._full_observe();pads=o['pads']
  if nets:pads=[p for p in pads if p['net'] in nets]
  if bbox:pads=[p for p in pads if bbox[0]<=p['xy_mm'][0]<=bbox[2] and bbox[1]<=p['xy_mm'][1]<=bbox[3]]
  return {'state_token':o['state_token'],'current_snapshot':o['current_snapshot'],'items':pads[offset:offset+30],'total_items':len(pads),'offset':offset,'next_offset':offset+30 if offset+30<len(pads) else None,'bbox_semantics':'Filters pad centers; may exclude large pads whose centers lie outside. Use [] for complete geometry.'}
