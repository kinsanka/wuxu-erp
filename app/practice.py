"""Prepare ordinary ERP drafts and track work submitted through the business modules."""

from datetime import date, timedelta

from erp import audit, eligible, execute, field, key, now, require, sample_dataset, today
from execution import commitments, new_production_line
from industry import apply as industry_action


def allowed(db,account):
    return account["role"]=="admin" and sample_dataset(db)


def launch(db,account,payload=None):
    require(allowed(db,account),"实操案例仅可在已初始化样例的账套由管理员创建",403)
    mode=field(payload or {},"mode","实操类型",20,True) or "standard"
    require(mode in {"standard","rush"},"实操类型无效")
    ident = key()
    code = "PRA-"+ident[:10].upper()
    due = date.fromisoformat(today())

    def action(kind,**values):
        return execute(db,kind,values,account)

    def master(entity,suffix,name,**values):
        ref = action("master",entity=entity,code=code+suffix,name=name,**values)["ref"]
        return db.one(f"SELECT id FROM {entity} WHERE code=%s",(ref,))["id"]

    site = master("sites","-W","实操仓 · "+code,type="factory")
    raw = master("items","-RM","结构件毛坯",type="material",unit="件",quality=True)
    product = master("items","-FG","装配支架",type="product",unit="套",quality=True)
    vendor = master("partners","-V","实操原料供应商",type="vendor")
    customer = master("partners","-C","实操设备客户",type="customer")
    bom = action("bom",item_id=product,version="A.01",lines=[dict(item_id=raw,quantity="2")],
                 steps=[dict(name="机加工"),dict(name="装配检验")])["id"]
    sale = action("sale",site_id=site,partner_id=customer,due=(due+timedelta(days=7)).isoformat(),
                  lines=[dict(item_id=product,quantity="4",price="465")])
    purchase = action("purchase",site_id=site,partner_id=vendor,due=(due+timedelta(days=2)).isoformat(),
                      lines=[dict(item_id=raw,quantity="8",price="32")])
    work = action("work",site_id=site,bom_id=bom,quantity="4",due=(due+timedelta(days=5)).isoformat())
    industry_action(db,"link_supply",dict(id=sale["id"],ref=work["ref"]),account)
    industry_action(db,"link_supply",dict(id=work["id"],ref=purchase["ref"]),account)
    db.execute("INSERT INTO practice_runs VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
               (ident,code,account["id"],site,product,raw,sale["id"],purchase["id"],work["id"],now()))
    if mode=="rush":
        new_production_line(db,{"code":code+"-LN","name":"装配实操产线（三班）","site_id":site,
                                "shift_start":"00:00","capacity":"1440"},account)
        db.execute("INSERT INTO practice_rush_runs VALUES (%s)",(ident,))
    audit(db,account,"创建工业实操案例",code,sale["ref"])
    return {"id":ident,"ref":code}


def latest(db,account):
    if not allowed(db,account):
        return None
    return db.one("SELECT id,code FROM practice_runs WHERE user_id=%s ORDER BY created DESC LIMIT 1",(account["id"],))


