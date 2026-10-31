from release_runtime import WORK, CODE, ENGINE, ENGINE_PYTHON, KICAD_PYTHON, KICAD_CLI
"""Validation and measurement only. No path-finding or route generation."""
import math,collections,json,uuid
from audit_board_v6 import sexpr,child,key
TOL=.15

def point(p):
 if not isinstance(p,list)or len(p)!=2 or any(type(x)not in (int,float)or not math.isfinite(x)or abs(x)>10000 for x in p):raise ValueError('Finite [x,y] millimetres required, |coordinate|<=10000')
 return p

def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
def distance(p,a,b):
 dx=b[0]-a[0];dy=b[1]-a[1];den=dx*dx+dy*dy;t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den))if den else 0
 return math.dist(p,[a[0]+t*dx,a[1]+t*dy])
def inside(p,poly):
 cs=[cross(a,b,p)for a,b in zip(poly,poly[1:]+poly[:1])];return all(x>=-1e-9 for x in cs)or all(x<=1e-9 for x in cs)
def intersect(a,b,c,d):
 return cross(a,b,c)*cross(a,b,d)<=0 and cross(c,d,a)*cross(c,d,b)<=0 and max(min(a[0],b[0]),min(c[0],d[0]))<=min(max(a[0],b[0]),max(c[0],d[0]))+1e-9 and max(min(a[1],b[1]),min(c[1],d[1]))<=min(max(a[1],b[1]),max(c[1],d[1]))+1e-9

def validate_guidance(g):
 if not isinstance(g,dict)or set(g)-{'waypoints','keepouts','layers','layer_costs','require_waypoints'}:raise ValueError('Unsupported guidance field')
 ps=g.get('waypoints',[])
 if not isinstance(ps,list)or len(ps)>16 or len(ps)==1:raise ValueError('Use zero or 2..16 waypoints')
 for p in ps:point(p)
 if any(math.dist(a,b)<1e-6 for a,b in zip(ps,ps[1:])):raise ValueError('Duplicate adjacent waypoint')
 polys=g.get('keepouts',[])
 if not isinstance(polys,list)or len(polys)>4:raise ValueError('At most four keepout polygons')
 for poly in polys:
  if not isinstance(poly,list)or not 3<=len(poly)<=12:raise ValueError('Convex polygon needs 3..12 vertices')
  for p in poly:point(p)
  turns=[cross(poly[i-1],poly[i],poly[(i+1)%len(poly)])for i in range(len(poly))]
  if not(all(t>1e-9 for t in turns)or all(t< -1e-9 for t in turns)):raise ValueError('Only strictly convex polygons supported')
  for i in range(len(poly)):
   for j in range(i+1,len(poly)):
    if j==i+1 or (i==0 and j==len(poly)-1):continue
    if intersect(poly[i],poly[(i+1)%len(poly)],poly[j],poly[(j+1)%len(poly)]):raise ValueError('Self-intersecting polygon')
 layers=g.get('layers',[])
 if not isinstance(layers,list)or len(layers)!=len(set(layers))or any(x not in ['F.Cu','B.Cu']for x in layers):raise ValueError('Unique supported copper layers required')
 costs=g.get('layer_costs',[])
 if costs and (not layers or len(costs)!=len(layers)or any(type(x)not in(int,float)or not math.isfinite(x)or not 1<=x<=1000 for x in costs)):raise ValueError('Layer costs 1..1000 must match ordered layers')
 if 'require_waypoints'in g and type(g['require_waypoints'])is not bool:raise ValueError('require_waypoints must be boolean')
 return g

def encode(node):return '('+' '.join(encode(x)if isinstance(x,list)else x for x in node)+')'
def overlay(source,target,g):
 tree=sexpr(source.read_text());ids=[];layers=child(tree,'layers')
 for name,num in [('User.1',39),('User.2',41)]:
  for item in tree:
   if isinstance(item,list)and item and item[0].startswith('gr_'):
    lay=child(item,'layer')
    if lay and lay[1].strip('"')==name:raise ValueError('Reserved temporary '+name+' already contains graphics; no user drawing overwritten')
  if not any(isinstance(x,list)and len(x)>1 and x[1].strip('"')==name for x in layers[1:]):layers.append([str(num),'"'+name+'"','user'])
 def add(shape):
  ident=str(uuid.uuid4());ids.append(ident);tree.append(shape+[['uuid','"'+ident+'"']])
 for a,b in zip(g.get('waypoints',[]),g.get('waypoints',[])[1:]):add(['gr_line',['start',*map(str,a)],['end',*map(str,b)],['stroke',['width','0.15'],['type','default']],['layer','"User.1"']])
 for poly in g.get('keepouts',[]):add(['gr_poly',['pts',*([ 'xy',*map(str,p)]for p in poly)],['stroke',['width','0.15'],['type','default']],['fill','none'],['layer','"User.2"']])
 target.write_text(encode(tree)+'\n');return ids

