"""Operational links, dispatch, personnel and trade settlement for factory documents."""

from erp import audit, date_field, field, get, key, new_ref, now, post, require, scaled, today


MODULE_ROLES = {"transport": {"warehouse"}, "people": {"planner"}, "finance": set(), "counts": {"warehouse"}}


def permitted(account, roles):
    require(account["role"]=="admin" or account["role"] in roles, "当前角色无操作权限",403)


def link_supply(db, payload, account):
    demand = get(db,"documents",payload,"id","需求单据")
    reference = field(payload,"ref","供给单号",80).upper()
    source = db.one("SELECT * FROM documents WHERE ref=%s",(reference,))
    expected = {"sale":"work","work":"purchase"}.get(demand["kind"])
    require(source and source["kind"]==expected, "供给单据不存在或类型不匹配",404)
    require(demand["site_id"]==source["site_id"], "需求与供给须属于同一仓库",409)
    require("cancelled" not in {demand["status"],source["status"]}, "已取消单据不能关联",409)
    if expected=="work":
        shared = db.one(
            "SELECT s.id FROM document_lines s JOIN document_lines w ON s.item_id=w.item_id "
            "WHERE s.doc_id=%s AND w.doc_id=%s LIMIT 1",(demand["id"],source["id"]),
        )
    else:
        shared = db.one(
            "SELECT p.id FROM document_lines p JOIN bom_lines b ON b.item_id=p.item_id "
            "WHERE p.doc_id=%s AND b.bom_id=%s LIMIT 1",(source["id"],demand["bom_id"]),
        )
    require(shared,"两单没有共同的成品或 BOM 组件",409)
    require(not db.one("SELECT 1 FROM supply_links WHERE demand_id=%s AND supply_id=%s",(demand["id"],source["id"])),
            "这两张单据已经关联",409)
    db.execute("INSERT INTO supply_links VALUES (%s,%s,%s)",(demand["id"],source["id"],now()))
    audit(db,account,"关联供给单据",demand["ref"],source["ref"])
    return {"ref":demand["ref"]}


def create_person(db,payload,account):
    code = field(payload,"code","工号",40).upper()
    name = field(payload,"name","姓名",80)
    team = field(payload,"team","班组",80)
    require(not db.one("SELECT 1 FROM personnel WHERE code=%s",(code,)),"工号已存在",409)
    db.execute("INSERT INTO personnel VALUES (%s,%s,%s,%s,1)",(key(),code,name,team))
    audit(db,account,"新增生产人员",code,team)
    return {"ref":code}


def unlink_supply(db,payload,account):
    demand = get(db,"documents",payload,"id","需求单据")
    source = get(db,"documents",payload,"supply_id","供给单据")
    changed = db.execute("DELETE FROM supply_links WHERE demand_id=%s AND supply_id=%s",(demand["id"],source["id"]))
    require(changed.rowcount,"该单据关联不存在",404)
    audit(db,account,"解除供给关联",demand["ref"],source["ref"])
    return {"ref":demand["ref"]}


def assign_step(db,payload,account):
    work = get(db,"documents",payload,"id","工单")
    step = get(db,"bom_steps",payload,"step_id","工序")
    worker = get(db,"personnel",payload,"person_id","生产人员")
    require(work["kind"]=="work" and work["status"] in {"draft","approved","running"},"当前工单不能派工",409)
    require(step["bom_id"]==work["bom_id"] and worker["active"],"工序或人员不适用",409)
    require(not db.one("SELECT 1 FROM work_steps WHERE doc_id=%s AND step_id=%s",(work["id"],step["id"])),
            "已报工的工序不能重新派工",409)
    db.execute("INSERT INTO work_assignments VALUES (%s,%s,%s,%s) ON CONFLICT(doc_id,step_id) "
               "DO UPDATE SET person_id=excluded.person_id,created=excluded.created",
               (work["id"],step["id"],worker["id"],now()))
    audit(db,account,"工序派工",work["ref"],step["name"]+" / "+worker["code"])
    return {"ref":work["ref"]}


UNREGISTERED = (" FROM movements m JOIN documents d ON d.ref=m.ref WHERE m.kind='销售发货' "
                "AND d.kind='sale' AND m.quantity<0 AND NOT EXISTS "
                "(SELECT 1 FROM shipment_movements sm WHERE sm.movement_id=m.id)")


