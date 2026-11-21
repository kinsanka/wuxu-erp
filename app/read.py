from erp import date, lookup, plan, require, today, find_unit

DOCUMENTS = ("SELECT d.*,s.name AS site_name,p.name AS partner_name,b.version,"
             " (SELECT COUNT(*) FROM document_lines x WHERE x.doc_id=d.id) AS line_count"
             " FROM documents d JOIN sites s ON s.id=d.site_id LEFT JOIN partners p ON p.id=d.partner_id"
             " LEFT JOIN boms b ON b.id=d.bom_id")

STOCK = ("SELECT st.quantity,l.id AS lot_id,l.code AS lot,l.expiry,l.status,s.id AS site_id,s.name AS site_name,"
         " i.id AS item_id,i.code,i.name,i.unit,i.type,i.tracked"
         " FROM stock st JOIN lots l ON l.id=st.lot_id JOIN sites s ON s.id=st.site_id"
         " JOIN items i ON i.id=l.item_id WHERE st.quantity>0")

MOVEMENTS = ("SELECT m.*,l.code AS lot,i.code AS item_code,i.name AS item_name,i.unit,s.name AS site_name"
             " FROM movements m JOIN lots l ON l.id=m.lot_id JOIN items i ON i.id=l.item_id JOIN sites s ON s.id=m.site_id")


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
    return {
        "open_orders": {row["kind"]: row["count"] for row in groups},
        "inspect_count": db.one("SELECT COUNT(*) AS n FROM lots WHERE status='pending'")["n"],
        "billing_count": db.one("SELECT COUNT(*) AS n FROM clinical WHERE status<>'confirmed'")["n"],
        "stock_count": len(stock), "expiry": sorted(expiry,key=lambda row:row["days_left"]), "low": low,
        "recent": db.all(DOCUMENTS+" ORDER BY d.created DESC LIMIT 8"),
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
        "users":db.all("SELECT id,username,name,role,enabled FROM users ORDER BY username") if account["role"]=="admin" else [],
        "summary": summary(db),
    }


def document(db,ident):
    result=db.one(DOCUMENTS+" WHERE d.id=%s",(ident,))
    require(result,"单据不存在",404)
    result["lines"]=db.all("SELECT l.*,i.code,i.name,i.unit,i.tracked,i.type FROM document_lines l JOIN items i ON i.id=l.item_id WHERE l.doc_id=%s ORDER BY i.code",(ident,))
    result["movements"]=db.all(MOVEMENTS+" WHERE m.ref=%s ORDER BY m.created DESC",(result["ref"],))
    if result["kind"]=="work":
        result["steps"]=db.all("SELECT b.*,w.minutes,w.note,w.actor,w.created FROM bom_steps b LEFT JOIN work_steps w ON w.step_id=b.id AND w.doc_id=%s WHERE b.bom_id=%s ORDER BY b.step_no",
                               (ident,result["bom_id"]))
        result["plan"]=plan(db,result) if result["status"] in {"draft","approved"} else []
    return result


def bom_detail(db,ident):
    result=lookup(db,"boms",ident,"BOM")
    result["lines"]=db.all("SELECT b.*,i.code,i.name,i.unit FROM bom_lines b JOIN items i ON i.id=b.item_id WHERE b.bom_id=%s ORDER BY i.code",(ident,))
    result["steps"]=db.all("SELECT * FROM bom_steps WHERE bom_id=%s ORDER BY step_no",(ident,))
    return result


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
