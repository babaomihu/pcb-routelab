from release_runtime import WORK, CODE, ENGINE, ENGINE_PYTHON, KICAD_PYTHON, KICAD_CLI
"""Anthropic wire-protocol relay; journals every send, never retries or invents tool calls."""
import os,fcntl,hashlib,json,threading,time,urllib.request,urllib.error
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from model_gateway_v2 import ROOT,store,NoRedirect

class LoopGateway:
 def __init__(self,scope,cap):
  self.scope,self.cap=scope,cap;self.denials=[]
  self.policy=json.loads((ROOT/'configs/model_v20.json').read_text())
  self.ledger=ROOT/'runs/v20/api_ledger';self.ledger.mkdir(parents=True,exist_ok=True)
  self.gate=ROOT/'runs/v20/harness'/scope/'response_gate.json';gateway=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    if self.path.split('?')[0] not in ['/v1/messages','/messages']:self.send_error(404);return
    gateway.forward(self,json.loads(self.rfile.read(int(self.headers['Content-Length']))))
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
  self.url=f'http://127.0.0.1:{self.server.server_port}'
 def start(self):self.thread.start()
 def close(self):self.server.shutdown();self.server.server_close();self.thread.join()
 def reserve(self,body):
  size=len(json.dumps(body).encode())
  with (self.ledger/'budget.lock').open('a+') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   folders=list(self.ledger.glob('*/reservation.json'))
   used=sum(json.loads(p.read_text())['scope']==self.scope for p in folders)
   clock=json.loads((self.gate.parent/'session_clock.json').read_text())
   reason=None
   if size>180000:reason='context_byte_cap'
   if time.time()-clock['started_at']>=1800:reason='session_wall_cap'
   if used>=self.cap or len(folders)>=self.policy['total_model_request_cap']:reason='request_cap'
   if reason:
    self.denials.append({'reason':reason,'time':time.time(),'exact_bytes':size});store(self.gate.parent/'gateway_denials.json',self.denials);raise RuntimeError(reason)
   folder=self.ledger/f'request_{len(folders)+1:04d}';folder.mkdir()
   store(folder/'request.json',body)
   store(folder/'reservation.json',{'scope':self.scope,'reserved_at':time.time(),'body_sha256':hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest(),'status':'reserved_no_automatic_retry','max_output_tokens':body['max_tokens'],'exact_upstream_bytes':size,'protocol':'anthropic-messages'})
   with (self.gate.parent/'response_gate.lock').open('a+') as gl:
    fcntl.flock(gl,fcntl.LOCK_EX);store(self.gate,{'response_number':used+1,'write_used':False})
   return folder
 def forward(self,h,body):
  ep=ROOT/'runs/v20/episodes'/self.scope
  if (ep/'state.json').exists() and json.loads((ep/'state.json').read_text()).get('status')=='finished':return self.host_terminal(h)
  if os.environ.get('PCB_ROUTELAB_ENABLE_MODEL')!='1' or os.environ.get('PCB_ROUTELAB_OFFLINE')=='1':
   raise RuntimeError('External model requests disabled')
  from pcb_routelab.model_config import provider
  conf=provider()
  body['model']=conf['model'];body['max_tokens']=min(body.get('max_tokens',4096),4096);body['stream']=True
  from context_v20 import compact_request
  state=json.loads((ep/'state.json').read_text()) if (ep/'state.json').exists() else None
  body,review=compact_request(body,self.gate.parent/'context_payloads',state)
  with (self.gate.parent/'context_log.jsonl').open('a') as log:log.write(json.dumps(review)+'\n')
  try:folder=self.reserve(body)
  except Exception as e:h.send_error(429,str(e));return
  start=time.monotonic();sent=False;meta={'scope':self.scope,'status':'inflight','usage':None};usage={};blocks={};functions=[]
  try:
   base=conf['base_url'].rstrip('/');url=base+('/messages' if base.endswith('/v1') else '/v1/messages')
   req=urllib.request.Request(url,data=json.dumps(body).encode(),headers={'x-api-key':conf['api_key'],'anthropic-version':'2023-06-01','Content-Type':'application/json'})
   with urllib.request.build_opener(NoRedirect).open(req,timeout=90) as response:
    h.send_response(200);h.send_header('Content-Type','text/event-stream');h.end_headers();sent=True
    with (folder/'stream.sse').open('wb') as log:
     while True:
      line=response.readline()
      if not line:break
      log.write(line);log.flush();h.wfile.write(line);h.wfile.flush()
      if line.startswith(b'data: '):
       try:e=json.loads(line[6:])
       except ValueError:continue
       typ=e.get('type')
       if typ=='message_start':
        m=e['message'];meta['returned_model']=m.get('model');usage.update(m.get('usage',{}))
       elif typ=='content_block_start':blocks[e['index']]={'block':e['content_block'],'json':''}
       elif typ=='content_block_delta' and e['delta'].get('type')=='input_json_delta':blocks[e['index']]['json']+=e['delta']['partial_json']
       elif typ=='content_block_stop':
        b=blocks.get(e['index'],{});item=b.get('block',{})
        if item.get('type')=='tool_use':
         args=json.loads(b['json']) if b['json'] else item.get('input',{})
         functions.append({'name':item['name'].removeprefix('mcp__routing__'),'arguments':args,'id':item['id']})
       elif typ=='message_delta':usage.update(e.get('usage',{}));meta['stop_reason']=e.get('delta',{}).get('stop_reason')
       elif typ=='message_stop':
        meta['status']='completed';meta['usage']=usage;break
       elif typ=='error':store(folder/'stream_error.json',e);meta['status']='provider_stream_error'
      if time.monotonic()-start>150:raise TimeoutError('Relay request wall limit')
   if meta['status']=='inflight':meta['status']='incomplete_stream'
  except Exception as e:
   meta.update(status='api_error',error_type=type(e).__name__)
   if isinstance(e,urllib.error.HTTPError):
    meta['http_status']=e.code;store(folder/'error.json',{'body':e.read(4000).decode(errors='replace').replace(conf['api_key'],'[REDACTED]')})
   if not sent:h.send_error(502,'Upstream failure; counted, no retry')
  finally:
   meta['seconds']=time.monotonic()-start;meta['partial_usage']=usage if meta['usage'] is None else None
   store(folder/'functions.json',functions);store(folder/'result.json',meta);h.close_connection=True
 def host_terminal(self,h):
  message='HOST_TERMINAL: model finish tool committed delivery; deterministic host confirmation, not model reasoning.'
  store(self.gate.parent/'host_terminal.json',{'origin':'host','real_model':False,'upstream_requests':0,'confirmation':message})
  events=[{'type':'message_start','message':{'id':'msg_host_terminal','type':'message','role':'assistant','model':'pcb-model','content':[],'stop_reason':None,'stop_sequence':None,'usage':{'input_tokens':0,'output_tokens':0}}},
   {'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}},
   {'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':message}},
   {'type':'content_block_stop','index':0},
   {'type':'message_delta','delta':{'stop_reason':'end_turn','stop_sequence':None},'usage':{'output_tokens':0}},
   {'type':'message_stop'}]
  h.send_response(200);h.send_header('Content-Type','text/event-stream');h.end_headers()
  for e in events:h.wfile.write(('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n').encode());h.wfile.flush()
  h.close_connection=True
