from release_runtime import WORK, CODE, ENGINE, ENGINE_PYTHON, KICAD_PYTHON, KICAD_CLI
"""Local Responses API relay with pre-send durable caps; never stores credentials."""
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import urllib.request
import urllib.error

ROOT=WORK


def store(p,data):
    with Path(p).open('w') as f:
        json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class Gateway:
    def __init__(self,scope,cap,fixed=False):
        self.scope,self.cap,self.fixed=scope,cap,fixed
        self.policy=json.loads((ROOT/'configs/run_policy.json').read_text())
        self.ledger=ROOT/'runs/api_ledger';self.ledger.mkdir(exist_ok=True)
        self.local_requests=0
        gateway=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                if self.path!='/v1/responses':
                    self.send_error(404);return
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if gateway.fixed:
                    gateway.fixed_response(self,body);return
                gateway.forward(self,body)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.url=f'http://127.0.0.1:{self.server.server_port}/v1'

    def start(self):self.thread.start()
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join()

    def reserve(self,body):
        if not self.policy['real_api_enabled']:raise RuntimeError('Real API disabled')
        with (self.ledger/'budget.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            previous=sorted(self.ledger.glob('request_*/reservation.json'))
            scopes=[json.loads(p.read_text())['scope'] for p in previous]
            if len(previous)>=self.policy['total_model_request_cap']:raise RuntimeError('Total model request cap exhausted')
            if scopes.count(self.scope)>=self.cap:raise RuntimeError('Task model request cap exhausted')
            folder=self.ledger/f'request_{len(previous)+1:03}';folder.mkdir(exist_ok=False)
            store(folder/'request.json',body)
            store(folder/'reservation.json',{'scope':self.scope,'reserved_at':time.time(),
                  'body_sha256':hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest(),
                  'status':'reserved_no_automatic_retry','max_output_tokens':body['max_output_tokens']})
            return folder

    def forward(self,h,body):
        conf=json.loads(Path(self.policy['provider_config_reference']).read_text())
        body['model']=conf['model'];body['store']=False;body['stream']=True
        body['max_output_tokens']=min(body.get('max_output_tokens',4096),self.policy['max_output_tokens_per_request'])
        body['reasoning']={'effort':'low'}
        try:folder=self.reserve(body)
        except Exception as e:
            h.send_error(429,str(e));return
        started=time.monotonic();meta={'scope':self.scope,'status':'inflight','usage':None}
        sent=False
        try:
            request=urllib.request.Request(conf['base_url'].rstrip('/')+'/responses',data=json.dumps(body).encode(),
                         headers={'Authorization':'Bearer '+conf['api_key'],'Content-Type':'application/json'})
            with urllib.request.build_opener(NoRedirect).open(request,timeout=90) as response:
                h.send_response(200);h.send_header('Content-Type','text/event-stream');h.end_headers();sent=True
                with (folder/'stream.sse').open('wb') as log:
                    while True:
                        line=response.readline()
                        if not line:break
                        log.write(line);log.flush()
                        h.wfile.write(line);h.wfile.flush()
                        if line.startswith(b'data: '):
                            try:event=json.loads(line[6:])
                            except ValueError:continue
                            if event.get('type') in ('response.completed','response.failed','response.incomplete'):
                                result=event['response'];store(folder/'response.json',result)
                                meta.update(status=result.get('status',event['type']),usage=result.get('usage'),returned_model=result.get('model'))
                        if time.monotonic()-started>150:raise TimeoutError('Relay request wall limit')
            if meta['status']=='inflight':meta['status']='incomplete_stream'
        except Exception as e:
            meta.update(status='api_error',error_type=type(e).__name__)
            if isinstance(e,urllib.error.HTTPError):
                meta['http_status']=e.code
                # Response body can aid protocol diagnosis; authentication headers never logged.
                text=e.read(6000).decode(errors='replace').replace(conf['api_key'],'[REDACTED]')
                store(folder/'error.json',{'body':text})
            if not sent:h.send_error(502,'Upstream failure; request counted, no retry')
        finally:
            meta['seconds']=time.monotonic()-started;store(folder/'result.json',meta)
            h.close_connection=True

    def fixed_response(self,h,body):
        self.local_requests+=1
        folder=ROOT/'runs/harness_fixed'/self.scope;folder.mkdir(parents=True,exist_ok=False) if self.local_requests==1 else None
        store(folder/f'request_{self.local_requests}.json',body)
        h.send_response(200);h.send_header('Content-Type','text/event-stream');h.end_headers()
        task=json.loads((ROOT/'data/tasks_v2/h2_1_1.json').read_text())
        tools=body.get('tools',[])
        name=next((x['name'] for x in tools if x.get('name','').endswith('attempt_candidates')),None)
        if self.local_requests==1 and name:
            item={'type':'function_call','id':'fc_local1','call_id':'call_local1','name':name,'arguments':'','status':'in_progress'}
            arguments=json.dumps({'candidate_ids':['c00','c01','c02'],'expected_state':task['board_sha256']})
            events=[{'type':'response.output_item.added','output_index':0,'item':item.copy()},
                    {'type':'response.function_call_arguments.delta','output_index':0,'item_id':'fc_local1','delta':arguments}]
            item.update(arguments=arguments,status='completed')
            events += [{'type':'response.function_call_arguments.done','output_index':0,'item_id':'fc_local1','arguments':arguments},
                       {'type':'response.output_item.done','output_index':0,'item':item.copy()}]
        else:
            item={'type':'message','id':'msg_local1','role':'assistant','status':'completed','content':[{'type':'output_text','text':'Fixed-response integration finished.','annotations':[]}]}
            events=[{'type':'response.output_item.added','output_index':0,'item':dict(item,content=[])},
                    {'type':'response.content_part.added','output_index':0,'content_index':0,'item_id':'msg_local1','part':{'type':'output_text','text':'','annotations':[]}},
                    {'type':'response.output_text.delta','output_index':0,'content_index':0,'item_id':'msg_local1','delta':'Fixed-response integration finished.'},
                    {'type':'response.output_item.done','output_index':0,'item':item}]
        response={'id':f'resp_fixed{self.local_requests}','object':'response','created_at':int(time.time()),'model':'pcb-model','status':'completed','output':[item],
                  'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2}}
        events=[{'type':'response.created','response':dict(response,status='in_progress',output=[])}]+events+[{'type':'response.completed','response':response}]
        for i,event in enumerate(events):
            event['sequence_number']=i
            h.wfile.write(('event: '+event['type']+'\ndata: '+json.dumps(event)+'\n\n').encode());h.wfile.flush()
        h.close_connection=True
