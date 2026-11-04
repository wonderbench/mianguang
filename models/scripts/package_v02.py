"""Verify and package the current enclosure artifacts without modifying PCB files."""
from pathlib import Path
import hashlib, json, zipfile

MODELS=Path(__file__).resolve().parents[1]
REPO=MODELS.parent
OUT=MODELS/'v0.2'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path):return json.loads(path.read_text())

pcb=REPO/'pcb/release_v02'
assert sha(pcb/'manifest.json')=='fd4339bd425b36fa923e9319b0f9c951d6cbc97a1826351783002f241a004e31', 'Frozen PCB manifest changed'
for f in load(pcb/'manifest.json')['files']:
    p=pcb/f['path'];assert sha(p)==f['sha256'] and p.stat().st_size==f['bytes'], f['path']
checks=load(OUT/'geometry_checks.json')
assert checks['status']=='PASS' and checks['failure_count']==0, 'Geometry checks have unresolved failures'
assert checks['checked_model_sha256']==sha(OUT/'Mianguang_Enclosure_V0.2.blend'), 'Geometry report is stale'
assert checks['checker_sha256']==sha(MODELS/'scripts/verify_enclosure_v02.py'), 'Checker changed after verification'
assert checks['reference_sha256']==sha(MODELS/'mechanical/pcb_v02_reference.json'), 'Reference changed after verification'
mesh=load(OUT/'mesh_checks.json')
assert len(mesh)==11 and all(x['nonmanifold_edges']==0 and x['connected_islands']==1 and x['volume_mm3']>0 for x in mesh)
assert len(list((OUT/'stl').glob('*.stl')))==11
assert len(list((OUT/'renders').glob('*.png')))==4
assert (OUT/'Mechanical_Layout_V0.2.svg').exists()

files=[p for p in OUT.rglob('*') if p.is_file() and p.suffix in {'.blend','.stl','.png','.svg','.json'} and p.name!='manifest.json']
files += [MODELS/'README.md'] + sorted((MODELS/'mechanical').glob('*.md')) + sorted((MODELS/'mechanical').glob('*.json'))
files += [MODELS/'scripts'/n for n in ['build_enclosure_v02.py','mount_v02.py','render_enclosure_v02.py','verify_enclosure_v02.py','draw_layout_v02.py','package_v02.py']]
files=sorted(set(files))
manifest={'version':'V0.2','date':'2026-11-04','scope':'PCB-referenced engineering prototype; physical qualification pending',
          'pcb_manifest_sha256':sha(pcb/'manifest.json'),'blender_version':checks['blender_version'],
          'geometry_summary':checks['summary'],'limitations':checks['limitations'],
          'files':[{'path':str(p.relative_to(REPO)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in files]}
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
dest=MODELS/'releases/Mianguang_Enclosure_V0.2_2026-11-04.zip';dest.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for p in files+[OUT/'manifest.json']:z.write(p,str(p.relative_to(REPO)))
with zipfile.ZipFile(dest) as z:
    assert z.testzip() is None
    for f in manifest['files']:
        assert hashlib.sha256(z.read(f['path'])).hexdigest()==f['sha256']
(MODELS/'LATEST.json').write_text(json.dumps({'version':'V0.2','directory':'v0.2','blend':'v0.2/Mianguang_Enclosure_V0.2.blend',
     'archive':str(dest.relative_to(MODELS)),'archive_bytes':dest.stat().st_size,'archive_sha256':sha(dest),
     'manifest':'v0.2/manifest.json','manifest_sha256':sha(OUT/'manifest.json')},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'files':len(files),'archive':str(dest.relative_to(REPO)),'bytes':dest.stat().st_size,'sha256':sha(dest),'geometry':checks['summary'],'frozen_pcb':'unchanged'},ensure_ascii=False))
