# Shoe colorway pipeline (Blender 5, headless)

Scripts still reference /tmp/shoe-parts; copy data/ there first:
    mkdir -p /tmp/shoe-parts && cp data/* /tmp/shoe-parts/

1. Parts:   LO=0.012 HI=0.065 SMOOTH=0 RGAP=4 REXT=1 LIP=0.008 blender -b /tmp/shoe-parts/merged.blend --python build_parts_v6.py   -> /tmp/shoe-parts/parts_v2.blend
2. Sole:    blender -b /tmp/shoe-parts/parts_v2.blend --python refine_band.py                                                   -> /tmp/shoe-parts/parts_v3.blend
3. Navy:    OUT=../shoe-navy.blend VT=AgX EXPO=1.0 INK='{"sole_heel_insert":0.6,"tongue_logo":0.6}' blender -b /tmp/shoe-parts/parts_v3.blend --python navy.py -- navy save
4. Bake:    blender -b ../shoe-navy.blend --python bake_navy.py          -> /tmp/shoe-parts/navy-color-bake.png
5. Final:   blender -b --factory-startup --python composite.py          -> /tmp/shoe-parts/navy-color-final.png
            then encode to models/navy-color.webp (PIL, WEBP q90)
Backup of the previous site texture: ../navy-color.orig.webp
