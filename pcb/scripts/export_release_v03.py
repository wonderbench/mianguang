"""Export the reviewed V0.3 candidate after both native strict checks pass.

This does not generate, fix, or route the design. The operator must finish the
save/reopen persistence review before running it. Intermediate export files stay
under verification/local; frozen releases (manifest.json present) are refused.
"""

import csv
import hashlib
import io
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from eda_bridge_v03 import PCB, PROJECT, REPORTS, ROOT, SCHEMATIC, open_document, run

OUT = ROOT / "release_v03"
RELEASE = "V0.3"
EXPECTED_REFERENCES = set(
    "C1 C2 C3 C4 C5 D1 D2 F1 J1 J2 J3 J4 J5 JP1 JP2 JP3 Q1 R1 R2 R3 R4 R5 U1".split()
)
SOURCE_NORMALIZATION = {
    "record_header_ignored": ["ticket"],
    "document_header_ignored": ["client", "updateTime", "version"],
    "records": "Final records keyed by document type/UUID and record type/ID; all payload fields retained",
    "project_footprint_comparison": "Exclude validated ELE_PLACEHOLDER allocation counters only; project serialization rebuilds these after deletion. All actual records remain exact.",
}


def stable_documents(source):
    """Compare final native records, ignoring only observed bookkeeping changes.

    Save/reopen in EDA 4.1.78 changes DOCHEAD client/updateTime/version and record
    ticket numbers. No geometry, rules, attributes or other record bodies are
    excluded here. Deleted records stay deleted, and new records stay visible.
    """
    documents, current = {}, None
    for line_number, line in enumerate(source.splitlines(), 1):
        if not line.strip():
            continue
        if "||" not in line:
            raise RuntimeError(f"Unrecognized native source line {line_number}")
        raw_head, raw_data = line.split("||", 1)
        head = json.loads(raw_head)
        body = raw_data.rstrip("|")
        data = json.loads(body) if body.strip() else None
        head = {key: value for key, value in head.items() if key != "ticket"}
        if head.get("type") == "DOCHEAD":
            if not isinstance(data, dict):
                raise RuntimeError("Invalid document header")
            current = (data.get("docType"), data.get("uuid"))
            normalized = {key: value for key, value in data.items()
                          if key not in SOURCE_NORMALIZATION["document_header_ignored"]}
            doc = documents.setdefault(current, {"records": {}})
            doc["header"] = [head, normalized]
        else:
            if current is None:
                raise RuntimeError("Native source record precedes document header")
            key = (head.get("type"), str(head.get("id", "")))
            if data in (None, ""):
                documents[current]["records"].pop(key, None)
            else:
                documents[current]["records"][key] = [head, data]
    if not documents:
        raise RuntimeError("No native documents found")
    return {key: {"header": value["header"],
                  "records": [value["records"][record] for record in sorted(value["records"])]}
            for key, value in documents.items()}


def stable_source(source):
    docs = stable_documents(source)
    return json.dumps([[list(key), docs[key]] for key in sorted(docs)], ensure_ascii=False, sort_keys=True)


def source_sha(source):
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def require_same_source(before, after, label):
    if not isinstance(before, str) or not isinstance(after, str) or stable_source(before) != stable_source(after):
        raise RuntimeError(f"{label} native records changed; candidate was not published")


FOOTPRINT_SNAPSHOT_JS = (
    "async function captureFootprints(){const references={},sources={};"
    "for(const component of await eda.pcb_PrimitiveComponent.getAll()){"
    "const ref=component.getState_Designator(),fp=component.getState_Footprint();"
    'if(!ref||!fp||!fp.uuid||references[ref])throw Error("Invalid component footprint identity");'
    "references[ref]=fp.uuid;if(!(fp.uuid in sources)){"
    "const source=await eda.lib_Footprint.getDocumentSource(fp.uuid,"
    + json.dumps(PROJECT)
    + ');if(!source)throw Error("Missing actual project footprint "+fp.uuid);sources[fp.uuid]=source;}}'
    "return {references,sources};}"
)


def require_same_footprints(before, after):
    if set(before.get("references", {})) != EXPECTED_REFERENCES:
        raise RuntimeError("PCB must contain exactly the reviewed 23 component designators")
    if before["references"] != after.get("references"):
        raise RuntimeError("Component/footprint association changed during checks/export")
    if set(before.get("sources", {})) != set(after.get("sources", {})):
        raise RuntimeError("Used footprint set changed during checks/export")
    for uuid, source in before["sources"].items():
        require_same_source(source, after["sources"][uuid], "Footprint " + uuid)


