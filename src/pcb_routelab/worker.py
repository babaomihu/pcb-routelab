"""One isolated routing job. All acceptance uses original rules and native KiCad."""
import collections
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from .runtime import assets, configure, load, save, sha, module, native_tools


class Cancelled(BaseException):pass


def stop(signum, frame):
    raise Cancelled('Task cancelled')


def invoke(argv, folder, seconds, env=None):
    folder.mkdir(parents=True, exist_ok=True)
    record={'argv':[str(x) for x in argv],'timeout_seconds':seconds,'started_at':time.time()}
    save(folder/'process.json',record)
    start=time.monotonic();proc=None
    try:
        with (folder/'process.log').open('w') as log:
            proc=subprocess.Popen(record['argv'],cwd=folder,env=env or os.environ.copy(),
                                  stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            record['pid']=proc.pid;save(folder/'process.json',record)
            try:proc.wait(timeout=seconds);record['status']='completed'
            except subprocess.TimeoutExpired:record['status']='timeout'
    finally:
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=3)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
        record.update(returncode=proc.returncode if proc else None,seconds=time.monotonic()-start)
        save(folder/'execution.json',record)
    return record


def native_input(A, board, work):
    # Source is a private byte-identical job copy; the user file is never passed to an engine.
    ast=A.sexpr(board.read_text())
    if not ast or ast[0]!='kicad_pcb':raise ValueError('Expected a KiCad PCB document')
    forms=[x for x in ast if isinstance(x,list) and x]
    if any(x[0] in ('zone','arc','module') for x in forms):
        raise ValueError('Zones, copper arcs or legacy modules are outside this release input scope; no automatic deletion/conversion')
    version=A.child(ast,'version')
    if not version or int(version[1])<20240101:raise ValueError('Legacy board format requires separately verified conversion')
    # Stable IDs are needed for both native DRC and saved/reloaded geometry.
    def ids(node):
        if isinstance(node,list):
            if node and node[0] in ('uuid','tstamp') and len(node)>1:yield node[1].strip('"')
            for x in node:yield from ids(x)
    identity=list(ids(ast))
    if not identity or len(identity)!=len(set(identity)) or '00000000-0000-0000-0000-000000000000' in identity:
        raise ValueError('Missing, duplicate or nil object identities; import repair is not implicit')
    snap=A.native_snapshot(board)
    version=subprocess.run([native_tools()['kicad_cli'],'--version'],capture_output=True,text=True,timeout=15,check=True).stdout.strip()
    if version!=snap['native_version'] or not version.startswith('10.0.'):
        raise ValueError('KiCad CLI/native Python must match a supported 10.0.x installation')
    ids=[int(k) for k,v in snap['net_names'].items() if int(k) and v]
    task={'id':'user','board':str(board.relative_to(work)),'board_sha256':sha(board),
          'rule_hashes':A.rules(board),'allowed_nets':ids,
          'target_net_names':[snap['net_names'][n] for n in ids],
          'allowed_geometry_backends':['krt'],'workflow':'whole_board','goal':'Improve or complete connections without relaxing original rules or breaking original connections'}
    save(work/'task.json',task)
    checked=A.audit(board,board,task,work/'input-audit')
    from input_gate_v12 import check_qualification
    gate=check_qualification(work/'input-audit');save(work/'input-gate.json',gate)
    if not gate['accepted']:raise ValueError('Unsupported or unverifiable input: '+', '.join(gate['reasons']))
    from rule_contract import derive,write_overrides
    floors=derive(snap,board.with_suffix('.kicad_dru').read_text() if board.with_suffix('.kicad_dru').exists() else '')
    save(work/'rule-contract.json',floors);write_overrides(work/'rule-floors.txt',floors)
    return task,checked


def package(A, raw, board, candidate):
    A.copy_board(raw,candidate)
    for ext in ('.kicad_pro','.kicad_dru','.pro'):
        p,q=board.with_suffix(ext),candidate.with_suffix(ext)
        if p.exists():shutil.copy2(p,q)
        elif q.exists():q.unlink()


