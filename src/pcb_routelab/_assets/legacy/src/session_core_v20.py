"""Stateful adapter for stock KRT; strategy decisions belong exclusively to model.

No custom routing/search. Immutable action inputs, explicit snapshot selection,
durable reservations and independent original-rule KiCad checks.
"""
from __future__ import annotations
from release_runtime import WORK, CODE, ENGINE, ENGINE_PYTHON, KICAD_PYTHON, KICAD_CLI
import collections,fcntl,hashlib,json,os,re,shutil,signal,subprocess,sys,time
from pathlib import Path
ROOT=WORK
sys.path.insert(0,str(CODE/'scripts'))
from audit_board_v6 import audit,copy_board,load,sha,rules
KRT=ENGINE/'route.py'
KRT_PYTHON=ENGINE_PYTHON
LIMITS={'engine_seconds':600,'session_seconds':1800,'model_actions':8,'model_action_seconds':120}

def action_cap(s):
 # V20 draw arm (single-net geometry only) gets an expanded transaction budget;
 # enhanced keeps 8 so the comparison is conservative in the draw arm's favor.
 if s['arm']=='native':return 1
 return 24 if s.get('tool_profile')=='draw' else 8

def save(path,data):
 path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp')
 with tmp.open('w') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
 os.replace(tmp,path)

def env_for_engine():
 env=dict(os.environ)
 for k in ['PYTHONPATH','PYTHONHOME','DYLD_LIBRARY_PATH']:env.pop(k,None)
 env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONPYCACHEPREFIX=str(ROOT/'cache/pycache'),TMPDIR=str(ROOT/'cache/tmp'),XDG_CACHE_HOME=str(ROOT/'cache/xdg'),KICAD_CONFIG_HOME=str(ROOT/'cache/kicad'),KICAD_CRASH_LOG_DIR=str(ROOT/'cache/crashlogs'),OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2')
 return env

