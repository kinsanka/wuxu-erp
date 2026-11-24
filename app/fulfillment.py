"""Industrial order execution views and expediting on live ERP records."""

from erp import audit, choice, date_field, execute, field, get, key, now, plan, require, scaled, today
from industry import link_supply, permitted
from read import DOCUMENTS, INDUSTRIAL_DOCUMENT, INDUSTRIAL_MOVEMENT, MOVEMENTS, document


def order_desk(db, kind):
    require(kind in {"purchase","sale"},"订单工作台不存在",404)
    role = "vendor" if kind=="purchase" else "customer"
    result = {
        "orders": db.all(DOCUMENTS+" WHERE d.kind=%s AND "+INDUSTRIAL_DOCUMENT
                         +" ORDER BY d.created DESC,d.ref LIMIT 500",(kind,)),
        "partners": db.all("SELECT id,code,name,contact FROM partners WHERE type IN (%s,'both') "
                           "AND id<>'medicalvendor' ORDER BY code",(role,)),
        "movements": db.all(MOVEMENTS+" WHERE "+INDUSTRIAL_MOVEMENT
                            +" AND d.kind=%s ORDER BY m.created DESC,m.id LIMIT 500",(kind,)),
    }
    if kind=="purchase":
        result["receipts"] = db.all(
            MOVEMENTS+" JOIN accepted_receipts ar ON ar.movement_id=m.id WHERE "+INDUSTRIAL_MOVEMENT
            +" AND m.kind='收货' AND d.kind='purchase' ORDER BY ar.accepted DESC,m.id LIMIT 500"
        )
    return result


def revise_delivery(db,payload,account):
    permitted(account,{"planner"})
    order = get(db,"documents",payload,"id","单据")
    require(order["kind"] in {"purchase","work"} and order["status"] not in {"done","cancelled"},
            "当前单据不能调整计划日期",409)
    due = date_field(payload,"due","新计划日期")
    require(due and due>=today() and due!=order["due"],"请填写不同且不早于今天的计划日期")
    if order["kind"]=="work":
        slot=db.one("SELECT day FROM work_slots WHERE doc_id=%s",(order["id"],))
        require(not slot or slot["day"]<=due,"新完工日早于已排产时段，请先调整排程",409)
    reason = field(payload,"note","调整依据",400)
    db.execute("UPDATE documents SET due=%s WHERE id=%s",(due,order["id"]))
    db.execute("INSERT INTO delivery_revisions VALUES (%s,%s,%s,%s,%s,%s,%s)",
               (key(),order["id"],order["due"],due,reason,account["username"],now()))
    audit(db,account,"调整计划日期",order["ref"],due+" · "+reason)
    return {"id":order["id"],"ref":order["ref"]}


def purchase_shortage(db,payload,account):
    permitted(account,{"planner"})
    work = get(db,"documents",payload,"id","工单")
    require(work["kind"]=="work" and work["status"] in {"draft","approved"},"当前工单不能生成缺料采购草稿",409)
    item = get(db,"items",payload,"item_id","组件")
    shortage = next((row for row in plan(db,work) if row["item_id"]==item["id"]),None)
    require(shortage and shortage["net"]>0,"该组件当前无需新增采购",409)
    amount = scaled(payload,"quantity","请购数量")
    require(amount<=shortage["net"]-shortage["draft"],"数量超过当前净缺料扣除本工单已关联草稿后的余量",409)
    due = date_field(payload,"due","预计到货日期")
    require(due and due>=today(),"预计到货日期不得早于今天")
    result = execute(db,"purchase",{
        "site_id":work["site_id"],"partner_id":payload.get("partner_id"),"due":due,
        "note":"来源工单 "+work["ref"],
        "lines":[{"item_id":item["id"],"quantity":payload["quantity"],"price":payload.get("price","")}],
    },account)
    link_supply(db,{"id":work["id"],"ref":result["ref"]},account)
    return result


def signed_quantities(db, order_id):
    return {
        row["item_id"]: int(row["quantity"]) for row in db.all(
            "SELECT l.item_id,SUM(-m.quantity) AS quantity FROM shipments sh "
            "JOIN shipment_movements sm ON sm.shipment_id=sh.id JOIN movements m ON m.id=sm.movement_id "
            "JOIN lots l ON l.id=m.lot_id WHERE sh.doc_id=%s AND sh.signed IS NOT NULL GROUP BY l.item_id",
            (order_id,),
        )
    }