def dispatch(db,payload,account):
    order = get(db,"documents",payload,"id","销售单")
    rows = db.all("SELECT m.id"+UNREGISTERED+" AND d.id=%s ORDER BY m.created,m.id",(order["id"],))
    require(rows,"该销售单没有待登记运单的发货流水",409)
    carrier = field(payload,"carrier","承运商",100)
    tracking = field(payload,"tracking","运单号",100)
    due = date_field(payload,"due","预计签收日期")
    require(due,"请填写预计签收日期")
    require(not db.one("SELECT 1 FROM shipments WHERE carrier=%s AND tracking=%s",(carrier,tracking)),"该承运商运单号已登记",409)
    ident, ref = key(), new_ref("SHIP")
    db.execute("INSERT INTO shipments VALUES (%s,%s,%s,%s,%s,%s,%s,NULL,NULL)",(ident,ref,order["id"],carrier,tracking,due,now()))
    for row in rows:
        db.execute("INSERT INTO shipment_movements VALUES (%s,%s)",(ident,row["id"]))
    audit(db,account,"登记承运发运",ref,order["ref"]+" / "+tracking)
    return {"ref":ref}


def sign_shipment(db,payload,account):
    shipment = get(db,"shipments",payload,"id","运单")
    require(not shipment["signed"],"该运单已签收",409)
    receipt = field(payload,"receipt","签收凭证",100)
    db.execute("UPDATE shipments SET signed=%s,receipt=%s WHERE id=%s",(now(),receipt,shipment["id"]))
    audit(db,account,"登记到货签收",shipment["ref"],receipt)
    return {"ref":shipment["ref"]}


BILLABLE_LINES = """WITH returned AS (SELECT receipt_id,SUM(quantity) AS quantity FROM purchase_returns GROUP BY receipt_id),
qualified AS (
    SELECT m.ref,l.item_id,SUM(m.quantity-COALESCE(r.quantity,0)) AS quantity FROM movements m JOIN lots l ON l.id=m.lot_id
     JOIN accepted_receipts a ON a.movement_id=m.id LEFT JOIN returned r ON r.receipt_id=m.id
     WHERE m.kind='收货' GROUP BY m.ref,l.item_id
    UNION ALL
    SELECT m.ref,l.item_id,SUM(-m.quantity) AS quantity FROM movements m JOIN lots l ON l.id=m.lot_id
     JOIN shipment_movements sm ON sm.movement_id=m.id JOIN shipments sh ON sh.id=sm.shipment_id
     WHERE m.kind='销售发货' AND sh.signed IS NOT NULL GROUP BY m.ref,l.item_id
), invoiced AS (SELECT line_id,SUM(quantity) AS quantity FROM trade_invoice_lines GROUP BY line_id)
SELECT dl.id AS line_id,d.id AS doc_id,d.ref AS doc_ref,d.kind,p.name AS partner,i.code,i.name,i.unit,dl.price,
       CAST(COALESCE(q.quantity,0) AS BIGINT) AS qualified,CAST(COALESCE(v.quantity,0) AS BIGINT) AS invoiced
FROM document_lines dl JOIN documents d ON d.id=dl.doc_id JOIN sites s ON s.id=d.site_id
JOIN items i ON i.id=dl.item_id LEFT JOIN partners p ON p.id=d.partner_id
LEFT JOIN qualified q ON q.ref=d.ref AND q.item_id=dl.item_id LEFT JOIN invoiced v ON v.line_id=dl.id
WHERE d.kind IN ('sale','purchase') AND s.type='factory' AND d.status IN ('partial','done') AND dl.price>0"""


