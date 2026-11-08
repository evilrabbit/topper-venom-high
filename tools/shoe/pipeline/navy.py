import bpy, json, sys
from mathutils import Vector
argv=sys.argv[sys.argv.index('--')+1:]; TAG=argv[0]; SAVE=len(argv)>1
P=json.load(open('/Users/evilrabbit/topper-venom/tools/navy/params.json'))
def hx(h): h=h.lstrip('#'); c=[int(h[i:i+2],16)/255 for i in (0,2,4)]; return tuple(((x+0.055)/1.055)**2.4 if x>0.04045 else x/12.92 for x in c)+(1,)
W,N,I,G=P['white'],P['navy'],P['ink'],'#c4c6cc'
INK={k:float(v) for k,v in json.loads(__import__('os').environ.get('INK','{}')).items()}
# part -> (color, detail, original)
spec={'side_triangle':(N,0.5,0),'outsole':(N,0.5,0),'toe_bumper':(N,0.5,0),'sole_window_logo':(N,0.3,0),'vamp_accent':(N,0.5,0),
      'eyelets':(I,0.3,0),'collar':(G,0.6,0)}
for m in bpy.data.materials:
    if not m.name.startswith('shoe_'): continue
    nm=m.name[5:]; c,d,o=next((v for k,v in spec.items() if nm.startswith(k)),(W,0.6,0))
    g=[n for n in m.node_tree.nodes if n.type=='GROUP'][0]
    g.inputs['Color'].default_value=hx(c); g.inputs['Detail'].default_value=d; g.inputs['Original'].default_value=o
    m.diffuse_color=hx(c)
    if nm in INK: g.inputs['Ink Threshold'].default_value=INK[nm]; g.inputs['Ink Color'].default_value=hx(I)
sc=bpy.context.scene
if SAVE:
    bpy.ops.wm.save_as_mainfile(filepath=__import__('os').environ.get('OUT','/tmp/shoe-parts/navy.blend'),copy=True); print('SAVED')
sc.render.engine='BLENDER_EEVEE' if 'BLENDER_EEVEE' in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items] else 'BLENDER_EEVEE_NEXT'
sc.view_settings.view_transform=__import__('os').environ.get('VT','AgX'); sc.view_settings.exposure=float(__import__('os').environ.get('EXPO','0.6')); sc.render.resolution_x=1152; sc.render.resolution_y=864
w=bpy.data.worlds.new('w'); sc.world=w; w.use_nodes=True; w.node_tree.nodes['Background'].inputs[0].default_value=(0.55,0.56,0.58,1); w.node_tree.nodes['Background'].inputs[1].default_value=0.5
for nm,loc,e in [('key',(-2.0,-1.5,2.2),P['key']*3),('fill',(-1.5,2.0,0.8),P['fill']*3),('rim',(2,1,1.5),120)]:
    l=bpy.data.objects.new(nm,bpy.data.lights.new(nm,'AREA')); l.data.energy=e; l.data.size=2.5; sc.collection.objects.link(l); l.location=loc; l.rotation_euler=(Vector((0,0,-0.05))-Vector(loc)).to_track_quat('-Z','Y').to_euler()
cam=bpy.data.objects.new('cam',bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera=cam; cam.data.lens=50
for k,v in {'ref':tuple(P['views']['ref']),'side':tuple(P['views']['side']),'other':(2.6,0,0.25),'back':(0.5,2.4,0.7)}.items():
    cam.location=v; cam.rotation_euler=(Vector((0,0,-0.03))-Vector(v)).to_track_quat('-Z','Y').to_euler()
    sc.render.filepath=f'/tmp/shoe-parts/{TAG}_{k}.png'; bpy.ops.render.render(write_still=True)
