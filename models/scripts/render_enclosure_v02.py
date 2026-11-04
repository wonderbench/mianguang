"""Render the saved V0.2 model; --preview writes only ignored local previews."""
from pathlib import Path
import bpy, sys
ROOT = Path(__file__).resolve().parents[1]
preview = '--preview' in sys.argv
out = ROOT.parent/'verification/local/model_previews' if preview else ROOT/'v0.2/renders'
out.mkdir(parents=True,exist_ok=True)
for i, name in enumerate(['Mianguang_V02_01_Desk','Mianguang_V02_02_Rear','Mianguang_V02_03_Wall_45deg','Mianguang_V02_04_Exploded']):
    s=bpy.data.scenes[name];bpy.context.window.scene=s;bpy.context.view_layer.update()
    s.render.filepath=str(out/['01_hero.png','02_rear.png','03_wall_45deg.png','04_exploded.png'][i])
    s.render.resolution_percentage=50 if preview else 100
    s.cycles.samples=12 if preview else 48
    bpy.ops.render.render(write_still=True,scene=name)
print('Rendered',out)
