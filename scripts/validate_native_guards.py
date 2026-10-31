"""Native negative acceptance cases; no network or model calls."""
import argparse,json,os,shutil,subprocess,sys
from pathlib import Path
from pcb_routelab.runtime import configure,load,save,native_tools
p=argparse.ArgumentParser();p.add_argument('--example',required=True);p.add_argument('--accepted',required=True);p.add_argument('--output',required=True);a=p.parse_args()
root=Path(a.output).resolve();root.mkdir(parents=True,exist_ok=False);configure(root)
import audit_board_v6 as A
from pcb_routelab.worker import native_input
original_example=Path(a.example).resolve();example=root/'fixture/board.kicad_pcb';A.copy_board(original_example,example);accepted=Path(a.accepted).resolve();checks=[]
# Real native source/candidate pair: same airwire count on the same net, different connected pads.
script=root/'make-pair.py'
script.write_text('''import pcbnew as k, wx, sys
from pathlib import Path
app=wx.App(False);root=Path(sys.argv[1]);b=k.LoadBoard(sys.argv[2]);net=next(n for n in b.GetNetsByNetcode().values() if n.GetNetname()=='SIGNAL_A')
fs=list(b.GetFootprints());fs.sort(key=lambda f:f.GetReference())
# Use three existing pads on one net, keep layout identical across both outputs.
for f in fs:
 for p in f.Pads():p.SetNet(net)
pads=[p for f in fs for p in f.Pads()]
for variant,indices in [('source',(0,1)),('candidate',(1,2))]:
 for tr in list(b.GetTracks()):b.Remove(tr)
 t=k.PCB_TRACK(b);t.SetStart(pads[indices[0]].GetPosition());t.SetEnd(pads[indices[1]].GetPosition());t.SetLayer(k.F_Cu);t.SetWidth(k.FromMM(.3));t.SetNet(net);b.Add(t)
 k.SaveBoard(str(root/(variant+'.kicad_pcb')),b)
''')
subprocess.run([native_tools()['kicad_python'],str(script),str(root),str(example)],check=True,capture_output=True,text=True)
for name in ('source','candidate'):shutil.copy2(example.with_suffix('.kicad_pro'),root/(name+'.kicad_pro'))
source=root/'source.kicad_pcb';candidate=root/'candidate.kicad_pcb';snap=A.native_snapshot(source)
ids=[int(k) for k,v in snap['net_names'].items() if int(k) and v]
task={'board_sha256':A.sha(source),'rule_hashes':A.rules(source),'allowed_nets':ids,'target_net_names':[snap['net_names'][n] for n in ids]}
r=A.audit(source,candidate,task,root/'connection-audit')
assert r['initial_unconnected']==r['final_unconnected'],r
assert r['per_net_connectivity_nonregression'] and not r['geometry']['original_pad_connections_preserved'] and not r['safe'],r
checks.append('native_same_count_connection_swap_rejected')
# Rule-file tampering cannot pass even when geometry is identical.
source=accepted/'review/board.kicad_pcb';copy=root/'tampered/board.kicad_pcb';A.copy_board(source,copy)
pro=load(copy.with_suffix('.kicad_pro'));pro['board']['design_settings']['rules']['min_clearance']=0.01;save(copy.with_suffix('.kicad_pro'),pro)
snap=A.native_snapshot(source);ids=[int(k) for k,v in snap['net_names'].items() if int(k) and v]
task={'board_sha256':A.sha(source),'rule_hashes':A.rules(source),'allowed_nets':ids,'target_net_names':[snap['net_names'][n] for n in ids]}
r=A.audit(source,copy,task,root/'rule-audit');assert not r['safe'] and not r['rules_unchanged'],r;checks.append('native_rule_relaxation_rejected')
save(root/'summary.json',{'passed':True,'checks':checks,'model_api_calls':0})
print(json.dumps({'passed':True,'checks':checks}))
