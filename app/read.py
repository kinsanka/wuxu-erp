from erp import date, lookup, plan, require, today, find_unit

DOCUMENTS = ("SELECT d.*,s.name AS site_name,p.name AS partner_name,b.version,"
             " (SELECT COUNT(*) FROM document_lines x WHERE x.doc_id=d.id) AS line_count"
             " FROM documents d JOIN sites s ON s.id=d.site_id LEFT JOIN partners p ON p.id=d.partner_id"
             " LEFT JOIN boms b ON b.id=d.bom_id")

STOCK = ("SELECT st.quantity,l.id AS lot_id,l.code AS lot,l.expiry,l.status,s.id AS site_id,s.name AS site_name,"
         " i.id AS item_id,i.code,i.name,i.unit,i.type,i.tracked"
         " FROM stock st JOIN lots l ON l.id=st.lot_id JOIN sites s ON s.id=st.site_id"
         " JOIN items i ON i.id=l.item_id WHERE st.quantity>0")

MOVEMENTS = ("SELECT m.*,l.code AS lot,l.status AS lot_status,l.expiry,i.code AS item_code,i.name AS item_name,i.unit,"
             " s.name AS site_name,d.id AS doc_id FROM movements m JOIN lots l ON l.id=m.lot_id"
             " JOIN items i ON i.id=l.item_id JOIN sites s ON s.id=m.site_id LEFT JOIN documents d ON d.ref=m.ref")


def summary(db):
    stock = db.all(STOCK + " ORDER BY i.code,s.code,l.code")
    current = today()
    current_date = date.fromisoformat(current)
    by_item = {}
    expiry = []
    for row in stock:
        if row["status"] == "released" and (not row["expiry"] or row["expiry"] >= current):
            by_item[row["item_id"]] = by_item.get(row["item_id"],0) + row["quantity"]
        if row["expiry"]:
            row["days_left"] = (date.fromisoformat(row["expiry"])-current_date).days
            if row["days_left"] <= 60:
                expiry.append(row)
    low = []
    for item in db.all("SELECT * FROM items WHERE minimum>0 ORDER BY code"):
        value = by_item.get(item["id"],0)
        if value < item["minimum"]:
            low.append(dict(item, available=value))
    groups = db.all("SELECT kind,COUNT(*) AS count FROM documents WHERE status IN ('approved','partial','running') GROUP BY kind")
    factory_open = " WHERE s.type='factory' AND d.status IN ('approved','partial','running')"
    factory_counts = db.all("SELECT d.kind,COUNT(*) AS count FROM documents d JOIN sites s ON s.id=d.site_id"
                            +factory_open+" GROUP BY d.kind")
    factory_pending = db.one("SELECT COUNT(DISTINCT l.id) AS n FROM lots l JOIN stock st ON st.lot_id=l.id "
                             "JOIN sites s ON s.id=st.site_id WHERE s.type='factory' AND st.quantity>0 AND l.status='pending'")["n"]
    return {
        "open_orders": {row["kind"]: row["count"] for row in groups},
        "inspect_count": db.one("SELECT COUNT(*) AS n FROM lots WHERE status='pending'")["n"],
        "billing_count": db.one("SELECT COUNT(*) AS n FROM clinical WHERE status<>'confirmed'")["n"],
        "stock_count": len(stock), "expiry": sorted(expiry,key=lambda row:row["days_left"]), "low": low,
        "recent": db.all(DOCUMENTS+" ORDER BY d.created DESC LIMIT 8"),
        "factory_open":{row["kind"]:row["count"] for row in factory_counts}, "factory_pending":factory_pending,
        "factory_due":db.all(DOCUMENTS+factory_open+" AND d.due IS NOT NULL ORDER BY d.due,d.created LIMIT 8"),
    }


def state(db,account):
    clinical_access = account["role"] in {"admin","clinical"}
    return {
        "account":account,"today":today(),
        "items":db.all("SELECT * FROM items ORDER BY code"),
        "sites":db.all("SELECT * FROM sites ORDER BY code"),
        "partners":db.all("SELECT * FROM partners ORDER BY code"),
        "boms":db.all("SELECT b.*,i.code,i.name FROM boms b JOIN items i ON i.id=b.item_id ORDER BY i.code,b.created DESC"),
        "documents":db.all(DOCUMENTS+" ORDER BY d.created DESC LIMIT 300"),
        "lots":db.all("SELECT l.*,i.code AS item_code,i.name AS item_name,i.tracked FROM lots l JOIN items i ON i.id=l.item_id ORDER BY l.created DESC"),
        "stock":db.all(STOCK+" ORDER BY i.code,s.code,l.code"),
        "movements":db.all(MOVEMENTS+" ORDER BY m.created DESC LIMIT 200"),
        "inspections":db.all("SELECT e.*,l.code AS lot,i.code AS item_code FROM inspections e JOIN lots l ON l.id=e.lot_id JOIN items i ON i.id=l.item_id ORDER BY e.created DESC LIMIT 100"),
        "units": db.all("SELECT u.*,l.code AS lot,i.name AS item_name,i.code AS item_code,s.name AS site_name FROM units u JOIN lots l ON l.id=u.lot_id JOIN items i ON i.id=l.item_id LEFT JOIN sites s ON s.id=u.site_id ORDER BY u.code LIMIT 200"),
        "clinical":db.all("SELECT c.*,u.code,i.name AS item_name,s.name AS site_name FROM clinical c JOIN units u ON u.id=c.unit_id JOIN lots l ON l.id=u.lot_id JOIN items i ON i.id=l.item_id JOIN sites s ON s.id=c.site_id ORDER BY c.created DESC LIMIT 300") if clinical_access else [],
        "audit":db.all("SELECT * FROM audit ORDER BY created DESC LIMIT 200") if account["role"]=="admin" else [],
        "users":db.all("SELECT id,username,name,role,enabled FROM users ORDER BY username") if account["role"]=="admin" and not account.get("is_demo") else [],
        "summary": summary(db),
    }


