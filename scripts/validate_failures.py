"""Offline CLI acceptance: native actions, rejection, timeout, cancel, export."""
import argparse,json,os,shutil,subprocess,sys,time
from pathlib import Path
from pcb_routelab.runtime import load,save
p=argparse.ArgumentParser();p.add_argument('--board',required=True);p.add_argument('--output',required=True);a=p.parse_args()
root=Path(a.output).resolve();root.mkdir(parents=True,exist_ok=False);board=Path(a.board).resolve();env=dict(os.environ,PCB_ROUTELAB_OFFLINE='1');checks=[]

def cli(*args):
 p=subprocess.run([sys.executable,'-m','pcb_routelab.cli',*map(str,args)],env=env,capture_output=True,text=True,timeout=180)
 save(root/f'command-{len(list(root.glob("command-*.json"))):02}.json',{'args':list(map(str,args)),'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
 return p

def run(name,*args):
 p=cli('run','--board',board,'--output',root/name,*args)
 return load(root/name/'result.json'),p

r,p=run('timeout','--seconds','.001');assert r['status']=='timeout' and not r['safe'],r
assert not (root/'timeout/review').exists();checks.append('timeout_not_delivered')
r,p=run('cancel','--background')
cli('cancel',root/'cancel')
for _ in range(200):
 r=load(root/'cancel/result.json')
 if r['status'] not in ('queued','running'):break
 time.sleep(.05)
assert r['status']=='cancelled' and not r['safe'],r;checks.append('background_cancel')
p=cli('export',root/'timeout','--output',root/'bad-export');assert p.returncode!=0 and not (root/'bad-export').exists();checks.append('timeout_export_denied')
save(root/'bad-policy.json',{'expression':'__import__("os")'})
r,p=run('bad-policy','--mode','policy','--policy',root/'bad-policy.json');assert r['status']=='error' and not (root/'bad-policy/engine').exists();checks.append('code_expression_rejected_before_engine')
# Unsupported input gets rejected without deletion or normalization.
fixture=root/'unsupported';fixture.mkdir();text=board.read_text();(fixture/'b.kicad_pcb').write_text(text[:text.rfind(')')]+'(zone)\n)\n');shutil.copy2(board.with_suffix('.kicad_pro'),fixture/'b.kicad_pro')
p=cli('run','--board',fixture/'b.kicad_pcb','--output',root/'zones');r=load(root/'zones/result.json');assert r['status']=='error' and not (root/'zones/engine').exists();checks.append('zone_not_silently_removed')
p=cli('run','--board',board,'--output',root/'timeout');assert p.returncode!=0;checks.append('existing_job_not_overwritten')
p=cli('run','--board',board,'--output',root/'online','--mode','harness','--enable-model');assert p.returncode!=0 and not (root/'online').exists();checks.append('offline_blocks_explicit_online_mode')
save(root/'summary.json',{'passed':True,'checks':checks,'model_api_calls':0})
print(json.dumps({'passed':True,'checks':checks}))
