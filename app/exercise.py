"""The report's urgent order exercise, isolated from operational ERP records."""

import json
from datetime import date, timedelta
from math import ceil, sqrt
from statistics import NormalDist

from erp import choice, date_field, field, require, scaled

ORDER_REF = "SO-SIM-001"
ORDER_QTY = 30
REQUESTED = "2026-11-20"
BASE = "2026-11-16"
VERSION = "REV-B"


def initial():
    return {
        "day": BASE, "version": VERSION, "credit": True, "capacity": 30, "transport": 1,
        "materials": [
            dict(code="M-A", name="壳体", usage=1, stock=50, frozen=5, other=20, po="PO-A",
                 ordered=20, state="confirmed", eta="2026-11-18", quality="2026-11-19"),
            dict(code="M-B", name="执行器", usage=2, stock=70, frozen=10, other=20, po="PO-B",
                 ordered=40, state="confirmed", eta="2026-11-17", quality="2026-11-18"),
            dict(code="M-C", name="包材", usage=1, stock=100, frozen=0, other=30, po="",
                 ordered=0, state="", eta=None, quality=None),
        ],
        "versions": [], "events": [],
        "ap": dict(ordered=20, accepted=18, invoiced=20, order_price=10000, invoice_price=10000, posted=False),
        "example_ar": dict(invoice=200000, credit=10000, received=150000, due="2026-11-15"),
        "ar": None,
    }


def workday(day, count):
    current = date.fromisoformat(day)
    for _ in range(count):
        current += timedelta(days=1)
        while current.weekday() >= 5:
            current += timedelta(days=1)
    return current.isoformat()


def active(model):
    return model["versions"][-1]["deliveries"] if model["versions"] else []


def available(row):
    pending = row["ordered"] if row["state"] == "received" else 0
    return row["stock"] - row["frozen"] - row["other"] - pending


def allocation(legs):
    return sum(leg["qty"] for leg in legs if leg["status"] == "reserved")


