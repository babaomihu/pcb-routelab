"""Conservative global generation floors; independent native DRC remains mandatory.

Net-class widths/via dimensions are preferred dimensions, not blanket DRC minima.
Clearance is an actual constraint: use the maximum effective class clearance.
This may overconstrain heterogeneous classes; report that limitation explicitly.
"""
import math
import re

KEYS=('clearance','track_width','via_diameter','via_drill','hole_to_hole',
      'pad_hole_to_hole','annular','board_edge')

def derive(snapshot, custom_rule_text=''):
    if snapshot['zone_count'] or snapshot['copper_arc_count']:
        raise ValueError('Unsupported zones or copper arcs')
    if re.search(r'\(\s*rule\b',custom_rule_text):
        raise ValueError('Custom rule compilation unsupported; do not silently ignore custom rules')
    r=snapshot['design_rules'];classes=r['effective_netclasses']
    def value(d,k):
        x=d[k]
        if type(x) not in (int,float) or not math.isfinite(x) or x<0:
            raise ValueError('Invalid dimensional rule: '+k)
        return x/1e6
    if not classes:raise ValueError('Missing effective net classes')
    width=value(r,'m_TrackMinWidth');drill=value(r,'m_MinThroughDrill')
    annular=value(r,'m_ViasMinAnnularWidth')
    # Rescue computes min(nominal, class width, fabrication floor). Reject
    # inconsistent classes until that engine path has a verified adapter.
    if any(value(c,'GetTrackWidth')<width for c in classes.values()):
        raise ValueError('Class nominal width below board minimum is unsupported')
    floors={'clearance':max(value(r,'m_MinClearance'),max(value(c,'GetClearance') for c in classes.values())),
        'track_width':width,'via_diameter':max(value(r,'m_ViasMinSize'),drill+2*annular),
        'via_drill':drill,'hole_to_hole':value(r,'m_HoleToHoleMin'),
        'pad_hole_to_hole':value(r,'m_HoleToHoleMin'),'annular':annular,
        'board_edge':value(r,'m_CopperEdgeClearance')}
    # Parser rejects zero overrides. A positive 1nm floor is conservative for
    # unconfigured zero minima; explicitly retain this deviation in metadata.
    zero_keys=[k for k,v in floors.items() if v==0]
    floors={k:max(v,.000001) for k,v in floors.items()}
    return {'version':'0.3-contract1','floors_mm':floors,'zero_floor_replacements_1nm':zero_keys,
        'hole_to_copper_mm':value(r,'m_HoleClearance'),
        'requires_independent_native_audit':True,
        'scope':'Global conservative class clearance; board dimension minima; no custom rules/zones/copper arcs.',
        'clearance_policy':'max(board_minimum, all_effective_class_clearances)'}

def write_overrides(path,contract):
    floors=contract['floors_mm']
    if set(floors)!=set(KEYS):raise ValueError('Incomplete floor contract')
    path.write_text('# Generated original-rule constraints, mm; never edits design rules.\n'+
        ''.join(f'{k} = {floors[k]:.9f}\n' for k in KEYS))
