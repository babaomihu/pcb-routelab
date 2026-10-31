import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pcb_routelab.runtime import module
ROOT=Path(__file__).resolve().parents[1]

class ResearchTests(unittest.TestCase):
    def test_planners_import(self):
        m=module('budget_planner',ROOT/'research/planner_v04.py')
        self.assertEqual(m.MODES,('fixed','round_robin','cost','full'))
        self.assertTrue(callable(m.proposals))

    def test_generator_and_provider_gate(self):
        m=module('research_generator',ROOT/'research/formal-generators-2026-10-10.py')
        with tempfile.TemporaryDirectory() as d:
            for method in ('numeric','program'):
                self.assertEqual(m.propose(method,101,0,[],Path(d))['expression'],'inc')
                with self.assertRaises(ValueError):m.propose(method,101,2,[],Path(d))
                history=[{'index':0,'executed_expression':'inc','summary':{'objective':[-1,0,1,1]},'parameters':{'a':1,'b':1,'c':1,'e':0}}]
                candidate=m.propose(method,101,2,history,Path(d))
                m.F.classify(candidate['expression'])
            a=module('research_model_gate',ROOT/'research/model-policy-r2-2026-10-11.py')
            with patch.dict(os.environ,{'PCB_ROUTELAB_OFFLINE':'1'}),patch('urllib.request.OpenerDirector.open') as network:
                with self.assertRaises(RuntimeError):a.call(Path(d)/'never-created',{},'generic-evolution')
                network.assert_not_called();self.assertFalse((Path(d)/'never-created').exists())

    def test_optional_sdk_signature(self):
        try:from deepseek_harness import DeepSeekHarness
        except ImportError:self.skipTest('Optional SDK not installed; core installation is supported')
        with patch.dict(os.environ,{'PCB_ROUTELAB_OFFLINE':'1'}):
            obj=DeepSeekHarness(profile='sdk-minimal',provider='pcb',model='pcb-model',max_tokens=4096,
                               initialize_timeout_seconds=60,request_timeout_seconds=60,shutdown_timeout_seconds=5)
            self.assertTrue(callable(obj.start))
            # Deliberately do not start/run a model session.
