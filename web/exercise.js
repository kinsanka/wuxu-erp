"use strict";

let exerciseModel=null;

const exercisePO={
  unconfirmed:["待确认","amber"],confirmed:["供方已确认","blue"],asn:["ASN 在途","blue"],
  received:["已实收待检","amber"],released:["质检放行","green"],
};

const exerciseStages={
  planned:["待锁料",""],reserved:["已锁料","blue"],produced:["完工待发","blue"],shipped:["在途","blue"],
  arrived:["已签收","amber"],accepted:["已验收","green"],
};

const exerciseNext={
  planned:["reserve","锁料"],reserved:["produce","生产完工"],produced:["ship","出库发运"],
  shipped:["arrive","到货签收"],arrived:["accept","客户验收"],
};

function exercisePage() {
  if (exerciseDemo) return exerciseDemoPage();
  if (!exerciseModel) return head("急单协同演练","正在读取模拟订单。");
  const {ref,qty:quantity,requested,controlled_version:controlled,analysis}=exerciseModel;
  const model=exerciseModel;
  const first=model.versions[0];
  const current=model.versions.at(-1);
  const editing=!current || current.deliveries.every(leg=>leg.status==="planned");
  const blockers=[...analysis.gates,...analysis.supply];
  const metrics=[
    ["当前现货可齐套",analysis.in_stock+" 套","仅计可用实物"],
    ["余量预计到达",analysis.full||"—","按可用供给与工作日试算"],
    ["客户原要求",requested,quantity+" 套 · 工程版本 "+controlled],
    ["首版承诺到达",first?.baseline.at(-1).arrival||"—",first?"V1 已归档":"待客户确认"],
  ];
  const overview=`<div class="metrics exercise-metrics">${metrics.map(([name,value,note])=>
    `<div class="metric"><span class="metric-top">${html(name)}</span><strong>${html(value)}</strong><small>${html(note)}</small></div>`).join("")}</div>`;
  const warnings=blockers.length
    ? `<ul class="exercise-warnings">${blockers.map(message=>`<li>${html(message)}</li>`).join("")}</ul>`
    : `<p class="exercise-message">${analysis.remaining?"工程版本、信用、产能和预计供给已通过试算。执行仍需客户确认及实际锁料。":"本单全部数量已有执行记录。"}</p>`;
  const materials=table(["物料／用量","实物","冻结／待检","预留 他单／本单","本单可用","未锁需求","净缺","预计足量可用","操作"],analysis.rows,row=>[
    item(row.name,row.code+" · "+row.usage+" 件／套"),numeric(row.stock),
    numeric(row.frozen+(row.state==="received"?row.ordered:0)),numeric(row.other+" / "+row.reserved),
    row.available<0?cfgLabel({bad:[String(row.available),"red"]},"bad"):numeric(row.available),
    numeric(row.need),numeric(row.shortage),clean(row.ready),button("调整实物","exerciseStock",row.code,"small"),
  ]);
  const supply=table(["采购单","物料／数量","预计到货","预计质量可用","供给状态","操作"],model.materials.filter(row=>row.po),row=>{
    const actions=[];
    if (["unconfirmed","confirmed","asn"].includes(row.state)) {
      actions.push(button("供方确认","exercisePO",row.po+"|confirm","small"));
    }
    const next={confirmed:["asn","记录 ASN"],asn:["receive","仓库实收"],received:["release","质检放行"]}[row.state];
    if (next) actions.push(button(next[1],"exercisePO",row.po+"|"+next[0],"small"));
    return [code(row.po),item(row.name,row.ordered+" 件"),clean(row.eta),clean(row.quality),cfgLabel(exercisePO,row.state),`<div class="actions">${actions.join("")}</div>`];
  });
  const proposal=Object.entries(analysis.schedules).flatMap(([option,segments])=>segments.map((leg,index)=>({...leg,option,index})));
  const plan=table(["试算方案","套数","最早发运","最早到达","操作"],proposal,row=>[
    text(row.option==="full"?"一次交付":`分批 · 第 ${row.index+1} 批`),numeric(row.qty),text(row.dispatch),text(row.arrival),
    editing && row.index===0?button("登记客户确认","exercisePromise",row.option,"small primary"):"—",
  ],"当前没有可下达方案。检查执行条件和供给状态。");
  const promised=table(["批次","套数","约定到达","状态","实际发运","实际签收","实际验收","下一步"],
    (current?.deliveries||[]).map((leg,index)=>({...leg,index:index+1})),leg=>{
      const next=exerciseNext[leg.status];
      return [numeric(leg.index),numeric(leg.qty),text(leg.arrival),cfgLabel(exerciseStages,leg.status),
        clean(leg.actual.shipped),clean(leg.actual.arrived),clean(leg.actual.accepted),
        next?button(next[1],"exerciseFulfill",leg.index+"|"+next[0],"small"):"—"];
    },"客户确认后生成交付批次。");
  const versions=table(["版本","确认日","客户确认凭证","承诺批次和到达日"],model.versions,row=>[
    bold("V"+row.number),text(row.day),code(row.ref),text(row.baseline.map(leg=>`${leg.qty} 套 / ${leg.arrival}`).join("，")),
  ]);
  const finance=exerciseFinanceSection(model,current);
  const inventory=table(["交期均值（天）","交期标准差（天）","安全库存（件）","再订货点（件）"],model.safety_stock,
    row=>[numeric(row.days),numeric(row.deviation),numeric(row.safety),numeric(row.reorder)]);
  const exceptions=table(["异常","责任岗位","跟踪期限","状态","关闭或复核依据"],model.exceptions,row=>[
    item(row.issue,row.ref),text(row.owner),text(row.due),
    cfgLabel({current:[!row.closed&&model.day>row.due?"超期 · "+row.stage:row.stage,row.closed?"green":model.day>row.due?"red":"amber"]},"current"),
    text(row.basis),
  ]);
  const events=table(["模拟日期","业务事件","关联单据","凭证／说明","操作人"],model.events.slice().reverse(),row=>[
    text(row.day),bold(row.event),code(row.ref),text(row.detail),text(row.actor),
  ]);
  return head("急单协同演练",`${ref} · 模拟日期 ${model.day} · 每个账号保存独立演练进度`,
    (walkthrough?"":button("开始实操演示","walkthroughStart","","primary"))
    +button("自动演示","exerciseOpenDemo")+button("调整日期与门禁","exerciseAdjust")+button("重置演练","exerciseReset","","danger")) + overview
    + `<div class="stack">${panel("订单齐套与异常",warnings+materials,"",`当前版本 ${model.version} / 信用${model.credit?"已放行":"未放行"} / 日产能 ${model.capacity || "待确认"}`)}
    ${panel("采购供给",supply,"","ASN 只记在途，GR 实收后，待检数量仍不可锁料。")}
    ${panel("交付方案与承诺",plan+section("当前承诺执行",promised)+section("承诺版本历史",versions),"","分批或改期须登记客户确认凭证。客户原要求和首版承诺保留。")}
    ${panel("异常跟踪",exceptions,"","以演练日期判断是否超期。")}${finance}${panel("安全库存敏感性",inventory,"","日均需求 20 件、需求标准差 5 件、周期无缺货概率 95%。")}
    ${panel("操作与凭证记录",events)}</div>`;
}