def return_purchase(db,payload,account):
    receipt = get(db,"movements",payload,"receipt_id","原收货流水")
    require(receipt["kind"]=="收货" and receipt["quantity"]>0,"原流水不是采购收货",409)
    line = db.one("SELECT dl.id,dl.fulfilled,i.type,d.id AS doc_id,s.type AS site_type FROM documents d "
                  "JOIN document_lines dl ON dl.doc_id=d.id JOIN lots l ON l.item_id=dl.item_id "
                  "JOIN items i ON i.id=l.item_id JOIN sites s ON s.id=d.site_id "
                  "WHERE d.kind='purchase' AND d.ref=%s AND l.id=%s",(receipt["ref"],receipt["lot_id"]))
    require(line and line["site_type"]=="factory" and line["type"]!="medical","仅支持工厂仓工业采购退货",409)
    quantity = scaled(payload,"quantity","退货数量")
    reason = field(payload,"reason","退货原因",400)
    returned = db.one("SELECT COALESCE(SUM(quantity),0) AS total FROM purchase_returns WHERE receipt_id=%s",(receipt["id"],))["total"]
    require(quantity<=receipt["quantity"]-returned and quantity<=line["fulfilled"],"退货超过原收货可退数量",409)
    if db.one("SELECT 1 FROM accepted_receipts WHERE movement_id=%s",(receipt["id"],)):
        billed = db.one(BILLABLE_LINES+" AND dl.id=%s",(line["id"],))
        require(not billed or billed["qualified"]-quantity>=billed["invoiced"],"退货会冲减已开票数量，须先处理发票冲减",409)
    ref = new_ref("RET")
    movement = post(db,receipt["lot_id"],receipt["site_id"],-quantity,"采购退货",receipt["ref"],account,ref+" · "+reason)
    db.execute("INSERT INTO purchase_returns VALUES (%s,%s,%s,%s)",(movement,receipt["id"],ref,quantity))
    db.execute("UPDATE document_lines SET fulfilled=fulfilled-%s WHERE id=%s",(quantity,line["id"]))
    has_receipts = db.one("SELECT 1 FROM document_lines WHERE doc_id=%s AND fulfilled>0 LIMIT 1",(line["doc_id"],))
    db.execute("UPDATE documents SET status=%s WHERE id=%s",("partial" if has_receipts else "approved",line["doc_id"]))
    audit(db,account,"登记采购退货",ref,receipt["ref"]+" / "+reason)
    return {"ref":ref}


def post_invoice(db,payload,account):
    line_id = field(payload,"line_id","单据明细",64)
    line = db.one(BILLABLE_LINES+" AND dl.id=%s",(line_id,))
    require(line,"单据明细未达到开票条件",409)
    quantity = scaled(payload,"quantity","开票数量")
    price = scaled(payload,"price","发票单价",100,True)
    require(price==line["price"],"发票单价与原单不一致",409)
    invoiced = int(line["invoiced"])
    require(quantity<=line["qualified"]-invoiced,"累计开票数量超过已签收或合格收货数量",409)
    amount = ((invoiced+quantity)*price+500)//1000 - (invoiced*price+500)//1000
    require(0<amount<=99999999900,"本次开票金额须在 0.01 至 999999999 元之间")
    direction = "ar" if line["kind"]=="sale" else "ap"
    ref = field(payload,"ref","发票号",80)
    due = date_field(payload,"due","到期日")
    require(due,"请填写到期日")
    invoice = db.one("SELECT * FROM trade_invoices WHERE direction=%s AND ref=%s",(direction,ref))
    if invoice:
        ident = invoice["id"]
        require(invoice["doc_id"]==line["doc_id"] and invoice["due"]==due,"同一发票号须使用同一原单和到期日",409)
        require(not db.one("SELECT 1 FROM trade_settlements WHERE invoice_id=%s",(ident,)),"该发票已开始核销",409)
        require(not db.one("SELECT 1 FROM trade_invoice_lines WHERE invoice_id=%s AND line_id=%s",(ident,line_id)),"该发票已登记这条明细",409)
    else:
        ident = key()
        db.execute("INSERT INTO trade_invoices VALUES (%s,%s,%s,%s,%s,%s)",(ident,ref,direction,line["doc_id"],due,now()))
    db.execute("INSERT INTO trade_invoice_lines VALUES (%s,%s,%s,%s,%s)",(ident,line_id,quantity,price,amount))
    audit(db,account,"登记应收" if direction=="ar" else "登记应付",ref,line["doc_ref"])
    return {"ref":ref}


