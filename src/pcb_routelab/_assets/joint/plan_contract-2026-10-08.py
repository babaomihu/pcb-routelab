"""Strict finite action contract shared by model and mechanism controls."""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def validate(plan, observation):
    if set(plan) != {'version', 'observation_sha256', 'order', 'assignments'}:
        raise ValueError('Unexpected plan fields')
    if plan['version'] != 1 or plan['observation_sha256'] != digest(observation):
        raise ValueError('Stale observation or unsupported version')
    ids = [str(n['id']) for n in observation['nets']]
    if not isinstance(plan['order'], list) or any(type(n) is not str for n in plan['order']):
        raise ValueError('Order must contain string net IDs')
    if len(plan['order']) != len(ids) or set(plan['order']) != set(ids):
        raise ValueError('Order must be a full permutation')
    front = set(observation['front_ids'])
    if set(plan['order'][:len(front)]) != front:
        raise ValueError('Native direct-first partition must be preserved')
    if not isinstance(plan['assignments'], dict) or set(plan['assignments']) != set(ids):
        raise ValueError('Every planned net needs an assignment')
    by_id = {str(n['id']): n for n in observation['nets']}
    for net, assignment in plan['assignments'].items():
        if not isinstance(assignment, dict) or set(assignment) != {'layer', 'corridor'}:
            raise ValueError('Unexpected assignment fields')
        layer = assignment['layer']
        if layer is not None and (type(layer) is not int or layer not in observation['allowed_layer_indices']):
            raise ValueError('Unknown or forbidden layer')
        corridor = assignment['corridor']
        if type(corridor) is not str or corridor not in ['none', *by_id[net]['corridors']]:
            raise ValueError('Unknown corridor')
    return plan


def observation_from_dumps(reference_hash, dumps, source_hashes):
    base = dumps['default']
    ids = {i for _, i in base['nets_input']}
    for name, dump in dumps.items():
        if set(i for _,i in dump['nets_input']) != ids:
            raise ValueError('Probe net universes differ')
        for key in ('grid_step', 'layers', 'track_width', 'clearance', 'via_size'):
            if dump['config'][key] != base['config'][key]:
                raise ValueError('Probe geometry differs: '+key)
    nets = []
    for name, nid in base['nets_input']:
        candidates = {key: dump['rough_paths'][str(nid)] for key, dump in dumps.items()
                      if str(nid) in dump['rough_paths']}
        nets.append({'id': str(nid), 'name': name, 'corridors': candidates})
    return {'version': 1, 'reference_sha256': reference_hash, 'probe_hashes': source_hashes,
            'config': base['config'], 'allowed_layer_indices': [i for i,c in enumerate(base['config']['layer_costs']) if c>=0],
            'nets': nets, 'front_ids': [str(i) for i in base['front_ids']],
            'native_order': [str(i) for _,i in base['order_used']],
            'native_layer_pref': base['layer_pref'], 'share_w': base['share_w'],
            'conflict_w': base['conflict_w'],
            'limitations': ['Rough probes exclude future copper; paths are proposals, not feasibility certificates.',
                'Multipoint nets may be represented by only a principal connection.',
                'Native direct-first routes and internal repair passes remain engine-controlled.',
                'Layer and corridor choices are soft preferences; legal detail routing may deviate.']}
