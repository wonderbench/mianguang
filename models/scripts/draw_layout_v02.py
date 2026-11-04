"""Write a source-backed SVG mechanical layout; Python standard library only.

Run from any directory. Uses frozen V0.2 placement CSV and extracted hole/pad
coordinates. Component heights remain labelled procurement assumptions (*).
"""
from pathlib import Path
import csv
import hashlib
import html
import json
import math
import unicodedata
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'models/v0.2/Mechanical_Layout_V0.2.svg'
REF = ROOT / 'models/mechanical/pcb_v02_reference.json'
CSV = ROOT / 'pcb/release_v02/PickPlace_Mianguang_V0.2.csv'
reference = json.loads(REF.read_text())
with CSV.open(encoding='utf-8-sig', newline='') as stream:
    placement = {r['Designator']: r for r in csv.DictReader(stream)}
components = {r['designator']: r for r in reference['components']}

def coord(ref):
    r = placement[ref]
    p = tuple(float(r[k].removesuffix('mm')) for k in ('Ref X', 'Ref Y'))
    assert all(abs(a-b) < .001 for a, b in zip(p, components[ref]['reference_xy_mm']))
    return p

def number(v):
    return f'{v:g}'

INK = '#243a3b'
MUTED = '#627776'
TEAL = '#217e79'
BLUE = '#486a9d'
GOLD = '#c7a46a'
GREEN = '#5d937d'
LIGHT = '#eaf0ec'
AMBER = '#8a6327'
svg = []
text_checks = []

def add(s):
    svg.append(s)

