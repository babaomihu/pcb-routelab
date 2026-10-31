"""Provider transport is replaced with an in-memory object; no socket or API calls."""
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from pcb_routelab.runtime import configure,save,load

class ModelOfflineTests(unittest.TestCase):
    def test_terminal_event_does_not_wait_for_eof(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);configure(root)
            import loop_gateway_v20 as m
            g=m.LoopGateway.__new__(m.LoopGateway);g.scope='fixture';g.gate=root/'session/response_gate.json';g.gate.parent.mkdir();g.denials=[]
            folder=root/'request';folder.mkdir();g.reserve=lambda body:folder
            class Response:
                calls=0
                def __enter__(self):return self
                def __exit__(self,*a):pass
                def readline(self):
                    self.calls+=1
                    if self.calls>1:raise TimeoutError('Transport kept open after terminal event')
                    return b'data: {"type":"message_stop"}\n'
            class Handler:
                wfile=io.BytesIO()
                def send_response(self,*a):pass
                def send_header(self,*a):pass
                def end_headers(self):pass
                def send_error(self,*a):raise AssertionError(a)
            response=Response()
            with patch.object(m,'ROOT',root),patch.dict(os.environ,{'PCB_ROUTELAB_ENABLE_MODEL':'1','PCB_ROUTELAB_OFFLINE':'0'}),\
                 patch('pcb_routelab.model_config.provider',return_value={'base_url':'https://example.invalid','api_key':'test-only-placeholder','model':'fixture'}),\
                 patch('urllib.request.build_opener') as opener:
                opener.return_value.open.return_value=response
                g.forward(Handler(),{'messages':[],'max_tokens':32})
            self.assertEqual(response.calls,1)
            self.assertEqual(load(folder/'result.json')['status'],'completed')

    def test_request_budget_reserved_before_send(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);configure(root)
            import loop_gateway_v20 as m
            g=m.LoopGateway.__new__(m.LoopGateway);g.scope='fixture';g.cap=1;g.denials=[]
            g.policy={'total_model_request_cap':1};g.ledger=root/'ledger';g.ledger.mkdir()
            g.gate=root/'session/response_gate.json';save(g.gate.parent/'session_clock.json',{'started_at':time.time()})
            first=g.reserve({'max_tokens':32});self.assertTrue((first/'reservation.json').is_file())
            with self.assertRaises(RuntimeError):g.reserve({'max_tokens':32})
            self.assertEqual(len(list(g.ledger.glob('*/reservation.json'))),1)