function exerciseFinanceSection(model,current) {
  const {ap,example_ar:example,ar}=model;
  const amount=value=>numeric(money.format(value/100));
  const balance=row=>row.invoice-row.credit-row.received;
  const gap=ap.invoiced-ap.accepted;
  const apStatus=ap.posted?"已确认应付":gap||ap.order_price!==ap.invoice_price?"差异待核":"匹配通过";
  const purchaseActions=ap.posted?"":(gap?button("登记供方修正","exerciseFinance","correct_ap","small"):"")
    +button("确认应付","exerciseFinance","post_ap","small");
  const purchase=table(["发票","采购量","合格 GR","开票量","PO／发票单价","数量差异","状态","操作"],[ap],()=>[
    code("AP-SIM-001"),numeric(ap.ordered),numeric(ap.accepted),numeric(ap.invoiced),
    amount(ap.order_price)+" / "+amount(ap.invoice_price),numeric(gap),bold(apStatus),`<div class="actions">${purchaseActions}</div>`,
  ]);
  const records=[{...example,ref:"AR-SIM-001"},...(ar?[ar]:[])];
  const sales=table(["销售发票","已开票","批准贷项","已核销实收","剩余应收","到期日","模拟账龄"],records,row=>{
    const day=row.ref==="AR-SIM-001"?"2026-11-16":model.day;
    const late=balance(row)>0?Math.max(0,(Date.parse(day)-Date.parse(row.due))/86400000):0;
    return [code(row.ref),amount(row.invoice),amount(row.credit),amount(row.received),amount(balance(row)),text(row.due),
      late?cfgLabel({late:[`逾期 ${late} 天`,"amber"]},"late"):"—"];
  });
  const cashActions=ar && balance(ar)>0
    ? button("登记批准贷项","exerciseFinance","credit_ar","small")+button("登记实收核销","exerciseFinance","receive_ar","small")
    : !ar&&current?.deliveries.every(leg=>leg.status==="accepted")?button("急单开票","exerciseFinance","issue_ar","small primary"):"";
  return panel("应收与应付",section("采购侧 · PO-INV 三单匹配",purchase)
    +section("销售侧 · 独立核账样例和急单模拟应收",sales)+`<div class="exercise-actions actions">${cashActions}</div>`);
}

async function loadExercise() {
  exerciseModel=await request("/api/exercise");
  if (page==="exercise") render();
}

