"""Public CLI; all model use is explicit and offline is the default."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from .runtime import assets, configure, load, save, sha, native_tools
from . import __version__


def doctor():
    tools=native_tools();checks={}
    for name,argv in [('kicad_cli',[tools['kicad_cli'],'--version']),
                      ('kicad_python',[tools['kicad_python'],'-c','import pcbnew; print(pcbnew.Version())'])]:
        try:
            p=subprocess.run(argv,capture_output=True,text=True,timeout=15)
            checks[name]={'ok':p.returncode==0,'version':p.stdout.strip(),'error':p.stderr.strip()[:300]}
        except (OSError,subprocess.TimeoutExpired) as e:checks[name]={'ok':False,'error':str(e)}
    for name in ('numpy','scipy','shapely'):
        try:
            m=__import__(name);checks[name]={'ok':True,'version':m.__version__}
        except ImportError:checks[name]={'ok':False,'error':'Install requirements.lock.txt'}
    sys.path.insert(0,str(assets()/'krt/rust_router'))
    try:
        import grid_router
        checks['rust_router']={'ok':True,'binary':str(Path(grid_router.__file__).name)}
    except ImportError:checks['rust_router']={'ok':False,'error':'Run pcb-routelab build-engine --build-dir PATH'}
    versions=[checks[k].get('version','') for k in ('kicad_cli','kicad_python')]
    checks['kicad_version_match']={'ok':len(set(versions))==1 and versions[0].startswith('10.0.'),
                                  'supported':'KiCad 10.0.x, release tested on 10.0.4'}
    return {'version':__version__,'ready':all(v['ok'] for v in checks.values()),'checks':checks,'model_requests':0}


def build_engine(folder):
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    source=assets()/'krt/rust_router';env=dict(os.environ,PYO3_PYTHON=sys.executable,CARGO_TARGET_DIR=str(folder/'target'))
    argv=['cargo','build','--release','--locked','--manifest-path',str(source/'Cargo.toml')]
    with (folder/'build.log').open('w') as log:
        p=subprocess.run(argv,cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT)
    save(folder/'build.json',{'argv':argv,'returncode':p.returncode,'python':sys.version,'model_requests':0})
    if p.returncode:raise RuntimeError('Rust build failed; see '+str(folder/'build.log'))
    name='libgrid_router.dylib' if sys.platform=='darwin' else 'libgrid_router.so'
    binary=folder/'target/release'/name
    if not binary.exists():raise RuntimeError('Unsupported build platform or missing Rust library')
    shutil.copy2(binary,source/'grid_router.so')
    return {'built':True,'sha256':sha(binary),'model_requests':0}


def create_job(a):
    source=Path(a.board).expanduser().resolve()
    if not source.is_file() or source.suffix!='.kicad_pcb':raise ValueError('Provide an existing .kicad_pcb')
    project=Path(a.project).expanduser().resolve() if a.project else source.with_suffix('.kicad_pro')
    if not project.is_file() or project.suffix!='.kicad_pro':raise ValueError('Matching .kicad_pro is required; use --project to supply it explicitly')
    if a.mode=='harness':
        if not a.enable_model or os.environ.get('PCB_ROUTELAB_OFFLINE')=='1':raise ValueError('Model mode is disabled; requires --enable-model and offline flag unset')
        os.environ['PCB_ROUTELAB_ENABLE_MODEL']='1'
        from .model_config import provider
        provider()
    else:
        os.environ['PCB_ROUTELAB_OFFLINE']='1';os.environ.pop('PCB_ROUTELAB_ENABLE_MODEL',None)
    if not 0<a.seconds<=1800:raise ValueError('seconds must be in (0,1800]')
    if not 1<=a.requests<=24:raise ValueError('requests must be in [1,24]')
    if a.mode=='joint' and not (a.plan and a.observation):raise ValueError('joint needs --plan and --observation from a probe job')
    if a.mode=='policy' and not a.policy:raise ValueError('policy needs --policy JSON')
    work=Path(a.output).expanduser().resolve()
    if work.exists():raise FileExistsError('Output must be a NEW directory; existing jobs are never overwritten or automatically repeated')
    work.mkdir(parents=True);(work/'input').mkdir()
    files={source:work/'input/board.kicad_pcb',project:work/'input/board.kicad_pro'}
    for ext in ('.kicad_dru','.pro'):
        p=source.with_suffix(ext)
        if p.exists():files[p]=work/('input/board'+ext)
    before={str(p):sha(p) for p in files}
    for p,q in files.items():shutil.copy2(p,q)
    if before!={str(p):sha(p) for p in files}:raise RuntimeError('Input changed during copy; create a stable disk snapshot first')
    for name in ('policy','plan','observation','options'):
        p=getattr(a,name,None)
        if p:save(work/(name+'.json'),load(Path(p)))
    save(work/'original-inputs.json',before)
    save(work/'request.json',{'version':__version__,'mode':a.mode,'seconds':a.seconds,'requests':a.requests,
                             'nets':a.net or [],'rip_nets':a.rip_net or [],'model_enabled':a.mode=='harness'})
    save(work/'result.json',{'status':'queued','model_requests':0})
    return work


def supervise(work):
    work=Path(work).resolve();request=load(work/'request.json')
    # O_EXCL prevents accidental duplicate supervisors on an unfinished job.
    fd=os.open(work/'supervisor.lock',os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    proc=None;deadline=time.monotonic()+request['seconds']+420
    status=None
    try:
        with (work/'worker.log').open('w') as log:
            proc=subprocess.Popen([sys.executable,'-m','pcb_routelab.worker',str(work)],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            save(work/'supervisor.json',{'pid':os.getpid(),'worker_pid':proc.pid,'started_at':time.time()})
            while proc.poll() is None:
                if (work/'cancel.request').exists():status='cancelled';break
                if time.monotonic()>deadline:status='timeout';break
                time.sleep(.15)
    except KeyboardInterrupt:status='cancelled'
    finally:
        if proc and proc.poll() is None:
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
        result=load(work/'result.json')
        if status:result.update(status=status,safe=False,task_success=False,reason='Cancelled by user' if status=='cancelled' else 'Supervisor deadline exceeded');result.pop('review_board',None)
        elif result.get('status') in ('running','queued'):result.update(status='error',safe=False,reason='Worker exited before terminal report')
        original=load(work/'original-inputs.json')
        result['original_inputs_unchanged']=all(Path(p).is_file() and sha(p)==h for p,h in original.items())
        if not result['original_inputs_unchanged']:result.update(status='protection_violation',safe=False,task_success=False,reason='Original input changed during the job; review required');result.pop('review_board',None)
        result['worker_returncode']=proc.returncode if proc else None
        save(work/'result.json',result)
    return result


def export(work,destination):
    work=Path(work).resolve();result=load(work/'result.json');dest=Path(destination).resolve()
    if result.get('status') not in ('success','safe_incomplete') or not result.get('safe'):raise ValueError('Only accepted improving candidates can be exported')
    for p,h in result.get('review_hashes',{}).items():
        path=(work/p).resolve()
        if not path.is_relative_to(work) or not path.is_file() or sha(path)!=h:raise ValueError('Review package modified since acceptance')
    if dest.exists():raise FileExistsError('Export destination must not exist')
    # Re-audit at export; editing a report or a review file cannot bypass acceptance.
    configure(work)
    import audit_board_v6 as A
    source=work/'input/board.kicad_pcb';candidate=work/'review/board.kicad_pcb'
    audit_dir=work/('export-audit-'+str(time.time_ns()))
    check=A.audit(source,candidate,load(work/'task.json'),audit_dir)
    if not check['safe'] or check['final_unconnected']>=check['initial_unconnected']:raise ValueError('Export revalidation failed')
    dest.mkdir(parents=True);A.copy_board(audit_dir/'candidate/board.kicad_pcb',dest/'board.kicad_pcb')
    save(dest/'report.json',result)
    return {'exported':str(dest),'model_requests':0}


def main():
    p=argparse.ArgumentParser(description='PCB RouteLab — isolated routing, planning and Harness experiments')
    p.add_argument('--version',action='version',version=__version__)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor',help='Offline dependency checks')
    q=sub.add_parser('build-engine');q.add_argument('--build-dir',required=True)
    q=sub.add_parser('run');q.add_argument('--board',required=True);q.add_argument('--project');q.add_argument('--output',required=True)
    q.add_argument('--mode',choices=['native','probe','joint','policy','harness'],default='native')
    q.add_argument('--seconds',type=float,default=120);q.add_argument('--requests',type=int,default=8)
    for name in ('plan','observation','policy','options'):q.add_argument('--'+name)
    q.add_argument('--net',action='append');q.add_argument('--rip-net',action='append')
    q.add_argument('--enable-model',action='store_true');q.add_argument('--background',action='store_true')
    for name in ('status','cancel','_supervise'):
        q=sub.add_parser(name);q.add_argument('job')
    q=sub.add_parser('export');q.add_argument('job');q.add_argument('--output',required=True)
    a=p.parse_args()
    try:
        if a.command=='doctor':r=doctor()
        elif a.command=='build-engine':r=build_engine(a.build_dir)
        elif a.command=='run':
            work=create_job(a)
            if a.background:
                with (work/'supervisor.log').open('w') as log:
                    child=subprocess.Popen([sys.executable,'-m','pcb_routelab.cli','_supervise',str(work)],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                r={'status':'started','job':str(work),'supervisor_pid':child.pid}
            else:r=supervise(work)
        elif a.command=='_supervise':r=supervise(a.job)
        elif a.command=='status':r=load(Path(a.job)/'result.json')
        elif a.command=='cancel':
            work=Path(a.job).resolve();r=load(work/'result.json')
            if r['status'] in ('running','queued'):(work/'cancel.request').touch();r={'status':'cancel_requested','job':str(work)}
        else:r=export(a.job,a.output)
        print(json.dumps(r,ensure_ascii=False,indent=2))
        if a.command=='doctor':return 0 if r['ready'] else 2
        return 2 if r.get('status') in ('error','rejected','engine_error','protection_violation','timeout','cancelled') else 0
    except (ValueError,RuntimeError,OSError,KeyError,json.JSONDecodeError) as e:
        print(json.dumps({'status':'error','reason':str(e)},ensure_ascii=False),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