def verify_and_deliver(A, board, candidate, task, work, result):
    checked=A.audit(board,candidate,task,work/'final-audit')
    result.update(safe=checked['safe'],task_success=checked['task_success'],
                  initial_unconnected=checked.get('initial_unconnected'),
                  final_unconnected=checked.get('final_unconnected'),audit='final-audit/result.json')
    if not checked['safe']:
        result.update(status='rejected',reason=checked.get('error') or 'Candidate failed original-rule or connection/protection checks')
        return
    improved=checked['final_unconnected']<checked['initial_unconnected']
    result['status']='success' if checked['task_success'] and improved else 'safe_incomplete' if improved else 'no_progress'
    result['reason']='Full connection and original-rule audit passed' if result['status']=='success' else 'Safe partial improvement' if improved else 'No connection improvement'
    # A reviewable safe copy is kept, but no-progress is never labelled a repaired board.
    A.copy_board(candidate,work/'review/board.kicad_pcb')
    result['review_board']='review/board.kicad_pcb'
    before=load(work/'final-audit/source_snapshot.json');after=load(work/'final-audit/candidate_snapshot.json')
    changes={}
    for kind in ('tracks','vias'):
        b=collections.Counter(json.dumps(x,sort_keys=True) for x in before[kind]);a=collections.Counter(json.dumps(x,sort_keys=True) for x in after[kind])
        changes[kind]={'added':[json.loads(x) for x in (a-b).elements()],
                       'removed':[json.loads(x) for x in (b-a).elements()]}
    save(work/'changes.json',changes)
    result['review_hashes']={str(p.relative_to(work)):sha(p) for p in (work/'review').iterdir() if p.is_file()}


