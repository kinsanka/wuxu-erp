"""Batch reservations, finite line scheduling and customer delivery commitments."""

import re
from datetime import datetime

from erp import (ERP_ZONE, active_lot, audit, date_field, doc_for, field, get, key,
                 new_ref, require, requirements, scaled, today)


def planning_access(account):
    require(account["role"] in {"admin","planner"},"当前角色无计划操作权限",403)


def reservable_demand(db, doc):
    lines=db.all("SELECT l.*,i.code,i.name,i.unit FROM document_lines l "
                 "JOIN items i ON i.id=l.item_id WHERE l.doc_id=%s",(doc["id"],))
    if doc["kind"]=="work":
        return list(requirements(db,doc,lines[0]))
    return [dict(row,required=row["quantity"]-row["fulfilled"]) for row in lines]


def reservation_view(db, doc):
    if doc["kind"]=="purchase" or doc["status"] not in {"draft","approved","partial"}:
        return []
    demand={row["item_id"]:row["required"] for row in reservable_demand(db,doc)}
    records=[row for row in db.all(
        "SELECT l.id,l.code,l.expiry,l.status,l.item_id,i.name,i.code AS item_code,i.unit,"
        "CAST(s.quantity-COALESCE(r.held,0) AS BIGINT) AS free,COALESCE(a.quantity,0) AS own "
        "FROM stock s JOIN lots l ON l.id=s.lot_id JOIN items i ON i.id=l.item_id "
        "LEFT JOIN (SELECT lot_id,SUM(quantity) AS held FROM stock_reservations WHERE site_id=%s "
        "GROUP BY lot_id) r ON r.lot_id=l.id "
        "LEFT JOIN stock_reservations a ON a.lot_id=l.id AND a.doc_id=%s "
        "WHERE s.site_id=%s AND s.quantity>0 AND i.type<>'medical' ORDER BY i.code,l.code",
        (doc["site_id"],doc["id"],doc["site_id"]),
    ) if row["item_id"] in demand]
    totals={}
    for row in records:
        totals[row["item_id"]]=totals.get(row["item_id"],0)+row["own"]
    current=today()
    for row in records:
        row["usable"]=row["status"]=="released" and (not row["expiry"] or row["expiry"]>=current)
        row["maximum"]=min(row["free"]+row["own"],demand[row["item_id"]]-totals[row["item_id"]]+row["own"]) if row["usable"] else 0
    return [row for row in records if row["maximum"]>0 or row["own"]>0]


def reserve_stock(db,payload,account):
    planning_access(account)
    doc=doc_for(db,payload,{"sale","work"},{"approved","partial"})
    lot=get(db,"lots",payload,"lot_id","锁料批次")
    reason=field(payload,"note","锁料依据",400)
    require("quantity" in payload,"请填写锁定数量")
    quantity=scaled(payload,"quantity","锁定数量",zero=True)
    current=db.one("SELECT quantity FROM stock_reservations WHERE doc_id=%s AND lot_id=%s",(doc["id"],lot["id"]))
    require(quantity!=(current["quantity"] if current else 0),"锁料数量没有变化",409)
    if quantity:
        active_lot(lot)
        row=next((row for row in reservation_view(db,doc) if row["id"]==lot["id"]),None)
        require(row and quantity<=row["maximum"],"数量超过本单需求或该批次未锁库存",409)
        db.execute("INSERT INTO stock_reservations VALUES (%s,%s,%s,%s) ON CONFLICT(doc_id,lot_id) "
                   "DO UPDATE SET quantity=excluded.quantity",(doc["id"],doc["site_id"],lot["id"],quantity))
    else:
        db.execute("DELETE FROM stock_reservations WHERE doc_id=%s AND lot_id=%s",(doc["id"],lot["id"]))
    audit(db,account,"调整批次锁料",doc["ref"],f"{lot['code']} · {(current['quantity'] if current else 0)/1000:g} → {quantity/1000:g} · {reason}")
    return {"id":doc["id"],"ref":doc["ref"]}


def parse_time(payload, name):
    time=field(payload,name,"开始时刻",5)
    require(re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]",time),"时刻格式为 HH:MM")
    return int(time[:2])*60+int(time[3:])


