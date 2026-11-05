"""Temporary visual fixture server; no database and no production data."""
import json
import math
import os
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace as Obj
from urllib.parse import parse_qs, urlparse
import sys

ROOT = Path(".design-preview").resolve()
APP = Path("platform/app").resolve()
sys.path.insert(0, str(APP))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.test_settings")
import django
django.setup()
from django.template import Context, Engine

BINDING = "10000000-0000-0000-0000-000000000001"


def context(query, path):
    now = datetime.now(timezone.utc)
    end = now.replace(second=0, microsecond=0)
    viewer = "viewer" in query
    states = [("fresh", "最近有新上报", 2), ("fresh", "最近有新上报", 5),
              ("expired", "观测已过期", 40), ("no_report", "超过60秒无新上报", 180),
              ("waiting", "等待首包", None), ("disabled", "已停用", 3600)]
    rows = []
    for i, (state, label, age) in enumerate(states):
        stamp = now - timedelta(seconds=age) if age is not None else None
        binding = Obj(pk=f"10000000-0000-0000-0000-{i+1:012d}",
            location_label_snapshot=f"松园试点 / {201+i//2} 室 / {i%2+1:02d} 床",
            resident_alias=f"演示住户 {chr(65+i)}", started_at=end - timedelta(days=3),
            ended_at=(end-timedelta(hours=1)) if "ended" in query else None,
            device=Obj(display_code=f"SIM-{i+1:03d}", is_simulator=True))
        snapshot = dict(state=state, label=label, work_label="待安装确认" if i==1 else "等待上报" if age is None else "工作条件就绪",
            occupancy="最近在床" if i==0 else "未知", rr=16 if i==0 else None, hr=72 if i==0 else None,
            rr_reason="有效" if i==0 else "安装未确认" if i==1 else "尚无观测" if age is None else "观测已过期",
            hr_reason="有效" if i==0 else "安装未确认" if i==1 else "尚无观测" if age is None else "观测已过期",
            lamp=dict(mode="auto", pwm=0, target=0) if state=="fresh" else None,
            received_at=stamp, captured_at=stamp, received_ms=round(stamp.timestamp()*1000) if stamp else "",
            captured_ms=round(stamp.timestamp()*1000) if stamp else "")
        rows.append(dict(binding=binding, snapshot=snapshot))
    if "long" in query:
        rows[0]["binding"].location_label_snapshot = "松园试点护理中心 / 东侧观察区二〇一房间 / 靠窗第一床"
        rows[0]["snapshot"]["hr_reason"] = "超出工程门控范围"
    counts=dict(bound=6, attention=1, not_fresh=4, fresh=2, expired=1, no_report=1, waiting=1, disabled=1)
    if "empty" in query:
        rows=[]
        counts={key:0 for key in counts}
    return dict(user=Obj(is_authenticated=path!="/login/", get_username="值班查看员" if viewer else "平台管理员"),
        request=Obj(resolver_match=Obj(url_name="overview" if path=="/" else "binding_detail")),
        can_manage=not viewer, can_export=not viewer, demo_mode=True, csrf_token="visual-fixture",
        rows=rows, counts=counts, sites=[Obj(pk=1,name="松园试点"),Obj(pk=2,name="青禾试点")], selected_site=None,
        unbound_devices=[Obj(display_code="SIM-007", is_simulator=True, enabled=True)],
        server_ms=round(now.timestamp()*1000), server_time=now.isoformat().replace("+00:00","Z"),
        binding=(rows or [dict(binding=Obj())])[0]["binding"], snapshot=rows[0]["snapshot"] if rows else {},
        initial_from=(end-timedelta(hours=8)).isoformat().replace("+00:00","Z"), initial_to=end.isoformat().replace("+00:00","Z"),
        form=Obj(errors="error" in query), next="/")


def series(query):
    now=datetime.now(timezone.utc)
    end=now.replace(second=0,microsecond=0)
    start=end-timedelta(hours=8)
    if "from" in query: start=datetime.fromisoformat(query["from"][0].replace("Z","+00:00"))
    if "to" in query: end=datetime.fromisoformat(query["to"][0].replace("Z","+00:00"))
    buckets=[]
    for i in range(int((end-start).total_seconds()/60)):
        gap=26 <= i%120 <= 36 or i%120==69 or i%120==71
        buckets.append(dict(minute=(start+timedelta(minutes=i)).isoformat().replace("+00:00","Z"),
            rr_bpm=None if gap else round(16+1.4*math.sin(i/21)+0.5*math.sin(i/4)),
            hr_bpm=None if gap else round(72+4*math.sin(i/17)+2*math.sin(i/4))))
    expected=len(buckets)*6
    received=sum(b["rr_bpm"] is not None for b in buckets)*6
    return dict(server_time=now.isoformat().replace("+00:00","Z"),
        effective_range=dict(from_=start.isoformat(),to=end.isoformat()),
        summary=dict(expected_slots=expected,received_slots=received,rr_valid_slots=received,hr_valid_slots=received,
                     report_completeness=received/expected,rr_valid_ratio=1,hr_valid_ratio=1),buckets=buckets)


def handler(templates, static):
    engine=Engine(dirs=[str(templates)], libraries={"static":"django.templatetags.static"})
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url=urlparse(self.path)
            query=parse_qs(url.query,keep_blank_values=True)
            if url.path.startswith("/static/"):
                target=static/url.path.removeprefix("/static/")
                if not target.is_file(): self.send_error(404);return
                data=target.read_bytes()
                content_type="text/css" if target.suffix==".css" else "text/javascript"
            elif url.path.startswith("/api/"):
                result=series(query)
                result["effective_range"]["from"]=result["effective_range"].pop("from_")
                data=json.dumps(result).encode()
                content_type="application/json"
            else:
                template="registration/login.html" if url.path=="/login/" else "monitoring/_overview.html" if url.path.startswith("/fragments/") else "monitoring/binding.html" if url.path.startswith("/bindings/") else "monitoring/overview.html"
                data=engine.get_template(template).render(Context(context(query,url.path))).encode()
                content_type="text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type",content_type)
            self.end_headers()
            self.wfile.write(data)
        def log_message(self,*args): pass
    return Handler


Thread(target=ThreadingHTTPServer(("127.0.0.1",8860),handler(ROOT/"before/templates",ROOT/"before/static")).serve_forever,daemon=True).start()
print("Visual fixture: before :8860; current :8861",flush=True)
ThreadingHTTPServer(("127.0.0.1",8861),handler(APP/"monitoring/templates",APP/"monitoring/static")).serve_forever()