def invoke(argv,out,timeout):
 started=time.monotonic();proc=None;status='error'
 with (out/'engine.log').open('x') as log:
  try:
   proc=subprocess.Popen(list(map(str,argv)),cwd=out,env=env_for_engine(),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
   save(out/'process.json',{'pid':proc.pid,'argv':list(map(str,argv)),'started_at':time.time(),'timeout_seconds':timeout})
   try:proc.wait(timeout=timeout);status='completed'
   except subprocess.TimeoutExpired:status='timeout'
  finally:
   if proc is not None and proc.poll() is None:
    os.killpg(proc.pid,signal.SIGTERM)
    try:proc.wait(timeout=3)
    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
 result={'status':status,'returncode':proc.returncode if proc else None,'seconds':time.monotonic()-started,'requested_timeout_seconds':timeout}
 save(out/'execution.json',result);return result

def exact_pattern(name):
 # KRT expands fnmatch patterns. Escape literal metacharacters, including '['.
 return ''.join({'*':'[*]','?':'[?]','[':'[[]'}.get(c,c) for c in name)

def command(source,target,nets,rip,options):
 # V19: size actions (track_width/via_size/via_drill) are model/rule-arm operators
 # against size-type original-rule rejections. They change new-copper geometry only;
 # original rule sidecars are still restored before audit, native arm unchanged.
 allowed={'grid_step':(.025,.25),'via_cost':(1,2000),'heuristic_weight':(1,3),'max_ripup':(0,8),
 'track_width':(.05,1.0),'via_size':(.2,2.0),'via_drill':(.1,1.0)}
 if set(options)-set(allowed)-{'force_reroute'}:raise ValueError('Unsupported option; rule/geometry changes forbidden')
 if 'via_drill' in options and 'via_size' in options and not options['via_drill']<options['via_size']:
  raise ValueError('via_drill must be smaller than via_size')
 argv=[KRT_PYTHON,KRT,source,target,'--nets']+([exact_pattern(n) for n in nets] if nets else ['*'])
 if rip:argv+=['--rip-existing-nets']+[exact_pattern(n) for n in rip]
 for k,v in options.items():
  if k=='force_reroute':
   if type(v)is not bool:raise ValueError('force_reroute must be boolean')
   if v:argv+=['--force-reroute']
   continue
  low,high=allowed[k]
  if type(v) not in (int,float) or not low<=v<=high:raise ValueError('Invalid option '+k)
  if k=='max_ripup' and type(v) is not int:raise ValueError('max_ripup must be integer')
  argv+=['--'+k.replace('_','-'),str(v)]
 if (ROOT/'rule-floors.txt').exists():argv+=['--fab-overrides',str(ROOT/'rule-floors.txt')]
 return argv

def brief(a):
 return {k:a.get(k) for k in ('status','safe','task_success','initial_unconnected','final_unconnected','remaining_by_net_name','new_drc_errors','geometry','final_geometry','error')}

class Session:
 def __init__(self,episode):
  if not re.fullmatch(r'[A-Za-z0-9_-]{1,90}',episode):raise ValueError('Invalid episode')
  self.path=ROOT/'runs/v20/episodes'/episode
 def read(self):return load(self.path/'state.json')
 def write(self,s):s['state_token']=hashlib.sha256(json.dumps(s,sort_keys=True).encode()).hexdigest()[:24];save(self.path/'state.json',s)
 @classmethod
 def create(cls,task_id,episode,arm):
  if arm not in ('native','model'):raise ValueError('Invalid arm')
  if not re.fullmatch(r'[A-Za-z0-9_-]{1,60}',task_id):raise ValueError('Invalid task')
  self=cls(episode);self.path.mkdir(parents=True,exist_ok=False)
  task=load(ROOT/f'data/v20/tasks/{task_id}.json');save(self.path/'task.json',task)
  source=ROOT/task['board']
  if sha(source)!=task['board_sha256'] or rules(source)!=task['rule_hashes']:raise ValueError('Task integrity failed')
  copy_board(source,self.path/'initial/board.kicad_pcb')
  checked=audit(source,self.path/'initial/board.kicad_pcb',task,self.path/'initial_audit')
  if not checked['safe']:raise RuntimeError('Unsupported input: '+str(checked.get('error',checked['status'])))
  from input_gate_v12 import check_qualification
  gate=check_qualification(self.path/'initial_audit');save(self.path/'input_gate.json',gate)
  if not gate['accepted']:raise RuntimeError('Input gate rejected before engine/API: '+str(gate['reasons']))
  profile=os.environ.get('PCB_TOOL_PROFILE','geometry') if arm=='model' else 'native'
  if profile not in ('geometry','parameters','native','draw'):raise ValueError('Unknown tool profile')
  start_policy=os.environ.get('PCB_START_POLICY','autonomous') if arm=='model' else 'native'
  if start_policy not in ('autonomous','default_first','native'):raise ValueError('Unknown start policy')
  s={'start_policy':start_policy,'tool_profile':profile,'episode':episode,'task_id':task_id,'arm':arm,'status':'active','started_at':time.time(),'runs_used':0,'engine_seconds':0.,'current':'initial','history':[],'candidates':{'initial':{'board':'initial/board.kicad_pcb','audit':'initial_audit','check':brief(checked)}}}
  self.write(s);return self
 def check_active(self,s,token=None):
  if s['status']!='active':raise ValueError('Session finished')
  if token is not None and token!=s['state_token']:raise ValueError('Stale state; observe again')
  if time.time()-s['started_at']>=LIMITS['session_seconds']:raise ValueError('Session time budget exhausted')
 def snapshot(self,s,candidate=None):
  c=s['candidates'][candidate or s['current']]
  return load(self.path/c['audit']/'candidate_snapshot.json')
 def observe(self):
  s=self.read();snap=self.snapshot(s);task=load(self.path/'task.json');check=s['candidates'][s['current']]['check']
  pads=snap['pads'];nc=collections.Counter(p['net_name'] for p in pads)
  pro=(self.path/s['candidates'][s['current']]['board']).with_suffix('.kicad_pro')
  project=load(pro) if pro.exists() else {}
  return {'task':task['id'],'goal':task['goal'],'state_token':s['state_token'],'current_snapshot':s['current'],'status':s['status'],'copper_layers':snap['copper_layers'],
   'nets':[{'name':name,'pad_count':nc[name],'remaining_connections':snap['remaining_by_net_name'].get(name,0)} for name in sorted(nc) if name],
   'pads':[{'net':p['net_name'],'ref':p['footprint']['GetReference'],'number':p['GetNumber'],'xy_mm':[v/1e6 for v in p['GetPosition']],'size_mm':[v/1e6 for v in p['GetSize']],'layers':p['GetLayerSet'],'shape':p['GetShape']} for p in pads],
   'geometry_summary':check.get('final_geometry'),'current_check':check,'outline':snap['outline'],
   'rules':{'net_classes':project.get('net_settings',{}),'board_rules':project.get('board',{}).get('design_settings',{}).get('rules',{}),'embedded_board_rules':snap['raw_setup_text'] if not project else [],'policy':'Original files immutable; engine reads classes; native DRC against original files is final authority.'},
   'geometry_access':'inspect_geometry returns current tracks/vias in pages, including other-net blockers; always inspect relevant geometry before planning local reroute.',
   'available_snapshots':{k:v['check'] for k,v in s['candidates'].items()},'history':[{k:v for k,v in h.items() if k not in ('engine_feedback',)} for h in s['history']],
   'budget':{'runs_used':s['runs_used'],'runs_cap':action_cap(s),'engine_seconds_used':s['engine_seconds'],'engine_seconds_cap':600,'session_seconds_used':round(time.time()-s['started_at'],2)},
   'capabilities':{'route_selected_nets':True,'continue_from_current':True,'rip_existing_selected_nets':True,'explicit_snapshot_selection':True,'layout_edit':False,'rule_edit':False,'engine':'stock KRT 0.21.2'}}
 def inspect_geometry(self,nets=None,offset=0):
  if nets is not None and (not isinstance(nets,list) or any(type(n) is not str for n in nets)):raise ValueError('nets must be a string list')
  if type(offset) is not int or offset<0:raise ValueError('offset must be nonnegative integer')
  s=self.read();snap=self.snapshot(s);items=[]
  for x in snap['tracks']:
   if not nets or x['net_name'] in nets:items.append({'type':'track','net':x['net_name'],'layer':x['layer'],'width_mm':x['width_nm']/1e6,'endpoints_mm':[[v/1e6 for v in p] for p in x['endpoints_nm']]})
  for x in snap['vias']:
   if not nets or x['net_name'] in nets:items.append({'type':'via','net':x['net_name'],'layers':x['layers'],'xy_mm':[v/1e6 for v in x['position_nm']],'diameter_mm':x['width_nm']/1e6,'drill_mm':x['drill_nm']/1e6})
  return {'state_token':s['state_token'],'current_snapshot':s['current'],'total_items':len(items),'offset':offset,'items':items[offset:offset+300],'next_offset':offset+300 if len(items)>offset+300 else None,'net_filter':nets or []}
 def route(self,nets,rip_existing,options,expected_state):
  with (self.path/'session.lock').open('a+') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX);s=self.read();self.check_active(s,expected_state)
   snap=self.snapshot(s);valid={n for n in snap['net_names'].values() if n}
   if not isinstance(nets,list) or not isinstance(rip_existing,list) or any(type(n) is not str for n in nets+rip_existing):raise ValueError('nets must be string lists')
   if not set(nets+rip_existing)<=valid:raise ValueError('Unknown net')
   if s['arm']=='native' and (nets or rip_existing or options):raise ValueError('Native group must use original all-net defaults')
   cap=action_cap(s)
   if s['runs_used']>=cap:raise ValueError('Action budget exhausted')
   remaining=600-s['engine_seconds'];timeout=min(remaining,1800-(time.time()-s['started_at']),600 if s['arm']=='native' or (s['arm']=='model' and s['runs_used']==0) else 120)
   if timeout<1:raise ValueError('Engine budget exhausted')
   run_id=f'run{s["runs_used"]+1}';out=self.path/run_id;source=self.path/s['candidates'][s['current']]['board']
   argv=command(out/'input/board.kicad_pcb',out/'raw/board.kicad_pcb',nets,rip_existing,options)
   out.mkdir();copy_board(source,out/'input/board.kicad_pcb');(out/'raw').mkdir()
   reservation={'id':run_id,'from':s['current'],'nets':nets,'rip_existing':rip_existing,'options':options,'reserved_at':time.time(),'status':'reserved','input_sha256':sha(source),'timeout_seconds':timeout}
   s['runs_used']+=1;s['history'].append(reservation);self.write(s);save(out/'reservation.json',reservation)
   try:
    ex=invoke(argv,out,timeout);s['engine_seconds']+=ex['seconds'];reservation['execution']=ex;reservation['status']='executed';raw=out/'raw/board.kicad_pcb'
    text=(out/'engine.log').read_text(errors='replace');reservation['engine_feedback']=text[-18000:]
    summaries=[]
    for line in text.splitlines():
     if line.startswith('JSON_SUMMARY: '):
      try:summaries.append(json.loads(line[len('JSON_SUMMARY: '):]))
      except ValueError:pass
    reservation['native_summaries']=summaries
    reservation['native_summary']=next((x for x in summaries if x.get('scope')=='run'),summaries[0] if summaries else None)
    if raw.exists():
     task=load(self.path/'task.json');candidate=out/'candidate/board.kicad_pcb';copy_board(raw,candidate)
     reservation['raw_rule_hashes']=rules(raw)
     original=ROOT/task['board']
     for ext in ('.kicad_pro','.kicad_dru','.pro'):
      a=original.with_suffix(ext);b=candidate.with_suffix(ext)
      if a.exists():shutil.copy2(a,b)
      elif b.exists():b.unlink()
     reservation['packaging_copper_identical']=sha(raw)==sha(candidate)
     a=audit(original,candidate,task,out/'audit');reservation['check']=brief(a)
     if a['safe'] and ex['status']=='completed' and ex['returncode']==0:
      s['candidates'][run_id]={'board':str(candidate.relative_to(self.path)),'audit':str((out/'audit').relative_to(self.path)),'check':brief(a)}
      if s['arm']=='native':s['current']=run_id
    else:reservation['check']={'status':'no_output','safe':False,'task_success':False}
   except Exception as e:
    reservation.update(status='adapter_error',error=type(e).__name__+': '+str(e))
    # Reserve remains evidence. Missing execution time cannot be treated as zero.
    if 'execution' not in reservation:s['engine_seconds']=600;s['engine_time_unknown']=True
   finally:self.write(s);save(out/'result.json',reservation)
   return {'run_id':run_id,'from_snapshot':reservation['from'],'check':reservation.get('check'),'error':reservation.get('error'),'native_summary':reservation.get('native_summary'),'native_summaries':reservation.get('native_summaries',[]),'engine_feedback':reservation.get('engine_feedback','')[-9000:],'state_token':s['state_token'],'requires_explicit_select':s['arm']=='model','current_snapshot':s['current'],'engine_seconds':s['engine_seconds']}
 def route_a2a4(self,*args,**kwargs):
  raise NotImplementedError("A2/A4 experimental backend is not bundled in this release")
 def select(self,snapshot,expected_state):
  with (self.path/'session.lock').open('a+') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX);s=self.read();self.check_active(s,expected_state)
   if snapshot not in s['candidates']:raise ValueError('Not an independently verified safe snapshot')
   s['history'].append({'action':'select','from':s['current'],'to':snapshot,'at':time.time()});s['current']=snapshot;self.write(s)
  return self.observe()
 def finish(self,reason):
  with (self.path/'session.lock').open('a+') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX);s=self.read()
   if s['status']=='finished':return load(self.path/'result.json')
   c=s['candidates'][s['current']];copy_board(self.path/c['board'],self.path/'final/board.kicad_pcb')
   s.update(status='finished',finished_at=time.time(),reason=str(reason)[:2000]);self.write(s)
   r={'task':s['task_id'],'episode':self.path.name,'arm':s['arm'],'selected':s['current'],'task_success':c['check']['task_success'],'safe':c['check']['safe'],'check':c['check'],'final_board':str((self.path/'final/board.kicad_pcb').relative_to(ROOT)),'engine_seconds':s['engine_seconds'],'engine_time_unknown':s.get('engine_time_unknown',False),'runs_used':s['runs_used'],'wall_seconds':time.time()-s['started_at']};save(self.path/'result.json',r);return r