def new_production_line(db,payload,account):
    planning_access(account)
    site=get(db,"sites",payload,"site_id","供应仓库")
    code=field(payload,"code","产线编码",40).upper()
    name=field(payload,"name","产线名称",100)
    start=parse_time(payload,"shift_start")
    capacity=scaled(payload,"capacity","班次分钟",1)
    require(start+capacity<=1440,"班次须在同一业务日内")
    require(not db.one("SELECT 1 FROM production_lines WHERE code=%s",(code,)),"产线编码已存在",409)
    db.execute("INSERT INTO production_lines VALUES (%s,%s,%s,%s,%s,%s)",(key(),code,name,site["id"],start,capacity))
    audit(db,account,"新增产线",code,name)
    return {"ref":code}


def line_calendar(db,payload,account):
    planning_access(account)
    line=get(db,"production_lines",payload,"line_id","产线")
    day=date_field(payload,"day","业务日期")
    require(day and day>=today(),"请选择今天或未来的业务日期")
    require("capacity" in payload,"请填写班次分钟")
    capacity=scaled(payload,"capacity","班次分钟",1,True)
    require(line["shift_start"]+capacity<=1440,"班次须在同一业务日内")
    require(not db.one("SELECT 1 FROM work_slots WHERE line_id=%s AND day=%s AND start_minute+minutes>%s",
                       (line["id"],day,line["shift_start"]+capacity)),"该调整会覆盖现有工单，请先改排",409)
    reason=field(payload,"note","变更依据",400)
    db.execute("INSERT INTO production_calendar VALUES (%s,%s,%s) ON CONFLICT(line_id,day) "
               "DO UPDATE SET capacity=excluded.capacity",(line["id"],day,capacity))
    audit(db,account,"调整产线日历",line["code"],f"{day} / {capacity} 分钟 · {reason}")
    return {"ref":line["code"]}


def schedule_work(db,payload,account):
    planning_access(account)
    work=doc_for(db,payload,{"work"},{"draft","approved"})
    reason=field(payload,"note","排程依据",400)
    old=db.one("SELECT * FROM work_slots WHERE doc_id=%s",(work["id"],))
    if payload.get("clear") is True:
        require(old,"本工单尚未排程",409)
        db.execute("DELETE FROM work_slots WHERE doc_id=%s",(work["id"],))
        audit(db,account,"取消工单排程",work["ref"],f"{old['day']} · {reason}")
        return {"id":work["id"],"ref":work["ref"]}
    line=get(db,"production_lines",payload,"line_id","产线")
    require(line["site_id"]==work["site_id"],"产线与工单供料仓不一致",409)
    day=date_field(payload,"day","生产日期")
    require(day and day>=today(),"请选择今天或未来的生产日期")
    require(not work["due"] or day<=work["due"],"排程晚于计划完工日，请先确认并变更工单交期",409)
    start=parse_time(payload,"start")
    minutes=scaled(payload,"minutes","计划分钟",1)
    calendar=db.one("SELECT capacity FROM production_calendar WHERE line_id=%s AND day=%s",(line["id"],day))
    capacity=calendar["capacity"] if calendar else line["capacity"]
    require(line["shift_start"]<=start and start+minutes<=line["shift_start"]+capacity,"工单排程超出当日班次容量",409)
    local=datetime.now(ERP_ZONE)
    require(day!=today() or start+minutes>local.hour*60+local.minute,"所选生产时段已经结束",409)
    conflict=db.one(
        "SELECT d.ref FROM work_slots x JOIN documents d ON d.id=x.doc_id "
        "WHERE x.line_id=%s AND x.day=%s AND x.doc_id<>%s AND x.start_minute<%s AND x.start_minute+x.minutes>%s",
        (line["id"],day,work["id"],start+minutes,start),
    )
    require(not conflict,f"与工单 {conflict['ref']} 的生产时段冲突" if conflict else "",409)
    db.execute("INSERT INTO work_slots VALUES (%s,%s,%s,%s,%s) ON CONFLICT(doc_id) DO UPDATE SET "
               "line_id=excluded.line_id,day=excluded.day,start_minute=excluded.start_minute,minutes=excluded.minutes",
               (work["id"],line["id"],day,start,minutes))
    audit(db,account,"调整工单排程" if old else "登记工单排程",work["ref"],
          f"{line['code']} / {day} / {payload['start']} / {minutes} 分钟 · {reason}")
    return {"id":work["id"],"ref":work["ref"]}


def production_board(db, params):
    day=date_field(params,"day","查询日期") or today()
    local=datetime.now(ERP_ZONE)
    return {"day":day,"current_minute":local.hour*60+local.minute,"lines":db.all(
        "SELECT l.*,s.name AS site,COALESCE(c.capacity,l.capacity) AS day_capacity FROM production_lines l "
        "JOIN sites s ON s.id=l.site_id LEFT JOIN production_calendar c ON c.line_id=l.id AND c.day=%s "
        "WHERE s.type='factory' ORDER BY l.code",(day,)),
        "slots":db.all("SELECT x.*,d.ref,d.status,d.due FROM work_slots x JOIN documents d ON d.id=x.doc_id "
                       "WHERE x.day=%s ORDER BY x.start_minute,d.ref",(day,))}


