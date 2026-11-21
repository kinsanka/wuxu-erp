import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from zoneinfo import ZoneInfo

DEMO = os.getenv("ERP_DEMO", "1") == "1"
ERP_ZONE = ZoneInfo(os.getenv("ERP_TIMEZONE", "Asia/Shanghai"))
ROLES = {"admin", "planner", "warehouse", "clinical", "viewer"}
WORKFLOW = {
    "master": {"planner"}, "purchase": {"planner"}, "sale": {"planner"}, "approve": {"planner"},
    "receive": {"warehouse"}, "ship": {"warehouse"}, "bom": {"planner"}, "work": {"planner"},
    "start": {"planner"}, "report": {"planner"}, "finish": {"planner"}, "inspect": {"warehouse"},
    "transfer": {"warehouse", "clinical"}, "use": {"clinical"}, "billing": {"clinical"},
    "user": set(), "password": ROLES,
}


class BusinessError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def require(condition, message, status=400):
    if not condition:
        raise BusinessError(message, status)


def key():
    return uuid4().hex


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def today():
    return datetime.now(ERP_ZONE).date().isoformat()


def field(data, name, label, limit=120, optional=False):
    value = data.get(name, "")
    require(isinstance(value, str), f"{label}须为文本")
    value = value.strip()
    require((value or optional) and len(value) <= limit, f"{label}必填或超出长度上限" if not optional else f"{label}超出长度上限")
    require(not any(ord(c) < 32 and c not in ("\r\n\t\x1d" if name in {"code", "codes"} else "\r\n\t") for c in value), f"{label}含无效字符")
    return value


def choice(data, name, label, choices):
    value = field(data, name, label)
    require(value in choices, f"{label}无效")
    return value


def scaled(data, name, label, scale=1000, zero=False):
    raw = str(data.get(name, "0" if zero else ""))
    require(re.fullmatch(r"[0-9]{1,9}(\.[0-9]{1,3})?", raw), f"{label}须为有效数字")
    try:
        value = Decimal(raw) * scale
    except InvalidOperation:
        raise BusinessError(f"{label}须为有效数字") from None
    require(value == value.to_integral_value() and (value > 0 or zero), f"{label}精度或数值无效")
    return int(value)


def date_field(data, name, label):
    value = field(data, name, label, 10, True)
    if value:
        try:
            require(date.fromisoformat(value).isoformat() == value, f"{label}格式应为 YYYY-MM-DD")
        except ValueError:
            raise BusinessError(f"{label}格式应为 YYYY-MM-DD") from None
    return value or None


def rows(data, name, minimum=1):
    result = data.get(name, [])
    require(isinstance(result, list) and minimum <= len(result) <= 60 and all(isinstance(row, dict) for row in result), "明细数量或格式无效（最多 60 行）")
    return result


def password_hash(password):
    salt = secrets.token_hex(16)
    return salt + ":" + hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def password_matches(password, encoded):
    salt, digest = encoded.split(":")
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(digest, candidate)


def session_key(token):
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(db, token):
    if not token or not re.fullmatch(r"[a-f0-9]{64}", token):
        return None
    return db.one(
        "SELECT u.id,u.username,u.name,u.role FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token=%s AND s.expires>%s AND u.enabled=1", (session_key(token), int(time.time())),
    )


def login(db, data):
    username = field(data, "username", "账号", 60).lower()
    password = field(data, "password", "密码", 160)
    account = db.one("SELECT * FROM users WHERE username=%s AND enabled=1", (username,))
    require(account and password_matches(password, account["password"]), "账号或密码错误", 401)
    token = secrets.token_hex(32)
    db.execute("DELETE FROM sessions WHERE expires <= %s", (int(time.time()),))
    db.execute("INSERT INTO sessions VALUES (%s,%s,%s)", (session_key(token), account["id"], int(time.time()) + 43200))
    return token


def note(data, label="备注"):
    return field(data, "note", label, 400, True)


def audit(db, account, action, ref, detail=""):
    db.execute("INSERT INTO audit VALUES (%s,%s,%s,%s,%s,%s)", (key(), account["username"], action, ref, detail, now()))


def lookup(db, table, ident, label):
    result = db.one(f"SELECT * FROM {table} WHERE id=%s", (ident,))
    require(result is not None, f"{label}不存在", 404)
    return result