function exerciseForm(title,operation,fields,collect=values=>values) {
  const revision=exerciseModel.revision;
  formDialog(title,"exercise",fields,"确认",values=>({revision,operation,...collect(values)}),
    result=>{exerciseModel=result;if(page==="exercise") render();});
}

function exerciseAdjust() {
  const row=exerciseModel;
  exerciseForm("调整模拟执行条件","adjust",
    grid(input("day","模拟日期",{type:"date",value:row.day,min:row.day})
      +input("version","订单工程版本",{value:row.version,maxlength:20})
      +select("credit","客户信用",[["yes","已放行"],["no","未放行"]],row.credit?"yes":"no")
      +input("capacity","已确认日产能（套，0 表示未确认）",{type:"number",min:"0",max:"1000",step:"1",value:row.capacity}))
    +help("按周一至周五计算生产与运输工作日。日期可向前推进。"),
    values=>({...values,credit:values.credit==="yes"}));
}

function exerciseStock(code) {
  const row=exerciseModel.materials.find(item=>item.code===code);
  if (!row) return;
  exerciseForm(`更新模拟实物 · ${row.name}`,"stock",
    grid([["stock","实物数量"],["frozen","冻结数量"],["other","其他订单预留量"]]
      .map(([key,label])=>input(key,label,{type:"number",min:"0",max:"100000",step:"1",value:row[key]})).join(""))
    +input("evidence","盘点或分配依据",{maxlength:100})
    +help("实物少于冻结、待检与预留合计时，系统会显示短差并阻断承诺和执行。"),
    values=>({...values,code}));
}

function exerciseSupply(value) {
  const [po,step]=value.split("|");
  const row=exerciseModel.materials.find(item=>item.po===po);
  if (!row) return;
  const title={confirm:"供方确认",asn:"记录 ASN 在途",receive:"GR 仓库实收",release:"来料质检放行"}[step];
  const fields=step==="confirm"
    ? grid(select("confirmed","供方承诺",[["yes","已确认"],["no","待确认"]],row.state==="unconfirmed"?"no":"yes")
      +input("eta","预计到货日",{type:"date",value:row.eta,required:false})
      +input("quality","预计质量可用日",{type:"date",value:row.quality,required:false}))
    : step==="release" ? input("evidence","质检凭证",{maxlength:100})
    : help(step==="asn" ? `确认记录 ${row.ordered} 件在途，预计 ${row.eta||"—"} 到货。` : `登记 ${row.ordered} 件实收并进入待检。`);
  exerciseForm(`${po} · ${title}`,"purchase",fields,values=>({...values,po,step,confirmed:values.confirmed==="yes"}));
}

function exercisePromise(option) {
  const schedule=exerciseModel.analysis.schedules[option];
  if (!schedule) return;
  exerciseForm("登记客户确认与承诺版本","promise",
    input("evidence","客户确认凭证编号",{maxlength:100,placeholder:"例如模拟邮件编号或签认单号"})
    +grid(schedule.map((leg,index)=>input("arrival"+(index+1),`第 ${index+1} 批 ${leg.qty} 套约定到达`,
      {type:"date",value:leg.arrival,min:leg.arrival})).join("")),
    values=>({...values,option}));
}

function exerciseFulfill(value) {
  const [leg,step]=value.split("|");
  const titles={reserve:"按批次锁料",produce:"确认生产完工",ship:"出库发运",arrive:"到货签收",accept:"客户验收"};
  const fields={ship:"发运单号",arrive:"签收回单号",accept:"验收凭证"};
  exerciseForm(`第 ${leg} 批 · ${titles[step]}`,"fulfill",
    fields[step]?input("evidence",fields[step],{maxlength:100}):help(step==="reserve"?"以质量已放行实物计算，不使用预报在途数量。":"确认已完成生产，系统将从本批锁定的数量扣除实物。"),
    values=>({...values,leg,step}));
}

function exerciseFinance(step) {
  const title={correct_ap:"登记供方修正发票",post_ap:"核对三单并确认应付",issue_ar:"登记急单销售发票",
    credit_ar:"登记已批准贷项",receive_ar:"登记实收核销"}[step];
  const hasAmount=["issue_ar","credit_ar","receive_ar"].includes(step);
  exerciseForm(title,"finance",input("evidence","业务凭证编号",{maxlength:100})
    +(hasAmount?input("amount","金额（元）",{type:"number",min:"0.01",step:"0.01"}):""),
    values=>({...values,step}));
}

const exerciseHandlers={exerciseAdjust,exerciseStock,exercisePO:exerciseSupply,exercisePromise,exerciseFulfill,exerciseFinance,
  exerciseReset:()=>exerciseForm("重置当前账号的演练","reset",help("清空本次演练的进度及凭证，并恢复报告中的基准数据。"))};