def run(work):
    work=configure(work)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    request=load(work/'request.json');board=work/'input/board.kicad_pcb'
    result={'status':'running','mode':request['mode'],'model_requests':0,'started_at':time.time(),
            'safe':False,'task_success':False,'model_protocol_validation':'not_requested'}
    save(work/'result.json',result)
    initial={str(p.relative_to(work)):sha(p) for p in (work/'input').iterdir() if p.is_file()}
    try:
        import audit_board_v6 as A
        task,checked=native_input(A,board,work)
        mode=request['mode'];candidate=work/'candidate/board.kicad_pcb'
        seconds=request['seconds'];raw=work/'raw/board.kicad_pcb';raw.parent.mkdir()
        opts=load(work/'options.json') if (work/'options.json').exists() else {}
        if not set(request.get('nets',[])+request.get('rip_nets',[]))<=set(task['target_net_names']):raise ValueError('Unknown target or rip net')
        from session_core_v20 import command
        argv=command(board,raw,request.get('nets',[]),request.get('rip_nets',[]),opts)
        if mode=='probe':
            dumps={};hashes={}
            for name,extra in [('default',[]),('back',['--layer-costs','3.0','1.0'])]:
                env=dict(os.environ,KICAD_GLOBAL_PLAN='1',KICAD_GLOBAL_PLAN_DUMP_EXIT='1',
                         KICAD_GLOBAL_PLAN_DUMP=str(work/f'{name}-probe.json'))
                ex=invoke(argv+extra,work/name,seconds/2,env)
                if ex['status']!='completed' or ex['returncode']!=0:raise RuntimeError('Planning probe failed: '+name)
                dumps[name]=load(work/f'{name}-probe.json');hashes[name]=sha(work/f'{name}-probe.json')
            C=module('release_plan_contract',assets()/'joint/plan_contract-2026-10-08.py')
            obs=C.observation_from_dumps(sha(board),dumps,hashes);save(work/'observation.json',obs)
            plan={'version':1,'observation_sha256':C.digest(obs),'order':obs['native_order'],
                  'assignments':{n['id']:{'layer':None,'corridor':'none'} for n in obs['nets']}}
            C.validate(plan,obs);save(work/'plan.json',plan)
            result.update(status='planned',reason='Native planning observation and editable plan exported; no model call',safe=True)
        elif mode=='harness':
            from .model_config import provider
            provider()
            save(work/'data/v20/tasks/user.json',task)
            save(work/'configs/model_v20.json',{'total_model_request_cap':request['requests']})
            ex=invoke([sys.executable,assets()/'legacy/scripts/run_model_v20.py','user','--episode','job',
                       '--requests',str(request['requests'])],work/'harness-process',seconds)
            hr=work/'runs/v20/harness/job/result.json'
            if hr.exists():
                h=load(hr);result['model_requests']=h.get('requests',0);result['model_finish_reason']=h.get('finish_reason')
            if ex['status']=='timeout':result.update(status='timeout',reason='Harness wall-time limit reached')
            elif ex['returncode']!=0:raise RuntimeError('Harness process failed; inspect harness-process/process.log')
            else:
                ep=work/'runs/v20/episodes/job/result.json'
                if not ep.exists():raise RuntimeError('Harness did not produce a final board')
                final=load(ep);source=(work/final['final_board']).resolve()
                if not source.is_relative_to(work):raise ValueError('Invalid final board path')
                package(A,source,board,candidate)
                verify_and_deliver(A,board,candidate,task,work,result)
        else:
            env=os.environ.copy()
            if mode=='joint':
                obs=load(work/'observation.json');plan=load(work/'plan.json')
                C=module('release_plan_contract',assets()/'joint/plan_contract-2026-10-08.py');C.validate(plan,obs)
                if obs['reference_sha256']!=sha(board):raise ValueError('Plan does not belong to this exact board')
                env.update(KICAD_GLOBAL_PLAN='1',KICAD_GLOBAL_PLAN_LAYER='pref',KICAD_GLOBAL_PLAN_ATTRACT='1')
                argv=[sys.executable,assets()/'joint/engine_adapter-2026-10-09.py',work/'observation.json',work/'plan.json',work/'plan-trace.json','--',*argv[2:]]
            elif mode=='policy':
                policy=load(work/'policy.json')
                K=module('release_policy_contract',assets()/'congestion/policy-contract-2026-10-09.py');K.Policy(policy['expression'])
                env['KICAD_HISTORY_ESCALATE']='0'
                argv=[sys.executable,assets()/'congestion/route-policy-r2-2026-10-09.py','--policy',work/'policy.json','--trace',work/'policy-trace.json','--',*argv[2:]]
            ex=invoke(argv,work/'engine',seconds,env);result['execution']=ex
            if ex['status']=='timeout':result.update(status='timeout',reason='Engine timeout; incomplete output is not accepted')
            elif ex['returncode']!=0:result.update(status='engine_error',reason='Engine failed; inspect engine/process.log')
            elif not raw.exists():result.update(status='engine_error',reason='Engine exited without a PCB output')
            else:
                result['raw_rule_hashes']=A.rules(raw)
                package(A,raw,board,candidate)
                verify_and_deliver(A,board,candidate,task,work,result)
    except Cancelled:
        result.update(status='cancelled',reason='Cancelled; no candidate accepted',safe=False,task_success=False)
        result.pop('review_board',None)
    except Exception as e:
        result.update(status='error',reason=type(e).__name__+': '+str(e),safe=False,task_success=False)
    finally:
        unchanged=initial=={str(p.relative_to(work)):sha(p) for p in (work/'input').iterdir() if p.is_file()}
        result['input_copy_unchanged']=unchanged
        if not unchanged:result.update(status='protection_violation',safe=False,task_success=False,reason='Input copy changed')
        result['finished_at']=time.time();save(work/'result.json',result)
    return result


if __name__=='__main__':
    print(json.dumps(run(sys.argv[1]),ensure_ascii=False))
