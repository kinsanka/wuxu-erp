"use strict";

const industryRoles = {transport:["warehouse"], people:["planner"], finance:[],counts:["warehouse"]};
const industryTitles = {transport:"运输与签收", people:"人员与工时", finance:"应收应付", counts:"库存盘点"};
const industryViews = {};
const industryTabs = {transport:"all",finance:"all"};
const tradeMoney = cents=>numeric(money.format(cents/100));
const unitQuantity = (value,unit)=>numeric(qty(value)+" "+unit);
const financeDirection = {ar:"应收", ap:"应付"};
const shipmentState = {signed:["已签收","green"], overdue:["签收逾期","red"], transit:["在途","blue"]};
const shipmentStatus = row=>cfgLabel(shipmentState,row.signed?"signed":row.due<state.today?"overdue":"transit");

async function loadIndustry(module) {
  const result=await request("/api/industry/"+module);
  if (page!==module) return;
  industryViews[module]=result;
  render();
}

function industryPage(module) {
  const view=industryViews[module];
  if (!view) return head(industryTitles[module],"正在读取业务记录。");
  return industryPages[module](view);
}

function industryMetrics(metrics) {
  return `<div class="metrics exercise-metrics industry-metrics">${metrics.map(([label,value])=>
    `<div class="metric"><span class="metric-top">${html(label)}</span><strong>${html(value)}</strong></div>`).join("")}</div>`;
}

function industrySections(placeholder,content) {
  const choices={
    transport:[["all","全部"],["pending","待登记运单"],["transit","在途"],["overdue","签收逾期"],["signed","已签收"]],
    finance:[["all","全部"],["ar","销售应收"],["ap","采购应付"],["payments","收款与付款"]],
  }[page];
  return `<div class="stack"><section class="panel">${choices?tabs("industryTab",industryTabs[page],choices):""}
    ${filters({placeholder})}</section><div id="filtered" class="stack">${content}</div></div>`;
}

function transportPage(view) {
  const selected=industryTabs.transport;
  const matchesStatus=row=>selected==="all"||(selected==="signed"?!!row.signed:!row.signed&&(selected==="transit"||row.due<state.today));
  return head(industryTitles.transport,"把已发生的出库流水登记到运单，跟踪预计到货和签收凭证。")
    +industryMetrics([["待登记运单批次",view.pending.length],["在途运单",view.shipments.filter(row=>!row.signed).length],
      ["签收逾期",view.shipments.filter(row=>!row.signed&&row.due<state.today).length]])
    +industrySections("搜索销售单、运单、客户或承运商",(["all","pending"].includes(selected)?panel("待登记运单",table(["销售单","交付批次","待登记发货流水","操作"],view.pending.filter(row=>matches(row.ref,row.commitment_ref)),row=>[
      link(row.ref,"document",row.id),row.commitment_ref?code(row.commitment_ref)+sub(row.commitment_due):"—",
      numeric(row.batches),button("登记运单","dispatch",row.id+"|"+(row.commitment_id||""),"small"),
    ])):"")+(selected==="pending"?"":panel("运输跟踪",table(["运单／物流单号","原销售单","客户","承运商","预计签收","状态","操作"],
      view.shipments.filter(row=>matchesStatus(row)&&matches(row.ref,row.tracking,row.doc_ref,row.customer,row.carrier,row.receipt)),row=>[
      link(row.ref,"shipmentDetail",row.id)+sub(row.tracking),link(row.doc_ref,"document",row.doc_id),text(row.customer),
      text(row.carrier),text(row.due),shipmentStatus(row),row.signed?clean(row.receipt):button("登记签收","signShipment",row.id,"small"),
    ]))));
}

