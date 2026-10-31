from release_runtime import WORK, CODE, ENGINE, ENGINE_PYTHON, KICAD_PYTHON, KICAD_CLI
"""Lossless local archives with explicitly lossy bounded views, shared by both arms.
No model calls, routing decisions, or state mutations occur in this module.
"""
import copy, hashlib, json, re
from pathlib import Path

TARGET_BYTES = 100000
HARD_BYTES = 180000

def encoded(value):
    return json.dumps(value, ensure_ascii=True).encode()

def archive(directory, value):
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True)
    digest=hashlib.sha256(raw.encode()).hexdigest()
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    path=directory/(digest+'.json')
    if not path.exists(): path.write_text(raw)
    return digest

def read_payload(directory, payload_id, offset=0):
    if not re.fullmatch('[0-9a-f]{64}',payload_id): raise ValueError('Invalid payload ID')
    if type(offset) is not int or offset<0: raise ValueError('Invalid offset')
    raw=(Path(directory)/(payload_id+'.json')).read_text()
    if hashlib.sha256(raw.encode()).hexdigest()!=payload_id: raise ValueError('Archive integrity failure')
    return {'payload_id':payload_id,'offset':offset,'text':raw[offset:offset+2000],
            'total_characters':len(raw),'next_offset':offset+2000 if offset+2000<len(raw) else None,
            'semantics':'Exact JSON text in Unicode character pages. Concatenate pages to recover full evidence.'}

def preview(value, depth=0):
    if isinstance(value,str): return value if len(value)<=900 else value[:900]+' [TRUNCATED; query archive]'
    if isinstance(value,list):
        return [preview(v,depth+1) for v in value[:6]]+([{'omitted_items':len(value)-6}] if len(value)>6 else [])
    if isinstance(value,dict):
        if depth>7: return {'omitted_nested_object':True}
        return {k:preview(v,depth+1) for k,v in value.items()}
    return value

def bounded_result(value,directory,limit=32000):
    if len(encoded(value))<=limit: return value
    ref=archive(directory,value); p=preview(value)
    core={k:value[k] for k in ['state_token','current_snapshot','run_id','safe','task_success','status','accepted','snapshot','next_offset','offset','total_items'] if isinstance(value,dict) and k in value}
    if isinstance(value,dict) and isinstance(value.get('check'),dict):
        core['check']={k:value['check'].get(k) for k in ['status','safe','task_success','final_unconnected','new_error_count','new_error_types','error']}
    return {**core,'compacted':True,'full_payload_id':ref,'query':'inspect_payload(payload_id, offset=0); page to recover exact complete original',
            'preview':p if len(encoded(p))<6500 else json.dumps(p,ensure_ascii=False)[:3000]+' [TRUNCATED PREVIEW]'}

def compact_observation(full,directory):
    o=copy.deepcopy(full); ref=archive(directory,full)
    pads=o.pop('pads',[])
    o['pads_access']={'count':len(pads),'tool':'inspect_pads(nets=[], bbox=[], offset=0); filters are optional, page size30','full_observation_payload_id':ref}
    # Native constraints stay in overview. Raw geometry is paged, not duplicated.
    for name in ['history','outline','available_snapshots','decision_support']:
        if name in o and len(encoded(o[name]))>7000:
            o[name]=bounded_result(o[name],directory,7000)
    return o

def capsule(state,directory):
    selected=state['candidates'][state['current']]['check']
    facts={k:state.get(k) for k in ['state_token','current','status','runs_used','engine_seconds','board_plan','active_intervention','quality_reference']}
    facts['current_check']={k:selected.get(k) for k in ['safe','task_success','final_unconnected','remaining_by_net_name','final_geometry']}
    facts['safe_candidates']={k:{x:v['check'].get(x) for x in ['safe','task_success','final_unconnected']} for k,v in state['candidates'].items()}
    # Retain every executed action, without large raw errors or transcripts.
    facts['action_outcomes']=[{k:h.get(k) for k in ['id','from','nets','options','guidance','error']}|{'check':{k:(h.get('check')or{}).get(k) for k in ['safe','task_success','final_unconnected']}} for h in state['history'] if h.get('id')]
    facts['origin']='Host exact state facts; plans/interventions were authored by model. No generated strategy.'
    return facts

def compact_request(body,directory,state=None):
    """Compact tool results, then evict oldest complete assistant/user rounds.
    First user instructions and most recent assistant/result pair always remain.
    No protocol blocks are spliced or reassigned to different tool IDs.
    """
    original=copy.deepcopy(body); result=copy.deepcopy(body)
    rawref=archive(directory,original)
    messages=result['messages']; changed=0
    for message in messages:
        content=message.get('content',[])
        if not isinstance(content,list): continue
        for block in content:
            if block.get('type')!='tool_result': continue
            payload=block.get('content',[])
            if len(encoded(payload))<=33000: continue
            ref=archive(directory,payload)
            # Decode single JSON text result to keep state/acceptance available.
            text=payload if isinstance(payload,str) else payload[0].get('text','') if len(payload)==1 else ''
            try: val=json.loads(text)
            except (ValueError,TypeError): val={'raw_result_preview':str(text)[:3000]}
            summary=bounded_result(val,directory,0)
            summary['original_tool_content_payload_id']=ref
            block['content']=[{'type':'text','text':json.dumps(summary,ensure_ascii=False)}]; changed+=1
    removed=[]
    while len(encoded(result))>TARGET_BYTES and len(messages)>=5:
        # Anthropic transcripts are initial user, assistant, user(tool_results), ...
        if messages[1]['role']!='assistant' or messages[2]['role']!='user': break
        removed.extend(messages[1:3]);del messages[1:3]
    if removed:
        oldref=archive(directory,removed)
        text='CONTEXT_ARCHIVE_NOTICE: Older complete rounds were archived, not forgotten permanently. Query inspect_payload for exact messages. '+json.dumps({'archive_payload_id':oldref,'removed_messages':len(removed),'current_state':capsule(state,directory) if state else None},ensure_ascii=False)
        # Add text AFTER tool_result blocks; preserve required adjacency.
        content=messages[-1]['content']
        if isinstance(content,str): messages[-1]['content']=[{'type':'text','text':content},{'type':'text','text':text}]
        else: content.append({'type':'text','text':text})
    return result,{'original_bytes':len(encoded(original)),'upstream_bytes':len(encoded(result)),'original_request_payload_id':rawref,'compacted_tool_results':changed,'archived_messages':len(removed),'hard_limit':HARD_BYTES,'target_bytes':TARGET_BYTES}