def delivery_complete(db, order_id):
    quantities = signed_quantities(db,order_id)
    lines = db.all("SELECT item_id,quantity FROM document_lines WHERE doc_id=%s",(order_id,))
    return bool(lines) and all(quantities.get(row["item_id"],0)>=row["quantity"] for row in lines)


def set_expedite(db,payload,account):
    permitted(account,{"planner"})
    order = get(db,"documents",payload,"id","销售单")
    require(order["kind"]=="sale","急单必须关联销售单",409)
    operation = choice(payload,"operation","操作",{"schedule","followup","close","cancel"})
    ticket = db.one("SELECT * FROM expedite_orders WHERE doc_id=%s",(order["id"],))
    timestamp = now()
    note = field(payload,"note","跟进说明",400)
    if operation=="schedule":
        require(order["status"]!="cancelled" and not delivery_complete(db,order["id"]),"已结束的销售单不能加急",409)
        require(not ticket or ticket["status"]=="open","已结束的急单不能修改交付目标",409)
        priority = choice(payload,"priority","优先级",{"urgent","critical"})
        due = date_field(payload,"due","目标签收日期")
        require(due and due>=today(),"目标签收日期不得早于今天")
        owner = field(payload,"owner","负责人",80)
        action = "调整交付目标" if ticket else "登记急单"
        db.execute(
            "INSERT INTO expedite_orders VALUES (%s,%s,%s,%s,%s,'open',%s) "
            "ON CONFLICT(doc_id) DO UPDATE SET priority=excluded.priority,due=excluded.due,"
            "owner=excluded.owner,updated=excluded.updated",
            (order["id"],priority,due,owner,ticket["reason"] if ticket else note,timestamp),
        )
        note = f"{'特急' if priority=='critical' else '急单'} / {due} / {owner} · {note}"
    else:
        require(ticket and ticket["status"]=="open","急单不存在或已结束",409)
        status = "open"
        if operation=="close":
            require(delivery_complete(db,order["id"]),"销售单尚未足量签收，不能关闭急单",409)
            status = "closed"
        if operation=="cancel":
            status = "cancelled"
        db.execute("UPDATE expedite_orders SET status=%s,updated=%s WHERE doc_id=%s",
                   (status,timestamp,order["id"]))
        action = {"followup":"记录跟进","close":"关闭急单","cancel":"撤销急单"}[operation]
    db.execute("INSERT INTO expedite_events VALUES (%s,%s,%s,%s,%s,%s)",
               (key(),order["id"],action,note,account["username"],timestamp))
    audit(db,account,action,order["ref"],note)
    return {"id":order["id"],"ref":order["ref"]}


def expedite_desk(db,ident=""):
    if not ident:
        return db.all(
            "SELECT e.*,d.ref,d.status AS doc_status,d.due AS order_due,p.name AS customer,s.name AS site "
            "FROM expedite_orders e JOIN documents d ON d.id=e.doc_id JOIN partners p ON p.id=d.partner_id "
            "JOIN sites s ON s.id=d.site_id WHERE "+INDUSTRIAL_DOCUMENT
            +" ORDER BY CASE WHEN e.status='open' THEN 0 ELSE 1 END,e.due,"
            "CASE WHEN e.priority='critical' THEN 0 ELSE 1 END,e.updated DESC"
        )
    order = document(db,ident)
    require(order["kind"]=="sale","销售单不存在",404)
    ticket = db.one("SELECT * FROM expedite_orders WHERE doc_id=%s",(ident,))
    signed = signed_quantities(db,ident)
    for line in order["lines"]:
        line["signed"] = signed.get(line["item_id"],0)
    work = db.all(
        "SELECT d.* FROM supply_links k JOIN documents d ON d.id=k.supply_id "
        "WHERE k.demand_id=%s AND d.kind='work' ORDER BY d.due,d.ref",(ident,),
    )
    for row in work:
        row["shortages"] = [item for item in plan(db,row) if item["shortage"]] if row["status"] in {"draft","approved"} else []
        row["purchase"] = db.all(
            "SELECT d.id,d.ref,d.status,d.due FROM supply_links k JOIN documents d ON d.id=k.supply_id "
            "WHERE k.demand_id=%s AND d.kind='purchase' ORDER BY d.due,d.ref",(row["id"],),
        )
    return {
        "order":order,"ticket":ticket,"work":work,
        "events":db.all("SELECT action,note,actor,created FROM expedite_events WHERE doc_id=%s ORDER BY created DESC,id",(ident,)),
    }


ORDER_ACTIONS = {"expedite":set_expedite,"revise_delivery":revise_delivery,"purchase_shortage":purchase_shortage}
