"""Bounded expression interpreter: no eval, code execution, attributes or I/O."""
import ast
import math
import numpy as np

NAMES = {'old', 'inc', 'contest', 'rip', 'frontier'}
FUNCTIONS = {'minimum': (np.minimum, 2), 'maximum': (np.maximum, 2),
             'sqrt': (np.sqrt, 1), 'log1p': (np.log1p, 1)}
OPS = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply, ast.Div: np.divide}

class Policy:
    def __init__(self, expression):
        if not isinstance(expression, str) or len(expression) > 1000:
            raise ValueError('Expression must be a string of at most 1000 characters')
        self.expression = expression
        self.tree = ast.parse(expression, mode='eval').body
        if len(list(ast.walk(self.tree))) > 100:
            raise ValueError('Expression exceeds 100 AST nodes')
        self.validate(self.tree, 0)

    def validate(self, n, depth):
        if depth > 12:
            raise ValueError('Expression nesting exceeds 12')
        if isinstance(n, ast.Constant):
            if type(n.value) not in (int, float) or not math.isfinite(n.value) or abs(n.value) > 100:
                raise ValueError('Invalid constant')
        elif isinstance(n, ast.Name) and n.id in NAMES:
            return
        elif isinstance(n, ast.BinOp) and type(n.op) in OPS:
            self.validate(n.left, depth+1); self.validate(n.right, depth+1)
        elif isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            self.validate(n.operand, depth+1)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCTIONS:
            if n.keywords or len(n.args) != FUNCTIONS[n.func.id][1]:
                raise ValueError('Invalid function arity')
            for a in n.args: self.validate(a, depth+1)
        else:
            raise ValueError('Forbidden syntax: '+type(n).__name__)

    def evaluate_node(self, n, values):
        if isinstance(n, ast.Constant): return n.value
        if isinstance(n, ast.Name): return values[n.id]
        if isinstance(n, ast.BinOp):
            return OPS[type(n.op)](self.evaluate_node(n.left, values), self.evaluate_node(n.right, values))
        if isinstance(n, ast.UnaryOp):
            v = self.evaluate_node(n.operand, values)
            return -v if isinstance(n.op, ast.USub) else v
        return FUNCTIONS[n.func.id][0](*(self.evaluate_node(a, values) for a in n.args))

    def charge(self, old, inc, event):
        if event not in ('contest', 'rip', 'frontier'):
            raise ValueError('Unclassified event')
        values = {'old': old, 'inc': inc, **{k:float(k==event) for k in ('contest','rip','frontier')}}
        with np.errstate(all='raise'):
            out = np.broadcast_to(np.asarray(self.evaluate_node(self.tree, values), dtype=np.float64), old.shape)
        if not np.all(np.isfinite(out)) or np.any(out<0) or np.any(out>1):
            raise ValueError('Charge must be finite in [0,1] mm')
        return out

def update(field, cells, inc, policy, event, knobs):
    """Same insertion/eviction/caching contract as native; only charge differs."""
    from time import perf_counter
    if inc<=0 or cells is None or len(cells)==0: return None
    t0=perf_counter()
    cells=np.unique(np.asarray(cells,dtype=np.int64))
    idx=np.searchsorted(field.keys,cells)
    hit=np.zeros(cells.size,dtype=bool)
    inside=idx<field.keys.size
    hit[inside]=field.keys[idx[inside]]==cells[inside]
    old=np.zeros(cells.size,dtype=np.float64)
    old[hit]=field.weights[idx[hit]]
    charge=policy.charge(old,inc,event)
    native=np.where(hit,np.maximum(inc,knobs['escalate']*old),inc)
    changed=int(np.count_nonzero(charge!=native))
    field.weights[idx[hit]]=old[hit]+charge[hit]
    fresh=~hit
    if fresh.any():
        field.keys=np.insert(field.keys,idx[fresh],cells[fresh])
        field.weights=np.insert(field.weights,idx[fresh],charge[fresh])
    over=field.keys.size-knobs['max_cells']
    if over>0:
        order=np.lexsort((field.keys,field.weights))
        keep=np.ones(field.keys.size,dtype=bool);keep[order[:over]]=False
        field.keys=field.keys[keep];field.weights=field.weights[keep];field.evicted+=over
    field.version+=1;field.record_s+=perf_counter()-t0
    return {'event':event,'cells':int(cells.size),'repeat_cells':int(hit.sum()),
            'changed_charges':changed,'increment_min':float(charge.min()),'increment_max':float(charge.max())}
