"""Export the already-reviewed V0.2 project; does not generate or reroute it.

Run from any directory while the exact saved V0.2 project is open in EasyEDA.
This intentionally overwrites release_v02 exports, invalidating its old manifest.
No manifest is produced until independent verification and documentation finish.
"""
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from eda_release_bridge import ROOT, PROJECT, PCB, SCHEMATIC, open_document, run

OUT = ROOT/'release_v02'
OUT.mkdir(exist_ok=True)

def json_write(name, data):
    (OUT/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')

def text_export(name, expression, document):
    value = run('return '+expression+';', 'export_'+name.replace('.','_'), document)
    (OUT/name).write_text(value)
    print(name, (OUT/name).stat().st_size, flush=True)

def file_export(name, expression, document):
    result = run('const file='+expression+';if(!file)throw Error("Export returned no file");return {name:file.name,bytes:Array.from(new Uint8Array(await file.arrayBuffer()))};', 'export_'+name.replace('.','_'), document)
    (OUT/name).write_bytes(bytes(result['bytes']))
    print(name, len(result['bytes']), flush=True)

def normalize_csv(name):
    path=OUT/name
    data=path.read_bytes()
    raw=data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
    delimiter='\t' if '\t' in raw.splitlines()[0] else ','
    rows=list(csv.reader(io.StringIO(raw), delimiter=delimiter))
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        csv.writer(stream).writerows(rows)

def main():
    open_document(SCHEMATIC)
    sch=run('await eda.sch_Document.save();return {details:await eda.sch_Drc.check(true,false,true),passed:await eda.sch_Drc.check(true,false,false)};', 'release_sch_check', SCHEMATIC)
    text_export('Mianguang_V0.2.esch', 'await eda.sys_FileManager.getDocumentSource()', SCHEMATIC)
    text_export('schematic_netlist.json', '(await eda.sch_ManufactureData.getNetlistFile()).text()', SCHEMATIC)
    file_export('Schematic_V0.2.png', 'await eda.sch_ManufactureData.getPngFile("Schematic_V0.2",{width:3500})', SCHEMATIC)
    open_document(PCB)
    pcb=run('await eda.pcb_Document.save();return {details:await eda.pcb_Drc.check(true,false,true),passed:await eda.pcb_Drc.check(true,false,false)};', 'release_pcb_check', PCB)
    if pcb['passed'] is not True or pcb['details']:
        raise RuntimeError('PCB DRC failed; refusing manufacturing export')
    json_write('native_checks.json', dict(project_uuid=PROJECT, release='V0.2', exported_at=datetime.now(timezone.utc).isoformat(), schematic=sch, pcb=pcb))
    text_export('Mianguang_V0.2.epcb', 'await eda.sys_FileManager.getDocumentSource()', PCB)
    text_export('pcb_netlist.json', '(await eda.pcb_ManufactureData.getNetlistFile()).text()', PCB)
    file_export('BOM_Mianguang_V0.2.csv', 'await eda.pcb_ManufactureData.getBomFile("BOM_Mianguang_V0.2","csv")', PCB)
    normalize_csv('BOM_Mianguang_V0.2.csv')
    file_export('BOM_Mianguang_V0.2.xlsx', 'await eda.pcb_ManufactureData.getBomFile("BOM_Mianguang_V0.2","xlsx")', PCB)
    file_export('PickPlace_Mianguang_V0.2.csv', 'await eda.pcb_ManufactureData.getPickAndPlaceFile("PickPlace_Mianguang_V0.2","csv")', PCB)
    normalize_csv('PickPlace_Mianguang_V0.2.csv')
    file_export('Gerber_Mianguang_V0.2.zip', 'await eda.pcb_ManufactureData.getGerberFile("Gerber_Mianguang_V0.2")', PCB)
    file_export('Mianguang_V0.2.epro2', 'await eda.sys_FileManager.getProjectFile("Mianguang_V0.2",undefined,"epro2")', PCB)
    file_export('PCB_Review_native.pdf', 'await eda.pcb_ManufactureData.getPdfFile("PCB_Review_V0.2")', PCB)
    from pypdf import PdfReader, PdfWriter
    native = OUT/'PCB_Review_native.pdf'
    reader = PdfReader(native)
    # Native report paginates its BOM variably; retain assembly and plotted layers.
    top = [i for i,p in enumerate(reader.pages) if 'MIANGUANG V0.2' in (p.extract_text() or '')]
    if len(top) != 1 or top[0]+2 != len(reader.pages)-1:
        raise RuntimeError('Unexpected native PDF page layout; inspect before extracting')
    writer = PdfWriter()
    for index in [0, top[0], top[0]+1, top[0]+2]:
        writer.add_page(reader.pages[index])
    writer.write(OUT/'PCB_Review_V0.2.pdf')
    (ROOT/'revision_v02').mkdir(exist_ok=True)
    native.replace(ROOT/'revision_v02/PCB_Review_native_final.pdf')

if __name__ == '__main__':
    main()
