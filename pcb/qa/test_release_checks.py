"""Mutation tests: plausible stale/incorrect release inputs must not pass."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import check_release as q

QA = Path(__file__).resolve().parent


def record(kind,ident,data):
    return ({'type':kind,'id':ident},data,1)


def doc(records,kind='FOOTPRINT',uid='fp'):
    return {'head':{'docType':kind,'uuid':uid},'records':records,'origin':'synthetic fixture'}


def socket():
    pads=[]
    for number in range(1,15):
        x=-300 if number<=7 else 300
        y=281-(number-1)*100 if number<=7 else 281-(14-number)*100
        pads.append(record('PAD','p'+str(number),{
            'num':str(number),'layerId':12,'plated':True,
            'centerX':x,'centerY':y,
            'hole':{'width':43.308,'height':43.308},
            'defaultPad':{'width':70.866,'height':70.866}}))
    return doc(pads)


def networks():
    comps={ref:{'pins':dict(pins),'props':{}} for ref,pins in q.CORE.items()}
    comps['R4']['pins']['2']='UART_TX_LINK'
    comps['R5']['pins']['2']='UART_RX_LINK'
    comps['JP2']={'pins':{'1':'UART_TX_LINK','2':'RADAR_RX'},'props':{}}
    comps['JP3']={'pins':{'1':'UART_RX_LINK','2':'RADAR_TX'},'props':{}}
    return comps


def status(report,key):
    return next(c['status'] for c in report.checks if c['id']==key)


def mounting_board(kind='FILL'):
    edge=[0,0,'L',0,56/q.MIL,66/q.MIL,56/q.MIL,66/q.MIL,0,0,0]
    records=[record('POLY','edge',{'layerId':11,'path':edge,'width':20})]
    for number,(x,y) in enumerate(((5,5),(61,5),(5,51),(61,51))):
        if kind=='FILL':
            data={'layerId':12,'fillStyle':'SOLID','width':1,
                  'path':[['CIRCLE',x/q.MIL,y/q.MIL,1.35/q.MIL]],
                  'netName':'','networkList':[],'isBridgingCopper':False}
        else:
            data={'layerId':12,'plated':False,'num':str(number),
                  'centerX':x/q.MIL,'centerY':y/q.MIL,
                  'hole':{'holeType':'ROUND','width':2.7/q.MIL,'height':2.7/q.MIL}}
        records.append(record(kind,'mount'+str(number),data))
    return doc(records,'PCB')


class ReleaseMutations(unittest.TestCase):
    def test_netlist_formula_normalization_preserves_part_identity(self):
        sch={'F1':{'pins':{'1':'5V_IN'},'props':{
            'Name':'={Manufacturer Part}','Manufacturer Part':'1206L110/16WR',
            'Symbol':'symbol','PCB Layer':'Default'}}}
        pcb=copy.deepcopy(sch)
        pcb['F1']['props'].update({'Name':'1206L110/16WR','PCB Layer':'TopLayer'})
        pcb['F1']['props'].pop('Symbol')
        self.assertEqual(q.normalized_net_components(sch),q.normalized_net_components(pcb))
        pcb['F1']['props']['Manufacturer Part']='K1206L050YR'
        self.assertNotEqual(q.normalized_net_components(sch),q.normalized_net_components(pcb))

    def test_source_defaults_do_not_hide_stale_text_or_live_no_connect(self):
        base=[record('COMPONENT','u',{'attrs':{'DeviceName':None},'zIndex':1}),
              record('ATTR','ref',{'parentId':'u','key':'Designator','value':'U1','zIndex':2}),
              record('ATTR','sym',{'parentId':'u','key':'Symbol','value':'symbol'}),
              record('TEXT','note',{'text':'V0.2','x':10,'y':20})]
        a=doc(copy.deepcopy(base),'SCH_PAGE','sch');a['origin']='archive.epru'
        b=doc(copy.deepcopy(base),'SCH_PAGE','sch');b['origin']='standalone.esch'
        b['records'][0][1]['attrs'].update(DeviceName='cached derived name',isSwitchClose=False)
        b['records'][0][1]['zIndex']=99
        b['records'][1][1]['strikeout']=False
        a['records'].append(record('ATTR','dead-nc',{'key':'NO_CONNECT','value':'yes','parentId':'u-deleted-pin'}))
        # Actual native IDs are a component ID, '-', then one pin ID without '-'.
        a['records'][-1][1]['parentId']='u-deleted'
        symbol=doc([record('PIN','live',{})],'SYMBOL','symbol')
        r=q.Report();q.select_document([a,b,symbol],'SCH_PAGE',r)
        self.assertEqual(status(r,'source.sch_page.copies'),'PASS')
        b['records'][3][1]['text']='V0.1'
        r=q.Report();q.select_document([a,b,symbol],'SCH_PAGE',r)
        self.assertEqual(status(r,'source.sch_page.copies'),'FAIL')
        b['records'][3][1]['text']='V0.2'
        a['records'][-1][1]['parentId']='u-live'
        r=q.Report();q.select_document([a,b,symbol],'SCH_PAGE',r)
        self.assertEqual(status(r,'source.sch_page.copies'),'FAIL')

    def test_deleted_native_records_do_not_reappear(self):
        lines=[]
        def line(kind,ident,data):
            body='' if data is None else json.dumps(data)
            return json.dumps({'type':kind,'id':ident})+'||'+body+'|'
        lines.append(line('DOCHEAD','h',{'docType':'PCB','uuid':'board'}))
        lines.append(line('LINE','old',{'startX':1}))
        lines.append(line('LINE','keep',{'startX':2}))
        lines.append(line('DOCHEAD','h2',{'docType':'PCB','uuid':'board'}))
        lines.append(line('LINE','old',None))
        lines.append(line('LINE','keep',{'startX':3}))
        records=q.native_documents('\n'.join(lines))[0]['records']
        self.assertEqual([(h['id'],d) for h,d,_ in records],[('keep',{'startX':3})])

    def test_uart_isolation_topology_and_bypass(self):
        good=networks();r=q.Report();q.check_networks(good,r)
        self.assertEqual(r.result()['status'],'PASS')
        # A direct net tie across JP2 defeats isolation despite the header existing.
        broken=copy.deepcopy(good)
        broken['R4']['pins']['2']='RADAR_RX'
        broken['JP2']['pins']['1']='RADAR_RX'
        r=q.Report();q.check_networks(broken,r)
        self.assertEqual(status(r,'netlist.jp2'),'FAIL')

    def test_xiao_bottom_ground_must_be_removed(self):
        comps=networks();comps['U1']['pins']['20']='GND'
        r=q.Report();q.check_networks(comps,r)
        self.assertEqual(status(r,'netlist.xiao_bottom_nc'),'FAIL')

    def test_duplicate_smd_pad_is_not_fourteen_through_holes(self):
        pcb={'U1':{'props':{'Footprint':'fp'}}}
        fp=socket();r=q.Report();q.check_xiao(pcb,{'fp':fp},{},r)
        self.assertEqual(status(r,'xiao.only_14_tht'),'PASS')
        self.assertEqual(status(r,'xiao.pitch_drills'),'PASS')
        duplicate=copy.deepcopy(fp['records'][0][1]);duplicate.update(layerId=1,plated=False)
        fp['records'].append(record('PAD','smd1',duplicate))
        r=q.Report();q.check_xiao(pcb,{'fp':fp},{},r)
        self.assertEqual(status(r,'xiao.only_14_tht'),'FAIL')

    def test_same_pad_number_cannot_hide_deleted_primitive(self):
        pcb={'U1':{'props':{'Footprint':'fp'}}}
        r=q.Report()
        q.check_pad_references(pcb,{'fp':socket()},[('U1','1','old-smd-pad','BUTTON_N')],r)
        self.assertEqual(status(r,'pcb.pad_primitive_references'),'FAIL')

    def test_old_fuse_is_rejected_even_when_networks_match(self):
        good=networks()
        sch={};pcb={}
        for ref,(part,lcsc) in q.PARTS.items():
            props={'Manufacturer Part':part,'Supplier Part':lcsc,'Device':'device-'+ref}
            good[ref]['props']=props
            sch[ref]={'props':dict(props)};pcb[ref]={'props':dict(props)}
        good['F1']['props']=dict(good['F1']['props'],**{'Manufacturer Part':'K1206L050YR','Supplier Part':'C2892420'})
        r=q.Report();q.check_parts(good,sch,pcb,[],r)
        self.assertEqual(status(r,'parts.F1.netlist'),'FAIL')
        self.assertEqual(status(r,'parts.F1.schematic'),'PASS')

    def test_manifest_detects_modified_export(self):
        with tempfile.TemporaryDirectory(prefix='test_',dir=QA) as temp:
            root=Path(temp);data=b'current export\n';(root/'pcb.epcb').write_bytes(data)
            manifest={'release':'V0.2','files':[{'path':'pcb.epcb','sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}]}
            (root/'manifest.json').write_text(json.dumps(manifest))
            r=q.Report();q.check_manifest(root,r,'V0.2')
            self.assertEqual(r.result()['status'],'PASS')
            (root/'pcb.epcb').write_bytes(b'stale export!!\n')
            r=q.Report();q.check_manifest(root,r,'V0.2')
            self.assertEqual(status(r,'manifest.files'),'FAIL')

    def test_bom_quantity_must_match_number_of_designators(self):
        comps=networks();sch={};pcb={};rows=[]
        for ref,c in comps.items():
            part,supplier=q.PARTS.get(ref,('',''))
            c['props']={'Manufacturer Part':part,'Supplier Part':supplier,'Device':'device-'+ref,
                        'Value':'','Manufacturer':'','Supplier':'','FootprintName':'fixture-'+ref}
            sch[ref]={'props':dict(c['props'])};pcb[ref]={'props':dict(c['props'])}
            rows.append(dict(c['props'],Designator=ref,Quantity='1',Footprint=c['props']['FootprintName']))
        r=q.Report();q.check_parts(comps,sch,pcb,[('PCB_BOM.csv',rows)],r)
        self.assertEqual(status(r,'bom.parts.PCB_BOM.csv'),'PASS')
        next(row for row in rows if row['Designator']=='F1')['Quantity']='2'
        r=q.Report();q.check_parts(comps,sch,pcb,[('PCB_BOM.csv',rows)],r)
        self.assertEqual(status(r,'bom.parts.PCB_BOM.csv'),'FAIL')

    def test_every_component_bom_value_purchase_and_footprint_field_is_bound(self):
        root=QA.parent/'release_v02'
        docs,nets,boms,_=q.inventory(root)
        report=q.Report()
        sch=q.attributes(q.select_document(docs,'SCH_PAGE',report))
        pcb=q.attributes(q.select_document(docs,'PCB',report))
        comps=q.net_components(next(net for name,net in nets if name=='schematic_netlist.json'))
        origin,rows=next((name,rows) for name,rows in boms if name=='BOM_Mianguang_V0.2.csv')
        r=q.Report();q.check_parts(comps,sch,pcb,[(origin,rows)],r)
        self.assertEqual(status(r,'bom.parts.'+origin),'PASS')
        self.assertEqual(len(comps),23)
        for ref in sorted(comps):
            for field in ('Value','Manufacturer Part','Manufacturer','Supplier Part','Supplier','Footprint'):
                with self.subTest(reference=ref,field=field):
                    changed=copy.deepcopy(rows)
                    row=next(row for row in changed if ref in row['Designator'].split(','))
                    row[field]='incorrect value or stale procurement metadata'
                    r=q.Report();q.check_parts(comps,sch,pcb,[(origin,changed)],r)
                    self.assertEqual(status(r,'bom.parts.'+origin),'FAIL')
        changed=copy.deepcopy(rows)
        for row in changed:row.pop('Value')
        r=q.Report();q.check_parts(comps,sch,pcb,[(origin,changed)],r)
        self.assertEqual(status(r,'bom.parts.'+origin),'FAIL')

    def test_external_parts_list_does_not_replace_electrical_bom(self):
        with tempfile.TemporaryDirectory(prefix='test_',dir=QA) as temp:
            root=Path(temp)
            (root/'external_BOM.csv').write_text('物料编号,名称\nEXT-01,雷达\n')
            self.assertEqual(q.inventory(root)[2],[])
            (root/'PCB_BOM.csv').write_text('Designator,Manufacturer Part,Supplier Part\nF1,1206L110/16WR,C3761685\n')
            self.assertEqual(len(q.inventory(root)[2]),1)

    def test_outline_width_is_not_board_size_and_extra_cutout_fails(self):
        # Native dimensions describe the cut centreline; plotted pen width is irrelevant.
        p=[0,0,'L',0,56/q.MIL,66/q.MIL,56/q.MIL,66/q.MIL,0,0,0]
        board=doc([record('POLY','edge',{'layerId':11,'path':p,'width':20})],'PCB')
        r=q.Report();q.check_board(board,r)
        self.assertEqual(status(r,'board.outline'),'PASS')
        board['records'].append(record('POLY','extra',{'layerId':11,'path':[10,10,'L',20,10,20,20,10,20,10,10]}))
        r=q.Report();q.check_board(board,r)
        self.assertEqual(status(r,'board.outline'),'FAIL')

    def test_round_cutouts_and_legacy_npth_pads_agree(self):
        import gerber_checks as g
        holes=[]
        for kind in ('PAD','FILL'):
            board=mounting_board(kind)
            r=q.Report();q.check_board(board,r)
            self.assertEqual(r.result()['status'],'PASS')
            anchors,found=g._native_points(board,{}, {}, {})
            self.assertEqual(anchors,[])
            self.assertEqual(len(found),4)
            self.assertTrue(all(p['plated'] is False and p['ref']=='BOARD' for p in found))
            holes.append(found)
        self.assertIsNotNone(g._match_holes(holes[0],holes[1],0,0))
        # Slot stroke width is display metadata, not additional drill radius.
        board['records'][1][1]['width']=40
        self.assertEqual(g._native_points(board,{}, {}, {})[1],holes[1])

    def test_round_cutout_wrong_position_or_diameter_is_rejected(self):
        import gerber_checks as g
        for coordinate in (1,2,3):
            with self.subTest(path_index=coordinate):
                board=mounting_board()
                board['records'][1][1]['path'][0][coordinate]+=.1/q.MIL
                r=q.Report();q.check_board(board,r)
                self.assertEqual(status(r,'board.npth'),'FAIL')
        expected=g._native_points(mounting_board(),{}, {}, {})[1]
        for field in ('x','y','d','plated'):
            with self.subTest(export_field=field):
                changed=copy.deepcopy(expected)
                changed[0][field]=True if field=='plated' else changed[0][field]+.1
                self.assertIsNone(g._match_holes(expected,changed,0,0))

    def test_unsupported_cutouts_remain_unverified(self):
        import gerber_checks as g
        cases=[{'path':[[0,0,'L',1,0,1,1,0,0]]},
               {'path':[['CIRCLE',1,1,2],['CIRCLE',3,3,2]]},
               {'path':[['CIRCLE',1,1,0]]},
               {'path':[['CIRCLE',1,1,3.3/q.MIL]]},
               {'path':[['CIRCLE',float('nan'),1,2]]},
               {'path':[['CIRCLE',1,1,True]]},
               {'fillStyle':'NONE'},{'netName':'GND'},{'isBridgingCopper':True}]
        for mutation in cases:
            with self.subTest(mutation=mutation):
                board=mounting_board()
                board['records'][1][1].update(mutation)
                r=q.Report();q.check_board(board,r)
                self.assertEqual(status(r,'board.npth'),'UNVERIFIED')
                with self.assertRaises(g.Unsupported):
                    g._native_points(board,{}, {}, {})

    def test_v03_cannot_retain_v02_drawing_text(self):
        sch=doc([record('ATTR','version',{'key':'Version','value':'V0.3'}),
                 record('TEXT','title',{'text':'MIANGUANG / V0.3'})],'SCH_PAGE')
        pcb=doc([record('STRING','title',{'text':'MIANGUANG V0.3'})],'PCB')
        r=q.Report();q.check_version(sch,pcb,r,'V0.3')
        self.assertEqual(r.result()['status'],'PASS')
        sch['records'][1][1]['text']='MIANGUANG / V0.2'
        r=q.Report();q.check_version(sch,pcb,r,'V0.3')
        self.assertEqual(status(r,'version.schematic'),'FAIL')
        sch['records'][1][1]['text']='MIANGUANG / V0.3'
        pcb['records'].append(record('STRING','old',{'text':'V0.2'}))
        r=q.Report();q.check_version(sch,pcb,r,'V0.3')
        self.assertEqual(status(r,'version.pcb'),'FAIL')

    def test_native_clean_gate_rejects_missing_report(self):
        with tempfile.TemporaryDirectory(prefix='test_',dir=QA) as temp:
            r=q.Report();q.check_native_checks(Path(temp),r,'V0.3')
            self.assertEqual(status(r,'native.present'),'FAIL')

    def test_native_clean_gate_rejects_warning_false_and_nonboolean_success(self):
        with tempfile.TemporaryDirectory(prefix='test_',dir=QA) as temp:
            root=Path(temp)
            for name in ('board.esch','board.epcb','project.epro2'):
                (root/name).write_text('final source '+name)
            good={'release':'V0.3','strict':True,
                  'schematic':{'passed':True,'details':[]},
                  'pcb':{'passed':True,'details':[]},
                  'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}}
            path=root/'native_checks.json'
            path.write_text(json.dumps(good))
            r=q.Report();q.check_native_checks(root,r,'V0.3')
            self.assertEqual(r.result()['status'],'PASS')
            self.assertEqual(r.context['native_checks_sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
            for domain in ('schematic','pcb'):
                for result in ({'passed':False,'details':[]},
                               {'passed':1,'details':[]},
                               {'passed':'true','details':[]},
                               {'passed':True,'details':[{'type':'warn','rule':'ATTRMATCHCODE'}]},
                               {'passed':True,'details':None},
                               {'passed':True,'details':{}},
                               {'passed':True},None):
                    with self.subTest(domain=domain,result=result):
                        bad=copy.deepcopy(good);bad[domain]=result
                        path.write_text(json.dumps(bad))
                        r=q.Report();q.check_native_checks(root,r,'V0.3')
                        self.assertEqual(status(r,'native.'+domain+'.clean'),'FAIL')

    def test_native_clean_gate_rejects_stale_source_version_and_non_strict_run(self):
        with tempfile.TemporaryDirectory(prefix='test_',dir=QA) as temp:
            root=Path(temp)
            for name in ('board.esch','board.epcb','project.epro2'):
                (root/name).write_text('final source '+name)
            good={'release':'V0.3','strict':True,
                  'schematic':{'passed':True,'details':[]},
                  'pcb':{'passed':True,'details':[]},
                  'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}}
            path=root/'native_checks.json'
            for value in (False,1,'true',None):
                with self.subTest(strict=value):
                    bad=copy.deepcopy(good);bad['strict']=value;path.write_text(json.dumps(bad))
                    r=q.Report();q.check_native_checks(root,r,'V0.3')
                    self.assertEqual(status(r,'native.strict'),'FAIL')
            bad=copy.deepcopy(good);bad['release']='V0.2';path.write_text(json.dumps(bad))
            r=q.Report();q.check_native_checks(root,r,'V0.3')
            self.assertEqual(status(r,'native.version'),'FAIL')
            path.write_text(json.dumps(good))
            for name in ('board.esch','board.epcb','project.epro2'):
                with self.subTest(changed_source=name):
                    source=root/name;original=source.read_bytes()
                    source.write_text('edited after EDA check (including embedded library only edits)')
                    r=q.Report();q.check_native_checks(root,r,'V0.3')
                    self.assertEqual(status(r,'native.source_binding'),'FAIL')
                    source.write_bytes(original)
            bad=copy.deepcopy(good);del bad['source_sha256']['project.epro2']
            path.write_text(json.dumps(bad))
            r=q.Report();q.check_native_checks(root,r,'V0.3')
            self.assertEqual(status(r,'native.source_binding'),'FAIL')

    def test_native_clean_gate_requires_all_source_types_and_valid_json(self):
        with tempfile.TemporaryDirectory(prefix='test_',dir=QA) as temp:
            root=Path(temp);path=root/'native_checks.json'
            good={'release':'V0.3','strict':True,
                  'schematic':{'passed':True,'details':[]},
                  'pcb':{'passed':True,'details':[]},'source_sha256':{}}
            path.write_text(json.dumps(good))
            r=q.Report();q.check_native_checks(root,r,'V0.3')
            self.assertEqual(status(r,'native.source_binding'),'FAIL')
            for text in ('[]','true','{broken'):
                with self.subTest(text=text):
                    path.write_text(text)
                    r=q.Report();q.check_native_checks(root,r,'V0.3')
                    self.assertEqual(status(r,'native.parse'),'FAIL')


if __name__=='__main__':
    unittest.main()
