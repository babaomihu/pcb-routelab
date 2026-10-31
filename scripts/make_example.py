"""Generate the original CC0 mechanism fixture using KiCad's bundled Python."""
import json
from pathlib import Path
import sys
import pcbnew as k
import wx
app=wx.App(False)

out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
b=k.BOARD()
for n,y in [('SIGNAL_A',20),('SIGNAL_B',30)]:
    net=k.NETINFO_ITEM(b,n);b.Add(net)
    for i,x in enumerate([20,40]):
        f=k.FOOTPRINT(b);f.SetReference(n+str(i+1));f.SetValue('RouteLab fixture')
        f.SetPosition(k.VECTOR2I(k.FromMM(x),k.FromMM(y)))
        p=k.PAD(f);p.SetNumber('1');p.SetAttribute(k.PAD_ATTRIB_SMD);p.SetShape(k.PAD_SHAPE_RECT)
        p.SetSize(k.VECTOR2I(k.FromMM(1.6),k.FromMM(1.6)));layers=k.LSET();layers.AddLayer(k.F_Cu);p.SetLayerSet(layers)
        p.SetPosition(f.GetPosition());p.SetNet(net);f.Add(p);b.Add(f)
for a,c in [((10,10),(50,10)),((50,10),(50,40)),((50,40),(10,40)),((10,40),(10,10))]:
    s=k.PCB_SHAPE();s.SetShape(k.SHAPE_T_SEGMENT);s.SetLayer(k.Edge_Cuts);s.SetWidth(k.FromMM(.05))
    s.SetStart(k.VECTOR2I(*(k.FromMM(v) for v in a)));s.SetEnd(k.VECTOR2I(*(k.FromMM(v) for v in c)));b.Add(s)
k.SaveBoard(str(out/'two-nets.kicad_pcb'),b)
pro={'meta':{'version':1},'board':{'design_settings':{'rules':{'min_clearance':0.2,'min_track_width':0.2,'min_via_diameter':0.6,'min_through_hole_diameter':0.3,'min_via_annular_width':0.15,'min_copper_edge_clearance':0.25,'min_hole_to_hole':0.25,'min_hole_clearance':0.25}}},
     'net_settings':{'classes':[{'name':'Default','clearance':0.2,'track_width':0.3,'via_diameter':0.6,'via_drill':0.3,'microvia_diameter':0.3,'microvia_drill':0.1,'diff_pair_width':0.3,'diff_pair_gap':0.25,'diff_pair_via_gap':0.25}],'netclass_assignments':{},'netclass_patterns':[]}}
(out/'two-nets.kicad_pro').write_text(json.dumps(pro,indent=2)+'\n')
