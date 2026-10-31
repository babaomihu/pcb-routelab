from release_runtime import WORK, CODE, ENGINE, ENGINE_PYTHON, KICAD_PYTHON, KICAD_CLI
"""Input qualification using existing native evidence; no routing or repair policy."""
import collections,json
from pathlib import Path

def check_qualification(directory):
 directory=Path(directory)
 audit=json.loads((directory/'result.json').read_text())
 drc_path=directory/'source/board.cli_drc.json'
 snapshot_path=directory/'source_snapshot.json'
 reasons=[]
 if not audit.get('safe'):reasons.append('unsupported_or_unverifiable_input')
 if not drc_path.exists() or not snapshot_path.exists():
  return {'accepted':False,'reasons':reasons+['missing_native_evidence'],'native_error_counts':{},'source':'KiCad CLI / existing native audit'}
 drc=json.loads(drc_path.read_text());snap=json.loads(snapshot_path.read_text())
 errors=[v for v in drc.get('violations',[]) if v.get('severity')=='error']
 if any(v.get('type')=='invalid_outline' for v in errors):reasons.append('invalid_outline_requires_input_repair')
 if snap.get('copper_layers')!=2:reasons.append('requires_two_copper_layers')
 if snap.get('zone_count') or snap.get('copper_arc_count'):reasons.append('zones_or_copper_arcs_outside_validated_scope')
 return {'accepted':not reasons,'reasons':reasons,'native_error_counts':dict(collections.Counter(v.get('type','unknown') for v in errors)),
         'existing_error_count':len(errors),'original_unconnected':audit.get('initial_unconnected'),
         'source':'Existing KiCad CLI DRC + native snapshot; no custom traditional routing',
         'qualification_evidence':str(directory),'interpretation':'Accepted means supported routing input, not error-free or fabrication-ready. Existing non-outline errors remain visible and immutable.'}
