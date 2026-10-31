"""Real stdio MCP + native routing; scripted caller, no model or HTTP API."""
import argparse,json,os,select,shutil,subprocess,sys,time
from pathlib import Path
from pcb_routelab.runtime import assets,configure,load,save
from pcb_routelab.worker import native_input

p=argparse.ArgumentParser();p.add_argument('--board',required=True);p.add_argument('--output',required=True);a=p.parse_args()
work=Path(a.output).resolve();work.mkdir(parents=True,exist_ok=False);configure(work)
os.environ.update(PCB_ROUTELAB_OFFLINE='1',PCB_EPISODE='offline',PCB_METHOD='enhanced',PCB_START_POLICY='autonomous',PCB_TOOL_PROFILE='geometry')
import audit_board_v6 as A
source=Path(a.board).resolve();board=work/'input/board.kicad_pcb';A.copy_board(source,board)
task,_=native_input(A,board,work);save(work/'data/v20/tasks/user.json',task)
from session_v20 import Session
s=Session.create('user','offline','model');s.bootstrap()
out=work/'runs/v20/harness/offline';out.mkdir(parents=True,exist_ok=True);counter=0;checks=[]
log=(work/'mcp.stderr.log').open('w')
proc=subprocess.Popen([sys.executable,str(assets()/'legacy/scripts/pcb_mcp_v20.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,env=os.environ.copy())

def request(method,params):
 global counter
 counter+=1;save(out/'response_gate.json',{'response_number':counter,'write_used':False})
 proc.stdin.write(json.dumps({'jsonrpc':'2.0','id':counter,'method':method,'params':params})+'\n');proc.stdin.flush()
 if not select.select([proc.stdout],[],[],120)[0]:raise TimeoutError('MCP did not reply')
 line=proc.stdout.readline()
 if not line:raise RuntimeError('MCP exited; inspect stderr')
 msg=json.loads(line)
 if 'error' in msg:raise RuntimeError(msg['error'])
 return msg['result']

def tool(name,args):
 r=request('tools/call',{'name':name,'arguments':args})
 if r.get('isError'):raise RuntimeError(str(r))
 checks.append(name)
 return json.loads(r['content'][0]['text'])

def token():return s.read()['state_token']
try:
 request('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'offline-test','version':'1'}})
 listing=request('tools/list',{});assert 'route_nets' in {t['name'] for t in listing['tools']}
 tool('observe',{})
 tool('plan_board',{'plan':{'approach':'default_all','priority_nets':[],'rationale':'Offline contract check of an existing router operation','steps':['Route all supported nets once and inspect independent checks'],'revision_reason':'Initial scripted contract test'},'expected_state':token()})
 tool('propose_intervention',{'plan':{'problem':'Two disconnected signal nets in synthetic fixture','evidence_run':'initial','evidence_ids':[],
      'hypothesis':'Existing default router can connect the unobstructed fixture','action':'route_nets','nets':[],
      'expected_effect':'Reduce remaining connections while preserving original rules','verification':'Independent native DRC and original connected groups','on_failure':'Keep initial snapshot and report the failure'},'expected_state':token()})
 r=tool('route_nets',{'nets':[],'rip_existing':[],'options':{},'expected_state':token(),
      'plan':{'objective':'initial','evidence_run':'initial','diagnosis':'Synthetic fixture contains two unconnected signal nets','expected_effect':'Connect both using the existing router and original rules'}})
 assert 'run1' in s.read()['candidates'],r
 tool('action_feedback',{})
 tool('commit_result',{'snapshot':'run1','expected_state':token(),'reason':'Scripted offline acceptance check passed'})
 final=load(s.path/'result.json');assert final['safe'] and final['task_success'],final
 save(work/'summary.json',{'passed':True,'calls':checks,'tools':len(listing['tools']),'model_api_calls':0,'real_model':False,
                           'safe':final['safe'],'task_success':final['task_success'],'scope':'Actual stdio server + native router; no model quality or provider authentication test'})
 print('MCP offline integration passed')
finally:
 proc.stdin.close()
 try:proc.wait(timeout=5)
 except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=5)
 log.close()
