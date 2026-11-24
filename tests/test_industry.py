import json
import unittest
from unittest.mock import patch

import test_workflows


class IndustrialWorkflowTests(unittest.TestCase):
    def setUp(self):
        rate_limit = patch("main.LOGIN_ATTEMPTS",{})
        rate_limit.start()
        self.addCleanup(rate_limit.stop)
        self.fixture = test_workflows.WorkflowTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.session = self.login("admin",self.fixture.admin_password)

    def login(self,user,password):
        status,headers,body = self.fixture.request("/api/login",dict(username=user,password=password))
        self.assertEqual(status,200,body.decode())
        return headers["Set-Cookie"].split(";",1)[0]

    def call(self,path,data=None,expected=200,session=None,token=""):
        status,_,body = self.fixture.request(path,data,cookie=self.session if session is None else session,idempotency=token)
        self.assertEqual(status,expected,body.decode())
        return json.loads(body)

    def act(self,action,expected=200,**payload):
        return self.call("/api/action/"+action,payload,expected)

    def test_sales_stock_to_transport_and_settlement(self):
        targets = self.call("/api/walkthrough")
        product = self.call("/api/item/"+targets["product"]["id"])
        self.assertEqual([row["version"] for row in product["boms"]],["A.01"])
        sale_id = targets["sale"]["id"]
        sale = self.call("/api/document/"+sale_id)
        self.assertEqual(sale["linked"][0]["id"],targets["work"]["id"])
        line = sale["lines"][0]
        self.assertEqual(line["inventory"],{"released":0,"pending":4000,"blocked":0,"expired":0})
        ship = dict(id=sale_id,line_id=line["id"],quantity="4")
        invoice = dict(line_id=line["id"],ref="AR-CUSTOMER-1",due=self.fixture.ahead(30),quantity="4",price="465")
        self.act("ship",409,**ship)
        self.act("inspect",lot_id=targets["batch"]["id"],verdict="released",note="出厂检验合格")
        self.act("ship",**ship)
        self.act("invoice",409,**invoice)
        payload = dict(id=sale_id,carrier="示例承运商",tracking="TRACK-001",due=self.fixture.ahead(2))
        first = self.call("/api/action/dispatch",payload,token="dispatch-retry-123")
        self.assertEqual(first,self.call("/api/action/dispatch",payload,token="dispatch-retry-123"))
        self.act("dispatch",409,**payload)
        shipment, = self.call("/api/industry/transport")["shipments"]
        detail = self.call("/api/industry/transport/"+shipment["id"])
        self.assertEqual([(row["lot"],row["quantity"]) for row in detail["lines"]],[("FG-DEMO-001",4000)])
        self.act("invoice",409,**invoice)
        self.act("sign_shipment",id=shipment["id"],receipt="POD-001")
        self.act("sign_shipment",409,id=shipment["id"],receipt="POD-002")
        self.act("invoice",409,**dict(invoice,quantity="5"))
        self.act("invoice",409,**dict(invoice,price="466"))
        self.act("invoice",**invoice)
        self.act("invoice",409,**invoice)
        row, = self.call("/api/industry/finance")["invoices"]
        self.assertEqual((row["direction"],row["amount"]),("ar",186000))
        first = self.act("payment",id=row["id"],ref="BANK-01",amount="500",date=self.fixture.ahead(0))
        self.act("payment",409,id=row["id"],ref="BANK-01",amount="500",date=self.fixture.ahead(0))
        self.act("settlement",409,id=row["id"],payment_id=first["id"],amount="501")
        self.act("settlement",id=row["id"],payment_id=first["id"],amount="500")
        self.act("settlement",409,id=row["id"],payment_id=first["id"],amount="500")
        second = self.act("payment",id=row["id"],ref="BANK-02",amount="1400",date=self.fixture.ahead(0))
        self.act("settlement",409,id=row["id"],payment_id=second["id"],amount="1361")
        self.act("settlement",id=row["id"],payment_id=second["id"],amount="1360")
        detail = self.call("/api/industry/finance/"+row["id"])
        self.assertEqual(sum(entry["amount"] for entry in detail["settlements"]),186000)
        self.act("user",username="shipping-staff",name="运输岗",password="test-shipping-14",role="warehouse")
        staff = self.login("shipping-staff","test-shipping-14")
        self.call("/api/industry/transport",session=staff)
        self.call("/api/industry/finance",session=staff,expected=403)

    def test_purchase_invoice_requires_released_receipts_and_supports_multiple_lines(self):
        order = self.act("purchase",site_id="factory",partner_id="vendor",due=self.fixture.ahead(2),lines=[
            dict(item_id="bearing",quantity="4",price="9.50"),dict(item_id="screw",quantity="5",price="1.20"),
        ])
        self.act("approve",id=order["id"],decision="approve")
        lines = {row["item_id"]:row["id"] for row in self.call("/api/document/"+order["id"])["lines"]}
        self.act("receive",id=order["id"],line_id=lines["bearing"],quantity="4",lot="QA-AP-BR")
        self.act("receive",id=order["id"],line_id=lines["screw"],quantity="5",lot="QA-AP-SC")
        invoice = dict(line_id=lines["bearing"],ref="AP-SUPPLIER-1",due=self.fixture.ahead(30),quantity="4",price="9.50")
        self.act("invoice",409,**invoice)
        lot = self.fixture.lot("QA-AP-BR")
        self.act("inspect",lot_id=lot["id"],verdict="released",note="尺寸与材质检查通过")
        self.act("inspect",lot_id=lot["id"],verdict="blocked",note="后续冻结，原验收记录应保留")
        self.act("invoice",**invoice)
        self.act("invoice",**dict(invoice,line_id=lines["screw"],quantity="5",price="1.20"))
        row, = self.call("/api/industry/finance")["invoices"]
        self.assertEqual((row["direction"],row["amount"]),("ap",4400))
        self.assertEqual(len(self.call("/api/industry/finance/"+row["id"])["lines"]),2)

    def test_linked_supply_assignment_clock_and_stock_count(self):
        work = self.fixture.work("1")
        order,line = self.fixture.purchase("bearing","factory","10",due=self.fixture.ahead(10))
        source = self.call("/api/document/"+order)
        self.act("link_supply",id=work["id"],ref=source["ref"])
        model = self.call("/api/document/"+work["id"])
        self.assertIn(order,{row["id"] for row in model["linked"]})
        bearing = next(row for row in model["plan"] if row["item_id"]=="bearing")
        self.assertIn((order,"late"),{(row["id"],row["schedule"]) for row in bearing["purchases"]})
        self.act("personnel",code="STAFF-02",name="车间人员",team="机加二班")
        worker = next(row for row in self.call("/api/industry/people")["people"] if row["code"]=="STAFF-02")
        step = model["steps"][0]["id"]
        self.act("assign_step",id=work["id"],step_id=step,person_id=worker["id"])
        self.act("start",id=work["id"])
        self.act("report",id=work["id"],step_id=step,minutes="37")
        self.act("assign_step",409,id=work["id"],step_id=step,person_id=worker["id"])
        assignment = next(row for row in self.call("/api/industry/people")["assignments"] if row["doc_id"]==work["id"])
        self.assertEqual(assignment["minutes"],37)
        self.act("unlink_supply",id=work["id"],supply_id=order)
        self.assertEqual(self.call("/api/document/"+work["id"])["linked"],[])
        self.act("receive",id=order,line_id=line,quantity="5",lot="COUNT-BR")
        lot = self.fixture.lot("COUNT-BR")
        self.act("inventory_count",site_id="factory",lot_id=lot["id"],book="5",counted="4",reason="盘点表 P-01")
        self.act("inventory_count",409,site_id="factory",lot_id=lot["id"],book="5",counted="2",reason="旧账面")
        count, = self.call("/api/industry/counts")
        self.assertEqual((count["book"],count["counted"]),(5000,4000))
        batch = self.call("/api/trace?lot="+lot["id"])
        self.assertEqual(batch["stock"][0]["quantity"],4000)
        self.assertIn("盘亏",{row["kind"] for row in batch["movements"]})

    def test_purchase_return_reopens_order_and_preserves_invoice_limit(self):
        order,line = self.fixture.purchase("bearing",count="4")
        self.act("receive",id=order,line_id=line,quantity="4",lot="RETURN-BR")
        details = self.call("/api/document/"+order)
        receipt, = details["movements"]
        self.act("purchase_return",receipt_id=receipt["id"],quantity="1",reason="来料尺寸不符")
        changed = self.call("/api/document/"+order)
        self.assertEqual((changed["status"],changed["lines"][0]["fulfilled"]),("partial",3000))
        self.assertEqual(next(row for row in changed["movements"] if row["kind"]=="收货")["returned"],1000)
        self.act("inspect",lot_id=receipt["lot_id"],verdict="released",note="剩余合格")
        invoice = dict(line_id=line,ref="AP-RETURN-1",due=self.fixture.ahead(7),price="12.34",quantity="3")
        self.act("invoice",409,**dict(invoice,quantity="4"))
        self.act("invoice",**invoice)
        self.act("purchase_return",409,receipt_id=receipt["id"],quantity="1",reason="须先冲减已开票数量")
        traced = self.call("/api/trace?lot="+receipt["lot_id"])
        self.assertEqual(traced["stock"][0]["quantity"],3000)

    def test_practice_gates_follow_the_real_draft_to_close_workflow(self):
        launch = self.call("/api/action/practice",{},token="practice-doubleclick-1")
        self.assertEqual(launch,self.call("/api/action/practice",{},token="practice-doubleclick-1"))
        path = "/api/walkthrough?run="+launch["id"]
        progress = self.call(path)
        self.assertFalse(any(progress["ready"].values()))
        self.assertEqual(self.call("/api/walkthrough")["latest"]["id"],launch["id"])
        sale,purchase,work = (progress[name]["id"] for name in ("sale","purchase","work"))
        orders = {ident:self.call("/api/document/"+ident) for ident in (sale,purchase,work)}
        self.assertTrue(all(row["status"]=="draft" and not row["movements"] for row in orders.values()))
        for ident in (sale,purchase,work):
            self.act("approve",id=ident,decision="approve")
        purchase_line = orders[purchase]["lines"][0]["id"]
        sale_line = orders[sale]["lines"][0]["id"]
        self.act("receive",id=purchase,line_id=purchase_line,quantity="8",lot=launch["ref"]+"-RAW")
        pending = self.call(path)["ready"]
        self.assertTrue(pending["sale"] and pending["purchase"])
        self.assertFalse(pending["raw"])
        self.act("start",409,id=work)
        receipt = self.call("/api/document/"+purchase)["movements"][0]
        self.act("inspect",lot_id=receipt["lot_id"],verdict="released",note="来料检验记录")
        self.act("personnel",code=progress["worker_code"],name="案例装配员",team="装配班")
        worker = next(row for row in self.call("/api/industry/people")["people"] if row["code"]==progress["worker_code"])
        self.act("start",id=work)
        steps = orders[work]["steps"]
        self.act("report",409,id=work,step_id=steps[0]["id"],minutes="15")
        for step in steps:
            self.act("assign_step",id=work,step_id=step["id"],person_id=worker["id"])
            self.act("report",id=work,step_id=step["id"],minutes="15")
        self.act("finish",id=work,lot=launch["ref"]+"-FG")
        batch = self.call(path)["batch"]
        self.assertEqual(batch["status"],"pending")
        self.act("ship",409,id=sale,line_id=sale_line,quantity="4")
        self.act("inspect",lot_id=batch["id"],verdict="released",note="成品质检记录")
        self.act("inventory_count",site_id=progress["site_id"],lot_id=batch["id"],book="4",counted="4",reason="实操盘点")
        self.act("ship",id=sale,line_id=sale_line,quantity="4")
        self.act("dispatch",id=sale,carrier="实操物流",tracking=launch["ref"]+"-T",due=self.fixture.ahead(1))
        shipment = next(row for row in self.call("/api/industry/transport")["shipments"] if row["doc_id"]==sale)
        self.act("sign_shipment",id=shipment["id"],receipt="实操签收回单")
        for ident,line,quantity,price,total,direction in (
            (purchase,purchase_line,"8","32","256","ap"),(sale,sale_line,"4","465","1860","ar"),
        ):
            ref = launch["ref"]+"-"+direction
            self.act("invoice",line_id=line,ref=ref,due=self.fixture.ahead(15),quantity=quantity,price=price)
            invoice = next(row for row in self.call("/api/industry/finance")["invoices"] if row["doc_id"]==ident)
            payment = self.act("payment",id=invoice["id"],ref=ref+"-BANK",amount=total,date=self.fixture.ahead(0))
            self.act("settlement",id=invoice["id"],payment_id=payment["id"],amount=total)
        self.assertTrue(all(self.call(path)["ready"].values()))
        trace = self.call("/api/trace?lot="+batch["id"])
        self.assertEqual(trace["upstream"][0]["id"],receipt["lot_id"])
        self.assertTrue(any(row["doc_id"]==sale for row in trace["movements"]))
        other = self.call("/api/action/practice",{})
        independent = self.call("/api/walkthrough?run="+other["id"])
        self.assertNotEqual(progress["site_id"],independent["site_id"])
        self.assertFalse(any(independent["ready"].values()))
