"""Target-budget scheduling over the unchanged v0.3 local action space.

Cross-state target statistics are scheduling hints only. Foreign-net permission
is still generated exclusively from matching geometry/target observations.
"""
import sys
from copy import deepcopy
from pathlib import Path
import itertools

WORK = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory_planner import Planner as PreviousPlanner, action_key, atomic_dump, geometry_signature

MODES = ('fixed', 'round_robin', 'cost', 'full')


def proposals(state, attempts):
    """All untried candidates, same ordering within each target as old full."""
    history = [h for h in attempts if h['input']['geometry'] == state['geometry']]
    tried = {action_key(h['action']) for h in history}
    result = {}
    for target in sorted(state['remaining'], key=lambda n: (state['remaining'][n], n)):
        if state['remaining'][target] <= 0:
            continue
        hs = [h for h in history if h['action']['target'] == target]
        base = {'target': target, 'rip': [], 'force': False, 'options': {}}
        ps = [('continue', base, 'target_only', [])]
        evidence = {}
        for h in hs:
            for n in set(h['feedback'].get('reported_blockers', [])):
                if n != target and n in state['net_cost']:
                    evidence.setdefault(n, []).append(h['id'])
        ranked = sorted(evidence, key=lambda n: (-len(evidence[n]), state['net_cost'][n]['length_mm'], state['net_cost'][n]['vias'], n))[:5]
        singles = [[n] for n in ranked]
        combos = [list(c) for k in (2, 3) for c in itertools.combinations(ranked, k)]
        singleton_attempts = sum(bool(h['action']['rip']) and len(h['action']['rip']) == 1 for h in hs)
        for rip in (combos + singles if singleton_attempts >= 2 else singles + combos):
            ps.append(('expand', {**base, 'rip': rip}, 'current_state_blocker_evidence', sorted({i for n in rip for i in evidence[n]})))
        if any(h['feedback'].get('engine_native_disagreement') for h in hs):
            ps.append(('continue', {**base, 'force': True}, 'native_engine_disagreement', [h['id'] for h in hs if h['feedback'].get('engine_native_disagreement')]))
        if any(h['feedback'].get('static_obstacle_hint') for h in hs):
            ps.append(('continue', {**base, 'options': {'grid_step': .05}}, 'static_obstacle_finer_grid', [h['id'] for h in hs if h['feedback'].get('static_obstacle_hint')]))
        ps = [p for p in ps if action_key(p[1]) not in tried]
        if ps:
            result[target] = ps
    return result


def empty_stats():
    return {'actions': 0, 'engine_seconds': 0., 'audit_seconds': 0.,
            'gain': 0, 'progress_events': 0, 'no_progress_streak': 0, 'last_selected': -1}


