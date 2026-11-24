import os
import secrets
from datetime import date, timedelta

from erp import ADMIN_ACCOUNT_ID, SEED_EXAMPLES, demo_login_enabled, execute, password_hash, today
from industry import apply as industry_action

ADMIN={"id":ADMIN_ACCOUNT_ID,"username":"admin","name":"系统管理员","role":"admin"}


def bootstrap(db):
    current=db.one("SELECT value FROM settings WHERE key='demo'")
    if current:
        return
    db.execute("INSERT INTO settings VALUES ('demo',%s)",(str(int(SEED_EXAMPLES)),))
    password=os.getenv("ERP_ADMIN_PASSWORD","").strip()
    if not password and demo_login_enabled(db):
        password=secrets.token_urlsafe(24)
    if os.getenv("ERP_POSTGRES") == "1":
        db_password=os.getenv("PGPASSWORD","")
        if len(db_password)<14 or db_password==password:
            raise RuntimeError("须设置至少 14 位、与管理员密码不同的 ERP_DB_PASSWORD。")
    if not 14 <= len(password) <= 160 or any(ord(c)<32 for c in password):
        raise RuntimeError("首次初始化须设置 14 至 160 位的 ERP_ADMIN_PASSWORD。")
    db.execute("INSERT INTO users VALUES (%s,%s,%s,%s,%s,1)",
               (ADMIN["id"],ADMIN["username"],ADMIN["name"],password_hash(password),ADMIN["role"]))
    for ident,code,name,kind in (
        ("factory","F01","工厂物料仓","factory"),
        ("central","H01","医院耗材中心库","central"),
        ("clinical","H02","手术室二级库","clinical"),
    ):
        db.execute("INSERT INTO sites VALUES (%s,%s,%s,%s)",(ident,code,name,kind))
    if SEED_EXAMPLES:
        seed_demo(db)


def seed_demo(db):
    def action(name, **payload):
        return execute(db,name,payload,ADMIN)

    def date_ahead(days):
        return (date.fromisoformat(today())+timedelta(days=days)).isoformat()

    db.execute("INSERT INTO partners VALUES ('vendor','V001','华源工业材料（演示）','vendor',''),"
               "('medicalvendor','V002','新程医疗供应（演示）','vendor',''),"
               "('customer','C001','海沐电器装配（演示）','customer','')")
    for row in (
        ("al","MAT-001","铝合金胚料","material","kg",40000,0,0,""),
        ("screw","MAT-002","M6 紧固螺钉","material","件",120000,0,0,""),
        ("bearing","MAT-003","精密轴承","material","件",18000,1,0,""),
        ("module","FG-001","伺服支架组件","product","套",5000,1,0,""),
        ("anchor","MED-001","骨科缝线锚钉","medical","盒",5000,1,1,"06912345678902"),
        ("kit","MED-002","手术无菌耗材包","medical","包",10000,0,1,""),
    ):
        db.execute("INSERT INTO items VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",row)

    def purchase(partner,site,lines):
        result=action("purchase",partner_id=partner,site_id=site,due=date_ahead(7),lines=[
            {"item_id":ident,"quantity":q,"price":p} for ident,q,p in lines])
        action("approve",id=result["id"],decision="approve")
        return result["id"]

    def receive(doc,item,lot,quantity,expiry="",codes=""):
        line=db.one("SELECT id FROM document_lines WHERE doc_id=%s AND item_id=%s",(doc,item))
        action("receive",id=doc,line_id=line["id"],quantity=quantity,lot=lot,expiry=expiry,codes=codes)
        return db.one("SELECT id FROM lots WHERE item_id=%s AND code=%s",(item,lot))["id"]

    industrial=purchase("vendor","factory",[("al","96","32.40"),("screw","240","0.85"),("bearing","40","23.30")])
    receive(industrial,"al","AL-DEMO-01","48")
    receive(industrial,"screw","SC-DEMO-01","160")
    bearing=receive(industrial,"bearing","BR-DEMO-01","20")
    action("inspect",lot_id=bearing,verdict="released",note="演示来料尺寸检验通过")

    medical=purchase("medicalvendor","central",[("anchor","6","380.00"),("kit","5","48.00")])
    anchor=receive(medical,"anchor","ANCH-DEMO-A","6",date_ahead(42),"\n".join(f"SPD-A{i:03}" for i in range(1,7)))
    receive(medical,"kit","KIT-DEMO-B","5",date_ahead(320),"\n".join(f"SPD-K{i:03}" for i in range(1,6)))
    action("inspect",lot_id=anchor,verdict="released",note="演示包装与效期检查通过")
    for code in ("SPD-A001","SPD-A002","SPD-A003"):
        action("transfer",from_id="central",to_id="clinical",code=code)
    action("use",code="SPD-A001",case_ref="OR-DEMO-2401",note="演示耗用，等待回执")

    bom=action("bom",item_id="module",version="A.01",lines=[
        {"item_id":"al","quantity":"2.250"},{"item_id":"screw","quantity":"6"},{"item_id":"bearing","quantity":"1"}],
        steps=[{"name":"机加工"},{"name":"部件装配"}])["id"]
    completed_work=action("work",bom_id=bom,site_id="factory",quantity="4",due=date_ahead(3))
    work=completed_work["id"]
    action("approve",id=work,decision="approve")
    action("start",id=work)
    industry_action(db,"personnel",dict(code="OP-DEMO-01",name="示例操作员",team="总装一班"),ADMIN)
    worker=db.one("SELECT id FROM personnel WHERE code='OP-DEMO-01'")["id"]
    for step in db.all("SELECT id FROM bom_steps WHERE bom_id=%s ORDER BY step_no",(bom,)):
        industry_action(db,"assign_step",dict(id=work,step_id=step["id"],person_id=worker),ADMIN)
        action("report",id=work,step_id=step["id"],minutes="25")
    action("finish",id=work,lot="FG-DEMO-001")
    work=action("work",bom_id=bom,site_id="factory",quantity="24",due=date_ahead(5),note="演示计划，用于查看当前缺料与预计未交量")["id"]
    action("approve",id=work,decision="approve")

    sale=action("sale",partner_id="customer",site_id="factory",due=date_ahead(6),lines=[{"item_id":"module","quantity":"4","price":"465.00"}])
    action("approve",id=sale["id"],decision="approve")
    source=db.one("SELECT ref FROM documents WHERE id=%s",(industrial,))["ref"]
    industry_action(db,"link_supply",dict(id=work,ref=source),ADMIN)
    industry_action(db,"link_supply",dict(id=completed_work["id"],ref=source),ADMIN)
    industry_action(db,"link_supply",dict(id=sale["id"],ref=completed_work["ref"]),ADMIN)
