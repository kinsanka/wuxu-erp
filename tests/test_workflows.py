import io
import json
import os
import secrets
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from http.client import parse_headers
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app"))

from db import initialize, transaction
from erp import BusinessError, execute, today
from main import Handler
from read import document, trace
from seed import ADMIN, bootstrap


class MemorySocket:
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = io.BytesIO()

    def settimeout(self, _timeout):
        pass

    def makefile(self, *_args):
        return self.input

    def sendall(self, value):
        self.output.write(value)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.admin_password=secrets.token_urlsafe(24)
        self.enterContext(patch("erp.DEMO_LOGIN",False))
        self.enterContext(patch("main.LOGIN_ATTEMPTS",{}))
        mode=patch.dict(os.environ,{"ERP_SQLITE":str(Path(self.directory.name)/"erp.sqlite3"),
                                    "ERP_ADMIN_PASSWORD":self.admin_password})
        mode.start()
        self.addCleanup(mode.stop)
        with transaction(True) as db:
            initialize(db)
            bootstrap(db)

    def action(self,name,account=ADMIN,**payload):
        with transaction(True) as db:
            return execute(db,name,payload,account)

    def row(self,sql,args=()):
        with transaction() as db:
            return db.one(sql,args)

    def purchase(self,item,site="factory",count="6",partner="vendor",due=""):
        result=self.action("purchase",partner_id=partner,site_id=site,due=due,
                           lines=[dict(item_id=item,quantity=count,price="12.34")])
        self.action("approve",id=result["id"],decision="approve")
        line=self.row("SELECT id FROM document_lines WHERE doc_id=%s",(result["id"],))["id"]
        return result["id"],line

    def work(self,count):
        bom=self.row("SELECT id FROM boms")["id"]
        result=self.action("work",bom_id=bom,site_id="factory",quantity=count,due=self.ahead(8))
        self.action("approve",id=result["id"],decision="approve")
        return result

    def lot(self,code):
        return self.row("SELECT * FROM lots WHERE code=%s",(code,))

    def ahead(self,days):
        return (date.fromisoformat(today())+timedelta(days=days)).isoformat()

    def request(self,path,payload=None,cookie="",origin="",idempotency=""):
        method="GET" if payload is None else "POST"
        body=json.dumps(payload).encode() if payload is not None else b""
        headers=[f"{method} {path} HTTP/1.1","Host: erp.test","Connection: close"]
        if payload is not None:
            headers += ["Content-Type: application/json",f"Content-Length: {len(body)}"]
        if cookie:
            headers.append("Cookie: "+cookie)
        if origin:
            headers.append("Origin: "+origin)
        if idempotency:
            headers.append("Idempotency-Key: "+idempotency)
        sock=MemorySocket(("\r\n".join(headers)+"\r\n\r\n").encode()+body)
        with patch.object(Handler,"log_message"):
            Handler(sock,("127.0.0.1",0),object())
        response=io.BytesIO(sock.output.getvalue())
        status=int(response.readline().split()[1])
        return status,parse_headers(response),response.read()

    def test_partial_receipt_and_atomic_overreceipt(self):
        order,line=self.purchase("al",count="6.5")
        self.action("receive",id=order,line_id=line,lot="AL-NEW",quantity="2.25")
        self.assertEqual(self.row("SELECT fulfilled FROM document_lines WHERE id=%s",(line,))["fulfilled"],2250)
        with self.assertRaises(BusinessError):
            self.action("receive",id=order,line_id=line,lot="AL-UNDONE",quantity="4.251")
        self.assertIsNone(self.lot("AL-UNDONE"))
        self.action("receive",id=order,line_id=line,lot="AL-NEW",quantity="4.25")
        self.assertEqual(self.row("SELECT status FROM documents WHERE id=%s",(order,))["status"],"done")
        self.assertEqual(self.row("SELECT quantity FROM stock WHERE lot_id=%s",(self.lot("AL-NEW")["id"],))["quantity"],6500)

    def test_existing_medical_records_are_excluded_without_deleting_history(self):
        with transaction(True) as db:
            db.execute("INSERT INTO sites VALUES ('old-h','H01','旧医院仓','central')")
            db.execute("INSERT INTO items VALUES ('old-m','MED-001','旧耗材','medical','盒',0,1,1,'')")
            db.execute("INSERT INTO lots VALUES ('old-l','old-m','MED-LOT',NULL,'released','2026-01-01')")
            db.execute("INSERT INTO stock VALUES ('old-l','old-h',1000)")
            db.execute("INSERT INTO units VALUES ('old-u','SPD-OLD',NULL,'old-l','old-h','stock')")
            db.execute("INSERT INTO documents VALUES ('old-doc','PO-LEGACY','purchase','approved','old-h',"
                       "'vendor',NULL,'','2026-01-01',NULL)")
            db.execute("INSERT INTO document_lines VALUES ('old-line','old-doc','old-m',1000,0,12000)")
            db.execute("INSERT INTO movements VALUES ('old-move','old-l','old-h',1000,'收货','PO-LEGACY',"
                       "'admin','2026-01-01','')")
        _,headers,_=self.request("/api/login",{"username":"admin","password":self.admin_password})
        session=headers["Set-Cookie"].split(";",1)[0]
        status,_,body=self.request("/api/state",cookie=session)
        self.assertEqual(status,200)
        for label in ("旧医院仓","旧耗材","PO-LEGACY","MED-LOT","SPD-OLD"):
            self.assertNotIn(label,body.decode())
        for path in ("/api/document/old-doc","/api/item/old-m","/api/trace?code=SPD-OLD","/api/export/clinical"):
            self.assertEqual(self.request(path,cookie=session)[0],404)
        self.assertNotIn("PO-LEGACY",self.request("/api/orders/purchase",cookie=session)[2].decode())
        self.assertNotIn("PO-LEGACY",self.request("/api/export/movements",cookie=session)[2].decode())
        self.assertEqual(self.request("/api/action/approve",{"id":"old-doc","decision":"cancel"},cookie=session)[0],404)
        self.assertEqual(self.row("SELECT quantity FROM stock WHERE lot_id='old-l'")["quantity"],1000)

    def test_mrp_preview_and_shortage_rolls_back_previous_components(self):
        work=self.work("20")
        with transaction() as db:
            result=document(db,work["id"])
        self.assertTrue(any(row["incoming"] for row in result["plan"]))
        # Aluminium fails first at 45 kg. Supply only that material so that
        # the following bearing check fails after aluminium has been allocated.
        order,line=self.purchase("al",count="20")
        self.action("receive",id=order,line_id=line,lot="AL-TEST-2",quantity="20")
        with self.assertRaisesRegex(BusinessError,"库存|可用数量"):
            self.action("start",id=work["id"])
        self.assertIsNone(self.row("SELECT id FROM movements WHERE ref=%s",(work["ref"],)))
        self.assertEqual(self.row("SELECT status FROM documents WHERE id=%s",(work["id"],))["status"],"approved")
        self.assertEqual(self.row("SELECT quantity FROM stock WHERE lot_id=%s",(self.lot("AL-TEST-2")["id"],))["quantity"],20000)

    def test_production_sequence_and_bidirectional_trace(self):
        work=self.work("2")
        self.action("start",id=work["id"])
        with transaction() as db:
            steps=document(db,work["id"])["steps"]
        with self.assertRaisesRegex(BusinessError,"工序"):
            self.action("report",id=work["id"],step_id=steps[1]["id"],minutes="14")
        with self.assertRaisesRegex(BusinessError,"报工"):
            self.action("finish",id=work["id"],lot="FG-TEST")
        for step in steps:
            self.action("report",id=work["id"],step_id=step["id"],minutes="14")
        result=self.action("finish",id=work["id"],lot="FG-TEST")
        with transaction() as db:
            output=trace(db,result["lot_id"],"",ADMIN)
            source=trace(db,self.lot("AL-DEMO-01")["id"],"",ADMIN)
        self.assertEqual(output["lot"]["status"],"pending")
        self.assertEqual({row["code"] for row in output["upstream"]},{"AL-DEMO-01","SC-DEMO-01","BR-DEMO-01"})
        self.assertIn("FG-TEST",{row["code"] for row in source["downstream"]})

    def test_fefo_shipping_and_quarantine(self):
        order,line=self.purchase("screw",count="12")
        self.action("receive",id=order,line_id=line,lot="SC-LATE",expiry=self.ahead(60),quantity="6")
        self.action("receive",id=order,line_id=line,lot="SC-EARLY",expiry=self.ahead(8),quantity="6")
        sale=self.action("sale",site_id="factory",partner_id="customer",
                         lines=[dict(item_id="screw",quantity="7",price="1.5")])
        self.action("approve",id=sale["id"],decision="approve")
        line=self.row("SELECT id FROM document_lines WHERE doc_id=%s",(sale["id"],))["id"]
        self.action("ship",id=sale["id"],line_id=line,quantity="4")
        self.assertEqual(self.row("SELECT quantity FROM stock WHERE lot_id=%s",(self.lot("SC-EARLY")["id"],))["quantity"],2000)
        self.action("inspect",lot_id=self.lot("SC-EARLY")["id"],verdict="blocked",note="召回测试")
        self.action("ship",id=sale["id"],line_id=line,quantity="3")
        self.assertEqual(self.row("SELECT quantity FROM stock WHERE lot_id=%s",(self.lot("SC-EARLY")["id"],))["quantity"],2000)
        self.assertEqual(self.row("SELECT quantity FROM stock WHERE lot_id=%s",(self.lot("SC-LATE")["id"],))["quantity"],3000)

    def test_industrial_transfer_permissions_freeze_and_atomic_stock(self):
        lot=self.lot("BR-DEMO-01")
        payload=dict(lot_id=lot["id"],from_id="factory",to_id="finished",quantity="12")
        with self.assertRaises(BusinessError) as denied:
            self.action("transfer",account=dict(ADMIN,role="viewer"),**payload)
        self.assertEqual(denied.exception.status,403)
        self.action("inspect",lot_id=lot["id"],verdict="blocked",note="模拟质量复查")
        with self.assertRaises(BusinessError):
            self.action("transfer",**payload)
        self.action("inspect",lot_id=lot["id"],verdict="released",note="复核后放行")

        def transfer(_):
            try:
                return self.action("transfer",**payload)["ref"]
            except BusinessError as error:
                return error.status

        with ThreadPoolExecutor(2) as executor:
            results=list(executor.map(transfer,range(2)))
        self.assertEqual(results.count(409),1)
        self.assertEqual(self.row("SELECT quantity FROM stock WHERE site_id='finished' AND lot_id=%s",
                                  (lot["id"],))["quantity"],12000)

    def test_http_routes_sessions_and_csv(self):
        status,headers,body=self.request("/")
        self.assertEqual(status,200)
        self.assertIn("物序".encode(),body)
        self.assertIn("default-src 'none'",headers["Content-Security-Policy"])
        self.assertEqual(self.request("/api/state")[0],401)
        payload={"username":"admin","password":self.admin_password}
        self.assertEqual(self.request("/api/login",payload,origin="https://foreign.test")[0],403)
        status,headers,_=self.request("/api/login",payload,origin="http://erp.test")
        self.assertEqual(status,200)
        session=headers["Set-Cookie"].split(";")[0]
        self.assertIn("HttpOnly",headers["Set-Cookie"])
        status,_,body=self.request("/api/state",cookie=session)
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)["account"]["role"],"admin")
        status,_,body=self.request("/api/trace?lot="+self.lot("FG-DEMO-001")["id"],cookie=session)
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)["lot"]["code"],"FG-DEMO-001")
        status,headers,body=self.request("/api/export/movements",cookie=session)
        self.assertEqual(status,200)
        self.assertIn("attachment",headers["Content-Disposition"])
        self.assertIn("生产完工",body.decode("utf-8-sig"))
        self.assertEqual(self.request("/api/logout",{},cookie=session)[0],200)
        self.assertEqual(self.request("/api/state",cookie=session)[0],401)

    @patch("erp.DEMO_LOGIN",True)
    def test_prefilled_demo_login_reuses_admin_without_account_management(self):
        admin_credentials={"username":"admin","password":self.admin_password}
        with patch("erp.DEMO_LOGIN",False):
            _,headers,_=self.request("/api/login",admin_credentials)
        admin_session=headers["Set-Cookie"].split(";",1)[0]
        meta=json.loads(self.request("/api/meta")[2])
        self.assertTrue(meta["demo_login"])
        demo_credentials=meta["demo_account"]
        self.assertEqual(demo_credentials["username"],"admin")
        self.assertNotEqual(demo_credentials["password"],self.admin_password)
        self.assertEqual(self.row("SELECT COUNT(*) AS n FROM users")["n"],1)
        self.assertEqual(self.request("/api/demo-credentials")[0],401)
        self.assertEqual(self.request("/api/state",cookie=admin_session)[0],401)
        self.assertEqual(self.request("/api/login",admin_credentials)[0],401)
        self.assertEqual(self.request("/api/login",demo_credentials,origin="https://foreign.test")[0],403)
        status,headers,body=self.request("/api/login",demo_credentials,origin="http://erp.test")
        self.assertEqual(status,200)
        self.assertEqual(headers["Cache-Control"],"no-store")
        self.assertIn("HttpOnly",headers["Set-Cookie"])
        self.assertEqual(json.loads(body),{"ok":True})
        session=headers["Set-Cookie"].split(";",1)[0]
        status,_,body=self.request("/api/state",cookie=session)
        self.assertEqual(status,200)
        state=json.loads(body)
        self.assertTrue(state["account"]["is_demo"])
        self.assertEqual(state["account"]["username"],"admin")
        self.assertEqual(state["users"],[])
        self.assertEqual(self.request("/api/exercise/demo",cookie=session)[0],200)
        self.assertTrue(json.loads(self.request("/api/walkthrough",cookie=session)[2])["practice_allowed"])
        self.assertEqual(self.request("/api/action/practice",{},cookie=session)[0],200)
        self.assertEqual(self.request("/api/action/user",{},cookie=session)[0],403)
        self.assertEqual(self.request("/api/action/password",{},cookie=session)[0],403)
        payload=dict(entity="partners",code="V-SHARED",name="演示流程供应商",type="vendor")
        self.assertEqual(self.request("/api/action/master",payload,cookie=session)[0],200)
        with patch("erp.DEMO_LOGIN",False):
            meta=json.loads(self.request("/api/meta")[2])
            self.assertFalse(meta["demo_login"])
            self.assertNotIn("demo_account",meta)
            self.assertEqual(self.request("/api/login",demo_credentials)[0],401)
            self.assertEqual(self.request("/api/state",cookie=session)[0],401)
            admin_state=json.loads(self.request("/api/state",cookie=admin_session)[2])
            self.assertIn("V-SHARED",{partner["code"] for partner in admin_state["partners"]})
        self.assertEqual(self.request("/api/logout",{},cookie=session)[0],200)
        self.assertEqual(self.request("/api/state",cookie=session)[0],401)
        _,headers,_=self.request("/api/login",demo_credentials)
        session=headers["Set-Cookie"].split(";",1)[0]
        with transaction(True) as db:
            db.execute("UPDATE settings SET value='0' WHERE key='demo'")
        self.assertFalse(json.loads(self.request("/api/meta")[2])["demo_login"])
        self.assertNotIn("demo_account",json.loads(self.request("/api/meta")[2]))
        self.assertEqual(self.request("/api/login",demo_credentials)[0],401)
        self.assertEqual(self.request("/api/state",cookie=session)[0],401)

    def test_bootstrap_demo_needs_no_configured_admin_password(self):
        empty=Path(self.directory.name)/"demo.sqlite3"
        with patch.dict(os.environ,{"ERP_SQLITE":str(empty),"ERP_ADMIN_PASSWORD":""}), patch("erp.DEMO_LOGIN",True):
            with transaction(True) as db:
                initialize(db)
                bootstrap(db)
            self.assertEqual(self.row("SELECT COUNT(*) AS n FROM users")["n"],1)
            demo_credentials=json.loads(self.request("/api/meta")[2])["demo_account"]
            self.assertEqual(self.request("/api/login",demo_credentials)[0],200)

    def test_expedite_tracks_real_order_and_requires_full_signed_delivery(self):
        _,headers,_=self.request("/api/login",{"username":"admin","password":self.admin_password})
        session=headers["Set-Cookie"].split(";",1)[0]
        sale=self.row("SELECT id FROM documents WHERE kind='sale'")["id"]

        def api(path,payload=None,expected=200):
            status,_,body=self.request(path,payload,cookie=session)
            self.assertEqual(status,expected,body)
            return json.loads(body)

        desk="/api/orders/expedite"
        action="/api/action/expedite"
        api(action,dict(id=sale,operation="schedule",priority="critical",owner="交付计划",
                        due=self.ahead(1),note="客户提前安装"))
        self.assertEqual(api(desk)[0]["priority"],"critical")
        detail=api(desk+"/"+sale)
        self.assertEqual(len(detail["work"]),1)
        self.assertEqual(len(detail["work"][0]["purchase"]),1)
        api(action,dict(id=sale,operation="followup",note="确认分两批发运"))
        api(action,dict(id=sale,operation="close",note="交付完毕"),409)
        self.action("inspect",lot_id=self.lot("FG-DEMO-001")["id"],verdict="released",note="首批检验合格")
        line=detail["order"]["lines"][0]["id"]
        for tracking in ("RUSH-101","RUSH-102"):
            api("/api/action/ship",dict(id=sale,line_id=line,quantity="2"))
            api("/api/action/dispatch",dict(id=sale,carrier="专线",tracking=tracking,due=self.ahead(1)))
            shipment=self.row("SELECT id FROM shipments WHERE tracking=%s",(tracking,))["id"]
            if tracking=="RUSH-102":
                api(action,dict(id=sale,operation="close",note="第二批还在途"),409)
            api("/api/action/sign_shipment",dict(id=shipment,receipt="POD-"+tracking))
        self.assertEqual(api(desk+"/"+sale)["order"]["lines"][0]["signed"],4000)
        api(action,dict(id=sale,operation="close",note="两张签收单齐全"))
        self.assertEqual(api(desk)[0]["status"],"closed")
        self.assertEqual(len(api(desk+"/"+sale)["events"]),3)

    def test_plan_shortage_creates_linked_po_and_keeps_delivery_revisions(self):
        _,headers,_=self.request("/api/login",{"username":"admin","password":self.admin_password})
        session=headers["Set-Cookie"].split(";",1)[0]
        run=json.loads(self.request("/api/action/practice",{},cookie=session)[2])
        model=json.loads(self.request("/api/walkthrough?run="+run["id"],cookie=session)[2])
        work=model["work"]["id"]
        component=model["raw"]["id"]
        payload=dict(id=work,item_id=component,partner_id="vendor",quantity="8",price="32",due=self.ahead(2))
        status,_,body=self.request("/api/action/purchase_shortage",payload,cookie=session)
        self.assertEqual(status,409,body)
        original=model["purchase"]["id"]
        self.action("approve",id=original,decision="cancel")
        status,_,body=self.request("/api/action/purchase_shortage",payload,cookie=session)
        self.assertEqual(status,200,body)
        new=json.loads(body)["id"]
        self.assertEqual(self.request("/api/action/purchase_shortage",payload,cookie=session)[0],409)
        status,_,body=self.request("/api/action/revise_delivery",dict(id=new,due=self.ahead(3),note="采购商确认"),
                                   cookie=session)
        self.assertEqual(status,200,body)
        doc=json.loads(self.request("/api/document/"+new,cookie=session)[2])
        self.assertEqual(doc["linked"][0]["id"],work)
        self.assertEqual(doc["delivery_revisions"][0]["previous_due"],self.ahead(2))
        self.assertEqual(doc["due"],self.ahead(3))

    def test_walkthrough_links_to_existing_erp_records(self):
        self.assertEqual(self.request("/api/walkthrough")[0],401)
        _,headers,_=self.request("/api/login",{"username":"admin","password":self.admin_password})
        session=headers["Set-Cookie"].split(";",1)[0]
        status,_,body=self.request("/api/walkthrough",cookie=session)
        self.assertEqual(status,200)
        targets=json.loads(body)
        for kind in ("sale","purchase","work"):
            status,_,body=self.request("/api/document/"+targets[kind]["id"],cookie=session)
            self.assertEqual(status,200)
            model=json.loads(body)
            self.assertEqual(model["kind"],kind)
            if kind=="work":
                self.assertIn(targets["batch"]["code"],{row["lot"] for row in model["movements"]})
        status,_,body=self.request("/api/trace?lot="+targets["batch"]["id"],cookie=session)
        self.assertEqual(status,200)
        self.assertIn("AL-DEMO-01",{row["code"] for row in json.loads(body)["upstream"]})

    def test_http_retry_does_not_repeat_partial_receipt(self):
        order,line=self.purchase("al",count="20")
        _,headers,_=self.request("/api/login",{"username":"admin","password":self.admin_password})
        session=headers["Set-Cookie"].split(";")[0]
        payload=dict(id=order,line_id=line,lot="AL-RETRY",quantity="2")
        path="/api/action/receive"
        key="test-repeat-receipt-123"
        first=self.request(path,payload,cookie=session,idempotency=key)
        second=self.request(path,payload,cookie=session,idempotency=key)
        self.assertEqual(first[0],200)
        self.assertEqual(first[2],second[2])
        self.assertEqual(self.row("SELECT fulfilled FROM document_lines WHERE id=%s",(line,))["fulfilled"],2000)
        self.assertEqual(self.request(path,dict(payload,quantity="3"),cookie=session,idempotency=key)[0],409)

    def test_bootstrap_requires_a_password_for_new_database(self):
        empty = Path(self.directory.name) / "empty.sqlite3"
        with patch.dict(os.environ, {"ERP_SQLITE": str(empty), "ERP_ADMIN_PASSWORD": ""}):
            with transaction(True) as db:
                initialize(db)
            with self.assertRaisesRegex(RuntimeError, "ERP_ADMIN_PASSWORD"):
                with transaction(True) as db:
                    bootstrap(db)
            with transaction() as db:
                self.assertIsNone(db.one("SELECT id FROM users"))

    def test_restart_does_not_reseed(self):
        lot=self.lot("AL-DEMO-01")
        self.action("transfer",lot_id=lot["id"],from_id="factory",to_id="finished",quantity="1")
        with patch.dict(os.environ, {"ERP_ADMIN_PASSWORD": ""}), patch("seed.SEED_EXAMPLES",False):
            with transaction(True) as db:
                initialize(db)
                bootstrap(db)
        row=self.row("SELECT quantity FROM stock WHERE site_id='finished' AND lot_id=%s",(lot["id"],))
        self.assertEqual(row["quantity"],1000)
        self.assertTrue(json.loads(self.request("/api/meta")[2])["demo"])
        status,_,_=self.request("/api/login",{"username":"admin","password":self.admin_password})
        self.assertEqual(status,200)


if __name__=="__main__":
    unittest.main()
