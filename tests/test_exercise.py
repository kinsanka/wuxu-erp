import json
import secrets
import unittest
from datetime import datetime, timedelta

import test_workflows


class ExerciseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_workflows.WorkflowTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.session = self.login("admin", self.fixture.admin_password)
        self.model = self.call("/api/exercise")

    def login(self, username, password):
        status, headers, body = self.fixture.request("/api/login", dict(username=username,password=password))
        self.assertEqual(status,200,body)
        return headers["Set-Cookie"].split(";")[0]

    def call(self, path, payload=None, expected=200, session=None, idempotency=""):
        status, _, body = self.fixture.request(path,payload,cookie=self.session if session is None else session,
                                               idempotency=idempotency)
        self.assertEqual(status,expected,body.decode())
        return json.loads(body)

    def act(self, operation, expected=200, **values):
        result=self.call("/api/action/exercise",dict(operation=operation,revision=self.model["revision"],**values),expected)
        if expected==200:
            self.model=result
        return result

    def day(self, value, **extra):
        settings=dict(day=value,version=self.model["version"],credit=self.model["credit"],capacity=self.model["capacity"])
        self.act("adjust",**dict(settings,**extra))

    def test_baseline_dates_and_purchase_quality_gates(self):
        analysis=self.model["analysis"]
        self.assertEqual(analysis["in_stock"],20)
        self.assertEqual([row["shortage"] for row in analysis["rows"]],[5,20,0])
        self.assertEqual(analysis["full"],"2026-11-23")
        self.assertEqual([(r["qty"],r["dispatch"],r["arrival"]) for r in analysis["schedules"]["split"]],
                         [(20,"2026-11-17","2026-11-18"),(10,"2026-11-20","2026-11-23")])
        self.assertEqual([r["safety"] for r in self.model["safety_stock"]],[37,39,68,69])
        self.assertEqual([r["reorder"] for r in self.model["safety_stock"]],[117,159,148,189])
        self.act("purchase",po="PO-B",step="asn")
        self.assertEqual(self.model["analysis"]["rows"][1]["available"],40)
        self.act("purchase",409,po="PO-B",step="receive")
        self.day("2026-11-17")
        self.act("purchase",po="PO-B",step="receive")
        self.assertEqual(self.model["analysis"]["rows"][1]["available"],40)
        self.act("purchase",409,po="PO-B",step="release",evidence="太早")
        self.day("2026-11-18")
        self.act("purchase",po="PO-B",step="release",evidence="QC-B")
        self.assertEqual(self.model["analysis"]["rows"][1]["available"],80)
        self.assertEqual(self.model["analysis"]["rows"][1]["frozen"],10)

    def test_hard_gates_overallocation_and_independent_sessions(self):
        self.assertEqual(self.call("/api/exercise",expected=401,session="")["error"],"请先登录")
        password=secrets.token_urlsafe(24)
        self.call("/api/action/user",dict(username="planner-sim",name="计划演练",password=password,role="planner"))
        isolated=self.login("planner-sim",password)
        self.day("2026-11-16",version="REV-A",credit=False,capacity="0")
        blockers=self.model["analysis"]["gates"]
        self.assertEqual(len(blockers),3)
        self.assertIsNone(self.model["analysis"]["full"])
        self.act("promise",409,option="split",evidence="C")
        self.day("2026-11-16",version="REV-B",credit=True,capacity="30")
        self.act("purchase",po="PO-A",step="confirm",confirmed=False,eta="2026-11-18",quality="2026-11-19")
        self.assertIn("PO",self.model["materials"][0]["po"])
        self.assertIn("缺少足量供方确认",self.model["analysis"]["supply"][0])
        self.act("purchase",po="PO-A",step="confirm",confirmed=True,eta="2026-11-18",quality="")
        self.assertEqual(self.model["analysis"]["schedules"],{})
        self.act("stock",code="M-A",stock="24",frozen="5",other="20",evidence="盘点")
        self.assertEqual(self.model["analysis"]["rows"][0]["available"],-1)
        self.assertIn("超过实物",self.model["analysis"]["gates"][0])
        self.assertEqual(self.call("/api/exercise",session=isolated)["analysis"]["in_stock"],20)
        self.assertEqual(self.call("/api/exercise",session=isolated)["revision"],0)
        self.assertEqual(self.call("/api/exercise")["revision"],self.model["revision"])
        stale=dict(operation="reset",revision=0)
        self.call("/api/action/exercise",stale,expected=409)
        reset=dict(operation="reset",revision=self.model["revision"])
        key="reset-simulation-exercise-test"
        first=self.call("/api/action/exercise",reset,idempotency=key)
        second=self.call("/api/action/exercise",reset,idempotency=key)
        self.assertEqual(first,second)
        self.assertEqual(first["analysis"]["in_stock"],20)

    def test_auto_demo_timed_steps_and_read_only_isolation(self):
        self.call("/api/exercise/demo",expected=401,session="")
        self.act("promise",option="full",evidence="保留的手动演练")
        manual=self.model
        before=self.call("/api/state")

        demo=self.call("/api/exercise/demo")
        self.assertEqual(demo,self.call("/api/exercise/demo"))
        self.assertEqual(demo["snapshot"]["available_kits"],20)
        self.assertEqual(len(demo["events"]),29)
        times=[event["end"] for event in demo["events"]]
        self.assertEqual(times,sorted(times))
        self.assertEqual(times[-1],demo["duration"])
        self.assertTrue(all(0<=event["start"]<event["end"] for event in demo["events"]))
        events={event["title"]:event for event in demo["events"]}
        self.assertLess(events["第一批 20 套生产完工"]["start"],events["壳体运输到厂"]["end"])
        self.assertLess(events["执行器排队和来料检验"]["start"],events["第一批 20 套生产完工"]["end"])
        transit=events["第二批跨周末到货"]
        first=datetime.fromisoformat(demo["start"])
        self.assertEqual((first+timedelta(minutes=transit["start"])).weekday(),4)
        self.assertEqual((first+timedelta(minutes=transit["end"])).weekday(),0)
        self.assertGreater(transit["end"]-transit["start"],48*60)
        blocked=[event for event in demo["events"] if event["blocked"]]
        self.assertEqual(len(blocked),2)
        self.assertIn("三单数量",blocked[0]["outcome"])
        self.assertIn("禁止超占",blocked[1]["outcome"])
        self.assertEqual(blocked[1]["snapshot"]["deliveries"][1]["status"],"planned")
        self.assertEqual(events["登记首笔实收并核销"]["snapshot"]["receivable"]["balance"],40000)
        final=demo["events"][-1]["snapshot"]
        self.assertEqual(final["accepted"],30)
        self.assertTrue(final["payable"]["confirmed"])
        self.assertEqual(final["receivable"]["balance"],0)
        self.assertEqual(self.call("/api/exercise"),manual)
        self.assertEqual(self.call("/api/state"),before)

    def test_split_promise_ship_accept_and_finance(self):
        before=self.call("/api/state")
        self.act("promise",400,option="full",evidence="")
        self.act("promise",option="full",evidence="客户首版")
        self.act("promise",option="split",evidence="客户分批签认")
        original=self.model["versions"][0]["baseline"]
        self.assertEqual(original,[dict(qty=30,dispatch="2026-11-20",arrival="2026-11-23")])
        self.act("fulfill",409,leg="2",step="reserve")
        self.act("fulfill",leg="1",step="reserve")
        self.act("fulfill",409,leg="2",step="reserve")
        self.act("promise",409,option="full",evidence="执行后改版")
        self.act("fulfill",409,leg="1",step="produce")
        self.act("purchase",po="PO-A",step="asn")
        self.act("purchase",po="PO-B",step="asn")
        self.day("2026-11-17")
        self.act("purchase",po="PO-B",step="receive")
        self.act("fulfill",leg="1",step="produce")
        self.act("fulfill",leg="1",step="ship",evidence="SHIP-1")
        self.act("fulfill",409,leg="1",step="arrive",evidence="过早")
        self.act("finance",409,step="issue_ar",evidence="ISSUE-EARLY",amount="2000")
        self.day("2026-11-18")
        self.act("fulfill",leg="1",step="arrive",evidence="POD-1")
        self.assertEqual(self.model["versions"][-1]["deliveries"][0]["status"],"arrived")
        self.act("fulfill",leg="1",step="accept",evidence="ACCEPT-1")
        self.act("purchase",po="PO-B",step="release",evidence="QC-B")
        self.act("purchase",po="PO-A",step="receive")
        self.act("fulfill",409,leg="2",step="reserve")
        self.day("2026-11-19")
        self.act("purchase",po="PO-A",step="release",evidence="QC-A")
        self.act("fulfill",leg="2",step="reserve")
        self.day("2026-11-20")
        self.act("fulfill",leg="2",step="produce")
        self.act("fulfill",leg="2",step="ship",evidence="SHIP-2")
        self.day("2026-11-23")
        self.act("fulfill",leg="2",step="arrive",evidence="POD-2")
        self.act("fulfill",leg="2",step="accept",evidence="ACCEPT-2")
        self.assertEqual(self.model["versions"][0]["baseline"],original)
        self.assertEqual([batch["actual"]["arrived"] for batch in self.model["versions"][-1]["deliveries"]],
                         ["2026-11-18","2026-11-23"])
        self.assertEqual(self.model["requested"],"2026-11-20")
        self.act("finance",409,step="post_ap",evidence="超差")
        self.act("finance",step="correct_ap",evidence="AP-更正至18")
        self.act("finance",step="post_ap",evidence="AP-匹配")
        self.act("finance",step="issue_ar",evidence="INV-30",amount="2000")
        self.act("finance",step="credit_ar",evidence="CREDIT-100",amount="100")
        self.act("finance",step="receive_ar",evidence="BANK-1500",amount="1500")
        self.act("finance",409,step="receive_ar",evidence="BANK-401",amount="401")
        ar=self.model["ar"]
        self.assertEqual(ar["invoice"]-ar["credit"]-ar["received"],40000)
        self.assertTrue(self.model["ap"]["posted"])
        self.assertEqual(self.model["ap"]["invoiced"],18)
        after=self.call("/api/state")
        for collection in ("stock","documents","clinical"):
            self.assertEqual(after[collection],before[collection])

