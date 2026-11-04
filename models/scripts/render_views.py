from pathlib import Path
import bpy, os
ROOT = str(Path(__file__).resolve().parents[1] / 'renders')
os.makedirs(ROOT, exist_ok=True)
names=[('SleepRadar_01_Desk','01_hero.png'),('SleepRadar_02_Rear','02_rear.png'),('SleepRadar_03_Wall_45deg','03_wall_45deg.png'),('SleepRadar_04_Exploded','04_exploded.png')]
for name,path in names:
    s=bpy.data.scenes[name]
    s.render.filepath=os.path.join(ROOT,path)
    bpy.ops.render.render(write_still=True,scene=name)