def document(db,ident):
    result=db.one(DOCUMENTS+" WHERE d.id=%s",(ident,))
    require(result,"单据不存在",404)
    result["lines"]=db.all("SELECT l.*,i.code,i.name,i.unit,i.tracked,i.type FROM document_lines l JOIN items i ON i.id=l.item_id WHERE l.doc_id=%s ORDER BY i.code",(ident,))
    result["movements"]=db.all(MOVEMENTS+" WHERE m.ref=%s ORDER BY m.created DESC",(result["ref"],))
    result["linked"]=db.all(
        "SELECT d.id,d.ref,d.kind,d.status,sl.demand_id,sl.supply_id FROM supply_links sl "
        "JOIN documents d ON d.id=CASE WHEN sl.demand_id=%s THEN sl.supply_id ELSE sl.demand_id END "
        "WHERE sl.demand_id=%s OR sl.supply_id=%s ORDER BY sl.created",(ident,ident,ident),
    )
    if result["kind"]=="sale":
        result["shipments"]=db.all("SELECT ref,carrier,tracking,due,signed,receipt FROM shipments WHERE doc_id=%s ORDER BY dispatched",(ident,))
        balances = {
            line["item_id"]: dict(released=0,pending=0,blocked=0,expired=0)
            for line in result["lines"]
        }
        current = today()
        for row in db.all(
            "SELECT l.item_id,l.status,l.expiry,s.quantity FROM document_lines dl JOIN lots l ON l.item_id=dl.item_id "
            "JOIN stock s ON s.lot_id=l.id WHERE dl.doc_id=%s AND s.site_id=%s AND s.quantity>0",
            (ident,result["site_id"]),
        ):
            bucket = "expired" if row["expiry"] and row["expiry"]<current else row["status"]
            balances[row["item_id"]][bucket] += row["quantity"]
        for line in result["lines"]:
            line["inventory"] = balances[line["item_id"]]
    if result["kind"]=="work":
        result["steps"]=db.all(
            "SELECT b.*,w.minutes,w.note,w.actor,w.created,p.name AS person,p.code AS person_code FROM bom_steps b "
            "LEFT JOIN work_steps w ON w.step_id=b.id AND w.doc_id=%s LEFT JOIN work_assignments a ON a.step_id=b.id AND a.doc_id=%s "
            "LEFT JOIN personnel p ON p.id=a.person_id WHERE b.bom_id=%s ORDER BY b.step_no",(ident,ident,result["bom_id"]),
        )
        result["plan"]=plan(db,result) if result["status"] in {"draft","approved"} else []
    if result["kind"]=="purchase":
        returns = {row["receipt_id"]:int(row["quantity"]) for row in db.all(
            "SELECT r.receipt_id,SUM(r.quantity) AS quantity FROM purchase_returns r JOIN movements m ON m.id=r.receipt_id "
            "WHERE m.ref=%s GROUP BY r.receipt_id",(result["ref"],),
        )}
        result["factory"] = db.one("SELECT type FROM sites WHERE id=%s",(result["site_id"],))["type"]=="factory"
        for movement in result["movements"]:
            if movement["kind"]=="收货":
                movement["returned"] = returns.get(movement["id"],0)
    return result


def walkthrough_targets(db):
    purchase = db.one(
        "SELECT d.id FROM documents d JOIN movements m ON m.ref=d.ref JOIN lots l ON l.id=m.lot_id "
        "WHERE d.kind='purchase' AND m.kind='收货' AND l.item_id='al' AND l.code='AL-DEMO-01' "
        "ORDER BY m.created LIMIT 1"
    )
    batch = db.one("SELECT id,code FROM lots WHERE item_id='module' AND code='FG-DEMO-001'")
    product = db.one("SELECT id,code FROM items WHERE id='module'")
    work = sale = None
    if batch:
        work = db.one("SELECT DISTINCT doc_id AS id FROM work_links WHERE output_lot=%s",(batch["id"],))
        sale = db.one(
            "SELECT d.id FROM documents d JOIN document_lines l ON l.doc_id=d.id "
            "WHERE d.kind='sale' AND d.site_id='factory' AND d.partner_id='customer' "
            "AND l.item_id='module' AND l.quantity=4000 ORDER BY d.created LIMIT 1"
        )
    return dict(product=product, sale=sale, purchase=purchase, work=work, batch=batch)