function peoplePage(view) {
  const byPerson={};
  for (const row of view.assignments) (byPerson[row.person_id]??=[]).push(row);
  const people=Object.fromEntries(view.people.map(row=>[row.id,row]));
  return head(industryTitles.people,"维护生产人员与班组。在工单的工序明细中派工，报工后汇总实际分钟。",
    button("＋ 新增人员","newPerson","","primary"))
    +industrySections("搜索工号、姓名、班组或工单",panel("人员与班组",table(["工号","姓名","班组","待报工","最近记录工时"],
      view.people.filter(row=>matches(row.code,row.name,row.team)),row=>{
      const assignments=byPerson[row.id]??[];
      return [code(row.code),bold(row.name),text(row.team),numeric(assignments.filter(entry=>entry.minutes===null&&entry.status!=="cancelled").length),
        numeric(assignments.reduce((total,entry)=>total+(entry.minutes??0),0)+" 分钟")];
    }))+panel("工序派工",table(["工单","工序","派工人员","工单状态","报工分钟","派工时间"],
      view.assignments.filter(row=>matches(row.ref,row.step,people[row.person_id]?.code,people[row.person_id]?.name,people[row.person_id]?.team)),row=>[
      link(row.ref,"document",row.doc_id),bold(row.step),text(people[row.person_id]?.name??"—"),cfgLabel(docStatus,row.status),
      row.minutes===null?"—":numeric(row.minutes),text(timestamp(row.created)),
    ]),"","显示最近 300 条派工记录，工时按派工人员归集。"));
}

function financePage(view) {
  const selected=industryTabs.finance;
  const balance = direction=>view.invoices.filter(row=>row.direction===direction).reduce((total,row)=>total+row.amount-row.settled,0);
  const status={cleared:["已结清","green"], overdue:["已逾期","red"], partial:["部分核销","amber"], open:["待核销","blue"]};
  const pending = (heading,kind)=>panel(heading,table(["原单据","物料","已满足数量","已开票","可开票","单价","操作"],
    view.lines.filter(row=>row.kind===kind&&matches(row.doc_ref,row.partner,row.code,row.name)),row=>[
      link(row.doc_ref,"document",row.doc_id)+sub(row.partner),item(row.name,row.code),unitQuantity(row.qualified,row.unit),
      unitQuantity(row.invoiced,row.unit),unitQuantity(row.qualified-row.invoiced,row.unit),tradeMoney(row.price),
      button("登记发票","newInvoice",row.line_id,"small"),
    ]));
  return head(industryTitles.finance,"按签收数量或合格收货数量登记发票，以收付款凭证分次核销。")
    +industryMetrics([["台账应收余额",money.format(balance("ar")/100)],["台账应付余额",money.format(balance("ap")/100)],
      ["台账逾期发票",view.invoices.filter(row=>row.amount>row.settled&&row.due<state.today).length]])
    +industrySections("搜索发票、原单据或往来单位",(["all","ar"].includes(selected)?pending("销售 · 已签收待开票","sale"):"")
      +(["all","ap"].includes(selected)?pending("采购 · 合格收货待核票","purchase"):"")
      +(selected==="payments"?"":panel("应收与应付台账",table(["发票","方向","原单据","发票金额","已核销","未结余额","到期日","状态","操作"],
        view.invoices.filter(row=>(selected==="all"||row.direction===selected)&&matches(row.ref,row.doc_ref,row.partner,financeDirection[row.direction])),row=>[
        link(row.ref,"invoiceDetail",row.id)+sub(row.partner),text(financeDirection[row.direction]),link(row.doc_ref,"document",row.doc_id),
        tradeMoney(row.amount),tradeMoney(row.settled),tradeMoney(row.amount-row.settled),text(row.due),
        cfgLabel(status,row.amount===row.settled?"cleared":row.due<state.today?"overdue":row.settled?"partial":"open"),
        row.amount>row.settled?`<div class="actions">${button(row.direction==="ar"?"登记收款单":"登记付款单","registerPayment",row.id,"small")}
          ${button("核销","settleInvoice",row.id,"small")}</div>`:"—",
      ]),"","显示最近 300 张发票。"))+(["all","payments"].includes(selected)?panel("收款单与付款单",table(["凭证编号","方向","往来单位","实际金额","已核销","可核销余额","收付款日期"],
        view.payments.filter(row=>matches(row.ref,row.partner,financeDirection[row.direction],
          ...view.invoices.filter(invoice=>invoice.direction===row.direction&&invoice.partner_id===row.partner_id).map(invoice=>invoice.doc_ref))),row=>[
          code(row.ref),text(row.direction==="ar"?"收款单":"付款单"),text(row.partner),tradeMoney(row.amount),tradeMoney(row.allocated),
          tradeMoney(row.amount-row.allocated),text(row.transacted),
        ])):""));
}

