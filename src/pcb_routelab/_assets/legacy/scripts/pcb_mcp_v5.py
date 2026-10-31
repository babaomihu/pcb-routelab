import json, math, os
from pathlib import Path

def schema(properties,required):return {'type':'object','properties':properties,'required':required,'additionalProperties':False}

def validate(value,s):
 t=s.get('type')
 good={'object':lambda:isinstance(value,dict),'string':lambda:isinstance(value,str),'integer':lambda:type(value) is int,'number':lambda:type(value) in (int,float) and math.isfinite(value)}
 if t in good and not good[t]():raise ValueError('Invalid '+t)
 if t=='object':
  if set(s.get('required',[]))-set(value):raise ValueError('Missing fields')
  if set(value)-set(s['properties']):raise ValueError('Unknown fields')
  for k,v in value.items():validate(v,s['properties'][k])
 if 'enum' in s and value not in s['enum']:raise ValueError('Invalid run_id')
 if t=='string' and not s.get('minLength',0)<=len(value)<=s.get('maxLength',len(value)):raise ValueError('Invalid string length')
 if t in ('integer','number'):
  if 'exclusiveMinimum' in s and value<=s['exclusiveMinimum']:raise ValueError('Cost must be positive')
  if 'maximum' in s and value>s['maximum']:raise ValueError('Cost exceeds host input guard')

def save(path,data):
 with Path(path).open('w') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())

TOKEN={'type':'string','minLength':1,'description':'Latest opaque state token'}
