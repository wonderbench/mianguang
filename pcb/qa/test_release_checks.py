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
            c['props']={'Manufacturer Part':part,'Supplier Part':supplier,'Device':'device-'+ref}
            sch[ref]={'props':dict(c['props'])};pcb[ref]={'props':dict(c['props'])}
            rows.append(dict(c['props'],Designator=ref,Quantity='1'))
        r=q.Report();q.check_parts(comps,sch,pcb,[('PCB_BOM.csv',rows)],r)
        self.assertEqual(status(r,'bom.parts.PCB_BOM.csv'),'PASS')
        next(row for row in rows if row['Designator']=='F1')['Quantity']='2'
        r=q.Report();q.check_parts(comps,sch,pcb,[('PCB_BOM.csv',rows)],r)
        self.assertEqual(status(r,'bom.parts.PCB_BOM.csv'),'FAIL')

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


if __name__=='__main__':
    unittest.main()