function countsPage(rows) {
  return head(industryTitles.counts,"按工厂仓和物料批次核对账面实物，登记盘盈或盘亏。",
    button("＋ 登记盘点","inventoryCount","","primary"))
    +industrySections("搜索盘点单、物料、批次或仓库",panel("盘点单据",table(["盘点单","物料／批次","仓库","盘点前账面","实盘","盘点差异","依据及登记人","登记时间"],
      rows.filter(row=>matches(row.ref,row.lot,row.name,row.code,row.site)),row=>[
      code(row.ref),link(row.lot,"lotTrace",row.lot_id)+sub(row.name+" · "+row.code),text(row.site),
      unitQuantity(row.book,row.unit),unitQuantity(row.counted,row.unit),unitQuantity(row.counted-row.book,row.unit),
      item(row.reason,row.actor),text(timestamp(row.created)),
    ]),"","显示最近 300 张盘点单据。"));
}

const industryPages = {transport:transportPage,people:peoplePage,finance:financePage,counts:countsPage};

async function itemDetail(id, isCurrent=()=>true) {
  const version=++dialogGeneration;
  const model=await request("/api/item/"+encodeURIComponent(id));
  if (version!==dialogGeneration || !isCurrent()) return;
  openGuidedDetail(model.name+" · "+model.code,
    `<div class="detail-meta">${text(kindText[model.type])} · ${text(model.unit)}<span>补货点 ${unitQuantity(model.minimum,model.unit)}</span>
      <span>入库质检 ${model.quality?"必检":"按常规收货"}</span></div>`
    +section("产品 BOM",table(["版本","创建时间"],model.boms,row=>[
      link(row.version,"bomDetail",row.id),text(timestamp(row.created)),
    ],"该物料没有自有 BOM。"))
    +section("用于哪些产品",table(["产品","BOM 版本","单位用量"],model.usage,row=>[
      item(row.name,row.code),link(row.version,"bomDetail",row.id),unitQuantity(row.quantity,model.unit),
    ],"暂无其他 BOM 使用此物料。"))
    +section("在库批次",table(["仓库","批次","库存","效期","状态"],model.stock,row=>[
      text(row.site_name),link(row.lot,"lotTrace",row.lot_id),unitQuantity(row.quantity,row.unit),dateText(row),cfgLabel(lotStatus,row.status),
    ]))+section("相关采购、生产与销售单据",docsTable(model.documents,true)));
}

function salesProgress(model) {
  const ready=["approved","partial"].includes(model.status);
  const readiness=table(["物料","未发数量","同仓可用","本单此刻可发","待检","冻结","过期"],model.lines,row=>{
    const stock=row.inventory;
    const show=value=>unitQuantity(value,row.unit);
    const open=["done","cancelled"].includes(model.status)?0:row.quantity-row.fulfilled;
    return [item(row.name,row.code),show(open),show(stock.released),show(ready?Math.min(open,stock.released):0),
      show(stock.pending),show(stock.blocked),show(stock.expired)];
  });
  const transport = showNav("transport") ? `<div class="actions document-section-actions">${button("前往运输与签收","go","transport","small")}</div>` : "";
  return section("发货可用量",help("同仓已放行且未过效期的实物可用于发货。数量随库存变化。")+readiness)
    +section("运单与签收",table(["运单","承运商／物流单号","预计签收","状态","签收凭证"],model.shipments,row=>[
      code(row.ref),item(row.carrier,row.tracking),text(row.due),shipmentStatus(row),clean(row.receipt),
    ],"暂无已登记运单。发货后可在运输与签收中登记。")+transport);
}

