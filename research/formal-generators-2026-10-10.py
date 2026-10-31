"""Outcome-frozen numeric, GP, generic LLM and PCB-feedback proposal rules."""
import ast
import copy
import importlib.util
import math
from pathlib import Path
import random
import sys
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('formal_generator_core',ROOT/'formal-core-2026-10-10.py')
F=importlib.util.module_from_spec(s);s.loader.exec_module(F)

def elites(history):
    unique={}
    for h in sorted(history,key=lambda h:(h['summary']['objective'],h['index'])):
        unique.setdefault(h['executed_expression'],h)
    return list(unique.values())[:4]

def numeric(seed,index,history):
    rng=random.Random(seed*100000+index)
    if index<18:
        values=[]
        for j in range(4):
            rr=random.Random(seed*100+j);order=list(range(16));rr.shuffle(order)
            values.append((order[index-2]+rng.random())/16)
        a,b,c=[.125*32**v for v in values[:3]]
        e=0. if index%2==0 else 2*values[3]
    else:
        parent=rng.choice(elites(history));p=parent.get('parameters') or {'a':.5,'b':.5,'c':.5,'e':0}
        a,b,c=[min(4.,max(.125,p[k]*math.exp(rng.gauss(0,.45)))) for k in ('a','b','c')]
        e=min(2.,max(0.,p['e']+rng.gauss(0,.35)))
    pars=dict(zip(('a','b','c','e'),[round(v,6) for v in (a,b,c,e)]))
    expr=f"minimum(1, maximum(inc*({pars['a']}*contest+{pars['b']}*rip+{pars['c']}*frontier), {pars['e']}*old))"
    return {'expression':expr,'parameters':pars,'origin':'numeric_adaptive_search'}

def random_expr(rng,depth=0):
    if depth>=2 or rng.random()<.35:
        return rng.choice(['old','inc','contest','rip','frontier','0.125','0.25','0.5','1','2','4'])
    a=random_expr(rng,depth+1);b=random_expr(rng,depth+1)
    op=rng.choice(['+','-','*','divide','minimum','maximum','sqrt','log1p'])
    if op in ('+','-','*'):return f'({a}{op}{b})'
    if op=='divide':return f'({a}/(1+maximum(0,{b})))'
    if op in ('sqrt','log1p'):return f'{op}(maximum(0,{a}))'
    return f'{op}({a},{b})'

def mutable_nodes(tree):
    return [n for n in ast.walk(tree) if isinstance(n,ast.expr) and not (isinstance(n,ast.Name) and n.id not in F.K.NAMES)]

def program(seed,index,history):
    rng=random.Random(seed*200000+index);parents=elites(history)
    for attempt in range(30):
        operation=rng.random()
        if operation<.25:
            expression=f'minimum(1, maximum(0, inc*({random_expr(rng)})))';kind='random_program'
        else:
            tree=ast.parse(rng.choice(parents)['executed_expression'],mode='eval')
            target=rng.choice(mutable_nodes(tree))
            if operation<.65:
                replacement=ast.parse(random_expr(rng),mode='eval').body;kind='tree_mutation'
            else:
                other=ast.parse(rng.choice(parents)['executed_expression'],mode='eval')
                replacement=copy.deepcopy(rng.choice(mutable_nodes(other)));kind='subtree_crossover'
            class Replace(ast.NodeTransformer):
                def visit(self,node):
                    return replacement if node is target else super().visit(node)
            tree=Replace().visit(tree)
            expression=f'minimum(1, maximum(0, {ast.unparse(tree)}))'
        try:F.classify(expression)
        except (ValueError,SyntaxError,FloatingPointError,ZeroDivisionError):continue
        return {'expression':expression,'origin':'genetic_program_search','operation':kind,'generation_attempts':attempt+1}
    return {'expression':parents[0]['executed_expression'],'origin':'genetic_program_search','operation':'generation_fallback','generation_attempts':30}

def llm(method,seed,index,history,folder):
    top=elites(history)
    compact=lambda h:{'index':h['index'],'expression':h['executed_expression'],'objective':h['summary']['objective'],
       'generation_status':h['generation']['status']}
    payload={'independent_run':seed,'candidate_position':index+1,'deployment':'one frozen expression, four fixed native contexts per board; select legal/U/vias/length',
      'objective':'lexicographic [-legal_complete, family_regressions, mean normalized vias, mean normalized length]',
      'elite_programs':[compact(h) for h in top],'own_history':[compact(h) for h in history],
      'proposal_instruction':'Propose one mutation, crossover, or distinct exploration. You may use nonlinear dependence on old if evidence supports it; do not merely rename a parent.',
      'shared_starting_information':'Both methods receive inc and 0.5*inc seed programs and their own evaluations; no other method results.'}
    if method=='pcb-feedback':
        selected={h['index']:h for h in [*top,history[-1]]}
        payload['paired_family_feedback']=[{'index':i,'expression':h['executed_expression'],'actual_results':F.feedback(h['rows'])} for i,h in sorted(selected.items())]
        payload['feedback_scope']='Compare the same family/context rows between programs; null event data are unknown; unconnected is not a DRC error.'
    result=F.A.call(folder/'request',payload,'generic-evolution' if method=='generic' else 'pcb-feedback')
    if result['status']!='validated':return {'expression':None,'origin':'real_provider_response','model_result':result}
    path=folder/'request/validated-policy-2026-10-09.json'
    return {'expression':F.C.load(path)['expression'],'origin':'real_provider_response','model_result':result,
      'validated_source':str(path),'validated_source_sha256':F.C.sha(path)}

def propose(method,seed,index,history,folder):
    if method not in ('numeric','program','generic','pcb-feedback'):raise ValueError('Unknown proposal method')
    if type(index) is not int or not 0<=index<32:raise ValueError('Candidate index must be 0..31')
    if index>=2 and not history:raise ValueError('Evaluate the shared initial proposals before evolving a candidate')
    if index<2:
        value=[1.,.5][index]
        return {'expression':['inc','0.5*inc'][index],'origin':'shared_manual_initialization',
          'parameters':{'a':value,'b':value,'c':value,'e':0.}}
    if method=='numeric':return numeric(seed,index,history)
    if method=='program':return program(seed,index,history)
    return llm(method,seed,index,history,folder)