class Planner(PreviousPlanner):
    def __init__(self, initial, mode='full', **limits):
        if mode not in MODES:
            raise ValueError('Unknown scheduling mode')
        super().__init__(initial, mode='full', **limits)
        self.data.update(version='0.4-budget1', scheduler=mode, target_ledger={})

    @classmethod
    def restore(cls, data):
        if data['version'] != '0.4-budget1' or data['scheduler'] not in MODES:
            raise ValueError('Unsupported checkpoint')
        obj = cls.__new__(cls)
        obj.data = deepcopy(data)
        return obj

    def ranking(self, state, candidates):
        d = self.data
        rows = []
        for target in candidates:
            h = d['target_ledger'].get(target, empty_stats())
            # Smoothed empirical utility, not a calibrated success probability.
            success = (1. + h['progress_events']) / (2. + h['actions'])
            gain = min(state['remaining'][target], (1. + h['gain']) / (1. + h['progress_events']))
            cost = max(1., (5. + h['engine_seconds'] + h['audit_seconds']) / (1. + h['actions']))
            score = success * gain / cost / (1. + .5 * h['no_progress_streak'])
            rows.append({'target': target, 'score': score, 'estimated_cost_seconds': cost,
                         'actions': h['actions'], 'last_selected': h['last_selected'],
                         'age': len(d['attempts']) - 1 - h['last_selected']})
        mode = d['scheduler']
        if mode == 'fixed':
            chosen = rows[0]
            reason = 'previous_fixed_target_priority'
        else:
            untried = [r for r in rows if not r['actions']]
            overdue = [r for r in rows if r['age'] >= 2 * len(rows)]
            if untried:
                chosen, reason = untried[0], 'initial_target_exploration'
            elif mode == 'round_robin' or overdue:
                chosen = min(overdue or rows, key=lambda r: (r['last_selected'], r['target']))
                reason = 'target_rotation' if mode == 'round_robin' else 'bounded_wait_fairness'
            else:
                chosen = min(rows, key=lambda r: (-r['score'], r['last_selected'], r['target']))
                reason = 'smoothed_gain_cost_priority'
        return chosen['target'], {'reason': reason, 'targets': rows}

    def next(self):
        d = self.data
        if d['stop']:
            return d['stop']
        if d['pending']:
            raise RuntimeError('Pending action must be reconciled first')
        if any(a['classification'] == 'infrastructure_or_integrity' for a in d['attempts']):
            return self.stop('infrastructure_or_integrity')
        if sum(d['best']['remaining'].values()) == 0:
            return self.stop('complete')
        if len(d['attempts']) >= d['limits']['actions']:
            return self.stop('action_budget')
        if self.spent >= d['limits']['engine_seconds']:
            return self.stop('engine_budget')
        while d['stack']:
            node = d['stack'][-1]
            s = node['state']
            ps = proposals(s, d['attempts'])
            if ps:
                target, ranking = self.ranking(s, ps)
                kind, action, reason, evidence = ps[target][0]
                item = {'id': f'a{len(d["attempts"])+1:03d}', 'decision': kind,
                        'action': action, 'reason': reason, 'evidence_actions': evidence,
                        'input': deepcopy(s), 'depth': node['depth'], 'checkpoint': s['sha256'],
                        'timeout_seconds': min(60., d['limits']['engine_seconds'] - self.spent),
                        'scheduling': ranking}
                d['pending'] = item
                d['events'].append({'event': kind, **deepcopy(item)})
                return item
            if len(d['stack']) == 1:
                return self.stop('supported_actions_exhausted')
            d['stack'].pop()
            d['events'].append({'event': 'backtrack', 'reason': 'branch_exhausted', 'from': s['geometry'], 'to': d['stack'][-1]['state']['geometry']})
        return self.stop('supported_actions_exhausted')

    def observe(self, feedback, candidate=None):
        d = self.data
        p = d['pending']
        if not p:
            raise RuntimeError('No pending action')
        in_probe = d['scheduler'] == 'full' and p['depth'] > 0
        # Every new neutral branch must have room for one measured follow-up.
        no_probe_budget = (len(d['attempts']) + 1 >= d['limits']['actions'] or
                           self.spent + feedback.get('engine_seconds', 0.) >= d['limits']['engine_seconds'])
        old_depth = d['limits']['depth']
        if d['scheduler'] == 'full' and (in_probe or no_probe_budget):
            d['limits']['depth'] = 0
        try:
            result = super().observe(feedback, candidate)
        finally:
            d['limits']['depth'] = old_depth
        entry = d['attempts'][-1]
        if in_probe and result != 'commit':
            # Do not preserve a neutral child produced by a neutral probe.
            while len(d['stack']) > 1:
                discarded = d['stack'].pop()
                d['events'].append({'event': 'backtrack', 'reason': 'one_probe_without_connectivity_gain',
                                    'from': discarded['state']['geometry'], 'to': d['stack'][-1]['state']['geometry']})
            entry['outcome_reason'] = 'one_probe_without_connectivity_gain'
        h = d['target_ledger'].setdefault(p['action']['target'], empty_stats())
        h['actions'] += 1
        h['engine_seconds'] += feedback.get('engine_seconds', 0.)
        h['audit_seconds'] += feedback.get('audit_seconds', 0.)
        gain = max(0, sum(p['input']['remaining'].values()) - sum(candidate['remaining'].values())) if result == 'commit' else 0
        h['gain'] += gain
        h['progress_events'] += gain > 0
        h['no_progress_streak'] = 0 if gain else h['no_progress_streak'] + 1
        h['last_selected'] = len(d['attempts']) - 1
        entry['target_ledger_after'] = deepcopy(h)
        return result