def settle_invoice(db,payload,account):
    invoice = get(db,"trade_invoices",payload,"id","发票")
    payment = get(db,"trade_payments",payload,"payment_id","收付款单")
    order = db.one("SELECT partner_id FROM documents WHERE id=%s",(invoice["doc_id"],))
    require(payment["partner_id"]==order["partner_id"] and payment["direction"]==invoice["direction"],
            "收付款单和发票的往来单位或方向不一致",409)
    amount = scaled(payload,"amount","核销金额",100)
    amount_due = db.one("SELECT SUM(amount) AS total FROM trade_invoice_lines WHERE invoice_id=%s",(invoice["id"],))
    settled = db.one("SELECT COALESCE(SUM(amount),0) AS total FROM trade_settlements WHERE invoice_id=%s",(invoice["id"],))
    require(amount<=amount_due["total"]-settled["total"],"核销金额超过未结余额",409)
    used = db.one("SELECT COALESCE(SUM(s.amount),0) AS total FROM payment_allocations a "
                  "JOIN trade_settlements s ON s.id=a.settlement_id WHERE a.payment_id=%s",(payment["id"],))
    require(amount<=payment["amount"]-used["total"],"核销金额超过收付款单可用余额",409)
    require(not db.one("SELECT 1 FROM trade_settlements WHERE invoice_id=%s AND ref=%s",(invoice["id"],payment["ref"])),
            "该凭证已用于这张发票，请核对原核销记录",409)
    ident = key()
    db.execute("INSERT INTO trade_settlements VALUES (%s,%s,%s,%s,%s)",(ident,invoice["id"],payment["ref"],amount,now()))
    db.execute("INSERT INTO payment_allocations VALUES (%s,%s)",(ident,payment["id"]))
    audit(db,account,"应收核销" if invoice["direction"]=="ar" else "应付核销",invoice["ref"],payment["ref"])
    return {"ref":payment["ref"]}


def register_payment(db,payload,account):
    invoice = get(db,"trade_invoices",payload,"id","发票")
    order = db.one("SELECT partner_id FROM documents WHERE id=%s",(invoice["doc_id"],))
    direction = invoice["direction"]
    ref = field(payload,"ref","收付款凭证",80).upper()
    amount = scaled(payload,"amount","实际收付款金额",100)
    transacted = date_field(payload,"date","收付款日期")
    require(transacted and transacted<=today(),"请填写实际收付款日期，日期不可晚于今天")
    require(not db.one("SELECT 1 FROM trade_payments WHERE direction=%s AND ref=%s",(direction,ref)),
            "收付款单已登记，请在台账中选择原单核销",409)
    require(not db.one("SELECT 1 FROM trade_settlements s JOIN trade_invoices f ON f.id=s.invoice_id "
                       "WHERE f.direction=%s AND UPPER(s.ref)=%s",(direction,ref)),"凭证已用于历史核销，请核对原记录",409)
    ident = key()
    db.execute("INSERT INTO trade_payments VALUES (%s,%s,%s,%s,%s,%s,%s)",
               (ident,ref,direction,order["partner_id"],amount,transacted,now()))
    audit(db,account,"登记收款单" if direction=="ar" else "登记付款单",ref,invoice["ref"])
    return {"id":ident,"ref":ref}


def record_count(db,payload,account):
    site = get(db,"sites",payload,"site_id","仓库")
    lot = get(db,"lots",payload,"lot_id","批次")
    item = db.one("SELECT type FROM items WHERE id=%s",(lot["item_id"],))
    require(site["type"]=="factory" and item["type"]!="medical","仅支持工厂仓工业物料盘点",409)
    require("book" in payload and "counted" in payload,"须填写账面和实盘数量")
    snapshot = scaled(payload,"book","盘点前账面库存",zero=True)
    counted = scaled(payload,"counted","实盘数量",zero=True)
    reason = field(payload,"reason","盘点依据",400)
    balance = db.one("SELECT quantity FROM stock WHERE site_id=%s AND lot_id=%s",(site["id"],lot["id"]))
    book = balance["quantity"] if balance else 0
    require(snapshot==book,"账面库存已变动，请刷新并重新核对盘点",409)
    ref = new_ref("CNT")
    difference = counted - book
    if difference:
        post(db,lot["id"],site["id"],difference,"盘盈" if difference>0 else "盘亏",ref,account,reason)
    db.execute("INSERT INTO inventory_counts VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
               (key(),ref,site["id"],lot["id"],book,counted,reason,account["username"],now()))
    audit(db,account,"登记库存盘点",ref,lot["code"]+" / "+reason)
    return {"ref":ref}


OPERATIONS = {
    "link_supply": (link_supply,{"planner"}), "unlink_supply": (unlink_supply,{"planner"}),
    "personnel": (create_person,MODULE_ROLES["people"]),
    "assign_step": (assign_step,MODULE_ROLES["people"]), "dispatch": (dispatch,MODULE_ROLES["transport"]),
    "sign_shipment": (sign_shipment,MODULE_ROLES["transport"]), "invoice": (post_invoice,MODULE_ROLES["finance"]),
    "payment": (register_payment,MODULE_ROLES["finance"]), "settlement": (settle_invoice,MODULE_ROLES["finance"]),
    "inventory_count": (record_count,MODULE_ROLES["counts"]),
    "purchase_return": (return_purchase,{"warehouse"}),
}