def package_footprint_state(document):
    """Project serialization rebuilds allocation counters after tombstones.

    Observed in D1/D2/F1/R0603/U1 after the PRECHECK03 silk edits: placeholder
    IDs, counts and grouping change, while every actual final record is equal.
    This exception applies only to package-vs-snapshot comparison. DRC/export
    before/after checks still compare the complete stable source.
    """
    records = []
    for head, data in document["records"]:
        if head.get("type") != "ELE_PLACEHOLDER":
            records.append([head, data])
            continue
        identifier = head.get("id", "")
        if (set(head) != {"type", "id"}
                or not isinstance(identifier, str)
                or not identifier.startswith("placeholder")
                or not identifier[len("placeholder"):].isdigit()
                or not isinstance(data, dict)
                or set(data) != {"dataType", "max"}
                or data["dataType"] not in {"ATTR", "FILL", "POLY", "PAD"}
                or type(data["max"]) is not int or data["max"] < 0):
            raise RuntimeError("Unrecognized footprint allocation placeholder; inspect before export")
    return {"header": document["header"], "records": records}


def require_project_footprints(path, snapshot):
    """The full package must contain the same final used footprint records."""
    exported = {}
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if Path(name).suffix.lower() not in (".epru", ".efoo"):
                continue
            for key, value in stable_documents(archive.read(name).decode("utf-8-sig")).items():
                if key[0] != "FOOTPRINT":
                    continue
                if key in exported and exported[key] != value:
                    raise RuntimeError("Package has conflicting copies of footprint " + str(key[1]))
                exported[key] = value
    for uuid, source in snapshot["sources"].items():
        expected = stable_documents(source)
        key = ("FOOTPRINT", uuid)
        if (key not in expected or key not in exported
                or package_footprint_state(expected[key]) != package_footprint_state(exported[key])):
            raise RuntimeError("Project package footprint differs from the checked source: " + uuid)


def ensure_unfrozen(directory):
    if (directory / "manifest.json").exists():
        raise RuntimeError(f"Refusing to overwrite frozen release: {directory}")


def require_clean(result, label):
    if (
        not isinstance(result, dict)
        or result.get("saved") is not True
        or result.get("passed") is not True
        or result.get("details") != []
    ):
        raise RuntimeError(f"{label} strict check/save failed: {result!r}")


def json_write(directory, name, value):
    (directory / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def text_export(directory, name, expression, document):
    value = run("return " + expression + ";", "export_" + name, document)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Empty or invalid text export: {name}")
    (directory / name).write_text(value, encoding="utf-8")
    print(name, (directory / name).stat().st_size, flush=True)
    return value


def file_export(directory, name, expression, document):
    result = run(
        "const file=" + expression + ';if(!file)throw Error("No export file");'
        + "return {name:file.name,bytes:Array.from(new Uint8Array(await file.arrayBuffer()))};",
        "export_" + name,
        document,
    )
    if not isinstance(result, dict) or not result.get("bytes"):
        raise RuntimeError(f"Empty or invalid binary export: {name}")
    data = bytes(result["bytes"])
    (directory / name).write_bytes(data)
    print(name, len(data), flush=True)


def normalize_csv(path):
    data = path.read_bytes()
    text = data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    if not text.strip():
        raise RuntimeError(f"Empty CSV: {path.name}")
    delimiter = "\t" if "\t" in text.splitlines()[0] else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if len(rows) < 2 or len(rows[0]) < 2:
        raise RuntimeError(f"Invalid CSV table: {path.name}")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream).writerows(rows)


def extract_review_pdf(native, output):
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(native)
    top = [
        i for i, page in enumerate(reader.pages)
        if "MIANGUANG V0.3" in (page.extract_text() or "")
    ]
    if len(top) != 1 or top[0] < 1 or top[0] + 2 != len(reader.pages) - 1:
        raise RuntimeError("Unexpected native PDF layout; inspect before extracting")
    writer = PdfWriter()
    for index in (0, top[0], top[0] + 1, top[0] + 2):
        writer.add_page(reader.pages[index])
    writer.write(output)