def get(db, table, data, name, label):
    return lookup(db, table, field(data, name, label, 64), label)


def unique(db, table, code):
    require(not db.one(f"SELECT id FROM {table} WHERE code=%s", (code,)), "编码已存在", 409)


def new_ref(prefix):
    return f"{prefix}-{today().replace('-', '')[2:]}-{secrets.token_hex(5).upper()}"


def master(db, data, account):
    entity = choice(data, "entity", "资料类型", {"items", "sites", "partners"})
    code = field(data, "code", "编码", 48).upper()
    name = field(data, "name", "名称")
    ident = key()
    unique(db, entity, code)
    if entity == "items":
        category = choice(data, "type", "物料分类", {"material", "product", "medical"})
        gtin = field(data, "gtin", "GTIN", 14, True)
        tracked = int(data.get("tracked") is True)
        require(not tracked or category == "medical", "一码一物仅支持医疗耗材")
        if gtin:
            require(re.fullmatch(r"[0-9]{14}", gtin) and sum(int(n) * (3 if i % 2 else 1) for i, n in enumerate(reversed(gtin))) % 10 == 0, "GTIN 须为校验通过的 14 位编号")
            require(not db.one("SELECT id FROM items WHERE gtin=%s", (gtin,)), "GTIN 已绑定其他物料", 409)
        db.execute("INSERT INTO items VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                   (ident, code, name, category, field(data,"unit","单位",12), scaled(data,"minimum","补货点",zero=True), int(data.get("quality") is True), tracked, gtin))
    elif entity == "sites":
        category = choice(data, "type", "仓库分类", {"factory", "central", "clinical"})
        db.execute("INSERT INTO sites VALUES (%s,%s,%s,%s)", (ident, code, name, category))
    else:
        category = choice(data, "type", "往来类型", {"vendor", "customer", "both"})
        db.execute("INSERT INTO partners VALUES (%s,%s,%s,%s,%s)", (ident, code, name, category, field(data,"contact","联系信息",120,True)))
    audit(db, account, "新增主数据", code, name)
    return {"id": ident, "ref": code}


def create_trade(db, data, account, kind):
    site = get(db, "sites", data, "site_id", "仓库")
    partner = get(db, "partners", data, "partner_id", "往来单位")
    require(site["type"] != "clinical", "采购或销售请使用工厂仓或中心库")
    require(partner["type"] in ("both", "vendor" if kind == "purchase" else "customer"), "往来单位类型不适用")
    ident, ref = key(), new_ref("PO" if kind == "purchase" else "SO")
    db.execute("INSERT INTO documents VALUES (%s,%s,%s,'draft',%s,%s,NULL,%s,%s,%s)",
               (ident, ref, kind, site["id"], partner["id"], note(data), now(), date_field(data,"due","交付日期")))
    seen = set()
    for row in rows(data, "lines"):
        item = get(db, "items", row, "item_id", "物料")
        require(item["id"] not in seen, "同一单据中物料不可重复")
        require(kind != "sale" or not item["tracked"], "一码一物耗材请通过临床耗用流程出库")
        qty = scaled(row, "quantity", "数量")
        require(not item["tracked"] or qty % 1000 == 0, "一码一物数量须为整数")
        db.execute("INSERT INTO document_lines VALUES (%s,%s,%s,%s,0,%s)",
                   (key(), ident, item["id"], qty, scaled(row,"price","单价",100,True)))
        seen.add(item["id"])
    audit(db, account, "新建单据", ref, note(data))
    return {"id": ident, "ref": ref}


def doc_for(db, data, kinds, statuses):
    doc = get(db, "documents", data, "id", "单据")
    require(doc["kind"] in kinds and doc["status"] in statuses, "当前单据状态无法执行此操作", 409)
    return doc


def approve(db, data, account):
    doc = doc_for(db, data, {"sale", "purchase", "work"}, {"draft", "approved"})
    action = choice(data, "decision", "审核决定", {"approve","cancel"})
    require(action == "cancel" or doc["status"] == "draft", "单据已经审核", 409)
    status = "approved" if action == "approve" else "cancelled"
    db.execute("UPDATE documents SET status=%s WHERE id=%s", (status, doc["id"]))
    audit(db, account, "审核通过" if status == "approved" else "取消单据", doc["ref"], note(data))
    return {"ref": doc["ref"]}


def post(db, lot, site, quantity, kind, ref, account, detail=""):
    balance = db.one("SELECT quantity FROM stock WHERE lot_id=%s AND site_id=%s", (lot, site))
    new = (balance["quantity"] if balance else 0) + quantity
    require(new >= 0, "库存不足", 409)
    db.execute("INSERT INTO stock VALUES (%s,%s,%s) ON CONFLICT (lot_id,site_id) DO UPDATE SET quantity=excluded.quantity",
               (lot, site, new))
    db.execute("INSERT INTO movements VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
               (key(), lot, site, quantity, kind, ref, account["username"], now(), detail))


def new_lot(db, item, code, expiry, new_only=False, pending=False):
    lot = db.one("SELECT * FROM lots WHERE item_id=%s AND code=%s", (item["id"], code))
    if lot:
        require(not new_only, "完工批号已存在，请使用新批号", 409)
        require(lot["expiry"] == expiry, "同一物料批号的效期必须一致", 409)
        require(lot["status"] != "blocked", "批次已冻结，不能继续收货", 409)
        if pending and lot["status"] == "released":
            db.execute("UPDATE lots SET status='pending' WHERE id=%s", (lot["id"],))
        return lot["id"]
    ident = key()
    db.execute("INSERT INTO lots VALUES (%s,%s,%s,%s,%s,%s)",
               (ident, item["id"], code, expiry, "pending" if pending else "released", now()))
    return ident


def parse_code(raw):
    raw = raw.strip(" \r\n\t")
    if not (raw.startswith("]d2") or raw.startswith("(01)") or ("\x1d" in raw and raw.startswith("01"))):
        require(raw and all(ord(c) > 32 for c in raw), "请填写有效包装码")
        return raw, {}
    fields = {}
    if raw.startswith("("):
        parts = re.split(r"\((\d{2})\)", raw)
        require(not parts[0] and len(parts) % 2 == 1, "GS1 格式不正确")
        pairs = zip(parts[1::2], parts[2::2])
    else:
        remaining = raw.removeprefix("]d2")
        assembled = []
        while remaining:
            ai, remaining = remaining[:2], remaining[2:]
            if ai in ("01","17"):
                size = 14 if ai == "01" else 6
                value, remaining = remaining[:size], remaining[size:]
            else:
                value, sep, remaining = remaining.partition("\x1d")
            assembled.append((ai, value))
        pairs = assembled
    for ai, value in pairs:
        require(ai in {"01","17","10","21"} and ai not in fields, "仅支持不重复的 GS1 字段 01、17、10、21")
        require(re.fullmatch(r"[0-9]{14}", value) if ai == "01" else re.fullmatch(r"[0-9]{6}", value) if ai == "17" else re.fullmatch(r"[A-Za-z0-9!%&'*+,./:;<=>?_\"-]{1,20}", value), "GS1 字段长度或字符无效")
        fields[ai] = value
    require("01" in fields and "21" in fields, "GS1 一物一码需要 GTIN 和序列号")
    return "".join(f"({ai}){fields[ai]}" for ai in ("01","17","10","21") if ai in fields), fields


def find_unit(db, raw, verify=True):
    code, gs = parse_code(raw)
    if gs:
        unit = db.one("SELECT u.*,l.code AS batch_code,l.expiry FROM units u JOIN lots l ON l.id=u.lot_id JOIN items i ON i.id=l.item_id WHERE i.gtin=%s AND u.serial=%s",
                      (gs["01"], gs["21"]))
        if unit and verify:
            require("10" not in gs or gs["10"] == unit["batch_code"], "扫描码批号与登记记录不一致", 409)
            require("17" not in gs or (unit["expiry"] and unit["expiry"][2:].replace("-","") == gs["17"]), "扫描码效期与登记记录不一致", 409)
        return unit
    return db.one("SELECT * FROM units WHERE code=%s", (code,))


def eligible(db, item, site):
    return db.all("SELECT s.quantity,l.id,l.code,l.expiry FROM stock s JOIN lots l ON l.id=s.lot_id WHERE l.item_id=%s AND s.site_id=%s AND s.quantity>0 "
                  "AND l.status='released' AND (l.expiry IS NULL OR l.expiry >= %s) ORDER BY CASE WHEN l.expiry IS NULL THEN 1 ELSE 0 END,l.expiry,l.created,l.id",
                  (item, site, today()))


def allocate(db, item, site, quantity):
    remaining, chosen = quantity, []
    for lot in eligible(db, item, site):
        amount = min(remaining, lot["quantity"])
        chosen.append((lot["id"], amount))
        remaining -= amount
        if not remaining:
            return chosen
    raise BusinessError("可用库存不足，请检查效期与批次状态", 409)


def complete_trade(db, data, account, kind):
    doc = doc_for(db, data, {kind}, {"approved", "partial"})
    line = get(db, "document_lines", data, "line_id", "单据行")
    require(line["doc_id"] == doc["id"], "明细不属于当前单据")
    item = lookup(db, "items", line["item_id"], "物料")
    qty = scaled(data, "quantity", "数量")
    require(qty <= line["quantity"] - line["fulfilled"], "数量超过待处理余量", 409)
    if kind == "purchase":
        lot_code = field(data, "lot", "批号", 64)
        expiry = date_field(data, "expiry", "效期")
        require(item["type"] != "medical" or expiry, "医疗耗材必须登记效期")
        require(not expiry or expiry >= today(), "禁止收货已过效期物料")
        lot = new_lot(db, item, lot_code, expiry, pending=bool(item["quality"]))
        if item["tracked"]:
            codes = field(data, "codes", "包装码", 12000).split("\n")
            require(qty == len(codes) * 1000, "包装码数量应与本次收货数量一致，一行一码")
            for raw in codes:
                require(len(raw) <= 220, "包装码不能超过 220 字符")
                code, gs = parse_code(raw)
                if gs:
                    require(item["gtin"] == gs["01"] and gs.get("10", lot_code) == lot_code, "扫描码 GTIN 或批号与收货资料不一致")
                    require("17" not in gs or (expiry and expiry[2:].replace("-","") == gs["17"]), "扫描码效期与收货资料不一致")
                require(not find_unit(db, raw, verify=False), f"包装码已登记 {code}", 409)
                db.execute("INSERT INTO units VALUES (%s,%s,%s,%s,%s,'stock')", (key(), code, gs.get("21"), lot, doc["site_id"]))
        post(db, lot, doc["site_id"], qty, "收货", doc["ref"], account, note(data))
    else:
        for lot, amount in allocate(db, item["id"], doc["site_id"], qty):
            post(db, lot, doc["site_id"], -amount, "销售发货", doc["ref"], account, note(data))
    db.execute("UPDATE document_lines SET fulfilled=fulfilled+%s WHERE id=%s", (qty, line["id"]))
    has_open = db.one("SELECT id FROM document_lines WHERE doc_id=%s AND fulfilled<quantity", (doc["id"],))
    db.execute("UPDATE documents SET status=%s WHERE id=%s", ("partial" if has_open else "done", doc["id"]))
    audit(db, account, "采购收货" if kind=="purchase" else "销售发货", doc["ref"], item["code"])
    return {"ref": doc["ref"]}


def create_bom(db, data, account):
    item = get(db, "items", data, "item_id", "成品")
    version = field(data, "version", "版本", 40)
    require(item["type"] == "product", "只可为制成品建立 BOM")
    require(not db.one("SELECT id FROM boms WHERE item_id=%s AND version=%s", (item["id"], version)), "BOM 版本已存在", 409)
    ident = key()
    db.execute("INSERT INTO boms VALUES (%s,%s,%s,%s)", (ident, item["id"], version, now()))
    seen = set()
    for row in rows(data, "lines"):
        component = get(db, "items", row, "item_id", "组件")
        require(component["id"] != item["id"] and not component["tracked"], "组件不能为本成品或一码一物耗材")
        require(component["id"] not in seen, "BOM 组件不可重复")
        db.execute("INSERT INTO bom_lines VALUES (%s,%s,%s,%s)", (key(), ident, component["id"], scaled(row,"quantity","单位用量")))
        seen.add(component["id"])
    for index, row in enumerate(rows(data, "steps", 0), start=1):
        db.execute("INSERT INTO bom_steps VALUES (%s,%s,%s,%s)", (key(), ident, index, field(row,"name","工序名称")))
    ref = item["code"] + " / " + version
    audit(db, account, "新建 BOM", ref)
    return {"id": ident, "ref": ref}


def create_work(db, data, account):
    bom = get(db, "boms", data, "bom_id", "BOM")
    site = get(db, "sites", data, "site_id", "仓库")
    require(site["type"] == "factory", "工单仓库须为工厂仓")
    qty = scaled(data, "quantity", "计划产量")
    ident, ref = key(), new_ref("WO")
    db.execute("INSERT INTO documents VALUES (%s,%s,'work','draft',%s,NULL,%s,%s,%s,%s)",
               (ident, ref, site["id"], bom["id"], note(data), now(), date_field(data,"due","计划完工日")))
    db.execute("INSERT INTO document_lines VALUES (%s,%s,%s,%s,0,0)", (key(), ident, bom["item_id"], qty))
    current = {"bom_id": bom["id"]}
    require(all(row["required"] <= 999999999000 for row in requirements(db, current, {"quantity": qty})), "单个组件需求超过数量上限")
    audit(db, account, "新建工单", ref, note(data))
    return {"id": ident, "ref": ref}


def requirements(db, doc, line):
    for row in db.all("SELECT b.item_id,b.quantity,i.code,i.name,i.unit FROM bom_lines b JOIN items i ON i.id=b.item_id WHERE b.bom_id=%s ORDER BY i.code", (doc["bom_id"],)):
        row["required"] = (row["quantity"] * line["quantity"] + 999) // 1000
        yield row


def plan(db, doc):
    line = db.one("SELECT * FROM document_lines WHERE doc_id=%s", (doc["id"],))
    result = []
    for row in requirements(db, doc, line):
        site_stock = sum(lot["quantity"] for lot in eligible(db, row["item_id"], doc["site_id"]))
        pending = db.one("SELECT COALESCE(SUM(l.quantity-l.fulfilled),0) AS qty FROM document_lines l JOIN documents d ON d.id=l.doc_id "
                         "WHERE l.item_id=%s AND d.site_id=%s AND d.kind='purchase' AND d.status IN ('approved','partial')"
                         " AND (d.due IS NULL OR d.due<=%s)",
                         (row["item_id"], doc["site_id"], doc["due"] or "9999-12-31"))
        row.update(available=site_stock, incoming=int(pending["qty"]), shortage=max(0,row["required"]-site_stock),
                   net=max(0, row["required"]-site_stock-int(pending["qty"])))
        result.append(row)
    return result


def start_work(db, data, account):
    doc = doc_for(db, data, {"work"}, {"approved"})
    line = db.one("SELECT * FROM document_lines WHERE doc_id=%s", (doc["id"],))
    for row in requirements(db, doc, line):
        require(sum(lot["quantity"] for lot in eligible(db,row["item_id"],doc["site_id"])) >= row["required"],
                f"领料失败：{row['name']}可用数量不足", 409)
        for lot, amount in allocate(db, row["item_id"], doc["site_id"], row["required"]):
            post(db, lot, doc["site_id"], -amount, "生产领料", doc["ref"], account)
    db.execute("UPDATE documents SET status='running' WHERE id=%s", (doc["id"],))
    audit(db, account, "领料开工", doc["ref"])
    return {"ref": doc["ref"]}


def report_work(db, data, account):
    doc = doc_for(db, data, {"work"}, {"running"})
    step = get(db, "bom_steps", data, "step_id", "工序")
    require(step["bom_id"] == doc["bom_id"], "工序不属于当前工单")
    next_step = db.one("SELECT b.id FROM bom_steps b LEFT JOIN work_steps w ON w.step_id=b.id AND w.doc_id=%s "
                       "WHERE b.bom_id=%s AND w.step_id IS NULL ORDER BY b.step_no LIMIT 1", (doc["id"], doc["bom_id"]))
    require(next_step and next_step["id"] == step["id"], "请按 BOM 工序顺序报工", 409)
    minutes = scaled(data, "minutes", "工时分钟", 1)
    require(minutes <= 100000, "工时超过上限")
    db.execute("INSERT INTO work_steps VALUES (%s,%s,%s,%s,%s,%s)",
               (doc["id"], step["id"], minutes, note(data), account["username"], now()))
    audit(db, account, "工序报工", doc["ref"], step["name"])
    return {"ref": doc["ref"]}


def finish_work(db, data, account):
    doc = doc_for(db, data, {"work"}, {"running"})
    require(not db.one("SELECT b.id FROM bom_steps b LEFT JOIN work_steps w ON w.step_id=b.id AND w.doc_id=%s "
                       "WHERE b.bom_id=%s AND w.step_id IS NULL", (doc["id"], doc["bom_id"])), "请先完成所有工序报工", 409)
    inputs = db.all("SELECT DISTINCT l.id,l.status,l.expiry FROM movements m JOIN lots l ON l.id=m.lot_id WHERE m.ref=%s AND m.kind='生产领料'", (doc["ref"],))
    require(all(lot["status"] == "released" and (not lot["expiry"] or lot["expiry"]>=today()) for lot in inputs),
            "投入批次存在隔离、冻结或效期异常，无法完工", 409)
    line = db.one("SELECT * FROM document_lines WHERE doc_id=%s", (doc["id"],))
    item = lookup(db,"items",line["item_id"],"成品")
    expiry = date_field(data, "expiry", "效期")
    require(not expiry or expiry >= today(), "效期不可早于当前日期")
    lot = new_lot(db,item,field(data,"lot","成品批号",64),expiry,new_only=True,pending=True)
    post(db, lot, doc["site_id"], line["quantity"], "生产完工", doc["ref"], account, note(data))
    for source in inputs:
        db.execute("INSERT INTO work_links VALUES (%s,%s,%s)", (doc["id"],source["id"],lot))
    db.execute("UPDATE document_lines SET fulfilled=quantity WHERE id=%s", (line["id"],))
    db.execute("UPDATE documents SET status='done' WHERE id=%s", (doc["id"],))
    audit(db, account, "完工待检", doc["ref"])
    return {"ref": doc["ref"], "lot_id": lot}


def inspect(db, data, account):
    lot = get(db, "lots", data, "lot_id", "批次")
    verdict = choice(data,"verdict","质检决定",{"released","blocked","pending"})
    reason = field(data,"note","检验结论或冻结原因",400)
    require(lot["status"] != verdict, "批次已经处于该状态", 409)
    require(verdict != "released" or not lot["expiry"] or lot["expiry"] >= today(), "过效期批次不能放行", 409)
    db.execute("UPDATE lots SET status=%s WHERE id=%s", (verdict,lot["id"]))
    db.execute("INSERT INTO inspections VALUES (%s,%s,%s,%s,%s,%s)", (key(),lot["id"],verdict,reason,account["username"],now()))
    audit(db,account,{"released":"质检放行","blocked":"冻结批次","pending":"隔离批次"}[verdict],lot["code"],reason)
    return {"ref": lot["code"]}


def active_lot(lot):
    require(lot["status"] == "released" and (not lot["expiry"] or lot["expiry"] >= today()), "批次未放行、已冻结或已过期", 409)


def transfer(db,data,account):
    source = get(db,"sites",data,"from_id","调出仓")
    target = get(db,"sites",data,"to_id","调入仓")
    require(source["id"] != target["id"], "调出仓与调入仓不能相同")
    scan = field(data,"code","包装码",220,True)
    if scan:
        unit = find_unit(db,scan)
        require(unit and unit["status"] == "stock" and unit["site_id"] == source["id"], "包装码不在调出仓、已耗用或未登记", 409)
        lot = lookup(db,"lots",unit["lot_id"],"批次")
        quantity = 1000
    else:
        require(account["role"] != "clinical", "临床角色请使用包装码调拨", 403)
        lot = get(db,"lots",data,"lot_id","批次")
        item = lookup(db,"items",lot["item_id"],"物料")
        require(not item["tracked"], "一码一物耗材必须逐件使用包装码调拨")
        quantity = scaled(data,"quantity","调拨数量")
    if account["role"] == "clinical":
        require("clinical" in (source["type"],target["type"]), "临床调拨需涉及二级库", 403)
    ref = new_ref("TR")
    item = lookup(db,"items",lot["item_id"],"物料")
    require("clinical" not in (source["type"],target["type"]) or item["type"] == "medical", "二级库仅允许医疗耗材")
    active_lot(lot)
    detail = f"{source['code']} → {target['code']}" + (f" / {unit['code']}" if scan else "")
    post(db,lot["id"],source["id"],-quantity,"调拨出库",ref,account,detail)
    post(db,lot["id"],target["id"],quantity,"调拨入库",ref,account,detail)
    if scan:
        db.execute("UPDATE units SET site_id=%s WHERE id=%s", (target["id"],unit["id"]))
    audit(db,account,"仓库调拨",ref,detail)
    return {"ref": ref}


def use_medical(db,data,account):
    unit = find_unit(db,field(data,"code","包装码",220))
    require(unit and unit["status"] == "stock", "包装码未登记或已经耗用", 409)
    site = lookup(db,"sites",unit["site_id"],"仓库")
    require(site["type"] == "clinical", "耗材须先调拨到临床二级库")
    lot = lookup(db,"lots",unit["lot_id"],"批次")
    active_lot(lot)
    case_ref = field(data,"case_ref","手术/业务号",80)
    ref = new_ref("USE")
    post(db,lot["id"],site["id"],-1000,"临床耗用",ref,account,unit["code"])
    db.execute("UPDATE units SET site_id=NULL,status='used' WHERE id=%s", (unit["id"],))
    db.execute("INSERT INTO clinical VALUES (%s,%s,%s,%s,%s,'pending',NULL,%s,%s,NULL)",
               (key(),ref,unit["id"],site["id"],case_ref,note(data),now()))
    audit(db,account,"临床耗用",ref,unit["code"])
    return {"ref": ref}


def billing(db,data,account):
    record = get(db,"clinical",data,"id","耗用记录")
    decision = choice(data,"decision","计费状态",{"confirmed","rejected"})
    require(record["status"] != "confirmed" and record["status"] != decision,"计费已确认或状态未变化",409)
    external = field(data,"billing_ref","费用回执",100,optional=decision=="rejected")
    comment = field(data,"note","原因",400,optional=decision=="confirmed")
    db.execute("UPDATE clinical SET status=%s,billing_ref=%s,billed=%s WHERE id=%s",(decision,external or None,now(),record["id"]))
    audit(db,account,"确认计费" if decision=="confirmed" else "计费退回",record["ref"],external or comment)
    return {"ref": record["ref"]}


def create_user(db,data,account):
    username = field(data,"username","账号",60).lower()
    require(re.fullmatch(r"[a-z0-9_.-]{2,60}",username),"账号限小写字母、数字、点、下划线或短横线")
    require(not db.one("SELECT id FROM users WHERE username=%s",(username,)),"账号已存在",409)
    password = field(data,"password","密码",160)
    require(len(password)>=12,"密码至少 12 位")
    role=choice(data,"role","角色",ROLES - {"admin"})
    db.execute("INSERT INTO users VALUES (%s,%s,%s,%s,%s,1)",
               (key(),username,field(data,"name","名称"),password_hash(password),role))
    audit(db,account,"新建账号",username)
    return {"ref":username}


def change_password(db,data,account):
    user = lookup(db,"users",account["id"],"账号")
    current = field(data,"current","当前密码",160)
    password = field(data,"password","新密码",160)
    require(password_matches(current,user["password"]),"当前密码错误",403)
    require(len(password)>=12 and password!=current,"新密码至少 12 位且需与当前密码不同")
    db.execute("UPDATE users SET password=%s WHERE id=%s",(password_hash(password),user["id"]))
    db.execute("DELETE FROM sessions WHERE user_id=%s",(user["id"],))
    audit(db,account,"更改密码",user["username"])
    return {"ref":user["username"]}


ACTIONS = {
    "master":master, "purchase":lambda d,v,u:create_trade(d,v,u,"purchase"),
    "sale":lambda d,v,u:create_trade(d,v,u,"sale"), "approve":approve,
    "receive":lambda d,v,u:complete_trade(d,v,u,"purchase"), "ship":lambda d,v,u:complete_trade(d,v,u,"sale"),
    "bom":create_bom, "work":create_work, "start":start_work, "report":report_work,
    "finish":finish_work, "inspect":inspect, "transfer":transfer, "use":use_medical, "billing":billing,
    "user":create_user,"password":change_password,
}


def execute(db,action,data,account):
    require(action in ACTIONS,"操作不存在",404)
    require(account["role"]=="admin" or account["role"] in WORKFLOW[action],"当前角色无操作权限",403)
    return ACTIONS[action](db,data,account)
