"""Read-only KRT import plus explicit planning hooks; never edits engine files.

Called as: python this.py OBSERVATION PLAN TRACE -- route.py arguments.
Finite candidate paths are bound to the board hash. All geometry remains KRT's.
"""
import atexit
import importlib.util
import json
from pathlib import Path
import runpy
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('joint_preflight', ROOT/'preflight-2026-10-08.py')
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
C = P.module('joint_contract', ROOT/'plan_contract-2026-10-08.py')


def native_path(points, allowed_layers):
    """Validate every JSON point, including the final point, before Rust FFI."""
    if not isinstance(points, (list, tuple)) or not points:
        raise ValueError('Empty or invalid corridor')
    result = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            raise ValueError('Corridor point must have x, y, layer')
        if any(type(value) is not int for value in point):
            raise ValueError('Corridor coordinates must be integers')
        if any(not -(2**31) <= value < 2**31 for value in point[:2]):
            raise ValueError('Corridor coordinate exceeds signed 32-bit range')
        if point[2] not in allowed_layers:
            raise ValueError('Corridor point uses forbidden layer')
        result.append(tuple(point))
    return result


def main():
    obs_path, plan_path, trace_path = map(Path, sys.argv[1:4])
    if sys.argv[4] != '--':
        raise ValueError('Missing argument separator')
    route_args = sys.argv[5:]
    observation = P.load(obs_path)
    plan = C.validate(P.load(plan_path), observation)
    if P.sha(Path(route_args[0])) != observation['reference_sha256']:
        raise ValueError('Plan is for a different board')
    trace = {'plan_sha256': P.sha(plan_path), 'observation_sha256': C.digest(observation),
             'events': [], 'route_exit': 'incomplete'}
    def emit(kind, **data):
        trace['events'].append({'event': kind, **data})
    atexit.register(lambda: P.save(trace_path, trace))
    sys.path.insert(0, str(P.ENGINE))
    import global_plan as G
    import env_knobs
    import single_ended_loop as loop
    native_plan = G.plan_global_routes
    native_order = G.apply_plan_order
    native_layer = G.plan_layer_config
    ids = {str(n['id']): n for n in observation['nets']}

    def planned(*args, **kwargs):
        result = native_plan(*args, **kwargs)
        if result is None:
            raise RuntimeError('Planning hook was not active')
        config = args[1]
        current = {str(i) for _,i in args[2]}
        if current != set(ids):
            raise RuntimeError('Actual planning net set differs from observation')
        if config.grid_step != observation['config']['grid_step'] or list(config.layers) != observation['config']['layers']:
            raise RuntimeError('Actual route grid/layers differ from observation')
        result.layer_pref.clear()
        result.rough_paths.clear()
        result.reservations.clear()
        for nid, assignment in plan['assignments'].items():
            if assignment['layer'] is not None:
                result.layer_pref[int(nid)] = assignment['layer']
            if assignment['corridor'] != 'none':
                result.rough_paths[int(nid)] = native_path(
                    ids[nid]['corridors'][assignment['corridor']],
                    observation['allowed_layer_indices'])
        result.conflict_w, result.share_w = G._conflict_graphs(result.rough_paths, config)
        result.river.clear()
        emit('plan_installed', net_ids=sorted(current), layer_pref=result.layer_pref,
             corridor_choices={n:a['corridor'] for n,a in plan['assignments'].items()},
             planning_knobs=dict(env_knobs.GLOBAL_PLAN))
        return result

    def ordered(net_ids, obj, front_ids=None):
        native = native_order(net_ids, obj, front_ids=front_ids)
        if {str(i) for i in (front_ids or [])} != set(observation['front_ids']):
            raise RuntimeError('Native front partition changed')
        by_id = {str(i): (n,i) for n,i in net_ids}
        chosen = [by_id[n] for n in plan['order']]
        emit('order_applied', native_order=[str(i) for _,i in native], actual_order=[str(i) for _,i in chosen])
        return chosen

    def layer_config(cfg, config, nid):
        out = native_layer(cfg, config, nid)
        emit('layer_consumed', net_id=str(nid), before=list(cfg.layer_costs or []),
             after=list(out.layer_costs or []), planned=plan['assignments'].get(str(nid),{}).get('layer'))
        return out

    def instrument(function, name):
        def call(*args, **kwargs):
            nid = args[1]
            cfg = args[2]
            attr = kwargs.get('attraction_path')
            emit('detailed_route', function=name, net_id=str(nid),
                 layer_costs=list(cfg.layer_costs or []), attraction_points=len(attr) if attr is not None else 0,
                 attraction_sha256=C.digest(attr) if attr is not None else None)
            return function(*args, **kwargs)
        return call

    G.plan_global_routes = planned
    G.apply_plan_order = ordered
    G.plan_layer_config = layer_config
    for name in ('route_net_with_obstacles', 'route_multipoint_main', 'route_oracle_links'):
        setattr(loop, name, instrument(getattr(loop, name), name))
    sys.argv = [str(P.ENGINE/'route.py'), *route_args]
    try:
        runpy.run_path(str(P.ENGINE/'route.py'), run_name='__main__')
        trace['route_exit'] = 0
    except SystemExit as exc:
        trace['route_exit'] = exc.code or 0
        raise
    except Exception as exc:
        trace['route_exit'] = 'error'
        trace['error'] = type(exc).__name__+': '+str(exc)
        raise
    finally:
        P.save(trace_path, trace)


if __name__ == '__main__':
    main()