function purchaseProgress(model) {
  const open=["approved","partial"].includes(model.status);
  const schedule=model.due && open && model.due<state.today ? help("采购到货已超过计划日期，请向供应商核对剩余到货安排。") : "";
  const remaining=table(["物料","采购数量","累计实收","待收数量"],model.lines,row=>[
    item(row.name,row.code),unitQuantity(row.quantity,row.unit),unitQuantity(row.fulfilled,row.unit),
    unitQuantity(model.status==="cancelled"?0:row.quantity-row.fulfilled,row.unit),
  ]);
  const receipts=model.movements.filter(row=>row.kind==="收货");
  return section("采购交付进度",schedule+remaining)+section("收货批次与质检",table(["物料","批次","实收","已退货","效期","当前质检状态","处理"],receipts,row=>[
    item(row.item_name,row.item_code),link(row.lot,"lotTrace",row.lot_id),unitQuantity(row.quantity,row.unit),unitQuantity(row.returned,row.unit),dateText(row),
    cfgLabel(lotStatus,row.lot_status),allowed("inspect")?`<div class="actions">${button("质检处理","inspect",row.lot_id,"small")}
      ${model.factory&&model.lines.some(line=>line.code===row.item_code&&line.type!=="medical")&&row.quantity>row.returned
        ?button("采购退货","returnPurchase",model.id+"|"+row.id,"small"):""}</div>`:"—",
  ],"暂无收货批次。"));
}

async function returnPurchaseForm(value) {
  const [id,receipt_id]=value.split("|");
  const model=await request("/api/document/"+encodeURIComponent(id));
  const receipt=model.movements.find(row=>row.id===receipt_id);
  if (!receipt) return;
  formDialog("采购退货 · "+receipt.lot,"purchase_return",input("quantity","退回数量（"+receipt.unit+"）",
    {type:"number",min:"0.001",max:(receipt.quantity-receipt.returned)/1000,step:"0.001"})
    +memo("reason","退货原因",true)+help("退货按原收货流水核对库存，确认后会恢复采购单待收数量。"),
    "确认退货",values=>({receipt_id,...values}),()=>openDocument(id),id);
}

function supplyChain(model) {
  const manage=allowed("link_supply");
  const label=model.kind==="sale"?"工单":"采购单";
  const add=manage && ["sale","work"].includes(model.kind) && model.status!=="cancelled"
    ? `<div class="actions document-section-actions">${button("＋ 关联"+label,"linkSupply",model.id+"|"+model.kind,"small")}</div>` : "";
  return section("需求与供给单据",table(["关系","单据","状态",...(manage?["操作"]:[])],model.linked,row=>[
    text(row.demand_id===model.id?"供给单据":"需求单据"),link(row.ref,"document",row.id),cfgLabel(docStatus,row.status),
    ...(manage?[button("解除关联","unlinkSupply",[row.demand_id,row.supply_id,model.id].join("|"),"small")]:[]),
  ],"暂无已关联的单据。")+add);
}

function dispatchForm(value) {
  const [id,commitment_id=""]=value.split("|");
  const pending=industryViews.transport?.pending.find(row=>row.id===id&&(row.commitment_id||"")===commitment_id);
  formDialog("登记实际承运运单","dispatch",grid(input("carrier","承运商",{maxlength:100})+input("tracking","运单号",{maxlength:100})
    +input("due","预计签收日期",{type:"date",value:pending?.commitment_due||""}))
    +help(pending?.commitment_ref?"只合并 "+pending.commitment_ref+" 的待登记发货流水。":"合并本单未挂交付承诺的待登记发货流水。"),
    "登记运单",values=>({id,commitment_id,...values}));
}

function signShipmentForm(id) {
  formDialog("登记到货签收","sign_shipment",input("receipt","签收凭证编号",{maxlength:100}),
    "确认签收",values=>({id,...values}));
}