def bom_detail(db,ident):
    result=lookup(db,"boms",ident,"BOM")
    result["lines"]=db.all("SELECT b.*,i.code,i.name,i.unit FROM bom_lines b JOIN items i ON i.id=b.item_id WHERE b.bom_id=%s ORDER BY i.code",(ident,))
    result["steps"]=db.all("SELECT * FROM bom_steps WHERE bom_id=%s ORDER BY step_no",(ident,))
    return result


def item_detail(db,ident):
    item = lookup(db,"items",ident,"物料")
    item["boms"] = db.all("SELECT id,version,created FROM boms WHERE item_id=%s ORDER BY created DESC",(ident,))
    item["usage"] = db.all(
        "SELECT b.id,b.version,i.code,i.name,bl.quantity FROM bom_lines bl JOIN boms b ON b.id=bl.bom_id "
        "JOIN items i ON i.id=b.item_id WHERE bl.item_id=%s ORDER BY i.code,b.version",(ident,),
    )
    item["stock"] = db.all(STOCK+" AND i.id=%s ORDER BY s.code,l.code",(ident,))
    item["documents"] = db.all(
        DOCUMENTS+" JOIN document_lines dl ON dl.doc_id=d.id WHERE dl.item_id=%s ORDER BY d.created DESC LIMIT 100",(ident,),
    )
    return item


def trace(db,lot_id,scan,account):
    unit=None
    if scan:
        unit=find_unit(db,scan)
        require(unit,"包装码不存在",404)
        lot_id=unit["lot_id"]
    lot=db.one("SELECT l.*,i.code AS item_code,i.name AS item_name FROM lots l JOIN items i ON i.id=l.item_id WHERE l.id=%s",(lot_id,))
    require(lot,"批次不存在",404)
    graph={}
    totals={}
    for direction, source, destination in (("upstream","output_lot","input_lot"),("downstream","input_lot","output_lot")):
        links=db.all(f"""WITH RECURSIVE graph(id) AS (
            SELECT id FROM lots WHERE id=%s
            UNION
            SELECT w.{destination} FROM work_links w JOIN graph g ON w.{source}=g.id
          )
          SELECT DISTINCT l.id,l.code,i.name,i.code AS item_code,l.status,l.expiry
          FROM graph g JOIN lots l ON l.id=g.id JOIN items i ON i.id=l.item_id
          WHERE l.id<>%s ORDER BY i.code,l.code LIMIT 1001""",(lot_id,lot_id))
        totals[direction]=len(links)>1000
        graph[direction]=links[:1000]
    used=db.all("SELECT c.ref,c.status,c.created,c.case_ref,u.code FROM clinical c JOIN units u ON u.id=c.unit_id WHERE u.lot_id=%s ORDER BY c.created DESC LIMIT 500",(lot_id,)) if account["role"] in {"clinical","admin"} else []
    if unit:
        unit["location"] = lookup(db,"sites",unit["site_id"],"仓库")["name"] if unit["site_id"] else ""
    return dict(lot=lot,unit=unit,**graph,truncated=any(totals.values()),uses=used,
                stock=db.all(STOCK+" AND l.id=%s ORDER BY s.code",(lot_id,)),
                movements=db.all(MOVEMENTS+" WHERE m.lot_id=%s ORDER BY m.created DESC LIMIT 500",(lot_id,)))


EXPORTS = {
    "stock": (STOCK+" ORDER BY i.code,s.code,l.code", (("code","物料编码"),("name","名称"),("site_name","仓库"),("lot","批号"),("expiry","效期"),("status","状态"),("quantity","库存"),("unit","单位"))),
    "movements": (MOVEMENTS+" ORDER BY m.created DESC", (("created","时间 UTC"),("kind","业务"),("ref","单据"),("item_code","物料编码"),("item_name","名称"),("site_name","仓库"),("lot","批号"),("quantity","数量"),("unit","单位"),("actor","操作人"),("detail","说明"))),
    "audit": ("SELECT * FROM audit ORDER BY created DESC", (("created","时间 UTC"),("actor","账号"),("action","操作"),("ref","引用"),("detail","说明"))),
    "clinical": ("SELECT c.*,u.code,i.name AS item_name FROM clinical c JOIN units u ON u.id=c.unit_id JOIN lots l ON l.id=u.lot_id JOIN items i ON i.id=l.item_id ORDER BY c.created DESC",
                 (("created","时间 UTC"),("ref","耗用单"),("case_ref","手术/业务号"),("item_name","耗材"),("code","包装码"),("status","计费状态"),("billing_ref","计费回执"),("note","备注"))),
}