def apply(db,action,payload,account):
    operation, roles = OPERATIONS[action]
    permitted(account,roles)
    return operation(db,payload,account)


def view(db,module,account,ident=""):
    require(module in MODULE_ROLES,"模块不存在",404)
    permitted(account,MODULE_ROLES[module])
    if ident and module=="transport":
        shipment = get(db,"shipments",{"id":ident},"id","运单")
        shipment["lines"] = db.all(
            "SELECT -m.quantity AS quantity,l.id AS lot_id,l.code AS lot,i.code,i.name,i.unit "
            "FROM shipment_movements sm JOIN movements m ON m.id=sm.movement_id JOIN lots l ON l.id=m.lot_id "
            "JOIN items i ON i.id=l.item_id WHERE sm.shipment_id=%s ORDER BY m.created",(ident,),
        )
        return shipment
    if ident and module=="finance":
        invoice = get(db,"trade_invoices",{"id":ident},"id","发票")
        invoice["lines"] = db.all(
            "SELECT f.quantity,f.price,f.amount,i.code,i.name,i.unit FROM trade_invoice_lines f "
            "JOIN document_lines l ON l.id=f.line_id JOIN items i ON i.id=l.item_id "
            "WHERE f.invoice_id=%s ORDER BY i.code",(ident,),
        )
        invoice["settlements"] = db.all("SELECT ref,amount,created FROM trade_settlements WHERE invoice_id=%s ORDER BY created",(ident,))
        return invoice
    require(not ident,"模块不支持单据详情",404)
    if module=="counts":
        return db.all("SELECT c.*,s.name AS site,l.code AS lot,i.name,i.code,i.unit FROM inventory_counts c "
                      "JOIN sites s ON s.id=c.site_id JOIN lots l ON l.id=c.lot_id JOIN items i ON i.id=l.item_id "
                      "ORDER BY c.created DESC LIMIT 300")
    if module=="transport":
        return {
            "pending":db.all("SELECT d.id,d.ref,COUNT(*) AS batches"+UNREGISTERED+" GROUP BY d.id,d.ref ORDER BY MAX(m.created) DESC LIMIT 300"),
            "shipments":db.all("SELECT sh.*,d.ref AS doc_ref,p.name AS customer FROM shipments sh JOIN documents d ON d.id=sh.doc_id "
                               "LEFT JOIN partners p ON p.id=d.partner_id ORDER BY sh.dispatched DESC LIMIT 300"),
        }
    if module=="people":
        return {
            "people":db.all("SELECT id,code,name,team FROM personnel WHERE active=1 ORDER BY code"),
            "assignments":db.all("SELECT a.person_id,d.id AS doc_id,d.ref,d.status,b.name AS step,w.minutes,a.created "
                                 "FROM work_assignments a JOIN documents d ON d.id=a.doc_id JOIN bom_steps b ON b.id=a.step_id "
                                 "LEFT JOIN work_steps w ON w.doc_id=a.doc_id AND w.step_id=a.step_id "
                                 "ORDER BY a.created DESC LIMIT 300"),
        }
    return {
        "lines":db.all(BILLABLE_LINES+" AND COALESCE(q.quantity,0)>COALESCE(v.quantity,0) ORDER BY d.created DESC LIMIT 300"),
        "invoices":db.all("SELECT f.*,d.ref AS doc_ref,d.partner_id,p.name AS partner,"
                          "CAST((SELECT SUM(amount) FROM trade_invoice_lines WHERE invoice_id=f.id) AS BIGINT) AS amount,"
                          "CAST(COALESCE((SELECT SUM(amount) FROM trade_settlements WHERE invoice_id=f.id),0) AS BIGINT) AS settled "
                          "FROM trade_invoices f JOIN documents d ON d.id=f.doc_id "
                          "LEFT JOIN partners p ON p.id=d.partner_id ORDER BY f.created DESC LIMIT 300"),
        "payments":db.all("SELECT x.*,p.name AS partner,CAST(COALESCE((SELECT SUM(s.amount) FROM payment_allocations a "
                          "JOIN trade_settlements s ON s.id=a.settlement_id WHERE a.payment_id=x.id),0) AS BIGINT) AS allocated "
                          "FROM trade_payments x JOIN partners p ON p.id=x.partner_id ORDER BY x.transacted DESC,x.created DESC LIMIT 300"),
    }
