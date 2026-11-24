"use strict";

const orderViews={};
const orderTabs={purchase:"orders",sale:"orders",expedite:"open"};
const expediteStates={open:["跟进中","blue"],closed:["已结案","green"],cancelled:["已撤销",""]};
const priorityLabels={urgent:"急单",critical:"特急"};

async function loadOrders(module) {
  const result=await request("/api/orders/"+module);
  if(page!==module) return;
  orderViews[module]=result;
  render();
}

function ordersPage(kind) {
  const isPurchase=kind==="purchase";
  const title=isPurchase?"采购管理":"销售履约";
  const view=orderViews[kind];
  if(!view) return head(title,"正在读取订单。");
  const choices=[
    ["orders",isPurchase?"采购订单":"销售订单"],["approval","待审核"],
    ["pending",isPurchase?"待收货":"待发货"],["overdue","订单逾期"],
    ...(isPurchase?[["received","收货明细"],["receipts","验收明细"],["returned","退货流水"],["partners","供应商"]]
      :[["shipped","发货明细"],["partners","客户"]]),
  ];
  const selected=orderTabs[kind];
  const open=row=>["approved","partial"].includes(row.status);
  const overdue=row=>open(row)&&row.due&&row.due<state.today;
  const actions=allowed(kind)?button(isPurchase?"＋ 新建采购单":"＋ 新建销售单","newTrade",kind,"primary"):"";
  let body;
  if(selected==="partners") {
    body=table(["编码","名称","联系信息"],view.partners.filter(row=>matches(row.code,row.name,row.contact)),row=>[
      code(row.code),bold(row.name),clean(row.contact),
    ]);
  } else if(["received","receipts","returned","shipped"].includes(selected)) {
    const records=selected==="receipts"?view.receipts:view.movements;
    const movementKind={received:"收货",receipts:"收货",returned:"采购退货",shipped:"销售发货"}[selected];
    body=recentMovement(records.filter(row=>row.kind===movementKind&&matches(row.ref,row.lot,row.item_code,row.item_name,row.site_name)));
  } else {
    const selectors={orders:row=>!filter.status||row.status===filter.status,approval:row=>row.status==="draft",pending:open,overdue};
    body=docsTable(view.orders.filter(row=>selectors[selected](row)&&matches(row.ref,row.site_name,row.partner_name,row.note)));
  }
  return head(title,"",actions)+`<section class="panel">${tabs("orderTab",selected,choices)}
    ${filters({status:selected==="orders"?pairs(docStatus,x=>x[0]):[],placeholder:selected==="partners"?"搜索往来单位":"搜索单据、往来单位、物料或批次"})}
    <div id="filtered">${body}</div></section>`;
}

function expeditePage() {
  const records=orderViews.expedite;
  if(!records) return head("急单处理","正在读取急单。");
  const selected=orderTabs.expedite;
  const overdue=row=>row.status==="open"&&row.due<state.today;
  const filtered=records.filter(row=>matches(row.ref,row.customer,row.owner,row.reason,row.site)
    && (selected==="overdue"?overdue(row):selected==="open"?row.status==="open":row.status!=="open"));
  return head("急单处理","跟踪单笔订单的目标签收日、供给和交付进度。",button("查看销售订单","go","sale"))
    +industryMetrics([["跟进中",records.filter(row=>row.status==="open").length],
      ["目标已逾期",records.filter(overdue).length],["已结案",records.filter(row=>row.status==="closed").length]])
    +`<section class="panel">${tabs("orderTab",selected,[["open","跟进中"],["overdue","目标逾期"],["history","已结束"]])}
    ${filters({placeholder:"搜索订单、客户或负责人"})}<div id="filtered">
    ${table(["急单／客户","优先级","原交付日","目标签收日","负责人","原单状态","急单状态"],filtered,row=>[
      link(row.ref,"expediteDetail",row.doc_id)+sub(row.customer),text(priorityLabels[row.priority]),
      clean(row.order_due),overdue(row)?bold(row.due)+sub("已逾期"):text(row.due),text(row.owner),
      cfgLabel(docStatus,row.doc_status),cfgLabel(expediteStates,row.status),
    ],"暂无匹配记录。可在销售单详情中登记急单。")}</div></section>`;
}

