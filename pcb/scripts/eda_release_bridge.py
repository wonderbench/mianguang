"""Project-guarded bridge for the saved V0.2 release; never uses active window."""
import json
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = '8955499269fd1ac3a71ec0ff5dc961906055730dccf1062637e2bf1a70a879b8'
PCB = 'd1f2f1e2dbed9b60'
SCHEMATIC = 'a83dc430db547724'
URL = 'http://127.0.0.1:49620'

def request(code, window, timeout=120):
    req = urllib.request.Request(URL+'/execute', json.dumps({'code': code, 'windowId': window}).encode(), {'Content-Type':'application/json'})
    try:
        result = json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode()) from exc
    if not result.get('success'):
        raise RuntimeError(result)
    return result['result']

def resolve_window():
    windows = json.load(urllib.request.urlopen(URL+'/eda-windows'))['windows']
    matches = []
    for window in windows:
        if not window['connected']:
            continue
        info = request('return await eda.dmt_Project.getCurrentProjectInfo();', window['windowId'])
        if info and info.get('uuid') == PROJECT and info.get('friendlyName') == '眠光 睡眠雷达夜灯 V0.2':
            matches.append(window['windowId'])
    if len(matches) != 1:
        raise RuntimeError(f'Expected exactly one V0.2 window; got {matches}')
    return matches[0]

def run(code, tag, document=None):
    guard = 'const project=await eda.dmt_Project.getCurrentProjectInfo();if(project.uuid!=='+json.dumps(PROJECT)+')throw Error("Wrong release project");'
    if document:
        guard += 'const document=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(document.uuid!=='+json.dumps(document)+')throw Error("Wrong release document");'
    result = request(guard+code, resolve_window())
    (ROOT/'reports').mkdir(exist_ok=True)
    (ROOT/'reports'/f'{tag}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result

def open_document(uuid):
    return run('await eda.dmt_EditorControl.openDocument('+json.dumps(uuid)+');await new Promise(r=>setTimeout(r,1500));return await eda.dmt_SelectControl.getCurrentDocumentInfo();', 'release_open_document')
