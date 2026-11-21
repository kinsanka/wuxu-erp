"""Deterministic playback of SO-SIM-001 using the manual exercise rules."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from erp import BusinessError
from exercise import (
    ORDER_QTY, ORDER_REF, REQUESTED, accept_promise, active, decision, finance,
    fulfill, initial, po_action,
)


@dataclass(frozen=True)
class Task:
    start: str
    end: str
    team: str
    title: str
    detail: str
    action: Callable[[dict, dict, dict], None] | None = None
    payload: dict | None = None
    blocked: bool = False


TASKS = (
    Task("16T08:30", "16T09:15", "计划／销售", "接单与齐套评估", "核对 REV-B、信用和产能。客户要求 30 套于 11 月 20 日到达，现货只够 20 套。"),
    Task("16T09:15", "16T10:45", "客户／销售", "确认首版承诺", "整单最早 11 月 23 日到达，存为 V1。",
         accept_promise, {"option": "full", "evidence": "DEMO-CUSTOMER-V1"}),
    Task("16T10:45", "16T13:45", "客户／销售", "协商 20＋10 套分批交付", "保存客户签认和 V2。客户原要求及 V1 继续保留。",
         accept_promise, {"option": "split", "evidence": "DEMO-CUSTOMER-V2"}),
    Task("16T13:45", "16T14:15", "计划／仓库", "第一批锁料", "锁定 20 套所需的现货，不使用在途或待检库存。",
         fulfill, {"leg": "1", "step": "reserve"}),
    Task("16T09:30", "16T15:00", "采购／供应商", "PO-B 记录预发货通知", "记录 40 件执行器的 ASN。此时可用库存不变。",
         po_action, {"po": "PO-B", "step": "asn"}),
    Task("16T09:45", "16T16:00", "采购／供应商", "PO-A 记录预发货通知", "记录 20 件壳体的 ASN。两家供应商并行备货。",
         po_action, {"po": "PO-A", "step": "asn"}),
    Task("16T15:00", "17T09:30", "供应商／运输", "执行器运输到厂", "包含夜间在途时间，车辆到厂后进入收货队列。"),
    Task("16T16:00", "18T09:00", "供应商／运输", "壳体运输到厂", "运输及到厂排队与第一批生产并行。"),
    Task("17T09:30", "17T10:00", "仓库", "PO-B 实收 40 件执行器", "扫描并登记 GR，库存增加 40 件，整批待检。",
         po_action, {"po": "PO-B", "step": "receive"}),
    Task("17T10:00", "18T11:30", "质量", "执行器排队和来料检验", "预计检验周期含排队与非工作时段。放行新增 40 件，原有冻结的 10 件单独处置。",
         po_action, {"po": "PO-B", "step": "release", "evidence": "DEMO-QC-B"}),
    Task("17T08:30", "17T16:00", "生产", "第一批 20 套生产完工", "模拟一个生产工作日，完工时扣减已锁定的物料。",
         fulfill, {"leg": "1", "step": "produce"}),
    Task("17T16:00", "17T17:00", "仓库／物流", "第一批出库发运", "完成打包、复核和运输交接，登记发运单。",
         fulfill, {"leg": "1", "step": "ship", "evidence": "DEMO-SHIP-01"}),
    Task("17T17:00", "18T10:30", "运输／客户", "第一批到达并签收", "11 月 17 日发运，18 日到货。记录签收回单后进入验收。",
         fulfill, {"leg": "1", "step": "arrive", "evidence": "DEMO-POD-01"}),
    Task("18T09:00", "18T09:30", "仓库", "PO-A 实收 20 件壳体", "扫码收货并进入隔离区。此时第二批仍不能锁料。",
         po_action, {"po": "PO-A", "step": "receive"}),
    Task("18T09:30", "19T11:00", "质量", "壳体排队和来料检验", "模拟等待检验、抽检及批准。放行时待检数量转为可用。",
         po_action, {"po": "PO-A", "step": "release", "evidence": "DEMO-QC-A"}),
    Task("18T10:30", "18T13:00", "客户／质量", "第一批验收 20 套", "客户检验签收的 20 套并出具验收凭证。",
         fulfill, {"leg": "1", "step": "accept", "evidence": "DEMO-ACCEPT-01"}),
    Task("18T13:00", "18T13:45", "应付财务", "供应商三单匹配被拦截", "独立采购样例中，发票 20 件、合格实收 18 件，存在 2 件差异。",
         finance, {"step": "post_ap", "evidence": "DEMO-AP-CHECK"}, True),
    Task("18T14:00", "18T14:15", "计划／仓库", "第二批提前锁料被拦截", "壳体已实收、仍待质检。系统重新检查可用实物数量。",
         fulfill, {"leg": "2", "step": "reserve"}, True),
    Task("18T13:45", "19T14:00", "供应商／采购", "更正供应商发票", "供应商复核差异并将开票量更正为 18 件。",
         finance, {"step": "correct_ap", "evidence": "DEMO-AP-CORRECTION"}),
    Task("19T14:00", "19T15:00", "应付财务", "确认采购应付", "复核更正发票、采购单和合格收货。三项匹配后确认应付。",
         finance, {"step": "post_ap", "evidence": "DEMO-AP-APPROVAL"}),
    Task("19T11:00", "19T11:30", "计划／仓库", "第二批锁料", "缺件已放行，为余下 10 套预留物料。",
         fulfill, {"leg": "2", "step": "reserve"}),
    Task("20T08:30", "20T15:30", "生产", "第二批 10 套生产完工", "领用锁定物料，完成余量生产。",
         fulfill, {"leg": "2", "step": "produce"}),
    Task("20T15:30", "20T16:30", "仓库／物流", "第二批出库发运", "周五完成交接，下一运输工作日为周一。",
         fulfill, {"leg": "2", "step": "ship", "evidence": "DEMO-SHIP-02"}),
    Task("20T16:30", "23T10:00", "运输／客户", "第二批跨周末到货", "经过周末等待，11 月 23 日（周一）签收。",
         fulfill, {"leg": "2", "step": "arrive", "evidence": "DEMO-POD-02"}),
    Task("23T10:00", "23T13:00", "客户／质量", "第二批验收 10 套", "取得第二次验收，订单累计验收 30 套。",
         fulfill, {"leg": "2", "step": "accept", "evidence": "DEMO-ACCEPT-02"}),
    Task("23T13:00", "23T15:30", "应收财务", "急单开票并确认应收", "两批都验收后开立 2,000 元模拟发票。",
         finance, {"step": "issue_ar", "evidence": "DEMO-INVOICE", "amount": "2000"}),
    Task("23T15:30", "24T11:30", "应收财务", "登记已批准贷项", "审批后登记 100 元贷项，账面剩余应收 1,900 元。",
         finance, {"step": "credit_ar", "evidence": "DEMO-CREDIT", "amount": "100"}),
    Task("24T11:30", "25T14:30", "客户／应收财务", "登记首笔实收并核销", "客户付款后入账 1,500 元，剩余应收 400 元。",
         finance, {"step": "receive_ar", "evidence": "DEMO-RECEIPT-01", "amount": "1500"}),
    Task("25T14:30", "26T16:00", "客户／应收财务", "核销尾款并结清应收", "演示客户再付 400 元，订单应收余额归零。",
         finance, {"step": "receive_ar", "evidence": "DEMO-RECEIPT-02", "amount": "400"}),
)


def timestamp(clock):
    return datetime.fromisoformat(f"2026-11-{clock}:00+08:00")


def snapshot(model):
    analysis = decision(model)
    deliveries = active(model)
    ar = model["ar"]
    ap = model["ap"]
    return {
        "available_kits": analysis["in_stock"],
        "confirmed_version": model["versions"][-1]["number"] if model["versions"] else None,
        "accepted": sum(row["qty"] for row in deliveries if row["status"] == "accepted"),
        "deliveries": deepcopy(deliveries),
        "materials": [
            {key: row[key] for key in ("code", "name", "available", "need", "shortage", "reserved", "state", "po")}
            for row in analysis["rows"]
        ],
        "payable": {"accepted": ap["accepted"], "invoiced": ap["invoiced"], "confirmed": ap["posted"]},
        "receivable": dict(ar, balance=ar["invoice"]-ar["credit"]-ar["received"]) if ar else None,
    }


def build_demo():
    model = initial()
    baseline = snapshot(model)
    account = {"username": "系统演示"}
    start = min(timestamp(task.start) for task in TASKS)
    events = []

    def minute(clock):
        return int((timestamp(clock)-start).total_seconds()//60)

    for task in sorted(TASKS, key=lambda item: item.end):
        model["day"] = timestamp(task.end).date().isoformat()
        outcome = ""
        if task.blocked:
            try:
                task.action(deepcopy(model), task.payload, account)
            except BusinessError as error:
                if error.status != 409:
                    raise
                outcome = str(error)
            else:
                raise RuntimeError(f"演示预期出现拦截：{task.title}")
        elif task.action:
            task.action(model, task.payload, account)
            entry = model["events"][-1]
            outcome = " · ".join(value for value in (entry["ref"],entry["detail"]) if value)
        events.append(dict(start=minute(task.start), end=minute(task.end), title=task.title, team=task.team,
                           detail=task.detail, outcome=outcome, blocked=task.blocked, snapshot=snapshot(model)))
    return dict(ref=ORDER_REF, quantity=ORDER_QTY, requested=REQUESTED, start=start.isoformat(),
                duration=events[-1]["end"], events=events, snapshot=baseline)