def decision(model):
    legs = active(model)
    remaining = ORDER_QTY - sum(leg["qty"] for leg in legs if leg["status"] != "planned")
    reserved = allocation(legs)
    results, gates, supply = [], [], []
    if model["version"] != VERSION:
        gates.append("工程版本不符，须使用受控 REV-B")
    if not model["credit"]:
        gates.append("客户信用尚未放行")
    if not model["capacity"]:
        gates.append("日产能尚未确认")
    shortage_coverage = []
    day = model["day"]
    for row in model["materials"]:
        held = reserved * row["usage"]
        free = available(row) - held
        need = remaining * row["usage"]
        shortage = max(0, need - max(free, 0))
        if free < 0:
            gates.append(f"{row['code']} 冻结、待检和预留合计超过实物")
        ready = day
        if shortage:
            if row["state"] not in {"confirmed", "asn", "received"} or row["ordered"] < shortage or not row["quality"]:
                supply.append(f"{row['code']} 缺 {shortage} 件，缺少足量供方确认或质量可用日期")
                ready = None
            elif row["quality"] < day:
                supply.append(f"{row['code']} 预计质量可用日已过且仍未放行")
                ready = None
            else:
                ready = row["quality"]
                shortage_coverage.append(ready)
        results.append(dict(row, reserved=held, available=free, need=need, shortage=shortage, ready=ready))
    in_stock = min(remaining, *(max(row["available"], 0) // row["usage"] for row in results))
    ready_date = max([day, *shortage_coverage])
    schedules = {}
    if remaining and not gates and not supply:
        full = schedule(remaining, ready_date, model)
        schedules["full"] = [full]
        if 0 < in_stock < remaining:
            first = schedule(in_stock, day, model)
            next_start = max(ready_date, first["dispatch"])
            schedules["split"] = [first, schedule(remaining-in_stock, next_start, model)]
    forecast = schedules.get("full", [])
    return {"rows": results, "in_stock": in_stock, "remaining": remaining, "gates": gates, "supply": supply,
            "schedules": schedules, "full": forecast[-1]["arrival"] if forecast else None}


def schedule(quantity, ready, model):
    dispatch = workday(ready, ceil(quantity / model["capacity"]))
    return dict(qty=quantity, dispatch=dispatch, arrival=workday(dispatch, model["transport"]))


def log(model, account, event, ref, detail=""):
    model["events"].append(dict(day=model["day"], actor=account["username"], event=event, ref=ref, detail=detail))


def po_action(model, payload, account):
    row = next((row for row in model["materials"] if row["po"] and row["po"]==payload.get("po")), None)
    require(row, "采购单不存在", 404)
    step = choice(payload, "step", "采购操作", {"confirm", "asn", "receive", "release"})
    state = row["state"]
    if step == "confirm":
        require(state in {"confirmed", "unconfirmed", "asn"}, "实收后不能改供方确认", 409)
        confirmed = payload.get("confirmed") is True
        eta = date_field(payload, "eta", "预计到货日")
        quality = date_field(payload, "quality", "预计质量可用日")
        require(not (eta and quality) or quality >= eta, "质量可用日不能早于预计到货日")
        row.update(state=(state if state=="asn" else "confirmed") if confirmed else "unconfirmed", eta=eta, quality=quality)
        log(model,account,"供方确认" if confirmed else "撤回供方确认",row["po"],quality or "质量可用日未定")
    elif step == "asn":
        require(state=="confirmed" and row["eta"], "先完成供方确认及预计到货日", 409)
        row["state"]="asn"
        log(model,account,"记录 ASN 在途",row["po"],row["eta"])
    elif step == "receive":
        require(state=="asn" and model["day"]>=row["eta"], "须先记录 ASN，并将模拟日期推进到到货日", 409)
        row["stock"] += row["ordered"]
        row["state"]="received"
        log(model,account,"GR 仓库实收待检",row["po"],f"{row['ordered']} 件")
    else:
        require(state=="received" and (not row["quality"] or model["day"]>=row["quality"]), "须先实收并核对模拟质量可用日期", 409)
        evidence = field(payload,"evidence","质检凭证",100)
        row["state"]="released"
        log(model,account,"来料质检放行",row["po"],evidence)


def accept_promise(model, payload, account):
    require(all(leg["status"]=="planned" for leg in active(model)), "已开始执行，当前演练只支持执行前改版", 409)
    option = choice(payload, "option", "交付方案", {"full", "split"})
    forecast = decision(model)
    require(not forecast["gates"] and not forecast["supply"], "；".join(forecast["gates"]+forecast["supply"]), 409)
    proposed = forecast["schedules"].get(option)
    require(proposed, "当前条件下没有该交付方案", 409)
    evidence = field(payload,"evidence","客户确认凭证",100)
    deliveries = []
    for index, row in enumerate(proposed,1):
        arrival = date_field(payload,f"arrival{index}",f"第 {index} 批约定到达日") or row["arrival"]
        require(arrival>=row["arrival"], "协商日期早于试算可达日期", 409)
        require(not deliveries or arrival>=deliveries[-1]["arrival"], "后一批到达日不能早于前一批")
        deliveries.append(dict(row, earliest_arrival=row["arrival"], arrival=arrival, status="planned", actual={}))
    version = len(model["versions"])+1
    model["versions"].append(dict(number=version, day=model["day"], ref=evidence, deliveries=deliveries,
                                  baseline=[{k: row[k] for k in ("qty","dispatch","arrival")} for row in deliveries]))
    log(model,account,"首次承诺" if version==1 else "承诺改版",f"{ORDER_REF} V{version}",evidence)


def fulfill(model, payload, account):
    legs = active(model)
    index = scaled(payload,"leg","交付批次",1)
    require(0<index<=len(legs), "先确认交付承诺", 409)
    leg = legs[index-1]
    step = choice(payload,"step","履约动作",{"reserve","produce","ship","arrive","accept"})
    transitions = {"reserve":("planned","reserved","锁料"),"produce":("reserved","produced","生产完工"),
                   "ship":("produced","shipped","出库发运"),"arrive":("shipped","arrived","到货签收"),
                   "accept":("arrived","accepted","客户验收")}
    source,target,label=transitions[step]
    require(leg["status"]==source,"此交付批次当前不能执行该动作",409)
    day=model["day"]
    evidence=""
    if step in {"produce","ship","arrive"}:
        require(date.fromisoformat(day).weekday()<5,"生产和运输按周一至周五推进",409)
    if step in {"reserve","produce","ship"}:
        forecast = decision(model)
        require(not forecast["gates"],"；".join(forecast["gates"]),409)
    if step=="reserve":
        require(all(batch["status"]!="planned" for batch in legs[:index-1]),"请按承诺顺序为各批次锁料",409)
        require(all(row["available"]>=leg["qty"]*row["usage"] for row in forecast["rows"]),
                "质量可用件不足，禁止超占库存。",409)
    elif step=="produce":
        require(all(batch["status"] not in {"planned","reserved"} for batch in legs[:index-1]),"请按承诺顺序完工",409)
        earliest=max(leg["dispatch"],workday(leg["actual"]["reserved"],ceil(leg["qty"]/model["capacity"])))
        require(day>=earliest,"尚未到实际齐套后的最早完工工作日",409)
        for row in model["materials"]:
            row["stock"]-=leg["qty"]*row["usage"]
    elif step=="ship":
        evidence=field(payload,"evidence","发运单号",100)
    elif step=="arrive":
        require(day>=workday(leg["actual"]["shipped"],model["transport"]),"尚未到按运输工作日计算的最早到货日",409)
        evidence=field(payload,"evidence","签收回单号",100)
    else:
        evidence=field(payload,"evidence","验收凭证",100)
    leg["status"]=target
    leg["actual"][target]=day
    log(model,account,label,f"{ORDER_REF} / 第 {index} 批",evidence or f"{leg['qty']} 套")


def adjust(model,payload,account):
    day = date_field(payload,"day","模拟日期") or model["day"]
    require(day>=model["day"],"演练日期只能向前推进")
    require(date.fromisoformat(day)<=date.fromisoformat(BASE)+timedelta(days=365),"日期超出演练范围")
    version = field(payload,"version","订单工程版本",20)
    capacity = scaled(payload,"capacity","日产能",1,True)
    require(capacity<=1000,"日产能最多 1,000 套")
    model.update(day=day,version=version,credit=payload.get("credit") is True,capacity=capacity)
    log(model,account,"更新执行条件",ORDER_REF,f"{version} / 日产能 {capacity}")


def count_stock(model,payload,account):
    code=field(payload,"code","物料",20)
    row=next((row for row in model["materials"] if row["code"]==code),None)
    require(row,"物料不存在",404)
    values={}
    for key,label in (("stock","实物数量"),("frozen","冻结数量"),("other","其他订单预留量")):
        value=scaled(payload,key,label,1,True)
        require(value<=100000,"模拟库存数量最多 100,000 件")
        values[key]=value
    evidence=field(payload,"evidence","盘点或分配依据",100)
    row.update(values)
    log(model,account,"更新模拟库存",code,evidence)


def finance(model,payload,account):
    step=choice(payload,"step","核账动作",{"correct_ap","post_ap","issue_ar","credit_ar","receive_ar"})
    evidence=field(payload,"evidence","业务凭证",100)
    ap=model["ap"]
    if step=="correct_ap":
        require(not ap["posted"] and ap["invoiced"] != ap["accepted"],"采购发票当前无需数量修正",409)
        ap["invoiced"]=ap["accepted"]
        log(model,account,"供方发票修正", "AP-SIM-001",evidence)
    elif step=="post_ap":
        require(not ap["posted"],"应付已确认",409)
        require(ap["accepted"]<=ap["ordered"] and ap["invoiced"]==ap["accepted"] and ap["invoice_price"]==ap["order_price"],
                "三单数量或单价不匹配，应付过账被拦截",409)
        ap["posted"]=True
        log(model,account,"三单匹配并确认应付","AP-SIM-001",evidence)
    elif step=="issue_ar":
        require(not model["ar"] and active(model) and all(leg["status"]=="accepted" for leg in active(model)),
                "须待全部交付验收，且销售发票只能开立一次",409)
        amount = scaled(payload,"amount","模拟发票金额",100)
        model["ar"]=dict(ref=evidence, invoice=amount,credit=0,received=0,due=workday(model["day"],5))
        log(model,account,"模拟开票与确认应收",ORDER_REF,evidence)
    else:
        ar=model["ar"]
        require(ar,"先确认销售应收",409)
        amount=scaled(payload,"amount","金额",100)
        require(amount<=ar["invoice"]-ar["credit"]-ar["received"],"金额超过剩余应收",409)
        key="credit" if step=="credit_ar" else "received"
        ar[key]+=amount
        log(model,account,"登记已批准贷项" if key=="credit" else "登记实收核销",ar["ref"],evidence)


def safety_stock():
    result=[]
    for days, deviation in [(4,1),(6,1),(4,2),(6,2)]:
        safety=ceil(NormalDist().inv_cdf(0.95)*sqrt(days*5**2+20**2*deviation**2))
        result.append(dict(days=days,deviation=deviation,safety=safety,reorder=days*20+safety))
    return result


def exceptions(model):
    shell, actuator, _ = model["materials"]
    legs = active(model)
    ap = model["ap"]
    shell_closed = shell["state"] == "released"
    quality_closed = actuator["frozen"] == 0 and actuator["state"] == "released"
    delivery_closed = bool(legs) and all(leg["status"]=="accepted" for leg in legs)
    return [
        dict(ref="EX-01", issue="壳体缺料", owner="物料计划／采购", due="2026-11-17",
             stage="已放行" if shell_closed else ("供方未确认" if shell["state"]=="unconfirmed" else "跟踪到货与质检"),
             basis="PO-A 供方确认、GR 和质检放行", closed=shell_closed),
        dict(ref="EX-02", issue="执行器质量冻结", owner="质量／仓储", due="2026-11-18",
             stage="已完成" if quality_closed else f"原冻结 {actuator['frozen']} 件",
             basis="PO-B 替代批次质检；原冻结件单独处置", closed=quality_closed),
        dict(ref="EX-03", issue="分批与交期变更", owner="客户订单／销售", due="2026-11-17",
             stage="已验收" if delivery_closed else ("已确认待履约" if legs else "待客户确认"),
             basis="原要求、承诺版本、客户签认和实际验收", closed=delivery_closed),
        dict(ref="EX-04", issue="采购发票差异", owner="采购／应付财务", due="2026-11-17",
             stage="已确认应付" if ap["posted"] else ("差异待核" if ap["invoiced"] != ap["accepted"] else "待确认应付"),
             basis="独立 PO-INV、合格 GR 与供方发票", closed=ap["posted"]),
    ]


def load(db, account):
    row=db.one("SELECT revision,snapshot FROM order_exercises WHERE user_id=%s",(account["id"],))
    return (row["revision"],json.loads(row["snapshot"])) if row else (0,initial())


def view(db, account):
    revision,model=load(db,account)
    return represent(revision,model)


def represent(revision,model):
    return dict(model,revision=revision,ref=ORDER_REF,qty=ORDER_QTY,requested=REQUESTED,controlled_version=VERSION,
                analysis=decision(model),safety_stock=safety_stock(),exceptions=exceptions(model))


def apply(db,payload,account):
    revision,model=load(db,account)
    require(type(payload.get("revision")) is int and payload["revision"]==revision,
            "演练进度已经更新，请刷新后再操作",409)
    operation=choice(payload,"operation","演练操作",{"adjust","stock","purchase","promise","fulfill","finance","reset"})
    handlers={"adjust":adjust,"stock":count_stock,"purchase":po_action,"promise":accept_promise,"fulfill":fulfill,"finance":finance}
    if operation=="reset":
        model=initial()
    else:
        handlers[operation](model,payload,account)
    revision+=1
    db.execute("INSERT INTO order_exercises (user_id,revision,snapshot) VALUES (%s,%s,%s) "
               "ON CONFLICT (user_id) DO UPDATE SET revision=excluded.revision,snapshot=excluded.snapshot",
               (account["id"],revision,json.dumps(model,ensure_ascii=False)))
    return represent(revision,model)
