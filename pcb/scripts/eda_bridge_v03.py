"""Guarded bridge for the independent Mianguang V0.3 working project.

Importing this module never connects to EDA or creates files. Every execution
resolves a matching window by project identity instead of using the active one.
"""

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
REPORTS = REPO / "verification/local/pcb_v03_work"
PROJECT = "f4312b686e296bdd77a0ad71377a658c7f15b61fee4283ea042b46d776ba0045"
PROJECT_NAME = "眠光 睡眠雷达夜灯 V0.3"
PCB = "d1f2f1e2dbed9b60"
SCHEMATIC = "a83dc430db547724"
URL = "http://127.0.0.1:49620"


def request(code, window, timeout=120):
    """Execute in an explicitly identified window; do not use implicit routing."""
    req = urllib.request.Request(
        URL + "/execute",
        json.dumps({"code": code, "windowId": window}).encode("utf-8"),
        {"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode("utf-8", errors="replace")) from exc
    if result.get("success") is not True:
        raise RuntimeError(result)
    if result.get("windowId") != window:
        raise RuntimeError("Bridge returned a result for a different window")
    return result.get("result")


def resolve_window():
    """Require exactly one connected window with the fixed V0.3 UUID and name."""
    with urllib.request.urlopen(URL + "/health", timeout=10) as response:
        health = json.load(response)
    if health.get("service") != "easyeda-bridge":
        raise RuntimeError("Endpoint is not the EasyEDA bridge")
    with urllib.request.urlopen(URL + "/eda-windows", timeout=10) as response:
        windows = json.load(response)["windows"]
    matches = []
    for window in windows:
        if not window.get("connected"):
            continue
        info = request(
            "return await eda.dmt_Project.getCurrentProjectInfo();",
            window["windowId"],
        )
        if (
            isinstance(info, dict)
            and info.get("uuid") == PROJECT
            and info.get("friendlyName") == PROJECT_NAME
        ):
            matches.append(window["windowId"])
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one V0.3 window; got {matches}")
    return matches[0]


def run(code, tag, document=None, timeout=120):
    """Run documented API code under project/document guards and record result."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", tag):
        raise ValueError("Report tag must be a simple file name")
    if document is not None and document not in (PCB, SCHEMATIC):
        raise ValueError("Document does not belong to the V0.3 release")
    guard = (
        "const project=await eda.dmt_Project.getCurrentProjectInfo();"
        "if(!project||project.uuid!=="
        + json.dumps(PROJECT)
        + "||project.friendlyName!=="
        + json.dumps(PROJECT_NAME)
        + ')throw Error("Wrong V0.3 project");'
    )
    if document is not None:
        guard += (
            "const document=await eda.dmt_SelectControl.getCurrentDocumentInfo();"
            "if(!document||document.uuid!=="
            + json.dumps(document)
            + ')throw Error("Wrong V0.3 document");'
        )
    result = request(guard + code, resolve_window(), timeout=timeout)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{tag}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def open_document(uuid):
    if uuid not in (PCB, SCHEMATIC):
        raise ValueError("Refusing to open a document outside the release")
    result = run(
        "const tab=await eda.dmt_EditorControl.openDocument("
        + json.dumps(uuid)
        + ');if(!tab)throw Error("Document open failed");'
        + "await new Promise(r=>setTimeout(r,1000));"
        + "return await eda.dmt_SelectControl.getCurrentDocumentInfo();",
        "open_" + uuid,
    )
    if not isinstance(result, dict) or result.get("uuid") != uuid:
        raise RuntimeError("Opened document did not become the current document")
    return result


open_doc = open_document