def text(x, y, value, size=18, color=INK, weight=400, anchor='start', max_width=None):
    # Conservative width check for the selected Chinese sans-serif stack.
    approx = sum(1 if unicodedata.east_asian_width(c) in ('W', 'F') else .61 for c in value) * size
    if max_width is not None:
        assert approx <= max_width, (value, approx, max_width)
    left = x if anchor == 'start' else x - approx if anchor == 'end' else x - approx / 2
    assert left >= 20 and left + approx <= 1580, (value, left, approx)
    assert 20 <= y - size <= 980, (value, y)
    text_checks.append({'text': value, 'width_estimate': round(approx, 1)})
    add(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{html.escape(value)}</text>')

def rect(x, y, w, h, fill, stroke='none', sw=1, r=0, dash=None, opacity=1):
    ds = f' stroke-dasharray="{dash}"' if dash else ''
    add(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" opacity="{opacity}"{ds}/>')

def line(x1, y1, x2, y2, color=MUTED, sw=1.4, dash=None, arrow=False):
    ds = f' stroke-dasharray="{dash}"' if dash else ''
    ar = ' marker-end="url(#arrow)"' if arrow else ''
    add(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{color}" stroke-width="{sw}"{ds}{ar}/>')

def circle(x, y, r, fill='white', stroke=INK, sw=1.5):
    add(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

def hdim(x1, x2, y, label, color=MUTED):
    line(x1, y, x2, y, color)
    for x in (x1, x2):
        line(x, y-5, x, y+5, color)
    text((x1+x2)/2, y-8, label, 16, color, anchor='middle')

def poly(points, fill='none', stroke=INK, width=2, dash=None, opacity=1):
    ds = f' stroke-dasharray="{dash}"' if dash else ''
    ps = ' '.join(f'{x:.2f},{y:.2f}' for x, y in points)
    add(f'<polygon points="{ps}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" stroke-linejoin="round" opacity="{opacity}"{ds}/>')

add('<?xml version="1.0" encoding="UTF-8"?>')
add('<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000" role="img" aria-labelledby="title desc">')
add('<title id="title">眠光 V0.2 外壳关键机械空间示意</title>')
add('<desc id="desc">三栏工程示意：冻结载板孔位和接口、侧剖叠层和雷达间距、桌面壁挂共用转轴与前盖固定孔。采购包络带星号，实物未验证。</desc>')
add('<defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="#627776"/></marker><pattern id="wallHatch" width="8" height="8" patternUnits="userSpaceOnUse"><path d="M0,8 L8,0" stroke="#bcc8c6" stroke-width="1"/></pattern></defs>')
add('<g font-family="Noto Sans CJK SC, PingFang SC, Microsoft YaHei, sans-serif">')
rect(0, 0, 1600, 1000, '#f7f8f5')
text(40, 62, '眠光 V0.2 · 外壳关键机械空间', 34, weight=650)
text(40, 96, 'PCB 孔位来自冻结工程；单位 mm；正投影 / 剖面示意', 19, MUTED)
text(1560, 94, '2026-11-04', 18, MUTED, anchor='end')
for x in (40, 560, 1080):
    rect(x, 126, 480, 794, 'white', '#dbe3dc', 1.2, r=18)

# 1. Carrier top view. Scale here is equal in X and Y.
text(64, 168, '01  载板孔位与接口', 24, weight=650)
text(64, 198, '元件面朝观察者；原点在板左下', 16, MUTED)
bx, by, scale = 96., 550., 5.6
def board_point(x, y):
    return bx + x*scale, by - y*scale

rect(bx, by-56*scale, 66*scale, 56*scale, '#eef4ee', GREEN, 2)
hdim(bx, bx+66*scale, 222, '66')
line(bx, 232, bx, 214)
line(bx+66*scale, 232, bx+66*scale, 214)
line(78, by-56*scale, 78, by)
line(73, by-56*scale, 83, by-56*scale)
line(73, by, 83, by)
text(72, 400, '56', 16, MUTED, anchor='end')
holes = reference['board']['mount_hole_pattern_nominal_mm']
assert holes == [[5, 5], [61, 5], [5, 51], [61, 51]]
for x, y in holes:
    px, py = board_point(x, y)
    circle(px, py, 2.7/2*scale, 'white', INK, 1.7)
    line(px-11, py, px+11, py, '#a1b1a7', 1)
    line(px, py-11, px, py+11, '#a1b1a7', 1)

xiao = reference['xiao']
x0, y0, x1, y1 = xiao['official_v13_edge_cuts_registered_bbox_xyxy_mm']
px, py = board_point(x0, y1)
rect(px, py, (x1-x0)*scale, (y1-y0)*scale, '#dae6df', GREEN, 1.5, r=6)
for x in xiao['socket_row_x_mm']:
    ys = sorted({round(p['center_xy_mm'][1], 5) for p in components['U1']['pads'] if abs(p['center_xy_mm'][0]-x) < .001})
    for y in ys:
        px, py = board_point(x, y)
        rect(px-4, py-4, 8, 8, GOLD, '#9e8252', 1, r=1)
ux, uy = board_point(33, 29.51740096)
text(ux, uy+2, 'U1', 18, TEAL, 600, anchor='middle')
text(ux, uy+24, 'XIAO', 14, TEAL, anchor='middle')
px, py = board_point(29, 41.7)
rect(px, py, 8*scale, 3*scale, '#a7b7b3', '#607b76', 1.2, r=3)
line(ux, py-6, ux, 274, TEAL, 1.8, arrow=True)
text(ux, 261, 'USB 朝 +Y', 16, TEAL, 600, anchor='middle')
row_x = [board_point(x, 0)[0] for x in xiao['socket_row_x_mm']]
hdim(row_x[0], row_x[1], 462, '15.24 排距', TEAL)

offsets = {'J1':(-18,18), 'J2':(5,-12), 'J3':(15,5), 'J4':(-10,-14),
           'J5':(-5,-31), 'JP1':(-2,23), 'JP2':(-9,23), 'JP3':(-2,-12)}
for ref in offsets:
    x, y = coord(ref)
    px, py = board_point(x, y)
    pads = components[ref]['pads']
    xs, ys = [p['center_xy_mm'][0] for p in pads], [p['center_xy_mm'][1] for p in pads]
    xx0, yy0 = board_point(min(xs)-1.3, max(ys)+1.3)
    rect(xx0, yy0, (max(xs)-min(xs)+2.6)*scale, (max(ys)-min(ys)+2.6)*scale,
         '#d0ddd6', '#7c9688', 1, r=2)
    for pad in pads:
        ppx, ppy = board_point(*pad['center_xy_mm'])
        circle(ppx, ppy, 2.2, GOLD, '#967a45', .8)
    dx, dy = offsets[ref]
    text(px+dx, py+dy, ref, 14, INK, 600, anchor='middle')
text(64, 588, '4 × Ø2.7 通孔 · 孔距 56 × 46', 20, TEAL, 600, max_width=432)
text(64, 618, '(5,5)  (61,5)  (5,51)  (61,51)', 17, MUTED, max_width=432)
line(64, 642, 496, 642, '#e1e8e1')
text(64, 674, '接口中心坐标（载板 X / Y）', 18, weight=600)
functions = {'J1':'5V', 'J2':'雷达', 'J3':'夜灯', 'J4':'按键', 'J5':'光照',
             'JP1':'电源隔离', 'JP2':'TX', 'JP3':'RX'}
rows = [('J1','J2'), ('J3','J4'), ('J5','JP1'), ('JP2','JP3')]
for index, row in enumerate(rows):
    for column, ref in enumerate(row):
        x, y = coord(ref)
        label = f'{ref} {functions[ref]}  ({number(x)},{number(y)})'
        text(64+column*222, 711+index*34, label, 15, MUTED, max_width=215)
text(64, 875, '仅标接口与孔；其余元件未展开。', 16, MUTED, max_width=432)

# 2. Side cutaway, with a common depth scale. Vertical placement is schematic.
text(584, 168, '02  侧剖与叠层', 24, weight=650)
text(584, 198, '前侧 ← 机身 Y 轴 → 后侧', 16, MUTED)
def depth(y):
    return 620 + (y+23.6)*7.2
front, rear = depth(-23.6), depth(22)
rect(front, 252, depth(-22)-front, 288, '#e1e5df', '#96a79d', 1)
rect(depth(19.6), 252, rear-depth(19.6), 288, '#e1e5df', '#96a79d', 1)
text(623, 571, '前板', 16, MUTED, anchor='middle')
text(941, 571, '背壳', 16, MUTED, anchor='middle')
rect(depth(-22), 276, depth(-17.5)-depth(-22), 74, '#e8f3f1')
hdim(depth(-22), depth(-17.5), 240, '4.5', TEAL)
line(depth(-17.5), 258, depth(-17.5), 358, TEAL, 2.8)
rect(depth(-17.3), 268, 7.2, 80, GREEN, '#426e5b', 1)
rect(depth(-16.3), 278, 8*7.2, 60, '#eef2f5', BLUE, 1.5, dash='6 4')
text((depth(-16.3)+depth(-8.3))/2, 313, '8*', 18, BLUE, 600, anchor='middle')
text(depth(-17.5)+3, 379, '雷达', 16, TEAL, 600, anchor='middle')
text(depth(-10), 362, '背面预留', 15, BLUE, anchor='middle')
line(depth(-22), 252, depth(-22), 552, '#aebeb4', 1, '4 4')

# Carrier PCB centre12.2, top11.4, back13.0. Top components point toward -Y.
rect(depth(11.4), 395, 1.6*7.2, 135, GREEN, '#426e5b', 1)
rect(depth(2.9), 423, 8.5*7.2, 31, GOLD, '#987b48', 1)
rect(depth(.4), 423, 2.5*7.2, 31, '#c0c7c1', '#829087', 1)
rect(depth(-1.2), 406, 1.6*7.2, 83, GREEN, '#426e5b', 1)
rect(depth(-4.4), 420, 3.2*7.2, 53, '#566a66', '#3c504b', 1)
text((depth(2.9)+depth(11.4))/2, 444, '8.5*', 16, '#654d24', 600, anchor='middle')
text(depth(-3), 511, 'XIAO 叠层*', 16, TEAL, 600, anchor='middle')
text(depth(12.2)+9, 389, '载板', 16, TEAL, 600, anchor='middle')
hdim(depth(-4.4), depth(11.4), 550, '总预留 15.8*', TEAL)

line(584, 597, 1016, 597, '#e1e8e1')
stack_rows = [
    ('载板', '中心 Y12.2；顶面11.4 / 背面13.0', GREEN),
    ('插接', '排母8.5* + 排针塑胶2.5* = 11.0*', GOLD),
    ('模组', 'XIAO板厚1.6* + 元件高3.2*', GREEN),
    ('前界', '最前元件到 Y−4.4', '#566a66'),
    ('雷达', '天线前面−17.5；前板内面−22', TEAL),
    ('背界', '雷达背面−16.3 + 8* → Y−8.3', BLUE),
]
for i, (tag, value, color) in enumerate(stack_rows):
    y = 630+i*34
    rect(585, y-13, 10, 10, color, r=2)
    text(605, y, tag, 16, color, 600)
    text(652, y, value, 15, MUTED, max_width=362)
rect(584, 841, 432, 52, '#faf4e7', r=8)
text(598, 863, '* 采购 / 插接包络，待到货量测。', 16, AMBER, max_width=406)
text(598, 884, '高度方向为示意；深度按同一比例绘制。', 14, AMBER, max_width=406)

# 3. Common-pivot side view. Y and Z use the same scale.
text(1104, 168, '03  桌面与壁挂', 24, weight=650)
text(1104, 198, '两种安装叠图；壁挂不使用底座', 16, MUTED)
line(1106, 225, 1132, 225, '#84968e', 3)
text(1139, 231, '0°', 16, MUTED)
line(1212, 225, 1238, 225, TEAL, 2.5, '6 4')
text(1245, 231, '桌面30°', 16, TEAL)
line(1378, 225, 1404, 225, BLUE, 2.5, '6 4')
text(1411, 231, '壁挂45°', 16, BLUE)
def side(y, z):
    return 1240+y*2.2, 635-z*2.2
def rotated(y, z, angle):
    a = math.radians(angle)
    dy, dz = y-34, z-90
    return side(34+dy*math.cos(a)-dz*math.sin(a),
                90+dy*math.sin(a)+dz*math.cos(a))

wall_x = side(95, 0)[0]
rect(wall_x, 274, 12, 361, 'url(#wallHatch)')
line(wall_x, 274, wall_x, 635, '#a3b0aa', 2)
text(wall_x-3, 268, '墙面 Y95', 16, MUTED, anchor='end')
neutral = [(-23.6,32), (22,32), (22,148), (-23.6,148)]
poly([side(*p) for p in neutral], '#f1f3ee', '#84968e', 1.8)
for angle, color in ((30,TEAL), (45,BLUE)):
    poly([rotated(*p, angle) for p in neutral], 'none', color, 2, '7 5')
# Deliberately diagrammatic arm lines; full construction lives in the .blend.
px, py = side(34, 90)
line(px, py, wall_x, py, '#aab7b0', 5)
sx, sy = side(78, 90)
line(sx, sy, *side(78, 7), '#8c9e95', 7)
base_x, base_top = side(-38, 7)
rect(base_x, base_top, 120*2.2, 5*2.2, '#d9e2db', '#83998c', 1.4, r=3)
line(1110, 635, 1497, 635, '#c5cec8', 1.2)
circle(px, py, 5.2, 'white', INK, 2)
line(px-12, py, px+12, py, INK, 1)
line(px, py-12, px, py+12, INK, 1)
text(px+12, py-18, '转轴', 15, INK, 600)
hdim(base_x, base_x+264, 665, '底座深120 / 宽100')
line(1104, 702, 1536, 702, '#e1e8e1')
mount_rows = [
    '转轴中心 (0,34,90)，转轴沿 X',
    '桌面 0–30°；壁挂 0–45°',
    '30°时前下角到底座顶面 ≈3.97',
    '前盖孔（机身 X / Z）：',
    '上侧 (±39,137)；下侧 (±42,39)',
]
for i, value in enumerate(mount_rows):
    text(1104, 734+i*32, value, 17, TEAL if i == 2 else MUTED, max_width=432)
text(1104, 893, '先固定支架，再装载板；限位需试装。', 15, MUTED, max_width=432)

text(40, 958, '示意图未绘制全部实体；不是制件加工图。实物装配、承载与射频性能尚未验证。', 18, MUTED, max_width=1510)
metadata = {
    'generator': 'models/scripts/draw_layout_v02.py',
    'pcb_placement_sha256': hashlib.sha256(CSV.read_bytes()).hexdigest(),
    'mechanical_reference_sha256': hashlib.sha256(REF.read_bytes()).hexdigest(),
    'coordinate_frames': 'Panel1 PCB XY; panel2 enclosureY; panel3 enclosureYZ and labelled XZ holes',
    'label_count': len(text_checks),
    'label_bounds_checked': True,
    'scope': 'Simplified illustration, not a complete solid or fabrication drawing',
}
add('</g>')
add('<metadata>'+html.escape(json.dumps(metadata, ensure_ascii=False))+'</metadata>')
add('</svg>')
payload = '\n'.join(svg)+'\n'
ET.fromstring(payload)
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(payload)
print(json.dumps({'svg': str(OUT), 'labels': len(text_checks), 'xml_valid': True}, ensure_ascii=False))
