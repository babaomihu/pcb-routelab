from release_runtime import WORK, CODE, ENGINE, ENGINE_PYTHON, KICAD_PYTHON, KICAD_CLI
"""Restore only unused original net declarations dropped by engine serialization."""
import json
from audit_board_v6 import native_snapshot,sexpr
from geometry_v9 import encode

def preserve_unused_nets(source,candidate):
 before=native_snapshot(source);after=native_snapshot(candidate)
 missing=set(before['net_names'].values())-set(after['net_names'].values())
 used={x['net_name'] for group in ('pads','tracks','vias') for x in before[group]}
 if missing & used:raise ValueError('Engine dropped a used network; cannot restore its declaration as a substitute for connectivity')
 if before['zone_count'] or before['copper_arc_count']:raise ValueError('Unsupported geometry for unused-net preservation')
 tree=sexpr(candidate.read_text());declared=[x for x in tree if isinstance(x,list) and x and x[0]=='net'];nextcode=max([int(x[1]) for x in declared]+[0])+1
 restored=[]
 for name in sorted(missing):
  if not name:raise ValueError('Unnamed net declaration missing')
  tree.append(['net',str(nextcode),json.dumps(name,ensure_ascii=False)]);restored.append({'name':name,'candidate_code':nextcode});nextcode+=1
 if restored:
  candidate.write_text(encode(tree)+'\n');final=native_snapshot(candidate)
  if any(final[k]!=after[k] for k in ('pads','tracks','vias','footprints','outline','design_rules')):raise ValueError('Metadata packaging changed physical board')
  if set(final['net_names'].values())!=set(before['net_names'].values()):raise ValueError('Net declaration preservation failed')
 return restored
