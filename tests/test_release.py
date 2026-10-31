import copy
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pcb_routelab.runtime import assets, configure, load, save, module
from pcb_routelab.model_config import provider
from pcb_routelab.cli import main

TEMP=tempfile.TemporaryDirectory()
configure(Path(TEMP.name))
import audit_board_v6 as audit
from session_core_v20 import command
from context_v20 import archive,read_payload
P=module('test_policy',assets()/'congestion/policy-contract-2026-10-09.py')
J=module('test_joint',assets()/'joint/plan_contract-2026-10-08.py')


class ReleaseTests(unittest.TestCase):
    def test_model_denied_before_http(self):
        with patch.dict(os.environ,{'PCB_ROUTELAB_OFFLINE':'1','PCB_ROUTELAB_ENABLE_MODEL':'1'},clear=False),patch('urllib.request.OpenerDirector.open') as network:
            with self.assertRaises(RuntimeError):provider()
            network.assert_not_called()

    def test_provider_validated_without_sending(self):
        env={'PCB_ROUTELAB_OFFLINE':'0','PCB_ROUTELAB_ENABLE_MODEL':'1','PCB_ROUTELAB_API_KEY':'test-only-placeholder',
             'PCB_ROUTELAB_BASE_URL':'https://example.invalid','PCB_ROUTELAB_MODEL':'fixture'}
        with patch.dict(os.environ,env),patch('urllib.request.OpenerDirector.open') as network:
            self.assertEqual(provider()['model'],'fixture')
            for u in ['http://example.invalid','https://user:pass@example.invalid','https://example.invalid/?key=x']:
                os.environ['PCB_ROUTELAB_BASE_URL']=u
                with self.assertRaises(ValueError):provider()
            network.assert_not_called()

    def test_model_cli_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'b.kicad_pcb').write_text('(kicad_pcb)');(p/'b.kicad_pro').write_text('{}')
            argv=['pcb-routelab','run','--board',str(p/'b.kicad_pcb'),'--output',str(p/'out'),'--mode','harness']
            with patch('sys.argv',argv),patch.dict(os.environ,{'PCB_ROUTELAB_OFFLINE':'1'}),patch('subprocess.Popen') as spawn:
                self.assertEqual(main(),2);spawn.assert_not_called();self.assertFalse((p/'out').exists())

    def test_net_globs_escaped(self):
        argv=command(Path('a'),Path('b'),['N[*]?'],[],{})
        self.assertIn('N[[][*]][?]',argv)

    def test_cannot_override_rules(self):
        for opts in [{'clearance':.01},{'grid_step':float('nan')},{'max_ripup':True}]:
            with self.assertRaises(ValueError):command(Path('a'),Path('b'),[],[],opts)

    def test_policy_rejects_code(self):
        for expr in ["__import__('os').system('echo bad')",'old.__class__','[x for x in old]','inc if old else 0','open("x")']:
            with self.assertRaises((ValueError,SyntaxError)):P.Policy(expr)

    def test_native_policy_identity(self):
        import numpy as np
        p=P.Policy('inc')
        for event in ('contest','rip','frontier'):
            self.assertTrue(np.all(p.charge(np.array([0.,1.,5.]),.1,event)==.1))

    def test_joint_rejects_stale_and_rule_fields(self):
        obs={'nets':[{'id':'1','corridors':{}}],'front_ids':[],'allowed_layer_indices':[0,1]}
        valid={'version':1,'observation_sha256':J.digest(obs),'order':['1'],'assignments':{'1':{'layer':None,'corridor':'none'}}}
        self.assertEqual(J.validate(valid,obs),valid)
        for change in [{'observation_sha256':'wrong'},{'order':['1','1']},{'clearance':0.01},
                       {'assignments':{'1':{'layer':True,'corridor':'none'}}}]:
            with self.assertRaises(ValueError):J.validate({**valid,**change},obs)

    def test_same_airwire_count_cannot_hide_broken_pair(self):
        snap={'tracks':[],'vias':[],'pads':[],'footprints':[],'layout_text':[],'outline':[],
              'design_rules':{},'net_names':{1:'A'},'zone_count':0,'copper_arc_count':0,'copper_layers':2,
              'locked_copper':[],'pad_components':[['p1','p2'],['p3']]}
        other=copy.deepcopy(snap);other['pad_components']=[['p1'],['p2','p3']]
        self.assertFalse(audit.compare_geometry(snap,other,{'A'})['original_pad_connections_preserved'])

    def test_locked_copper_not_movable(self):
        snap={'tracks':[{'net_name':'A','geometry':'original'}],'vias':[],'pads':[],'footprints':[],'layout_text':[],
              'outline':[],'design_rules':{},'net_names':{1:'A'},'zone_count':0,'copper_arc_count':0,'copper_layers':2,
              'locked_copper':[['track',{'net_name':'A','geometry':'original'}]],'pad_components':[['p1']]}
        other=copy.deepcopy(snap);other['tracks'][0]['geometry']='moved'
        self.assertFalse(audit.compare_geometry(snap,other,{'A'})['locked_copper_preserved'])

    def test_worsened_same_item_drc_is_new(self):
        old={'violations':[{'type':'clearance','severity':'error','description':'actual 0.19','items':[{'uuid':'x','pos':{}}]}]}
        new=copy.deepcopy(old);new['violations'][0]['description']='actual 0.10'
        result=audit.compare_drc(old,new,{'x':['track',1]},{'x':['track',1]})
        self.assertEqual(result['new_error_count'],1)

    def test_lossless_evidence_pagination(self):
        with tempfile.TemporaryDirectory() as d:
            value={'long':'原规则'*3000};ident=archive(d,value);text='';offset=0
            while True:
                page=read_payload(d,ident,offset);text+=page['text'];offset=page['next_offset']
                if offset is None:break
            self.assertEqual(json.loads(text),value)
            Path(d,ident+'.json').write_text('{}')
            with self.assertRaises(ValueError):read_payload(d,ident,0)

    def test_mcp_does_not_advertise_missing_backends(self):
        m=importlib.import_module('pcb_mcp_v20')
        names={t['name'] for t in m.TOOLS}
        self.assertIn('route_guided',names);self.assertIn('commit_result',names)
        self.assertNotIn('edit_copper',names);self.assertNotIn('route_length_target',names)


if __name__=='__main__':unittest.main()
