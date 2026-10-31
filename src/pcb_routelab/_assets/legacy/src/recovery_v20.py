from release_runtime import WORK, CODE, ENGINE, ENGINE_PYTHON, KICAD_PYTHON, KICAD_CLI
"""Offline recovery: no API, no engine, no automatic candidate selection."""
import fcntl,json,os,time
from pathlib import Path
from audit_board_v6 import ROOT,load,sha,audit,copy_board
from session_core_v20 import save,brief

def recover_episode(episode):
 from session_legacy_v20 import Session
 session=Session(episode);ep=session.path
 with (ep/'session.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  state=session.read()
  for process in ep.glob('run*/process.json'):
   if not (process.parent/'execution.json').exists():
    pid=load(process)['pid']
    try:os.kill(pid,0)
    except ProcessLookupError:pass
    except PermissionError:raise RuntimeError('Process identity inaccessible; no recovery while execution uncertain')
    else:raise RuntimeError('Unsettled engine PID still alive; refuse recovery')
  container=ep/'recovery';container.mkdir(exist_ok=True)
  out=container/f'attempt_{len(list(container.glob("attempt_*")))+1:04d}';out.mkdir(exist_ok=False)
  # Any execution outcome without completion receipt stays unknown; never reissued.
  unknown=[p.parent.name for p in ep.glob('run*/reservation.json') if not (p.parent/'execution.json').exists()]
  candidates=dict(state['candidates'])
  for record in ep.glob('run*/result.json'):
   rid=record.parent.name;r=load(record);ex=r.get('execution',{})
   if rid in candidates or not r.get('check',{}).get('safe') or ex.get('status')!='completed' or ex.get('returncode')!=0:continue
   if r.get('backend') and not r.get('eligible_for_selection'):continue
   if (record.parent/'candidate/board.kicad_pcb').exists():candidates[rid]={'board':f'{rid}/candidate/board.kicad_pcb','audit':f'{rid}/audit','check':r['check']}
  task=load(ep/'task.json')
  # Engine completed but caller died before audit/state commit: recover only the
  # persisted raw output with its successful execution receipt, never reroute.
  for reservation in ep.glob('run*/reservation.json'):
   rid=reservation.parent.name
   if rid in candidates:continue
   execution=reservation.parent/'execution.json';raw=reservation.parent/'raw/board.kicad_pcb'
   if not execution.exists() or not raw.exists():continue
   ex=load(execution);rec=load(reservation)
   if ex.get('status')!='completed' or ex.get('returncode')!=0:continue
   if rec.get('backend','krt')!='krt':continue
   board=out/rid/'staged/board.kicad_pcb';copy_board(raw,board)
   if rec.get('backend'):
    overlay=reservation.parent/'overlay.json'
    if not overlay.exists():continue
    from geometry_v9 import clean_overlay
    clean_overlay(raw,board,reservation.parent/'input/board.kicad_pcb',load(overlay)['uuids'])
   import shutil
   for ext in ['.kicad_pro','.kicad_dru','.pro']:
    source=(ROOT/task['board']).with_suffix(ext);target=board.with_suffix(ext)
    if source.exists():shutil.copy2(source,target)
    elif target.exists():target.unlink()
   candidates[rid]={'board':str(board.relative_to(ep)),'audit':None,'check':{},'recovered_reservation':rec}
  exports=[]
  for rid,c in candidates.items():
   board=ep/c['board'];dest=out/rid;dest.mkdir(exist_ok=True)
   # Fresh audit each explicit recovery invocation; original rules, no geometry changes.
   check=audit(ROOT/task['board'],board,task,dest/'audit')
   eligible=check['safe']
   if rid!='initial':
    rec_path=ep/rid/'result.json';rec=load(rec_path) if rec_path.exists() else c.get('recovered_reservation',next((x for x in state['history'] if x.get('id')==rid),{}))
    if rec.get('backend'):
     from geometry_v9 import geometry_feedback,other_copper_preserved
     snap=load(dest/'audit/candidate_snapshot.json');feedback=geometry_feedback(snap,rec['nets'][0],rec.get('guidance',{}),[])
     before=load(ep/rec['from']/'audit/candidate_snapshot.json') if rec['from']!='initial' else load(ep/'initial_audit/candidate_snapshot.json')
     eligible=eligible and feedback['hard_constraints_satisfied'] and other_copper_preserved(before,snap,rec['nets'][0])
   if eligible:copy_board(board,dest/'board.kicad_pcb')
   exports.append({'snapshot':rid,'origin':('model_selected' if state['arm']=='model' else 'native_selected') if rid==state['current'] else 'host_recovery_unselected','safe':check['safe'],'eligible':bool(eligible),'task_success':bool(eligible and check['task_success']),'board':str((dest/'board.kicad_pcb').relative_to(ROOT)) if eligible else None,'audit':str((dest/'audit/result.json').relative_to(ROOT)),'source_sha256':sha(board)})
  # Finish only the persisted selected state, never a newly found better candidate.
  selected=next(x for x in exports if x['snapshot']==state['current'])
  primary=ep/'result.json'
  if not primary.exists():
   if not selected['eligible']:raise RuntimeError('Selected snapshot fails fresh audit; no final delivered')
   c=candidates[state['current']];check=load(ROOT/selected['audit']);copy_board(ep/c['board'],ep/'final/board.kicad_pcb')
   seconds=state['engine_seconds'];known_ids={x['id'] for x in state['history'] if x.get('execution')}
   for p in ep.glob('run*/execution.json'):
    if p.parent.name not in known_ids:seconds+=load(p).get('seconds',0)
   result={'task':state['task_id'],'episode':episode,'arm':state['arm'],'selected':state['current'],'task_success':check['task_success'],'safe':check['safe'],'check':brief(check),'final_board':str((ep/'final/board.kicad_pcb').relative_to(ROOT)),'engine_seconds':seconds,'engine_time_unknown':bool(unknown or state.get('engine_time_unknown')),'runs_used':state['runs_used'],'wall_seconds':time.time()-state['started_at'],'terminal_origin':'host_recovery_selected_snapshot'}
   save(primary,result);state.update(status='finished',finished_at=time.time(),reason='Offline recovery of persisted model-selected snapshot');session.write(state)
  final_path=ep/'final/board.kicad_pcb'
  if primary.exists() and (not final_path.exists() or sha(final_path)!=selected['source_sha256']):
   if not selected['eligible']:raise RuntimeError('Cannot recover unsafe selected final')
   if final_path.exists():
    copy_board(final_path,out/'prior_inconsistent_final/board.kicad_pcb')
   copy_board(ep/candidates[state['current']]['board'],final_path)
  # Repair a crash after finish marked state but before result, or the reverse.
  if session.read()['status']!='finished':
   state=session.read();state.update(status='finished',finished_at=time.time(),reason='Recovered persisted terminal receipt');session.write(state)
  manifest={'episode':episode,'recovery_attempt':str(out.relative_to(ROOT)),'origin':'host_recovery','api_requests':0,'engine_invocations':0,'auto_selected_candidate':False,'selected':state['current'],'primary_result':str(primary.relative_to(ROOT)),'unknown_execution_runs':unknown,'exports':exports,'recoverable_complete':any(x['task_success'] for x in exports),'unselected_complete':[x['snapshot'] for x in exports if x['task_success'] and x['snapshot']!=state['current']],'metric_rule':'Unselected recovery boards never count as model-selected success.'}
  save(out/'manifest.json',manifest);save(container/'manifest.json',manifest);return manifest
