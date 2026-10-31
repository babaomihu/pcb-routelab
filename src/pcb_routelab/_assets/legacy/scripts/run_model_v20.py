from release_runtime import WORK, CODE, ENGINE, ENGINE_PYTHON, KICAD_PYTHON, KICAD_CLI
"""Single real Harness model; native engine candidates require explicit safe selection."""
import argparse,json,os,re,time
from pathlib import Path
ROOT=WORK
from loop_gateway_v20 import LoopGateway,store

PROMPT=('You are the single autonomous whole-board PCB routing planner using real DeepSeek Harness tools. '
'Read start_policy and INITIAL_OBSERVATION. If autonomous, the host has performed ZERO routing: all first-action decisions belong to you. If default_first, the host ran the stock default once as a comparator and its result is visible; that was not your decision. '
'Before your first engine action, call plan_board with YOUR strategy inferred from actual pads, layout, original rules and any existing copper. You may choose one stock default all-net call, prioritized individual nets, geometric guidance, parameter choices, or a combination. No network/path/parameter answer is prescribed. Simple default may be the best first move. Do not force geometry merely to demonstrate it. '
'Your task is to finish the WHOLE board, not only a priority net. Inspect geometry/rules/DRC as needed, execute, inspect feedback, select a safe snapshot explicitly, continue or revise plan_board based on evidence. A temporary geometric hypothesis may change when later routing improves the whole-board result; only original user constraints are immutable. '
'route_nets with nets=[], rip_existing=[], options={} is the unchanged stock all-net default. Individual named nets across separate calls express your priority; a nets list alone does not control internal solver order. The stock engine can change more copper than anticipated; read actual_copper_changes. Continue from the explicitly selected snapshot. You can revert to an earlier safe snapshot before completion. '
'For route_nets, plan.evidence_run may be initial or an actually executed run. objective initial is for a first routing action, continue for unfinished planned routing, repair for a diagnosed failure, quality for a complete board. Distinguish route completion from native rule compliance. Never relax original design rules or change layout or netlist. Copper sizes may change only when they satisfy original rules. '
'route_guided supports existing KRT single-net waypoints, convex keepouts, copper layers and layer costs. Soft waypoints may be skipped; require_waypoints checks that invocation. Inspect the returned actual geometry. Later all-net calls may rewrite earlier geometry; do not claim a final waypoint is kept without checking. Parameter changes and network priority can matter without geometric actions. '
'All actual engine candidates are checked against the ORIGINAL board and rules. Unsafe/rejected candidates cannot be selected. No candidate is selected automatically. Safe partial copper is not task success. Stop when the entire board meets the task or when evidence/budget shows you cannot complete; report failures honestly. Once a complete safe snapshot exists, preserve completion, do not increase its vias, and keep length <=1.01 of the first complete reference. '
'Budget: 8 engine transactions, 600 cumulative engine seconds, geometry and subsequent transactions at most120 seconds, 24 real requests each4096 outputtokens, 1800 sessionseconds, no retries. Planning/revision consumes a model response but no engine transaction. Only one write per model response; use the exact latest expected_state. Host terminal confirmation is not model reasoning. KRT is the formal backend; no shell or direct copper generation. No electrical/manufacturing signoff.\nINITIAL_OBSERVATION:\n')

