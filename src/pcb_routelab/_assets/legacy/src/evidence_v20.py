from release_runtime import WORK, CODE, ENGINE, ENGINE_PYTHON, KICAD_PYTHON, KICAD_CLI
"""Read-only evidence organization. No routing, parameter selection or causal guesses."""
import collections,hashlib,json,math,re
from pathlib import Path

def stable(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def overlap(a,b):return a[0]<=b[2] and a[2]>=b[0] and a[1]<=b[3] and a[3]>=b[1]
def paged(items,offset,limit=80):
 if type(offset)is not int or offset<0:raise ValueError('offset must be nonnegative integer')
 return {'items':items[offset:offset+limit],'total_items':len(items),'offset':offset,'next_offset':offset+limit if offset+limit<len(items) else None}

def local_geometry(snap,nets,bbox,layers,offset=0):
 valid={v for v in snap['net_names'].values() if v}
 if not isinstance(nets,list) or any(n not in valid for n in nets):raise ValueError('Unknown net')
 if not isinstance(layers,list) or any(l not in ['F.Cu','B.Cu'] for l in layers):raise ValueError('Only existing two-layer copper supported')
 if bbox:
  if len(bbox)!=4 or any(type(n)not in (int,float) or not math.isfinite(n) for n in bbox) or bbox[0]>=bbox[2] or bbox[1]>=bbox[3]:raise ValueError('bbox = [xmin,ymin,xmax,ymax], finite increasing mm')
 elif nets:
  p=[p for p in snap['pads'] if p['net_name'] in nets];points=[p['GetPosition'] for p in p]
  if not points:raise ValueError('No pads; specify bbox')
  margin=2+max(math.hypot(*p['GetSize'])/2e6 for p in p)
  bbox=[min(p[0] for p in points)/1e6-margin,min(p[1] for p in points)/1e6-margin,max(p[0] for p in points)/1e6+margin,max(p[1] for p in points)/1e6+margin]
 else:raise ValueError('Provide nets or bbox')
 items=[]
 for i,p in enumerate(snap['pads']):
  x,y=[v/1e6 for v in p['GetPosition']];rad=math.hypot(*p['GetSize'])/2e6
  if overlap([x-rad,y-rad,x+rad,y+rad],bbox) and (not layers or set(layers)&set(p['GetLayerSet'])):
   items.append({'id':f'pad:{i}','type':'pad','net':p['net_name'],'ref':p['footprint']['GetReference'],'pin':p['GetNumber'],'xy_mm':[x,y],'size_mm':[n/1e6 for n in p['GetSize']],'rotation':p['GetOrientationDegrees'],'shape':p['GetShape'],'layers':[l for l in p['GetLayerSet'] if l in ['F.Cu','B.Cu']],'drill_mm':[n/1e6 for n in p['GetDrillSize']]})
 for i,t in enumerate(snap['tracks']):
  ends=[[v/1e6 for v in p] for p in t['endpoints_nm']];rad=t['width_nm']/2e6
  box=[min(p[0] for p in ends)-rad,min(p[1] for p in ends)-rad,max(p[0] for p in ends)+rad,max(p[1] for p in ends)+rad]
  if overlap(box,bbox) and (not layers or t['layer'] in layers):items.append({'id':f'track:{i}','type':'track','net':t['net_name'],'layer':t['layer'],'endpoints_mm':ends,'width_mm':rad*2})
 for i,v in enumerate(snap['vias']):
  x,y=[n/1e6 for n in v['position_nm']];rad=v['width_nm']/2e6
  if overlap([x-rad,y-rad,x+rad,y+rad],bbox) and (not layers or set(layers)&set(v['layers'])):items.append({'id':f'via:{i}','type':'via','net':v['net_name'],'xy_mm':[x,y],'layers':v['layers'],'diameter_mm':rad*2,'drill_mm':v['drill_nm']/1e6})
 relevant=sorted({x['net'] for x in items});rules=snap['design_rules']
 return {**paged(items,offset),'bbox_mm':bbox,'requested_nets':nets,'layer_filter':layers,'neighbor_nets':relevant,'outline':snap['outline'],'rules':{'units':'nm','board':{k:v for k,v in rules.items() if k!='effective_netclasses'},'netclasses':{n:rules.get('effective_netclasses',{}).get(n) for n in relevant}},'selection_semantics':'Conservative shape bounds (pads use circumscribed circles, tracks bounding boxes); may overinclude. ALL neighboring nets included, not inferred blockers. Continue pages. IDs scoped to this snapshot; no zones/arcs supported.'}

def diagnose(ep,run_id,net,offset):
 if run_id!='initial' and not re.fullmatch(r'run[1-9][0-9]*',run_id):raise ValueError('Invalid run')
 base=ep/'initial_audit' if run_id=='initial' else ep/run_id/'audit'
 if not base.exists():
  if not (ep/run_id/'reservation.json').exists():raise ValueError('Unknown run')
 audit=json.loads((base/'result.json').read_text()) if (base/'result.json').exists() else {}
 snap=json.loads((base/'candidate_snapshot.json').read_text()) if (base/'candidate_snapshot.json').exists() else None
 if net and snap and net not in snap['net_names'].values():raise ValueError('Unknown net')
 evidence=[]
 if audit:evidence.append({'id':f'{run_id}:audit:summary','kind':'native_audit_summary','safe':audit.get('safe'),'task_success':audit.get('task_success'),'remaining':audit.get('remaining_by_net_name'),'source':str(base/'result.json'),'json_pointer':'/'})
 execution=ep/run_id/'execution.json'
 if execution.exists():evidence.append({'id':f'{run_id}:execution','kind':'execution','data':json.loads(execution.read_text()),'source':str(execution)})
 for i,err in enumerate(audit.get('new_drc_errors') or []):
  names=sorted({n for item in err.get('items',[]) for n in re.findall(r'\[([^\]]+)\]',item.get('description',''))})
  if net and net not in names:continue
  refs=[]
  for item in err.get('items',[]):
   point=item.get('pos');near=[]
   if point and snap:
    for p in snap['pads']:
     dist=math.dist([point['x'],point['y']],[n/1e6 for n in p['GetPosition']])
     if dist<=2:near.append({'ref':p['footprint']['GetReference'],'pin':p['GetNumber'],'net':p['net_name'],'distance_mm':round(dist,4)})
   refs.append({'item':item,'nearby_pads':sorted(near,key=lambda p:p['distance_mm'])[:12]})
  evidence.append({'id':f'{run_id}:drc:{i}','kind':'native_drc_new_error','type':err.get('type'),'description':err.get('description'),'nets':names,'objects':refs,'source':str(base/'result.json'),'json_pointer':f'/new_drc_errors/{i}','causal_interpretation':'Rule violation is verified; nearby pads are context, not proven blockers.'})
 log=ep/run_id/'engine.log'
 if log.exists():
  lines=log.read_text(errors='replace').splitlines()
  for number,line in enumerate(lines,1):
   if line.startswith('JSON_SUMMARY: '):
    try:
     obj=json.loads(line[14:]);subset={k:obj[k] for k in ['scope','failed_single','open_single','failed_multipoint','cleanup_disconnected','successful','failed','min_clearance_used'] if k in obj}
     evidence.append({'id':f'{run_id}:log:{number}','kind':'engine_summary','data':subset,'source':str(log),'line':number})
    except ValueError:pass
   elif re.search(r'blocked by|no rippable|route stuck|ripped_by|failed net|re-route failed|warning:|static blockers:',line,re.I):
    window=[{'line':i+1,'text':lines[i]} for i in range(max(0,number-7),min(len(lines),number+10))]
    if net and not any(net in x['text'] for x in window):continue
    blockers=[];targets=[];cells=[]
    for x in window:
     clean=re.sub(r'\x1b\[[0-9;]*m','',x['text'])
     hit=re.match(r'\s*\d+\. (.+): (\d+) \(',clean)
     if hit:blockers.append({'net':hit[1],'reported_blocked_cells':int(hit[2]),'source_line':x['line']})
     hit=re.search(r'target=\((-?[0-9.]+),\s*(-?[0-9.]+)\)',clean)
     if hit:targets.append({'xy_mm':[float(hit[1]),float(hit[2])],'source_line':x['line'],'meaning':'Engine target, not obstruction coordinate'})
     hit=re.search(r'cell \((-?\d+),\s*(-?\d+), layer=(\d+)\)',clean)
     if hit:cells.append({'grid_cell':[int(hit[1]),int(hit[2])],'engine_layer_index':int(hit[3]),'source_line':x['line'],'units':'native grid indices; not converted to mm without exact grid origin'})
    evidence.append({'id':f'{run_id}:log:{number}','kind':'engine_report','text':line,'source':str(log),'line':number,'reported_blockers':blockers,'reported_targets':targets,'reported_grid_cells':cells,'context':window,'causal_interpretation':'Engine-reported search frontier blockers; not proof a particular reroute will solve the board. Unknown position/layer remains unknown.'})
 remaining=audit.get('remaining_by_net_name',{})
 return {**paged(evidence,offset,30),'run_id':run_id,'net_filter':net,'safe':audit.get('safe'),'remaining_by_net':{k:v for k,v in remaining.items() if v and (not net or k==net)},'snapshot_available':snap is not None,'unknowns':['Any blocking identity/location/layer not explicitly stated remains unknown.','Empty evidence is not proof of no obstacle.'],'source_of_truth':'Native audit governs rules/connectivity; engine self-report may disagree. Query inspect_region with this run_id to inspect rejected candidate; current board may differ.'}

def effects(ep,state):
 results=[];seen=collections.Counter()
 for h in state['history']:
  rid=h.get('id')
  if not rid:continue
  source=state['candidates'].get(h['from'],{});before=source.get('check',{});after=h.get('check') or {}
  sig=stable({'input':h.get('input_sha256') or (hashlib.sha256((ep/rid/'input/board.kicad_pcb').read_bytes()).hexdigest() if (ep/rid/'input/board.kicad_pcb').exists() else None),'nets':sorted(h.get('nets',[])),'rip':sorted(h.get('rip_existing',[])),'options':h.get('options'),'guidance':h.get('guidance')});seen[sig]+=1
  delta={}
  for label,key in [('remaining','final_unconnected'),('new_errors',None),('vias','vias'),('length_mm','straight_track_length_mm')]:
   if label=='new_errors':a=len(before.get('new_drc_errors')or[]);b=len(after.get('new_drc_errors')or[]) if after else None
   elif label in ('vias','length_mm'):a=(before.get('final_geometry')or{}).get(key);b=(after.get('final_geometry')or{}).get(key)
   else:a=before.get(key);b=after.get(key)
   delta[label]=b-a if a is not None and b is not None else None
  same=None;before_snap=ep/source.get('audit','__missing__')/'candidate_snapshot.json';after_snap=ep/rid/'audit/candidate_snapshot.json'
  if before_snap.exists() and after_snap.exists():
   a=json.loads(before_snap.read_text());b=json.loads(after_snap.read_text());same=all(a[k]==b[k] for k in ['tracks','vias'])
  results.append({'run_id':rid,'from_snapshot':h['from'],'eligible':rid in state['candidates'],'safe':after.get('safe'),'task_success':after.get('task_success'),'delta_after_minus_before':delta,'copper_unchanged':same,'no_connectivity_progress':delta['remaining'] is not None and delta['remaining']>=0,'same_input_action_occurrence':seen[sig],'repeated_identical_action':seen[sig]>1,'fingerprint':sig,'interpretation':'No connectivity gain may still improve quality; unchanged copper differs from rejected tool call. Compare original-rule safety first.','source':str(ep/rid/'audit/result.json')})
 return results