def clean_overlay(raw,target,source,ids):
 tree=sexpr(raw.read_text());original=sexpr(source.read_text());new=[]
 for item in tree:
  if isinstance(item,list)and item:
   ident=child(item,'uuid')if item[0].startswith('gr_')else None
   if ident and ident[1].strip('"')in ids:continue
   if item[0]=='layers':item=child(original,'layers')
  new.append(item)
 target.write_text(encode(new)+'\n')

def geometry_feedback(snap,net,g,via_points=None,endpoint_mode=False):
 tracks=[t for t in snap['tracks']if t['net_name']==net];vias=[v for v in snap['vias']if v['net_name']==net]
 segs=[([x/1e6 for x in t['endpoints_nm'][0]],[x/1e6 for x in t['endpoints_nm'][1]],t['width_nm']/2e6,t)for t in tracks]
 hits=[]
 for p in g.get('waypoints',[]):
  d=min(((min(math.dist(p,a),math.dist(p,b))if endpoint_mode else distance(p,a,b))for a,b,_,t in segs),default=None);hits.append({'requested_mm':p,'measurement':'nearest same-net track endpoint'if endpoint_mode else 'nearest same-net track centerline','distance_mm':d,'within_0_15mm':d is not None and d<=TOL})
 vh=[]
 for p in via_points or []:
  v=min(vias,key=lambda v:math.dist(p,[x/1e6 for x in v['position_nm']]))if vias else None
  actual=[x/1e6 for x in v['position_nm']]if v else None;d=math.dist(p,actual)if actual else None;vh.append({'requested_mm':p,'actual_mm':actual,'distance_mm':d,'within_0_15mm':d is not None and d<=TOL})
 violations=[]
 for poly in g.get('keepouts',[]):
  edges=list(zip(poly,poly[1:]+poly[:1]))
  for t in snap['tracks']:
   a,b=[[x/1e6 for x in pt]for pt in t['endpoints_nm']];radius=t['width_nm']/2e6
   if inside(a,poly)or inside(b,poly)or any(intersect(a,b,c,d)or min(distance(a,c,d),distance(b,c,d),distance(c,a,b),distance(d,a,b))<=radius for c,d in edges):violations.append({'kind':'track','net':t['net_name'],'layer':t['layer'],'endpoints_mm':[a,b]})
  for v in snap['vias']:
   p=[x/1e6 for x in v['position_nm']]
   if inside(p,poly)or min(distance(p,a,b)for a,b in edges)<=v['width_nm']/2e6:violations.append({'kind':'via','net':v['net_name'],'xy_mm':p})
 layers=sorted({t['layer']for t in tracks});layer_ok=not g.get('layers')or set(layers)<=set(g['layers'])
 hard=(not g.get('require_waypoints')or all(x['within_0_15mm']for x in hits))and not violations and layer_ok and all(x['within_0_15mm']for x in vh)
 return {'net':net,'waypoints':hits,'all_waypoints_observed':all(x['within_0_15mm']for x in hits),'vias_requested':vh,'actual_vias':[{'xy_mm':[x/1e6 for x in v['position_nm']],'layers':v['layers']}for v in vias],'actual_track_layers':layers,'track_layers_allowed':layer_ok,'keepout_copper_violations':violations,'hard_constraints_satisfied':hard,'tolerance_mm':TOL,'semantics':'KRT waypoints soft unless explicitly required; layer costs are preference; layer restrictions measured on tracks, through-via spans reported separately.'}

def other_copper_preserved(before,after,net):
 return all(collections.Counter(key(t)for t in before[k]if t['net_name']!=net)==collections.Counter(key(t)for t in after[k]if t['net_name']!=net)for k in ['tracks','vias'])