async function shipmentDetail(id) {
  const row=await request("/api/industry/transport/"+encodeURIComponent(id));
  openGuidedDetail("运单 · "+row.ref,`<div class="detail-meta">${shipmentStatus(row)}${text(row.carrier)} · ${text(row.tracking)}
    <span>预计签收 ${text(row.due)}</span><span>实际签收 ${text(timestamp(row.signed))}</span><span>凭证 ${clean(row.receipt)}</span></div>`
    +(row.commitment?help("对应交付批次 "+row.commitment.ref+" · 承诺签收 "+row.commitment.due):"")
    +section("装运批次",table(["物料","批次","数量"],row.lines,line=>[
      item(line.name,line.code),link(line.lot,"lotTrace",line.lot_id),unitQuantity(line.quantity,line.unit),
    ])));
}

function newPersonForm() {
  formDialog("新增生产人员","personnel",grid(input("code","工号",{maxlength:40,value:walkthrough?.targets.worker_code||""})+input("name","姓名",{maxlength:80})
    +input("team","班组",{maxlength:80})),"保存人员");
}

async function assignStepForm(value) {
  const [id,step_id]=value.split("|");
  const view=await request("/api/industry/people");
  if (!view.people.length) {
    openDialog("工序派工",help("先在人员与工时中新增生产人员。")+button("前往人员与工时","go","people"));
    return;
  }
  const worker=view.people.find(row=>row.code===walkthrough?.targets.worker_code);
  formDialog("工序派工","assign_step",select("person_id","人员与班组",pick(view.people,row=>row.code+" · "+row.name+" · "+row.team),worker?.id),
    "确认派工",values=>({id,step_id,...values}),()=>openDocument(id),id);
}

function newInvoiceForm(line_id) {
  const line=industryViews.finance.lines.find(row=>row.line_id===line_id);
  if (!line) return;
  const remaining=line.qualified-line.invoiced;
  formDialog("登记发票 · "+line.doc_ref,"invoice",grid(input("ref","发票号",{maxlength:80})
    +input("quantity","开票数量（"+line.unit+"）",{type:"number",value:remaining/1000,min:"0.001",max:remaining/1000,step:"0.001"})
    +input("price","发票单价（元）",{type:"number",value:line.price/100,min:"0",step:"0.01"})+input("due","到期日",{type:"date"}))
    +help("如发票包含多种物料，在同一原单的其他明细中使用相同发票号和到期日。"),"登记发票",values=>({line_id,...values}));
}

async function invoiceDetail(id) {
  const row=await request("/api/industry/finance/"+encodeURIComponent(id));
  openGuidedDetail(financeDirection[row.direction]+"发票 · "+row.ref,
    section("开票明细",table(["物料","开票数量","单价","金额"],row.lines,line=>[
      item(line.name,line.code),unitQuantity(line.quantity,line.unit),tradeMoney(line.price),tradeMoney(line.amount),
    ]))+section("收付款核销记录",table(["凭证编号","金额","入账时间"],row.settlements,entry=>[
      code(entry.ref),tradeMoney(entry.amount),text(timestamp(entry.created)),
    ])));
}

function settleInvoiceForm(id) {
  const invoice=industryViews.finance.invoices.find(row=>row.id===id);
  if (!invoice) return;
  const payments=industryViews.finance.payments.filter(row=>row.direction===invoice.direction&&row.partner_id===invoice.partner_id&&row.amount>row.allocated);
  if (!payments.length) {
    openDialog("核销 · "+invoice.ref,help("请先登记同一往来单位的收付款单。")+button("登记收付款单","registerPayment",id,"primary"));
    return;
  }
  const form=formDialog("核销 · "+invoice.ref,"settlement",grid(select("payment_id","收付款单",
    pick(payments,row=>row.ref+" · 余额 "+money.format((row.amount-row.allocated)/100)),payments[0].id)
    +input("amount","本次核销金额（元）",{type:"number",min:"0.01",step:"0.01"})),"确认核销",values=>({id,...values}));
  const setAmount=()=>{
    const payment=payments.find(row=>row.id===form.elements.payment_id.value);
    const available=payment?Math.min(invoice.amount-invoice.settled,payment.amount-payment.allocated)/100:0;
    form.elements.amount.max=String(available);
    form.elements.amount.value=available?String(available):"";
  };
  form.elements.payment_id.addEventListener("change",setAmount);
  setAmount();
}