def view(db,ident,account):
    require(allowed(db,account),"当前账号无权查看实操进度",403)
    run = db.one("SELECT * FROM practice_runs WHERE id=%s AND user_id=%s",(ident,account["id"]))
    require(run,"实操案例不存在",404)
    docs = {
        name:db.one("SELECT id,ref,status FROM documents WHERE id=%s",(run[name+"_id"],))
        for name in ("sale","purchase","work")
    }
    product = db.one("SELECT id,code FROM items WHERE id=%s",(run["product_id"],))
    raw = db.one("SELECT id,code FROM items WHERE id=%s",(run["raw_id"],))
    batch = db.one("SELECT l.id,l.code,l.status FROM lots l JOIN movements m ON m.lot_id=l.id "
                   "WHERE m.ref=%s AND m.kind='生产完工' ORDER BY m.created LIMIT 1",(docs["work"]["ref"],))
    receipt = db.one("SELECT COALESCE(SUM(m.quantity-COALESCE((SELECT SUM(r.quantity) FROM purchase_returns r "
                     "WHERE r.receipt_id=m.id),0)),0) AS total FROM movements m JOIN accepted_receipts a "
                     "ON a.movement_id=m.id WHERE m.ref=%s AND m.kind='收货'",(docs["purchase"]["ref"],))["total"]
    worker_code = run["code"]+"-OP"
    raw_available = sum(lot["quantity"] for lot in eligible(db,run["raw_id"],run["site_id"],run["work_id"]))
    ready = {
        "sale":docs["sale"]["status"] in {"approved","partial","done"},
        "purchase":docs["purchase"]["status"]=="done",
        "raw":receipt>=8000 and (raw_available>=8000 or docs["work"]["status"] in {"running","done"}),
        "people":bool(db.one("SELECT 1 FROM personnel WHERE code=%s AND active=1",(worker_code,))),
        "work":docs["work"]["status"]=="done", "quality":bool(batch and batch["status"]=="released"),
        "counts":bool(batch and db.one("SELECT 1 FROM inventory_counts WHERE lot_id=%s AND site_id=%s",(batch["id"],run["site_id"]))),
        "ship":docs["sale"]["status"]=="done",
    }
    signed = db.one("SELECT COALESCE(SUM(-m.quantity),0) AS total FROM shipments s JOIN shipment_movements sm ON sm.shipment_id=s.id "
                    "JOIN movements m ON m.id=sm.movement_id WHERE s.doc_id=%s AND s.signed IS NOT NULL",(run["sale_id"],))["total"]
    ready["transport"] = signed>=4000
    for name,quantity in (("sale",4000),("purchase",8000)):
        invoices = db.all(
            "SELECT (SELECT SUM(quantity) FROM trade_invoice_lines WHERE invoice_id=f.id) AS quantity,"
            "(SELECT SUM(amount) FROM trade_invoice_lines WHERE invoice_id=f.id) AS amount,"
            "COALESCE((SELECT SUM(amount) FROM trade_settlements WHERE invoice_id=f.id),0) AS settled "
            "FROM trade_invoices f WHERE f.doc_id=%s",(docs[name]["id"],),
        )
        ready["finance_"+name] = sum(row["quantity"] for row in invoices)>=quantity and all(row["settled"]==row["amount"] for row in invoices)
    rush=bool(db.one("SELECT 1 FROM practice_rush_runs WHERE run_id=%s",(ident,)))
    if rush:
        ticket=db.one("SELECT status FROM expedite_orders WHERE doc_id=%s",(run["sale_id"],))
        splits=[row for row in commitments(db,run["sale_id"]) if not row["cancelled"]]
        def locked(order_id):
            return db.one("SELECT COALESCE(SUM(quantity),0) AS n FROM stock_reservations WHERE doc_id=%s",(order_id,))["n"]
        shipped=db.one("SELECT fulfilled FROM document_lines WHERE doc_id=%s",(run["sale_id"],))["fulfilled"]
        ready.update({
            "rush":bool(ticket and ticket["status"] in {"open","closed"}),
            "commitments":len(splits)>=2 and sum(row["quantity"] for row in splits)==4000,
            "raw_lock":locked(run["work_id"])>=8000 or docs["work"]["status"] in {"running","done"},
            "slot":bool(db.one("SELECT 1 FROM work_slots WHERE doc_id=%s",(run["work_id"],))),
            "product_lock":locked(run["sale_id"])+shipped>=4000,
            "rush_close":bool(ticket and ticket["status"]=="closed"),
        })
    return dict(**docs,run_id=ident,code=run["code"],site_id=run["site_id"],worker_code=worker_code,rush=rush,
                raw=raw,product=product,batch=batch,ready=ready)