def main():
    # Check the PDF dependency before asking EDA to perform any work.
    import pypdf  # noqa: F401

    ensure_unfrozen(OUT)
    REPORTS.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix="export_candidate_", dir=REPORTS))
    started = datetime.now(timezone.utc).isoformat()

    open_document(SCHEMATIC)
    sch = run(
        "const saved=await eda.sch_Document.save();"
        "const sourceBefore=await eda.sys_FileManager.getDocumentSource();"
        "const details=await eda.sch_Drc.check(true,false,true);"
        "const passed=await eda.sch_Drc.check(true,false,false);"
        "const sourceAfter=await eda.sys_FileManager.getDocumentSource();"
        "return {saved,details,passed,sourceBefore,sourceAfter};",
        "strict_schematic", SCHEMATIC,
    )
    require_clean(sch, "Schematic")
    require_same_source(sch["sourceBefore"], sch["sourceAfter"], "Schematic during DRC")
    open_document(PCB)
    pcb = run(
        FOOTPRINT_SNAPSHOT_JS
        + "const saved=await eda.pcb_Document.save();"
        + "const sourceBefore=await eda.sys_FileManager.getDocumentSource();"
        + "const footprintsBefore=await captureFootprints();"
        + "const details=await eda.pcb_Drc.check(true,false,true);"
        + "const passed=await eda.pcb_Drc.check(true,false,false);"
        + "const sourceAfter=await eda.sys_FileManager.getDocumentSource();"
        + "const footprintsAfter=await captureFootprints();"
        + "return {saved,details,passed,sourceBefore,sourceAfter,footprintsBefore,footprintsAfter};",
        "strict_pcb", PCB,
    )
    require_clean(pcb, "PCB")
    require_same_source(pcb["sourceBefore"], pcb["sourceAfter"], "PCB during DRC")
    require_same_footprints(pcb["footprintsBefore"], pcb["footprintsAfter"])

    open_document(SCHEMATIC)
    sch_source = text_export(staged, "Mianguang_V0.3.esch", "await eda.sys_FileManager.getDocumentSource()", SCHEMATIC)
    require_same_source(sch["sourceAfter"], sch_source, "Schematic since DRC")
    text_export(staged, "schematic_netlist.json", "await (await eda.sch_ManufactureData.getNetlistFile()).text()", SCHEMATIC)
    file_export(staged, "Schematic_V0.3.png", 'await eda.sch_ManufactureData.getPngFile("Schematic_V0.3",{width:3500})', SCHEMATIC)

    open_document(PCB)
    pcb_source = text_export(staged, "Mianguang_V0.3.epcb", "await eda.sys_FileManager.getDocumentSource()", PCB)
    require_same_source(pcb["sourceAfter"], pcb_source, "PCB since DRC")
    text_export(staged, "pcb_netlist.json", "await (await eda.pcb_ManufactureData.getNetlistFile()).text()", PCB)
    for extension in ("csv", "xlsx"):
        name = "BOM_Mianguang_V0.3." + extension
        file_export(staged, name, f'await eda.pcb_ManufactureData.getBomFile("BOM_Mianguang_V0.3","{extension}")', PCB)
    normalize_csv(staged / "BOM_Mianguang_V0.3.csv")
    file_export(staged, "PickPlace_Mianguang_V0.3.csv", 'await eda.pcb_ManufactureData.getPickAndPlaceFile("PickPlace_Mianguang_V0.3","csv")', PCB)
    normalize_csv(staged / "PickPlace_Mianguang_V0.3.csv")
    file_export(staged, "Gerber_Mianguang_V0.3.zip", 'await eda.pcb_ManufactureData.getGerberFile("Gerber_Mianguang_V0.3")', PCB)
    file_export(staged, "Mianguang_V0.3.epro2", 'await eda.sys_FileManager.getProjectFile("Mianguang_V0.3",undefined,"epro2")', PCB)
    require_project_footprints(staged / "Mianguang_V0.3.epro2", pcb["footprintsAfter"])
    file_export(staged, "PCB_Review_native.pdf", 'await eda.pcb_ManufactureData.getPdfFile("PCB_Review_V0.3")', PCB)
    extract_review_pdf(staged / "PCB_Review_native.pdf", staged / "PCB_Review_V0.3.pdf")

    # A user/editor change during the sequential exports invalidates the whole run.
    for document, expected, label in ((PCB, pcb_source, "PCB"), (SCHEMATIC, sch_source, "SCH")):
        open_document(document)
        current = run("return await eda.sys_FileManager.getDocumentSource();", "source_after_export_" + label, document)
        require_same_source(expected, current, label + " during export")
    open_document(PCB)
    footprints_final = run(FOOTPRINT_SNAPSHOT_JS + "return await captureFootprints();", "footprints_after_export", PCB)
    require_same_footprints(pcb["footprintsAfter"], footprints_final)

    json_write(staged, "native_checks.json", {
        "project_uuid": PROJECT,
        "release": RELEASE,
        "strict": True,
        "started_at": started,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "schematic": {key: sch[key] for key in ("saved", "details", "passed")},
        "pcb": {key: pcb[key] for key in ("saved", "details", "passed")},
        "source_sha256": {
            name: hashlib.sha256((staged / name).read_bytes()).hexdigest()
            for name in ("Mianguang_V0.3.esch", "Mianguang_V0.3.epcb", "Mianguang_V0.3.epro2")
        },
        "native_records_unchanged_since_drc": True,
        "source_comparison": SOURCE_NORMALIZATION,
        "checked_source_sha256": {
            domain: {phase: source_sha(result[phase]) for phase in ("sourceBefore", "sourceAfter")}
            for domain, result in (("schematic", sch), ("pcb", pcb))
        },
        "component_footprints": footprints_final["references"],
        "footprint_source_sha256": {uuid: source_sha(source) for uuid, source in footprints_final["sources"].items()},
        "footprint_semantic_sha256": {uuid: source_sha(stable_source(source)) for uuid, source in footprints_final["sources"].items()},
        "project_footprints_match_checked_sources": True,
        "save_reopen_review": "Required separately before this export; this script does not claim a reopen test",
    })
    ensure_unfrozen(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    for source in staged.iterdir():
        if source.name != "PCB_Review_native.pdf":
            ensure_unfrozen(OUT)
            shutil.copyfile(source, OUT / source.name)
    print(f"Exported candidate to {OUT}; native PDF retained at {staged}", flush=True)
    print("No manifest/release approval was generated. Run independent QA and visual review before freezing.", flush=True)


if __name__ == "__main__":
    main()