function registerPaymentForm(id) {
  const invoice=industryViews.finance.invoices.find(row=>row.id===id);
  if (!invoice) return;
  const label=invoice.direction==="ar"?"收款单":"付款单";
  formDialog("登记"+label+" · "+invoice.partner,"payment",grid(input("ref","银行或收付款凭证号",{maxlength:80})
    +input("date","实际发生日期",{type:"date",value:state.today,max:state.today})
    +input("amount","实际金额（元）",{type:"number",value:(invoice.amount-invoice.settled)/100,min:"0.01",step:"0.01"})),
    "保存"+label,values=>({id,...values}));
}

function linkSupplyForm(value) {
  const [id,kind]=value.split("|");
  const label=kind==="sale"?"生产工单":"采购单";
  formDialog("关联"+label,"link_supply",input("ref",label+"号",{maxlength:80})
    +help("供给必须和需求属于同仓，并包含对应成品或 BOM 组件。关联用于跟踪供给，库存分配仍由实际领料和发货处理。"),
    "确认关联",values=>({id,...values}),()=>openDocument(id),id);
}

function unlinkSupplyForm(value) {
  const [demand,supply_id,current]=value.split("|");
  formDialog("解除供给关联","unlink_supply",help("解除两张单据的关联。相关单据和库存流水仍可在原模块查看。"),
    "确认解除",()=>({id:demand,supply_id}),()=>openDocument(current),current);
}

function inventoryCountForm(value) {
  const [lotId,siteId]=value?value.split("|"):[walkthrough?.targets.batch?.id,walkthrough?.targets.site_id];
  const industrialLots=state.lots.filter(lot=>state.items.some(item=>item.id===lot.item_id&&item.type!=="medical"));
  const sites=state.sites.filter(site=>site.type==="factory");
  let book = 0;
  const form = formDialog("工厂仓库存盘点","inventory_count",
    grid(select("site_id","盘点仓库",siteOptions(sites),siteId)+select("lot_id","批次",lotOptions(industrialLots),lotId))
    +'<p class="form-hint" data-count-book aria-live="polite"></p>'
    +input("counted","实盘数量",{type:"number",min:"0",step:"0.001"})+memo("reason","盘点依据",true,"记录盘点表号或差异原因"),
    "确认盘点",values=>({...values,book:String(book/1000)}));
  const refreshBook=()=>{
    const selectedLot=form.elements.lot_id.value;
    const selectedSite=form.elements.site_id.value;
    book=state.stock.find(row=>row.lot_id===selectedLot&&row.site_id===selectedSite)?.quantity??0;
    const unit=state.items.find(row=>row.id===industrialLots.find(lot=>lot.id===selectedLot)?.item_id)?.unit??"";
    form.querySelector('[data-count-book]').textContent=selectedLot&&selectedSite?"当前账面库存 "+qty(book)+" "+unit:"选择仓库和批次后核对账面数量。";
  };
  form.elements.lot_id.addEventListener("change",refreshBook);
  form.elements.site_id.addEventListener("change",refreshBook);
  refreshBook();
}

const industryHandlers = {
  dispatch:dispatchForm,signShipment:signShipmentForm,shipmentDetail,newPerson:newPersonForm,assignStep:assignStepForm,
  newInvoice:newInvoiceForm,invoiceDetail,settleInvoice:settleInvoiceForm,linkSupply:linkSupplyForm,unlinkSupply:unlinkSupplyForm,
  itemDetail,inventoryCount:inventoryCountForm,registerPayment:registerPaymentForm,returnPurchase:returnPurchaseForm,
};