def main():
 if os.environ.get('PCB_ROUTELAB_ENABLE_MODEL')!='1' or os.environ.get('PCB_ROUTELAB_OFFLINE')=='1':raise RuntimeError('Model mode requires explicit online opt-in')
 from deepseek_harness import DeepSeekHarness
 p=argparse.ArgumentParser();p.add_argument('task');p.add_argument('--episode',required=True);p.add_argument('--requests',type=int,default=24);p.add_argument('--start-policy',choices=['autonomous','default_first'],default='autonomous');p.add_argument('--method',choices=['legacy','enhanced'],default='enhanced');p.add_argument('--profile',choices=['parameters','geometry','draw'],default='geometry');p.add_argument('--staged-smoke',action='store_true');a=p.parse_args()
 os.environ['PCB_METHOD']=a.method
 if a.method=='legacy':
  from session_legacy_v20 import Session as NativeSession
 else:
  from session_v20 import Session as NativeSession
 if a.staged_smoke and a.task!='dev_dev_smoke_empty':raise ValueError('Guided staging only permitted on synthetic development smoke')
 if not re.fullmatch(r'[A-Za-z0-9_-]{1,60}',a.task) or not re.fullmatch(r'[A-Za-z0-9_-]{1,70}',a.episode):raise ValueError('Invalid identifier')
 req_cap=48 if a.profile=='draw' else 24
 if not 1<=a.requests<=req_cap:raise ValueError(f'V20 cap is 1..{req_cap} requests including final summary')
 out=ROOT/'runs/v20/harness'/a.episode;out.mkdir(parents=True,exist_ok=False)
 os.environ['PCB_TOOL_PROFILE']=a.profile
 os.environ['PCB_START_POLICY']=a.start_policy
 started=time.monotonic();store(out/'session_clock.json',{'started_at':time.time()})
 result={'arm':'model','method':a.method,'task':a.task,'episode':a.episode,'real_model':True,'start_policy':a.start_policy,'tool_profile':a.profile,'guided_staged_smoke':a.staged_smoke,'requests':0};gateway=None;session=None
 try:
  session=NativeSession.create(a.task,a.episode,'model');obs=session.bootstrap();store(out/'initial_observation.json',obs)
  gateway=LoopGateway(a.episode,a.requests);gateway.start()
  keys=['PCB_METHOD','PCB_START_POLICY','PCB_TOOL_PROFILE','PCB_ASSIST_ROOT','PCBWORLD_PILOT_ROOT','PCBWORLD_ENGINE_HOME','PCBWORLD_KICAD_RL_BUILD_DIR','BUILD_DIR','DYLD_LIBRARY_PATH','KICAD_ENGINE_REUSE','PYTHONPATH','PYTHONDONTWRITEBYTECODE','PYTHONPYCACHEPREFIX','TMPDIR','XDG_CACHE_HOME','KICAD_CONFIG_HOME','KICAD_CRASH_LOG_DIR','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS']
  allowed={k:v for k,v in os.environ.items() if k in keys or k.startswith('PCB_ROUTELAB_') and k not in ('PCB_ROUTELAB_API_KEY',)};allowed['PCB_EPISODE']=a.episode
  python=ENGINE_PYTHON
  patch=[{'id':'llm-deepseek','disabled':True},{'id':'persistent-bash','disabled':True},{'id':'persistent-pwsh','disabled':True},{'insert':[{'id':'llm-pi-ai','name':'@deepseek-ai/dsh-llm-pi-ai','config':{'providers':{'pcb':{'api':'anthropic-messages','apiKeyEnv':'PCB_GATEWAY_KEY','baseURL':gateway.url,'timeoutMs':180000,'streamIdleTimeoutMs':170000,'retryPolicy':{'mode':'normal','maxRetries':0},'models':[{'id':'pcb-model','contextWindow':131072,'maxTokens':4096}]}}}},{'id':'mcp-pcb','name':'@deepseek-ai/dsh-mcp-client','config':{'serverName':'routing','transport':'stdio','command':str(python),'args':[str(CODE/'scripts/pcb_mcp_v20.py')],'cwd':str(ROOT),'env':allowed,'toolCallTimeoutMs':600000,'failOnStartupError':True,'reconnect':{'enabled':False}}}]}]
  store(out/'patch.json',patch);prompt=PROMPT+json.dumps(obs,ensure_ascii=False)
  prompt+='\nShared context access: pad details are paged by inspect_pads; inspect_payload retrieves exact archived observations/results/history by payload ID. Read relevant pads and constraints before proposing coordinate actions. Compacted previews are explicitly incomplete. Old complete turns may be archived with an exact current-state capsule; retrieve earlier evidence if needed. This mechanism never chooses routing actions.'
  if a.method=='enhanced':prompt+='\nV14 workflow: use diagnose and inspect_region to examine specific failures. Before EACH engine transaction call propose_intervention with your evidence IDs, hypothesis, expected change, verification and fallback. Review action_feedback to avoid identical ineffective repeats; a prior failure on a DIFFERENT board snapshot is not the same experiment. Use commit_result to explicitly select and deliver a safe candidate in one call when ready. These are authored workflow aids; you retain all routing decisions. Initial default_all remains valid.'
  if a.staged_smoke:prompt+='\nGUIDED INTEGRATION TEST ONLY (not an efficacy result): first route NET1 only and select the safe result, then observe the updated board, route NET2 only, select and finish. Use options={} to verify the stateful interface; do not run all nets at once.'
  if a.profile=='draw':prompt+='\nDRAW PROFILE (V20 baseline): bulk engine scheduling is DISABLED for you - route_nets and route_length_target do not exist in your tool list. You must complete the board by routing nets ONE AT A TIME with route_guided (KRT waypoints) or edit_copper (atomic coordinate primitives). You have 48 requests and 24 engine transactions. Prioritize nets by routability; inspect geometry before coordinate actions; select each safe result before the next net. Finish honestly when budget runs out.'
  store(out/'prompt.json',{'prompt':prompt,'model_identity':'User-authorized Claude endpoint; development Codex model is separate.'})
  with DeepSeekHarness(profile='sdk-minimal',provider='pcb',model='pcb-model',max_tokens=4096,cwd=str(ROOT),runtime_cwd=str(ROOT),dsh_home=str(ROOT/'runtime/dsh-home'),patches=(str(out/'patch.json'),),env={'PCB_GATEWAY_KEY':'local-relay-only'},initialize_timeout_seconds=60,request_timeout_seconds=max(1,1740-(time.monotonic()-started)),shutdown_timeout_seconds=5) as harness:
   reply=harness.run(prompt,session_id='v20_'+a.episode);store(out/'events.json',reply.events);result.update(harness_finish_reason=reply.finish_reason,final_response=reply.final_response,finish_reason=reply.finish_reason)
 except Exception as e:result.update(finish_reason='initialization_failed' if session is None else 'harness_error',error_type=type(e).__name__,error=str(e))
 finally:
  if gateway:
   gateway.close()
   if gateway.denials:result['gateway_termination_reason']=gateway.denials[-1]['reason']
  if session:
   try:
    finished=session.finish('host termination: '+result.get('finish_reason','unknown'));result['host_finish']=finished
    result.update(task_success=finished.get('task_success'),safe=finished.get('safe'),budget=finished.get('budget'),engine_seconds=finished.get('engine_seconds'),selected_run_id=finished.get('selected'),final_board=finished.get('final_board'),episode_status=finished.get('episode_status'))
   except Exception as e:result['host_finalize_error']={'type':type(e).__name__,'message':str(e)}
  if session and a.method=='enhanced':
   try:
    from recovery_v20 import recover_episode
    result['recovery']=recover_episode(a.episode)
   except Exception as e:result['recovery_error']=type(e).__name__+': '+str(e)
  used=[p for p in (ROOT/'runs/v20/api_ledger').glob('request_*/reservation.json') if json.loads(p.read_text()).get('scope')==a.episode]
  api=[json.loads((p.parent/'result.json').read_text()) if (p.parent/'result.json').exists() else {'status':'reserved_unknown','usage':None} for p in used]
  result['terminal_confirmation_origin']='host' if (out/'host_terminal.json').exists() else None
  result.update(requests=len(used),api_results=api,returned_models=sorted({x['returned_model'] for x in api if x.get('returned_model')}),reasoning_effort='provider_default',monetary_cost=None,walltime_seconds=time.monotonic()-started)
  state_path=ROOT/'runs/v20/episodes'/a.episode/'state.json'
  if state_path.exists():
   try:
    state=json.loads(state_path.read_text());result.update(final_state=state,episode_status=state.get('status'),budget=result.get('budget',state.get('budget')),selected_run_id=state.get('current'))
   except Exception as e:result['state_error']=type(e).__name__
  else:result.update(episode_status='initialization_failed',budget=None,final_board=None)
  store(out/'result.json',result)
 print(json.dumps({k:result.get(k) for k in ('episode','finish_reason','task_success','requests','selected_run_id','final_board','error')},ensure_ascii=False))
if __name__=='__main__':main()
