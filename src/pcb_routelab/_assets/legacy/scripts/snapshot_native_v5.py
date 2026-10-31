from release_runtime import WORK, CODE, ENGINE, ENGINE_PYTHON, KICAD_PYTHON, KICAD_CLI
"""Read-only KiCad native snapshot worker, invoked with KiCad bundled Python.
Uses upstream pcbforeman LoadBoard/GetTracks/GetNetInfo inspection APIs;
never imports SES, saves, deletes, routes, or applies project rules.
"""
import json,sys
import pcbnew

def snapshot(path):
 b=pcbnew.LoadBoard(path)
 if b is None:raise RuntimeError('Native LoadBoard failed')
 pt=lambda p:[int(p.x),int(p.y)]
 uid=lambda o:str(o.m_Uuid.AsString())
 rows=[];vias=[];ids={};uuid_nets={};pads=[];footprints=[];pad_ids={};locked=[]
 def value(x):
  if hasattr(x,'x') and hasattr(x,'y'):return pt(x)
  if hasattr(x,'Seq'):return [b.GetLayerName(int(n)) for n in x.Seq()]
  if isinstance(x,(str,int,float,bool)):return x
  return str(x)
 def fields(o,methods):return {n:value(getattr(o,n)()) for n in methods}
 names={int(k):str(v.GetNetname()) for k,v in b.GetNetsByNetcode().items()}
 for t in b.GetTracks():
  name=str(t.GetNetname());ident=uid(t);uuid_nets[ident]=name
  if t.GetClass()=='PCB_VIA':
   r={'net_name':name,'position_nm':pt(t.GetPosition()),'width_nm':int(t.GetWidth(t.TopLayer())),'drill_nm':int(t.GetDrillValue()),'layers':[b.GetLayerName(t.TopLayer()),b.GetLayerName(t.BottomLayer())],'via_type':int(t.GetViaType())};vias.append(r);ids[ident]=['via',r]
  elif t.GetClass()=='PCB_TRACK':
   r={'net_name':name,'endpoints_nm':sorted([pt(t.GetStart()),pt(t.GetEnd())]),'width_nm':int(t.GetWidth()),'layer':b.GetLayerName(t.GetLayer())};rows.append(r);ids[ident]=['track',r]
  else:raise RuntimeError('Unsupported native copper class '+t.GetClass())
 for t in b.GetTracks():
  if t.IsLocked():locked.append(ids[uid(t)])
 for f in b.GetFootprints():
  fr=fields(f,['GetPosition','GetOrientationDegrees','GetAttributes','GetReference','GetValue','IsLocked','GetLocalClearance','GetLocalSolderMaskMargin','GetLocalSolderPasteMargin','GetLocalSolderPasteMarginRatio','GetDuplicatePadNumbersAreJumpers']);fr['layer']=b.GetLayerName(f.GetLayer());footprints.append(fr);ids[uid(f)]=['footprint',fr]
  for p in f.Pads():
   if p.GetShape()==pcbnew.PAD_SHAPE_CUSTOM:raise RuntimeError('Custom pad primitives unsupported: fail closed')
   pr=fields(p,['GetPosition','GetFPRelativePosition','GetOrientationDegrees','GetSize','GetShape','GetLayerSet','GetNumber','GetAttribute','GetDrillSize','GetDrillShape','GetOffset','GetDelta','GetRoundRectRadiusRatio','GetChamferPositions','GetChamferRectRatio','GetLocalClearance','GetLocalSolderMaskMargin','GetLocalSolderPasteMargin','GetLocalSolderPasteMarginRatio','GetLocalThermalGapOverride','GetLocalThermalSpokeWidthOverride']);pr['net_name']=str(p.GetNetname());pr['footprint']=fr;pads.append(pr);pad_ids[uid(p)]=json.dumps(pr,sort_keys=True);uuid_nets[uid(p)]=str(p.GetNetname());ids[uid(p)]=['pad',pr]
 # Native connectivity graph: preserve original pad-component membership, not only airwire counts.
 b.BuildConnectivity()
 conn=b.GetConnectivity();items=list(b.GetTracks())+[p for f in b.GetFootprints() for p in f.Pads()]
 parent={uid(x):uid(x) for x in items}
 def find(x):
  while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
  return x
 for item in items:
  for neighbor in list(conn.GetConnectedPads(item))+list(conn.GetConnectedTracks(item)):
   a,c=uid(item),uid(neighbor)
   if c in parent:parent[find(a)]=find(c)
 groups={}
 for ident,identity in pad_ids.items():groups.setdefault(find(ident),[]).append(identity)
 if len(set(pad_ids.values()))!=len(pad_ids):raise RuntimeError('Ambiguous duplicate pad geometry identity')
 components=sorted([sorted(g) for g in groups.values()])
 settings=b.GetDesignSettings()
 rulefields=['m_MinClearance','m_TrackMinWidth','m_ViasMinSize','m_ViasMinAnnularWidth','m_MinThroughDrill','m_MicroViasMinDrill','m_MicroViasMinSize','m_CopperEdgeClearance','m_HoleClearance','m_HoleToHoleMin','m_SolderMaskExpansion','m_SolderMaskMinWidth','m_SolderMaskToCopperClearance','m_SolderPasteMargin','m_SolderPasteMarginRatio','m_AllowSoldermaskBridgesInFPs','m_TentViasBack','m_TentViasFront','m_CapVias','m_FillVias','m_PlugViasBack','m_PlugViasFront','m_CoverViasBack','m_CoverViasFront']
 design={n:value(getattr(settings,n)) for n in rulefields}
 netrules={}
 for f in b.GetFootprints():
  for p in f.Pads():
   nc=settings.m_NetSettings.GetEffectiveNetClass(str(p.GetNetname()));netrules[str(p.GetNetname())]=fields(nc,['GetClearance','GetTrackWidth','GetViaDiameter','GetViaDrill','GetuViaDiameter','GetuViaDrill','GetDiffPairWidth','GetDiffPairGap','GetDiffPairViaGap'])
 design['effective_netclasses']=netrules
 return {'pad_components':components,'locked_copper':sorted(locked,key=lambda v:json.dumps(v,sort_keys=True)),'tracks':rows,'vias':vias,'native_uuid_identities':ids,'uuid_net_names':uuid_nets,'native_net_names':names,'copper_layers':int(b.GetCopperLayerCount()),'native_version':pcbnew.Version(),'pads':pads,'footprints':footprints,'design_rules':design}
if __name__=='__main__':
 try:print(json.dumps(snapshot(sys.argv[1]),ensure_ascii=False))
 except Exception as e:print(json.dumps({'error':repr(e)}));sys.exit(1)
