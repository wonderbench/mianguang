from pathlib import Path
import bpy
src=bpy.data.scenes['SleepRadar_01_Desk']
for s in bpy.data.scenes:
    if s.name.startswith('SleepRadar_') and s!=src:
        for o in s.objects:
            if o.parent:
                old=src.objects.get(o.name.split('.')[0])
                if old:o.matrix_parent_inverse=old.matrix_parent_inverse.copy()
if bpy.context.window:bpy.context.window.scene=src
bpy.ops.wm.save_as_mainfile(filepath=str(Path(__file__).resolve().parents[1] / 'Sleep_Radar_Nightlight_Concept.blend'),compress=True)
