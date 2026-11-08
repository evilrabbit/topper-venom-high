import bpy, time
t=time.time()
RES=2048
img=bpy.data.images.new('navy_bake',RES,RES,alpha=False,float_buffer=False)
img.colorspace_settings.name='sRGB'
objs=[o for o in bpy.data.objects if o.type=='MESH']
for m in {o.active_material for o in objs}:
    nt=m.node_tree; N=nt.nodes
    g=[n for n in N if n.type=='GROUP'][0]
    out=[n for n in N if n.type=='OUTPUT_MATERIAL'][0]
    em=N.new('ShaderNodeEmission'); nt.links.new(g.outputs['Base Color'],em.inputs['Color']); nt.links.new(em.outputs[0],out.inputs['Surface'])
    tx=N.new('ShaderNodeTexImage'); tx.image=img
    for n in N: n.select=False
    tx.select=True; N.active=tx
sc=bpy.context.scene; sc.render.engine='CYCLES'; sc.cycles.device='CPU'; sc.cycles.samples=1
sc.render.bake.margin=16; sc.render.bake.margin_type='EXTEND'
for o in bpy.data.objects: o.select_set(False)
for o in objs: o.select_set(True)
bpy.context.view_layer.objects.active=objs[0]
bpy.ops.object.join()   # one object => one bake pass; margins only fill empty texels, never other islands
objs=[bpy.context.view_layer.objects.active]
print('JOINED',len(objs[0].data.polygons),len(objs[0].data.materials))
bpy.ops.object.bake(type='EMIT')
img.filepath_raw='/tmp/shoe-parts/navy-color-bake.png'; img.file_format='PNG'; img.save()
print('BAKED',round(time.time()-t,1))
