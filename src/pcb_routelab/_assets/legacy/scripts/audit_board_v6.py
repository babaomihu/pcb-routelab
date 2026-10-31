from release_runtime import WORK, CODE, ENGINE, ENGINE_PYTHON, KICAD_PYTHON, KICAD_CLI
"""Independent V6 native-copy audit. Does not route or modify input/candidate."""
import argparse,collections,hashlib,json,re,shutil,time,math
from decimal import Decimal,InvalidOperation
from pathlib import Path
ROOT=WORK

def load(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def key(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def dump(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def rules(p):return {ext:sha(p.with_suffix(ext)) if p.with_suffix(ext).exists() else None for ext in ('.kicad_pro','.kicad_dru','.pro')}
def copy_board(p,q):
 q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
 for ext in ('.kicad_pro','.kicad_dru','.pro'):
  if p.with_suffix(ext).exists():shutil.copy2(p.with_suffix(ext),q.with_suffix(ext))

def sexpr(text):
 tokens=re.findall(r'"(?:\\.|[^"\\])*"|\(|\)|[^\s()]+',text);stack=[];root=None
 for t in tokens:
  if t=='(':
   item=[]
   if stack:stack[-1].append(item)
   stack.append(item)
  elif t==')':
   if not stack:raise ValueError('Unbalanced sexpr')
   item=stack.pop()
   if not stack:root=item
  elif stack:stack[-1].append(t)
  else:raise ValueError('Invalid sexpr token')
 if stack or root is None:raise ValueError('Incomplete sexpr')
 return root

def token(t):
 if t.startswith('"'):return ['quoted',json.loads(t)]
 try:
  d=Decimal(t)
  if not d.is_finite():raise ValueError('Nonfinite board token')
  return ['number',str(d.normalize())]
 except InvalidOperation:return ['atom',t]

def canonical(node,nets):
 if not isinstance(node,list):return token(node)
 if node and node[0] in ('uuid','tstamp'):return None
 if node and node[0]=='net' and len(node)>=2:return ['net_name',token(node[-1])]
 parts=[canonical(x,nets) for x in node];parts=[x for x in parts if x is not None]
 # Child forms carry named fields; retain atom order and point sequences.
 # Simpler direct split avoids order dependence of named property serialization.
 atomparts=[canonical(x,nets) for x in node if not isinstance(x,list)]
 childparts=[canonical(x,nets) for x in node if isinstance(x,list)];childparts=[x for x in childparts if x is not None]
 if node and node[0] in ('pts','xy','xyz'):return parts
 return atomparts+sorted(childparts,key=key)

def child(node,name):return next((x for x in node if isinstance(x,list) and x and x[0]==name),None)
def uuids(node):
 return [x[1].strip('"') for x in node if isinstance(x,list) and x and x[0] in ('uuid','tstamp') and len(x)>1]
def text_snapshot(board):
 ast=sexpr(board.read_text());forms=[x for x in ast if isinstance(x,list) and x]
 nets={int(x[1]):x[2].strip('"') for x in forms if x[0]=='net' and len(x)>2}
 layout=[];ids={}
 for f in forms:
  if f[0] in ('footprint','module'):
   norm=canonical(f,nets);layout.append(norm)
   for ident in uuids(f):ids[ident]=['footprint',norm]
   for p in f:
    if isinstance(p,list) and p and p[0]=='pad':
     for ident in uuids(p):ids[ident]=['pad_in_footprint',norm,canonical(p,nets)]
  elif f[0] in ('gr_line','gr_arc','gr_circle','gr_poly','gr_rect','gr_curve'):
   layer=child(f,'layer')
   if layer and layer[1].strip('"')=='Edge.Cuts':
    for ident in uuids(f):ids[ident]=['outline',canonical(f,nets)]
 return {'layout_text':sorted(layout,key=key),'zone_count':sum(f[0]=='zone' for f in forms),'copper_arc_count':sum(f[0]=='arc' for f in forms),'net_names':nets,'uuid_identities':ids}

def native_snapshot(board):
 import subprocess,os
 python=str(KICAD_PYTHON)
 proc=subprocess.run([python,str(CODE/'scripts/snapshot_native_v5.py'),str(board)],capture_output=True,text=True,timeout=60,env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME')})
 if proc.returncode:raise RuntimeError(proc.stdout+proc.stderr)
 native=json.loads(proc.stdout.strip().splitlines()[-1]);text=text_snapshot(board)
 if 'error' in native:raise RuntimeError(native['error'])
 ast=sexpr(board.read_text());forms=[x for x in ast if isinstance(x,list) and x]
 text['net_names']={int(k):v for k,v in native.pop('native_net_names').items()}
 text['uuid_identities'].update(native.pop('native_uuid_identities'))
 # Full text canonical geometry supplements native copper with exact pads/layout/outline/rules.
 pads=sorted([canonical(p,text['net_names']) for f in forms if f[0] in ('footprint','module') for p in f if isinstance(p,list) and p and p[0]=='pad'],key=key)
 outline=sorted([canonical(f,text['net_names']) for f in forms if child(f,'layer') and child(f,'layer')[1].strip('"')=='Edge.Cuts'],key=key)
 design=sorted([canonical(f,text['net_names']) for f in forms if f[0] in ('setup','net_class')],key=key)
 native['pads']=sorted(native['pads'],key=key);native['footprints']=sorted(native['footprints'],key=key)
 text['raw_layout_text']=text['layout_text'];text['raw_setup_text']=design
 text['layout_text']=native['footprints']
 return dict(text,**native,outline=outline,remaining_by_net_name={})

def remaining_from_cli(report,snapshot):
 counts=collections.Counter()
 for row in report.get('unconnected_items',[]):
  names={snapshot['uuid_net_names'].get(item.get('uuid')) for item in row.get('items',[])}
  if None in names or len(names)!=1:raise ValueError('Unconnected item UUID missing or mixed net names')
  counts[next(iter(names))]+=1
 return dict(counts)

def drc_identity(v,idmap,unmapped):
 items=[]
 for item in v.get('items',[]):
  ident=item.get('uuid');mapped=idmap.get(ident)
  if ident and mapped is not None:identity=['geometry',mapped]
  elif ident:identity=['unmapped_uuid',ident];unmapped.append(ident)
  else:identity=['description',item.get('description','')];unmapped.append('missing_uuid:'+item.get('description',''))
  # Exact native positions retained; no coordinate tolerance/rounding.
  items.append([identity,item.get('pos',{})])
 return [v.get('type'),sorted(items,key=key),v.get('description'),v.get('severity')]

def compare_drc(before,after,bmap,amap):
 old=[v for v in before.get('violations',[]) if v.get('severity')=='error'];new=[v for v in after.get('violations',[]) if v.get('severity')=='error'];missing=[]
 bc=collections.Counter(key(drc_identity(v,bmap,missing)) for v in old);ac=collections.Counter(key(drc_identity(v,amap,missing)) for v in new);added=ac-bc;removed=bc-ac
 def select(rows,mp,counts):
  counts=counts.copy();result=[]
  for v in rows:
   k=key(drc_identity(v,mp,[]))
   if counts[k]:result.append(v);counts[k]-=1
  return result
 return {'initial_error_count':len(old),'final_error_count':len(new),'new_error_count':sum(added.values()),'removed_error_count':sum(removed.values()),'new_errors':select(new,amap,added),'removed_errors':select(old,bmap,removed),'unmapped_error_item_uuids':sorted(set(missing)),'identity_verified':not missing,'identity_method':'Exact multiset(error type, UUID mapped to native wire/via or full static pad/footprint geometry+net identity, exact DRC item pos); no UUID-byte equality requirement; unknown identity fails closed'}

def compare_geometry(before,after,allowed_names):
 equal=lambda k:before[k]==after[k]
 protected=lambda snap,k:collections.Counter(key(x) for x in snap[k] if x['net_name'] not in allowed_names)
 after_components=[set(x) for x in after['pad_components']]
 connected=all(any(set(group)<=g for g in after_components) for group in before['pad_components'])
 all_after=collections.Counter(key(['track',x]) for x in after['tracks'])+collections.Counter(key(['via',x]) for x in after['vias'])
 locked=not (collections.Counter(key(x) for x in before['locked_copper'])-all_after)
 return {'original_pad_connections_preserved':connected,'locked_copper_preserved':locked and equal('locked_copper'),'copper_layer_count_preserved':equal('copper_layers'),'non_target_tracks_preserved':protected(before,'tracks')==protected(after,'tracks'),'non_target_vias_preserved':protected(before,'vias')==protected(after,'vias'),'pads_preserved':equal('pads'),'footprints_preserved':equal('footprints'),'physical_layout_preserved':equal('layout_text'),'outline_preserved':equal('outline'),'design_rules_preserved':equal('design_rules'),'netlist_names_preserved':set(before['net_names'].values())==set(after['net_names'].values()),'coverage_verified':before['zone_count']==after['zone_count']==before['copper_arc_count']==after['copper_arc_count']==0}

def geometry_summary(snapshot):
 return {'straight_track_length_mm':sum((math.dist(x['endpoints_nm'][0],x['endpoints_nm'][1])/1000000 if 'endpoints_nm' in x else math.dist(x['endpoints'][0],x['endpoints'][1])) for x in snapshot['tracks']),'tracks':len(snapshot['tracks']),'vias':len(snapshot['vias']),'copper_arcs':snapshot['copper_arc_count'],'zones':snapshot['zone_count']}

def cli_audit(board):
 import subprocess,os
 report=board.with_suffix('.cli_drc.json')
 env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME','DYLD_LIBRARY_PATH')}
 cmd=[str(KICAD_CLI),'pcb','drc','--format','json','--all-track-errors','--refill-zones','--output',str(report),str(board)]
 proc=subprocess.run(cmd,capture_output=True,text=True,timeout=120,env=env)
 board.with_suffix('.cli.log').write_text(proc.stdout+proc.stderr)
 if proc.returncode or not report.exists():raise RuntimeError('Native CLI failed: '+str(proc.returncode))
 data=load(report)
 if not isinstance(data.get('violations'),list) or not isinstance(data.get('unconnected_items'),list):raise RuntimeError('Incomplete native DRC schema')
 counts=collections.Counter(v.get('type') for v in data['violations'])
 if any(n>=1000 for n in counts.values()):raise RuntimeError('DRC report may be capped; complete verification unavailable')
 return {'report':str(report)}

def audit(source,candidate,task,out):
 source=Path(source).resolve();candidate=Path(candidate).resolve();out=Path(out).resolve()
 if any(p.suffix!='.kicad_pcb' or not p.is_file() for p in (source,candidate)):raise ValueError('source/candidate must be existing native PCB files')
 if out.exists():raise FileExistsError(out)
 out.mkdir(parents=True)
 before_hash={'source':sha(source),'candidate':sha(candidate),'source_rules':rules(source),'candidate_rules':rules(candidate)}
 result={'status':'failed','eligible':False,'eligible_for_selection':False,'input_coverage_eligible':False,'safe':False,'safety_pass':False,'goal':False,'goal_achieved':False,'task_success':False,'source':str(source),'candidate':str(candidate),'model_requests':0,'routing_actions':0,'input_hashes':before_hash,'geometry_tolerance':0}
 try:
  copied={}
  for name,p in [('source',source),('candidate',candidate)]:
   q=out/name/'board.kicad_pcb';copy_board(p,q);copied[name]=q
  initial=native_snapshot(copied['source']);final=native_snapshot(copied['candidate'])
  b=load(cli_audit(copied['source'])['report']);a=load(cli_audit(copied['candidate'])['report'])
  initial['remaining_by_net_name']=remaining_from_cli(b,initial);final['remaining_by_net_name']=remaining_from_cli(a,final)
  dump(out/'source_snapshot.json',initial);dump(out/'candidate_snapshot.json',final)
  allowed={initial['net_names'].get(int(n)) for n in task['allowed_nets']}
  if None in allowed or not allowed:raise ValueError('Unknown source target net')
  targets=set(task['target_net_names'])
  if not targets or not targets<=allowed:raise ValueError('Task source target net-name mismatch')
  for snap in (initial,final):
   names=list(snap['net_names'].values())
   if len(names)!=len(set(names)):raise ValueError('Ambiguous duplicate net names')
   if not allowed<=set(names):raise ValueError('Candidate target net names missing')
  reload=native_snapshot(copied['candidate']);reload['remaining_by_net_name']=remaining_from_cli(a,reload);independent_reload_stable=reload==final
  dump(out/'candidate_reload_snapshot.json',reload)
  strict_text={'raw_layout_text_equal':initial['raw_layout_text']==final['raw_layout_text'],'raw_setup_text_equal':initial['raw_setup_text']==final['raw_setup_text'],'policy':'Raw serialization evidence retained; physical fields compared with same-version KiCad10 native API. net code/name serialization, HPGL plotting, added default fields are not geometry substitutes. Native duplicate-pad-jumper field checked; custom pads fail closed.'}
  dump(out/'strict_text_comparison.json',strict_text)
  geometry=compare_geometry(initial,final,allowed);delta=compare_drc(b,a,initial['uuid_identities'],final['uuid_identities'])
  initial_unc=len(b.get('unconnected_items',[]));final_unc=len(a.get('unconnected_items',[]));remaining={name:final['remaining_by_net_name'].get(name,0) for name in sorted(targets)}
  pernet_nonregression=all(final['remaining_by_net_name'].get(name,0)<=initial['remaining_by_net_name'].get(name,0) for name in initial['net_names'].values())
  source_hash_ok=before_hash['source']==task['board_sha256'];rule_expected=task.get('rule_hashes',before_hash['source_rules']);rules_preserved=before_hash['source_rules']==before_hash['candidate_rules']==rule_expected
  goal=all(v==0 for v in remaining.values()) and final_unc==0;safe=pernet_nonregression and independent_reload_stable and all(geometry.values()) and rules_preserved and source_hash_ok and final_unc<=initial_unc and delta['identity_verified'] and delta['new_error_count']==0
  input_geometry=geometry_summary(initial);final_geometry=geometry_summary(final);geometry_delta={k:final_geometry[k]-input_geometry[k] for k in ('straight_track_length_mm','tracks','vias')}
  result.update(strict_text_comparison=strict_text,input_geometry=input_geometry,final_geometry=final_geometry,geometry_delta=geometry_delta,metrics=geometry_delta,eligible=safe,eligible_for_selection=safe,input_coverage_eligible=geometry['coverage_verified'] and source_hash_ok,independent_reload_stable=independent_reload_stable,per_net_connectivity_nonregression=pernet_nonregression,initial_remaining_by_net_name=initial['remaining_by_net_name'],safe=safe,safety_pass=safe,goal=goal,goal_achieved=goal,task_success=safe and goal,remaining_target_airwires=remaining,remaining_by_net_name=final['remaining_by_net_name'],initial_unconnected=initial_unc,final_unconnected=final_unc,unconnected_nonregression=final_unc<=initial_unc,new_drc_errors=delta['new_errors'],native_delta=delta,geometry=geometry,protected_unchanged=all(geometry[k] for k in ('non_target_tracks_preserved','non_target_vias_preserved','pads_preserved','footprints_preserved','physical_layout_preserved','outline_preserved')),rules_unchanged=rules_preserved,source_hash_verified=source_hash_ok,rule_hashes_before=before_hash['source_rules'],rule_hashes_candidate=before_hash['candidate_rules'],status='passed' if safe and goal else ('safe_incomplete' if safe else 'failed'),scope='zero zones and zero copper arcs; exact native geometry/net multiset, same-version native physical footprint/pad/layout fields (raw serialization evidence retained separately); no electrical signoff')
 except Exception as e:result['error']=type(e).__name__+': '+str(e)
 unchanged=before_hash=={'source':sha(source),'candidate':sha(candidate),'source_rules':rules(source),'candidate_rules':rules(candidate)};result['source_candidate_unchanged']=unchanged
 if not unchanged:result.update(status='failed',safe=False,safety_pass=False,eligible=False,eligible_for_selection=False,task_success=False)
 dump(out/'result.json',result);return result

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True);p.add_argument('--candidate',required=True);p.add_argument('--task',required=True);p.add_argument('--out',required=True);args=p.parse_args()
 r=audit(args.source,args.candidate,load(args.task),args.out);print(json.dumps({k:r.get(k) for k in ('status','eligible','safe','goal','remaining_target_airwires','error')},ensure_ascii=False))
 if not r['safe']:raise SystemExit(1)
if __name__=='__main__':main()
