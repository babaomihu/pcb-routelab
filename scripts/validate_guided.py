"""Native single-net guided-route contract check; scripted, zero model API calls."""
import argparse,os
from pathlib import Path
from pcb_routelab.runtime import configure,load,save
from pcb_routelab.worker import native_input
p=argparse.ArgumentParser();p.add_argument('--board',required=True);p.add_argument('--output',required=True);a=p.parse_args()
work=Path(a.output).resolve();work.mkdir(parents=True,exist_ok=False);configure(work)
os.environ.update(PCB_ROUTELAB_OFFLINE='1',PCB_START_POLICY='autonomous',PCB_TOOL_PROFILE='geometry')
import audit_board_v6 as A
board=work/'input/board.kicad_pcb';A.copy_board(Path(a.board).resolve(),board)
task,_=native_input(A,board,work);save(work/'data/v20/tasks/user.json',task)
from session_v20 import Session
s=Session.create('user','guided','model');s.bootstrap();net=task['target_net_names'][0]
s.plan_board({'approach':'geometric_first','priority_nets':[net],'rationale':'Exercise the existing single-net guided-route interface','steps':['Route one observed net on the front copper layer'],'revision_reason':'Initial offline contract check'},s.read()['state_token'])
s.propose_intervention({'problem':'One observed net has an unconnected pad pair','evidence_run':'initial','evidence_ids':[],
 'hypothesis':'The existing router can use front-layer guidance for this net','action':'route_guided','nets':[net],
 'expected_effect':'Connect this net without modifying other-net copper','verification':'Check original native rules and actual guidance consumption','on_failure':'Reject output and preserve the initial state'},s.read()['state_token'])
r=s.route_guided(net,{'layers':['F.Cu']},{},'Offline guided interface test with native validation',s.read()['state_token'])
assert 'run1' in s.read()['candidates'],r
s.select('run1',s.read()['state_token']);final=s.finish('Scripted guided check complete')
check=load(s.path/'run1/audit/result.json')
assert check['safe'] and check['final_unconnected']<check['initial_unconnected'],check
save(work/'summary.json',{'passed':True,'safe':True,'model_api_calls':0,'initial_unconnected':check['initial_unconnected'],
                        'final_unconnected':check['final_unconnected'],'net':net,'scope':'Existing KRT front-layer single-net guidance; no model or new algorithm'})
print('Guided-route offline check passed')