async function openExpedite(id) {
  const generation=dialogGeneration;
  const {order,ticket,work,events}=await request("/api/orders/expedite/"+encodeURIComponent(id));
  if(generation!==dialogGeneration) return;
  const complete=order.lines.every(line=>line.signed>=line.quantity);
  const canEdit=allowed("expedite")&&(!ticket||ticket.status==="open");
  const actions=button("打开原销售单","document",id)
    +(canEdit&&order.status!=="cancelled"&&!complete?button(ticket?"调整交付目标":"登记为急单","expediteSchedule",id,"primary"):"")
    +(canEdit&&ticket?button("记录跟进","expediteFollowup",id)
      +(complete?button("关闭急单","expediteClose",id,"primary"):"")+button("撤销急单","expediteCancel",id):"");
  const header=ticket?`<div class="detail-meta">${cfgLabel(expediteStates,ticket.status)}
    <span>${text(priorityLabels[ticket.priority])}</span><span>目标签收 ${text(ticket.due)}</span>
    <span>负责人 ${text(ticket.owner)}</span><span>原交付日 ${clean(order.due)}</span></div>
    <p class="detail-note">${html(ticket.reason)}</p>`:"";
  const delivery=section("订单交付进度",table(["物料","订购量","已发货","已签收","待签收","当前仓可用"],order.lines,row=>[
    item(row.name,row.code),unitQuantity(row.quantity,row.unit),unitQuantity(row.fulfilled,row.unit),unitQuantity(row.signed,row.unit),
    unitQuantity(row.quantity-row.signed,row.unit),unitQuantity(row.inventory.released,row.unit),
  ]));
  const supply=section("工单与供应",work.length?work.map(row=>
    `<div class="detail-meta">${link(row.ref,"document",row.id)}${cfgLabel(docStatus,row.status)}
      <span>计划完工 ${clean(row.due)}</span></div>`
    +table(["缺料组件","需求","当前可用","窗口内在途","预计净缺"],row.shortages,short=>[
      item(short.name,short.code),unitQuantity(short.required,short.unit),unitQuantity(short.available,short.unit),
      unitQuantity(short.incoming,short.unit),unitQuantity(short.net,short.unit),
    ],["draft","approved"].includes(row.status)?"当前试算无缺料":"缺料试算适用于未开工工单")
    +table(["关联采购单","状态","计划到货"],row.purchase,source=>[
      link(source.ref,"document",source.id),cfgLabel(docStatus,source.status),clean(source.due),
    ],"未关联采购单。可从工单详情关联。")).join(""):help("尚未关联生产工单。可在原销售单里关联同仓、同成品的工单。"));
  const history=section("跟进记录",table(["动作","说明","操作人","时间"],events,event=>[
    bold(event.action),text(event.note),text(event.actor),text(timestamp(event.created)),
  ]));
  openGuidedDetail("急单处理 · "+order.ref,header+`<div class="actions">${actions}</div>`+delivery+supply+history);
}

async function expediteSchedule(id) {
  const {ticket,order}=await request("/api/orders/expedite/"+encodeURIComponent(id));
  formDialog(ticket?"调整交付目标":"登记急单","expedite",grid(
    select("priority","优先级",pairs(priorityLabels),ticket?.priority||"urgent")
    +input("owner","负责人",{maxlength:80,value:ticket?.owner||""})
    +input("due","目标签收日期",{type:"date",min:state.today,value:ticket?.due||order.due||""}))
    +memo("note",ticket?"调整原因":"急单原因",true),"保存急单",
  values=>({...values,id,operation:"schedule"}),()=>openExpedite(id),id);
}

function expediteUpdate(id,operation) {
  const label={followup:"记录跟进",close:"关闭急单",cancel:"撤销急单"}[operation];
  formDialog(label,"expedite",memo("note","说明",true),label,values=>({...values,id,operation}),()=>openExpedite(id),id);
}

async function reviseDelivery(id) {
  const order=await request("/api/document/"+encodeURIComponent(id));
  const label=order.kind==="purchase"?"更新预计到货":"调整计划完工";
  formDialog(label+" · "+order.ref,"revise_delivery",
    input("due","新计划日期",{type:"date",min:state.today,value:order.due||""})
    +memo("note","调整依据",true),"保存计划",values=>({...values,id}),()=>openDocument(id),id);
}

async function purchaseShortage(value) {
  const [id,item_id]=value.split("|");
  const order=await request("/api/document/"+encodeURIComponent(id));
  const line=order.plan.find(row=>row.item_id===item_id);
  if(!line||line.net<=line.draft) throw new Error("该组件当前无需新增采购");
  const max=String((line.net-line.draft)/1000);
  const vendors=state.partners.filter(row=>["vendor","both"].includes(row.type));
  formDialog("生成采购草稿 · "+line.name,"purchase_shortage",grid(
    select("partner_id","供应商",pick(vendors,row=>row.code+" · "+row.name))
    +input("quantity","请购数量（"+line.unit+"）",{type:"number",value:max,min:"0.001",max,step:"0.001"})
    +moneyInput()+input("due","预计到货日期",{type:"date",min:state.today}))
    +help("生成同仓采购草稿并关联当前工单。审核后进入待收货。"),"生成采购草稿",
  values=>({...values,id,item_id}),result=>openDocument(result.id),id);
}

const orderHandlers={
  orderTab:value=>{orderTabs[page]=value;filter={...filterDefaults};render();},
  expediteDetail:openExpedite,expediteSchedule,
  expediteFollowup:id=>expediteUpdate(id,"followup"),
  expediteClose:id=>expediteUpdate(id,"close"),expediteCancel:id=>expediteUpdate(id,"cancel"),
  reviseDelivery,purchaseShortage,
};