def work_slot(db, ident):
    return db.one("SELECT x.*,l.code,l.name FROM work_slots x JOIN production_lines l ON l.id=x.line_id WHERE x.doc_id=%s",(ident,))


def commitments(db, doc_id):
    result=db.all(
        "SELECT c.*,i.code,i.name,i.unit,CAST(COALESCE(SUM(-m.quantity),0) AS BIGINT) AS shipped,"
        "CAST(COALESCE(SUM(CASE WHEN sh.signed IS NOT NULL THEN -m.quantity ELSE 0 END),0) AS BIGINT) AS signed,"
        "MAX(sh.signed) AS last_signed FROM delivery_commitments c JOIN document_lines l ON l.id=c.line_id "
        "JOIN items i ON i.id=l.item_id LEFT JOIN delivery_movements x ON x.commitment_id=c.id "
        "LEFT JOIN movements m ON m.id=x.movement_id LEFT JOIN shipment_movements sm ON sm.movement_id=m.id "
        "LEFT JOIN shipments sh ON sh.id=sm.shipment_id WHERE l.doc_id=%s GROUP BY c.id,i.id,i.code,i.name,i.unit ORDER BY c.due,c.ref",
        (doc_id,),
    )
    for row in result:
        if row["cancelled"]:
            row["status"]="cancelled"
        elif row["signed"]>=row["quantity"]:
            signed_day=datetime.fromisoformat(row["last_signed"]).astimezone(ERP_ZONE).date().isoformat()
            row["status"]="signed" if signed_day<=row["due"] else "late"
        else:
            row["status"]="overdue" if row["due"]<today() else "transit" if row["shipped"] else "open"
    return result


def set_commitment(db,payload,account):
    planning_access(account)
    sale=doc_for(db,payload,{"sale"},{"draft","approved","partial"})
    line=get(db,"document_lines",payload,"line_id","销售明细")
    require(line["doc_id"]==sale["id"],"明细不属于当前销售单",409)
    ident=field(payload,"commitment_id","交付批次",64,True)
    old=db.one("SELECT * FROM delivery_commitments WHERE id=%s AND line_id=%s AND cancelled=0",(ident,line["id"])) if ident else None
    require(not ident or old,"交付批次不存在或已撤销",404)
    require(not old or not db.one("SELECT 1 FROM delivery_movements WHERE commitment_id=%s",(ident,)),
            "已有发货流水的承诺须保留原记录",409)
    reason=field(payload,"note","交付依据",400)
    if payload.get("cancel") is True:
        require(old,"请选择要撤销的交付承诺",409)
        db.execute("UPDATE delivery_commitments SET cancelled=1 WHERE id=%s",(ident,))
        audit(db,account,"撤销交付承诺",sale["ref"],old["ref"]+" · "+reason)
        return {"id":sale["id"],"ref":old["ref"]}
    due=date_field(payload,"due","承诺签收日")
    require(due and due>=today(),"承诺签收日不得早于今天")
    quantity=scaled(payload,"quantity","承诺数量")
    planned=sum(row["quantity"]-row["shipped"] for row in commitments(db,sale["id"])
                if row["line_id"]==line["id"] and not row["cancelled"] and row["id"]!=ident)
    require(quantity<=line["quantity"]-line["fulfilled"]-planned,"数量超过该销售明细未承诺的余量",409)
    ref=old["ref"] if old else new_ref("DLV")
    db.execute("INSERT INTO delivery_commitments VALUES (%s,%s,%s,%s,%s,%s,0) "
               "ON CONFLICT(id) DO UPDATE SET quantity=excluded.quantity,due=excluded.due,note=excluded.note",
               (ident or key(),ref,line["id"],quantity,due,reason))
    audit(db,account,"调整交付承诺" if old else "登记交付承诺",sale["ref"],f"{ref} / {due} / {quantity/1000:g} · {reason}")
    return {"id":sale["id"],"ref":ref}


EXECUTION_ACTIONS={
    "reserve_stock":reserve_stock,"production_line":new_production_line,"line_calendar":line_calendar,
    "schedule_work":schedule_work,"delivery_commitment":set_commitment,
}
