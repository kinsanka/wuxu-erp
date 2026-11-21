"use strict";

const $ = id => document.getElementById(id);
const html = value => String(value ?? "").replace(/[&<>"']/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[character]);
const number = new Intl.NumberFormat("zh-CN", {maximumFractionDigits: 3});
const money = new Intl.NumberFormat("zh-CN", {style:"currency",currency:"CNY"});
const qty = value => number.format(value / 1000);
const clean = value => value ? html(value) : "—";
const timestamp = value => value ? new Date(value).toLocaleString("zh-CN", {hour12:false}) : "—";
const roleText = {admin:"管理员",planner:"采购／计划",warehouse:"仓储／质检",clinical:"临床耗材",viewer:"只读"};
const kindText = {purchase:"采购单",sale:"销售单",work:"生产工单",material:"原料／组件",product:"制成品",medical:"医疗耗材",factory:"工厂仓",central:"医院中心库",clinical:"临床二级库",vendor:"供应商",customer:"客户",both:"供应商兼客户"};
const docStatus = {draft:["草稿",""],approved:["已审核","blue"],partial:["部分处理","amber"],running:["生产中","blue"],done:["已完成","green"],cancelled:["已取消",""]};
const lotStatus = {pending:["待检／隔离","amber"],released:["已放行","green"],blocked:["已冻结","red"]};
const billingStatus = {pending:["待对账","amber"],confirmed:["已确认","green"],rejected:["已退回","red"]};
const rights = {
  master:["planner"], purchase:["planner"], sale:["planner"], approve:["planner"], receive:["warehouse"],
  ship:["warehouse"], bom:["planner"], work:["planner"], start:["planner"], report:["planner"], finish:["planner"],
  inspect:["warehouse"], transfer:["warehouse","clinical"], use:["clinical"], billing:["clinical"], user:[],
};
const navigation = [
  ["运营", [["home","工作台","⌂"],["purchase","采购管理","↙"],["sale","销售履约","↗"],["exercise","急单协同演练","▣"]]],
  ["制造与医疗", [["work","生产与 BOM","▦"],["stock","库存与质检","◇"],["clinical","医院耗材","✚"],["trace","批次追溯","◎"]]],
  ["管理", [["master","主数据","≡"],["reports","报表与审计","▤"],["users","账号管理","☷"]]],
];
const pages = Object.fromEntries(navigation.flatMap(([,entries])=>entries.map(([id,label])=>[id,label])));
const filterDefaults = {status:"", site:"", q:""};
let state = null;
let demo = false;
let page = "home";
let stockTab = "stock";
let masterTab = "items";
let workTab = "docs";
let filter = {...filterDefaults};
let traceRecord = null;
let traceQuery = {};
let toastTimer;
let dialogGeneration = 0;

function cfgLabel(map,key) {
  const [label,color] = map[key] || [key,""];
  return `<span class="status ${html(color)}"><i></i>${html(label)}</span>`;
}

const text = value => html(value);
const sub = value => `<small>${html(value)}</small>`;
const code = value => `<span class="ref">${html(value)}</span>`;
const numeric = value => `<span class="num">${html(value)}</span>`;
const bold = value => `<span class="strong">${html(value)}</span>`;
const item = (name, reference) => bold(name) + sub(reference);
const allowed = action => state?.account.role === "admin" || (rights[action] || []).includes(state?.account.role);
const hasClinical = () => ["admin","clinical"].includes(state?.account.role);
const showNav = id => id !== "users" || allowed("user");

function button(label,action,value="",style="") {
  return `<button type="button" class="button ${html(style)}" data-action="${html(action)}" data-value="${html(value)}">${html(label)}</button>`;
}

function link(label,action,value) {
  return `<button type="button" class="link" data-action="${html(action)}" data-value="${html(value)}">${html(label)}</button>`;
}

function exportLink(label,id) {
  return `<a class="button" href="/api/export/${html(id)}">${html(label)} ↓</a>`;
}

function table(headers, records, render, empty="暂无记录") {
  if (!records.length) return `<p class="empty">${html(empty)}</p>`;
  return `<div class="table-scroll"><table><thead><tr>${headers.map(label=>`<th scope="col">${html(label)}</th>`).join("")}</tr></thead><tbody>${
    records.map(record=>`<tr>${render(record).map(cell=>`<td>${cell}</td>`).join("")}</tr>`).join("")
  }</tbody></table></div>`;
}

function head(title,description,actions="") {
  return `<header class="page-head"><div><h1>${html(title)}</h1>${description?`<p>${html(description)}</p>`:""}</div><div class="actions">${actions}</div></header>`;
}

function panel(title,body,action="",description="") {
  return `<section class="panel"><div class="panel-heading"><div><h2>${html(title)}</h2>${description?`<p>${html(description)}</p>`:""}</div>${action}</div>${body}</section>`;
}

function section(title,body) {
  return `<section class="detail-section"><h3>${html(title)}</h3>${body}</section>`;
}

function options(list,selection="") {
  return list.map(([value,label])=>`<option value="${html(value)}"${value===selection?" selected":""}>${html(label)}</option>`).join("");
}

const pick = (list,fn) => list.map(row=>[row.id,fn(row)]);
const itemOptions = (source=state.items) => pick(source,row=>row.code+" · "+row.name);
const siteOptions = (source=state.sites) => pick(source,row=>row.name);
const lotOptions = (source=state.lots) => pick(source,row=>row.code+" · "+row.item_name);
const pairs = (a,b) => Object.entries(a).map(([key,label])=>[key,b?b(label):label]);

function filters({placeholder="搜索编码、名称或单据", status=[], sites=false, actions=""}={}) {
  return `<div class="toolbar"><div class="filters"><input type="search" aria-label="${html(placeholder)}" placeholder="${html(placeholder)}" value="${html(filter.q)}" data-filter="q">${status.length?`<select aria-label="筛选状态" data-filter="status">${options([["","全部状态"],...status],filter.status)}</select>`:""}${sites?`<select aria-label="筛选仓库" data-filter="site">${options([["","全部仓库"],...siteOptions()],filter.site)}</select>`:""}</div><div class="actions">${actions}</div></div>`;
}

function tabs(group,selected,labels) {
  return `<div class="tabs">${labels.map(([id,label])=>`<button type="button" class="tab ${id===selected?"active":""}" data-action="${html(group)}" data-value="${html(id)}" aria-pressed="${id===selected}">${html(label)}</button>`).join("")}</div>`;
}

function matches(...fields) {
  const query=filter.q.trim().toLowerCase();
  return !query || fields.some(value=>String(value??"").toLowerCase().includes(query));
}

function isExpired(lot) {
  return lot.expiry && lot.expiry < state.today;
}

function dateText(lot) {
  return isExpired(lot) ? cfgLabel({expired:["已过期","red"]},"expired")+" "+clean(lot.expiry) : clean(lot.expiry);
}

function docsTable(records,withKind=false) {
  return table(["单据号",...(withKind?["业务"]:[]),"对象","状态","计划日期"],records,row=>[
    link(row.ref,"document",row.id),
    ...(withKind?[text(kindText[row.kind])]:[]),
    text(row.partner_name || row.site_name),cfgLabel(docStatus,row.status),clean(row.due),
  ]);
}

function recentMovement(records) {
  return table(["业务","物料／批次","仓库","变动","单据","时间"],records,row=>[
    bold(row.kind),item(row.item_name,row.lot),text(row.site_name),numeric((row.quantity>0?"+":"")+qty(row.quantity)+" "+row.unit),code(row.ref),text(timestamp(row.created)),
  ]);
}

function docsPage(kind) {
  const heading = {purchase:["采购管理","记录供应商订单、审核及分批验收入库。","＋ 新建采购单"],
    sale:["销售履约","管理客户销售单和可用批次发货。","＋ 新建销售单"]}[kind];
  const records = state.documents.filter(row=>row.kind===kind && matches(row.ref,row.site_name,row.partner_name,row.note) && (!filter.status || row.status===filter.status));
  return head(heading[0],heading[1],allowed(kind)?button(heading[2],"newTrade",kind,"primary"):"")
    + `<section class="panel">${filters({status:pairs(docStatus,x=>x[0])})}<div id="filtered">${docsTable(records)}</div></section>`;
}

function metric(title,value,hint,target,icon,style="",action="go") {
  return `<button type="button" class="metric" data-action="${html(action)}" data-value="${html(target)}"><span class="metric-top">${html(title)}<span class="metric-icon ${html(style)}" aria-hidden="true">${html(icon)}</span></span><strong>${html(value)}</strong><small>${html(hint)}</small></button>`;
}

function notices(records,render) {
  return records.length ? `<div class="notice-list">${records.map(render).join("")}</div>` : '<p class="empty">暂无预警</p>';
}

function homePage() {
  const model=state.summary;
  const open=model.open_orders;
  const cards = [
    metric("待收货采购",open.purchase||0,"已审核或待收货","purchase","↙"),
    metric("执行中工单",open.work||0,"待领料或生产中","work","▦","blue"),
    metric("待检批次",model.inspect_count,"待检与隔离","inspection","◇","amber","goStock"),
    hasClinical() ? metric("临床待对账",model.billing_count,"待回执或退回","clinical","✚","blue") : metric("待发货销售",open.sale||0,"已审核或待发货","sale","↗","blue"),
  ].join("");
  const expiry=notices(model.expiry.slice(0,5),row=>`<div class="notice-row"><div>${link(row.name,"lotTrace",row.lot_id)}${sub(row.site_name+" · "+row.lot)}</div>${cfgLabel({e:[row.days_left<0?`过期 ${Math.abs(row.days_left)} 天`:`剩余 ${row.days_left} 天`,row.days_left<0?"red":"amber"]},"e")}</div>`);
  const low=notices(model.low.slice(0,5),row=>`<div class="notice-row"><div>${bold(row.name)}${sub(row.code+" · 补货点 "+qty(row.minimum)+" "+row.unit)}</div>${numeric(qty(row.available)+" "+row.unit)}</div>`);
  return head("运营总览","查看采购、生产、库存与临床耗材的待办和预警。",
      allowed("purchase")?button("＋ 新建采购单","newTrade","purchase","primary"):"")
    + `<div class="metrics">${cards}</div><div class="board"><div class="stack">${panel("最近单据",docsTable(model.recent,true))}${panel("最近出入库",recentMovement(state.movements.slice(0,6)),button("库存流水","goStock","movements","small"))}</div><div class="stack">${panel("60 天效期预警",expiry,button("查看库存","goStock","stock","small"))}${panel("低于补货点",low,"","按全仓可用批次汇总")}</div></div>`;
}

function workPage() {
  const isDocs = workTab==="docs";
  const rows = isDocs ? state.documents.filter(row=>row.kind==="work" && matches(row.ref,row.site_name,row.version,row.note) && (!filter.status||row.status===filter.status))
    : state.boms.filter(row=>matches(row.code,row.name,row.version));
  const tableView=isDocs ? docsTable(rows) : table(["成品","BOM 版本","创建时间"],rows,row=>[
    item(row.name,row.code),link(row.version,"bomDetail",row.id),text(timestamp(row.created)),
  ]);
  return head("生产与 BOM","管理物料清单版本，核算工单缺料，按工序完成报工。",
    (allowed("bom")?button("＋ 新建 BOM","newBom"):"")+(allowed("work")?button("＋ 新建工单","newWork","","primary"):""))
    + `<section class="panel">${tabs("workTab",workTab,[["docs","生产工单"],["boms","物料清单"]])}${filters({status:isDocs?pairs(docStatus,x=>x[0]):[]})}<div id="filtered">${tableView}</div></section>`;
}

function stockPage() {
  const bar = allowed("transfer") ? button("⇄ 库存调拨","transfer","","primary") : "";
  const tabList = [["stock","库存明细"],["inspection","批次质检"],["movements","出入库流水"],["units","一物一码"]];
  let body, params={};
  if (stockTab==="stock") {
    const stocks=state.stock.filter(row=>matches(row.code,row.name,row.lot,row.site_name) && (!filter.site||filter.site===row.site_id) && (!filter.status||filter.status===row.status));
    body=table(["物料","仓库","批次","库存","效期","状态"],stocks,row=>[
      item(row.name,row.code),text(row.site_name),link(row.lot,"lotTrace",row.lot_id),numeric(qty(row.quantity)+" "+row.unit),dateText(row),cfgLabel(lotStatus,row.status),
    ]);
    params={status:pairs(lotStatus,x=>x[0]),sites:true,actions:exportLink("导出库存","stock")};
  } else if (stockTab==="inspection") {
    const lots=state.lots.filter(row=>matches(row.item_code,row.item_name,row.code) && (!filter.status || filter.status===row.status));
    body=table(["批次","物料","效期","状态","处理"],lots,row=>[
      link(row.code,"lotTrace",row.id),item(row.item_name,row.item_code),dateText(row),cfgLabel(lotStatus,row.status),allowed("inspect")?button("检验／冻结","inspect",row.id,"small"):"—",
    ])+section("最近质检记录",table(["批次","结果","检验结论","操作人","时间"],state.inspections,row=>[
      link(row.lot,"lotTrace",row.lot_id),cfgLabel(lotStatus,row.verdict),text(row.note),text(row.actor),text(timestamp(row.created)),
    ]));
    params={status:pairs(lotStatus,x=>x[0])};
  } else if (stockTab==="movements") {
    body=recentMovement(state.movements.filter(row=>matches(row.ref,row.lot,row.item_code,row.item_name,row.kind,row.site_name) && (!filter.site||filter.site===row.site_id)));
    params={sites:true,actions:exportLink("导出完整流水","movements")};
  } else {
    body=table(["包装码","耗材","批次","仓库","状态"],state.units.filter(row=>matches(row.code,row.item_name,row.lot,row.site_name) && (!filter.site||filter.site===row.site_id)),row=>[
      link(row.code,"codeTrace",row.code),item(row.item_name,row.item_code),link(row.lot,"lotTrace",row.lot_id),clean(row.site_name),cfgLabel({stock:["在库","green"],used:["已耗用","blue"]},row.status),
    ]);
    params={sites:true,placeholder:"搜索加载的包装码或批次",actions:button("扫描精确查找","go","trace")};
  }
  return head("库存与质检","查看批次、仓库、余量与效期，处理调拨、隔离、放行和冻结。",bar)
    + `<section class="panel">${tabs("stockTab",stockTab,tabList)}${filters(params)}<div id="filtered">${body}</div></section>`;
}

function clinicalPage() {
  if (!hasClinical()) return head("医院耗材","此页面需要临床耗材或管理员权限。");
  const records=state.clinical.filter(row=>matches(row.ref,row.case_ref,row.item_name,row.code,row.billing_ref) && (!filter.status||row.status===filter.status));
  const body=table(["耗用单／耗材","包装码","手术／业务号","计费状态","费用回执","对账"],records,row=>[
    item(row.item_name,row.ref),link(row.code,"codeTrace",row.code),code(row.case_ref),cfgLabel(billingStatus,row.status),clean(row.billing_ref),
    row.status!=="confirmed"?button("登记回执","billing",row.id,"small"):"—",
  ]);
  return head("医院耗材","中心库调拨到手术室二级库后，以包装码登记耗用和费用回执。",
      button("⇄ 扫码调拨","transfer","clinical")+button("＋ 扫码耗用","use","","primary"))
    + `<section class="panel">${filters({placeholder:"搜索手术号、耗材或包装码",status:pairs(billingStatus,x=>x[0]),actions:exportLink("导出耗用对账","clinical")})}<div id="filtered">${body}</div></section>`;
}

function tracePage() {
  const form = `<form id="trace-form" class="toolbar"><div class="filters"><select id="trace-lot" name="lot" aria-label="选择批次">${options([["","选择物料批次"],...lotOptions()],traceQuery.lot||"")}</select><input type="search" name="code" maxlength="220" aria-label="包装码" value="${html(traceQuery.code||"")}" placeholder="或扫描包装码"></div><button class="button primary">查询追溯</button></form>`;
  const content=[head("批次追溯","查询采购来源、生产投入产出、调拨流向和临床耗用。"),`<section class="panel">${form}</section>`];
  if (!traceRecord) return content.join("");
  const {lot,unit,upstream,downstream,movements,stock,uses,truncated}=traceRecord;
  const related=(label,lots)=>panel(label,table(["批次","物料","状态","效期"],lots,row=>[
    link(row.code,"lotTrace",row.id),item(row.name,row.item_code),cfgLabel(lotStatus,row.status),dateText(row),
  ]));
  const onHand=table(["仓库","余额"],stock,row=>[text(row.site_name),numeric(qty(row.quantity)+" "+row.unit)]);
  const events=unit ? movements.filter(row=>row.detail.includes(unit.code) || row.kind==="收货" || row.kind==="生产完工") : movements;
  content.push(`<div class="panel separate"><div class="panel-heading"><div><h2>${html(lot.code)} · ${html(lot.item_name)}</h2><p>${unit?html(unit.code+" · "+(unit.location||"已耗用")):html(lot.item_code)}</p></div><div class="actions">${cfgLabel(lotStatus,lot.status)}${allowed("inspect")?button("检验／冻结","inspect",lot.id,"small"):""}</div></div>${onHand}</div>`,
    `<div class="board trace-board"><div class="stack">${panel(unit?"包装码和批次流水":"批次流水",recentMovement(events),"","最多显示最近 500 条批次流水")}${hasClinical()?panel("临床耗用",table(["耗用单","手术／业务号","状态","包装码"],uses.filter(row=>!unit||row.code===unit.code),row=>[code(row.ref),code(row.case_ref),cfgLabel(billingStatus,row.status),code(row.code)])):""}</div><div class="stack">${related("上游投入批次",upstream)}${related("下游产出批次",downstream)}${truncated?'<p class="form-hint">上游或下游超过 1,000 个批次，结果已截取。</p>':""}</div></div>`);
  return content.join("");
}

function masterPage() {
  const selected = state[masterTab].filter(row=>matches(row.code,row.name,row.type));
  let view;
  if (masterTab==="items") view = table(["物料","分类","单位","补货点","入库质检","一码一物","GTIN"],selected,row=>[
    item(row.name,row.code),text(kindText[row.type]),text(row.unit),numeric(qty(row.minimum)),text(row.quality ? "需要":"—"),text(row.tracked?"启用":"—"),code(row.gtin||"—"),
  ]);
  if (masterTab==="sites") view = table(["仓库","分类"],selected,row=>[item(row.name,row.code),text(kindText[row.type])]);
  if (masterTab==="partners") view = table(["往来单位","分类","联系信息"],selected,row=>[item(row.name,row.code),text(kindText[row.type]),clean(row.contact)]);
  return head("主数据","物料单位、追溯规则与仓库分类会应用到后续单据。",
      allowed("master")?button("＋ 新增资料","newMaster",masterTab,"primary"):"")
    + `<section class="panel">${tabs("masterTab",masterTab,[["items","物料"],["sites","仓库"],["partners","供应商与客户"]])}${filters()}<div id="filtered">${view}</div></section>`;
}

function reportsPage() {
  const model=state.summary;
  const counts=table(["仓库","在库批次数","有效可用批次","待检或冻结批次"],state.sites,site=>{
    const rows=state.stock.filter(row=>row.site_id===site.id);
    return [item(site.name,site.code),numeric(rows.length),numeric(rows.filter(row=>row.status==="released"&&!isExpired(row)).length),numeric(rows.filter(row=>row.status!=="released").length)];
  });
  const auditRows=table(["时间","账号","操作","引用","说明"],state.audit,row=>[
    text(timestamp(row.created)),text(row.actor),bold(row.action),code(row.ref),clean(row.detail),
  ]);
  return head("报表与审计","查询仓库运营指标，导出库存快照、完整流水和有权限的审计记录。",
    exportLink("库存","stock")+exportLink("流水","movements")+(hasClinical()?exportLink("耗用对账","clinical"):"")+(allowed("user")?exportLink("审计","audit"):""))
    + `<div class="stack">${panel("分仓库存",counts)}${panel("低库存明细",table(["物料","可用库存","补货点"],model.low,row=>[
      item(row.name,row.code),numeric(qty(row.available)+" "+row.unit),numeric(qty(row.minimum)+" "+row.unit),
    ]))}${allowed("user")?panel("操作审计",auditRows,"","显示最近 200 条，完整数据可导出"):""}</div>`;
}

function usersPage() {
  return head("账号管理","为采购计划、仓储质检和临床耗材岗位分配操作角色。",button("＋ 新建账号","newUser","","primary"))
    + panel("用户列表",table(["姓名","用户名","角色","状态"],state.users,row=>[
      bold(row.name),code(row.username),text(roleText[row.role]),cfgLabel({1:["启用","green"],0:["停用",""]},row.enabled),
    ]));
}

const renderers={home:homePage,exercise:exercisePage,purchase:()=>docsPage("purchase"),sale:()=>docsPage("sale"),work:workPage,stock:stockPage,clinical:clinicalPage,trace:tracePage,master:masterPage,reports:reportsPage,users:usersPage};

function render() {
  $("crumb").textContent=pages[page];
  $("business-date").textContent=state.today;
  $("mode").hidden=!demo;
  $("account").innerHTML=`<span class="avatar">${html(state.account.name.slice(0,1))}</span><span>${html(state.account.name)}<small>${html(roleText[state.account.role])}</small></span>`;
  $("nav").innerHTML=navigation.map(([label,entries])=>`<div class="nav-label">${html(label)}</div>${entries.filter(([id])=>showNav(id)).map(([id,name,icon])=>
    `<button type="button" class="nav-item ${page===id?"active":""}" data-action="go" data-value="${id}"${page===id?' aria-current="page"':""}><span class="nav-icon" aria-hidden="true">${html(icon)}</span>${html(name)}</button>`
  ).join("")}`).join("");
  $("main").innerHTML=renderers[page]();
  if (page==="exercise" && exerciseDemo) refreshExerciseDemo();
}

function updateFiltered() {
  const target=$("filtered");
  if (!target) return;
  const template=document.createElement("template");
  template.innerHTML=renderers[page]();
  target.innerHTML=template.content.querySelector("#filtered").innerHTML;
}

function go(id) {
  if (!Object.hasOwn(pages,id) || !showNav(id)) return;
  if (page==="exercise" && id!=="exercise") {
    if (exerciseDemoLoading) stopExerciseDemo();
    else pauseExerciseDemo();
  }
  page=id;
  filter={...filterDefaults};
  $("sidebar").classList.remove("open");
  $("navigation-toggle").setAttribute("aria-expanded","false");
  render();
  window.scrollTo(0,0);
  $("main").focus({preventScroll:true});
}

function notify(message,error=false) {
  clearTimeout(toastTimer);
  $("toast").textContent=message;
  $("toast").classList.toggle("error",error);
  $("toast").hidden=false;
  toastTimer=setTimeout(()=>$("toast").hidden=true,4500);
}

function requestKey() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)),x=>x.toString(16).padStart(2,"0")).join("");
}

async function request(path,payload,key="") {
  let response;
  try {
    response=await fetch(path,payload===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json",...(key?{"Idempotency-Key":key}:{})},body:JSON.stringify(payload)});
  } catch {
    throw new Error("无法连接服务，请刷新后重试");
  }
  const result=await response.json();
  if (!response.ok) {
    const error = new Error(result.error||"请求失败");
    error.status=response.status;
    throw error;
  }
  return result;
}

async function loadState() {
  state=await request("/api/state");
  $("starting").hidden=true;
  $("login-screen").hidden=true;
  $("app").hidden=false;
  render();
}

function showLogin() {
  stopExerciseDemo();
  state=null;
  traceRecord=null;
  exerciseModel=null;
  traceQuery={};
  page="home";
  filter={...filterDefaults};
  $("starting").hidden=true;
  $("app").hidden=true;
  $("login-screen").hidden=false;
  $("login-error").hidden=true;
  $("demo-fill").hidden=!demo;
  if ($("dialog").open) $("dialog").close();
  $("login-form").reset();
  $("login-form").elements.username.focus();
}

function input(name,label,{type="text",value="",required=true,placeholder="",min="",max="",maxlength=120,step=""}={}) {
  return `<label>${html(label)}<input name="${name}" type="${type}" value="${html(value)}" placeholder="${html(placeholder)}"${required?" required":""}
      ${min!==""?` min="${html(min)}"`:""}${max!==""?` max="${html(max)}"`:""}${step?` step="${html(step)}"`:""}${type==="text"||type==="password"?` maxlength="${html(maxlength)}"`:""}></label>`;
}

function select(name,label,choices,selection="",required=true) {
  return `<label>${html(label)}<select name="${name}"${required?" required":""}>${options([["","请选择"],...choices],selection)}</select></label>`;
}

function memo(name="note",label="备注",required=false,placeholder="",maxlength=400) {
  return `<label>${html(label)}<textarea name="${name}" maxlength="${maxlength}" placeholder="${html(placeholder)}"${required?" required":""}></textarea></label>`;
}

const quantity = (label="数量",value="",required=true) => input("quantity",label,{type:"number",value,min:"0.001",max:"999999999",step:"0.001",required});
const moneyInput = () => input("price","单价（元）",{type:"number",min:"0",max:"999999999",step:"0.01",required:false});
const dueInput = label => input("due",label||"计划交付日期",{type:"date",required:false});
const checkbox = (id,label) => `<label class="check"><input type="checkbox" name="${id}" value="1">${html(label)}</label>`;
const grid = body => `<div class="form-grid">${body}</div>`;
const help = text => `<p class="form-hint">${html(text)}</p>`;

function openDialog(title,body) {
  dialogGeneration += 1;
  $("dialog-title").textContent=title;
  $("dialog-body").innerHTML=body;
  if (!$("dialog").open) $("dialog").showModal();
  $("dialog").scrollTop=0;
}

function formDialog(title,action,body,submit="保存",collect=values=>values,onSuccess=null,returnDoc="") {
  openDialog(title,`<form id="operation-form">${body}<p class="form-error" role="alert" hidden></p><div class="form-actions">${returnDoc?button("返回单据","document",returnDoc):button("取消","closeDialog")}<button class="button primary" type="submit">${html(submit)}</button></div></form>`);
  const form=$("operation-form");
  let lastPayload;
  let lastKey;
  form.addEventListener("submit",async event=>{
    event.preventDefault();
    const submitButton=event.submitter || form.querySelector('button[type="submit"]');
    const errorBox=form.querySelector(".form-error");
    errorBox.hidden=true;
    submitButton.disabled=true;
    let result;
    try {
      const payload=collect(Object.fromEntries(new FormData(form)),form);
      const encoded=JSON.stringify(payload);
      if (lastPayload!==encoded) {lastPayload=encoded;lastKey=requestKey();}
      result=await request("/api/action/"+action,payload,lastKey);
    } catch (error) {
      if (error.status===401) showLogin();
      else {
        errorBox.textContent=error.message;
        errorBox.hidden=false;
      }
      submitButton.disabled=false;
      return;
    }
    $("dialog").close();
    if (action==="password") {
      showLogin();
      notify("密码已更改，请重新登录");
      return;
    }
    notify(result.ref ? "操作成功 · "+result.ref : "操作成功");
    try {
      await loadState();
      if (page==="trace" && (traceQuery.lot || traceQuery.code)) await refreshTrace();
      if (onSuccess) await onSuccess(result);
    } catch (error) {
      if (error.status===401) showLogin();
      else notify("操作已保存，数据刷新失败，请手动刷新",true);
    }
  });
  return form;
}

function withRows(form,group,initial=1) {
  const container=form.querySelector(`[data-rows="${group}"]`);
  const add=form.querySelector(`[data-add="${group}"]`);
  const bom=group==="bom";
  const steps=group==="steps";
  const source=bom?state.items.filter(row=>!row.tracked):group==="sale"?state.items.filter(row=>!row.tracked):state.items;
  const rowHTML=()=>{
    if (steps) return `<div class="edit-row step">${input("name","工序名称")}<button class="button small danger" type="button" data-remove aria-label="移除本行">移除</button></div>`;
    return `<div class="edit-row ${bom?"bom":""}">${select("item_id",bom?"组件":"物料",itemOptions(source))}${quantity(bom?"单位用量":"数量")}${bom?"":moneyInput()}<button class="button small danger" type="button" data-remove aria-label="移除本行">移除</button></div>`;
  };
  const append=()=> {
    if (container.children.length>=60) return;
    container.insertAdjacentHTML("beforeend",rowHTML());
  };
  add.addEventListener("click",()=>{append();container.lastElementChild?.querySelector("select,input")?.focus();});
  container.addEventListener("click",event=>{
    const remove=event.target.closest("[data-remove]");
    if (remove && container.children.length>(steps?0:1)) remove.parentElement.remove();
  });
  for(let i=0;i<initial;i+=1) append();
}

function rowEditor(id,label) {
  return `<div><div class="line-head"><strong>${html(label)}</strong><button type="button" class="button small soft" data-add="${id}">＋ 添加行</button></div><div class="edit-lines" data-rows="${id}"></div></div>`;
}

function collectRows(form,group) {
  return Array.from(form.querySelectorAll(`[data-rows="${group}"] .edit-row`),row=>
    Object.fromEntries(Array.from(row.querySelectorAll("input,select"),el=>[el.name,el.value])));
}

function newTrade(kind) {
  const purchase=kind==="purchase";
  const partners=state.partners.filter(row=>row.type==="both"||row.type===(purchase?"vendor":"customer"));
  const sites=state.sites.filter(row=>row.type!=="clinical");
  const form=formDialog("新建"+kindText[kind],kind,
    grid(select("partner_id",purchase?"供应商":"客户",pick(partners,row=>row.name))+select("site_id",purchase?"收货仓":"发货仓",siteOptions(sites))+dueInput())
    + rowEditor(kind,"单据明细")+memo(),"保存草稿",
    (values,form)=>({partner_id:values.partner_id,site_id:values.site_id,due:values.due,note:values.note,lines:collectRows(form,kind).map(row=>({...row,price:row.price||"0"}))}),
    result=>openDocument(result.id));
  withRows(form,kind);
}

function newBOM() {
  const form=formDialog("新建物料清单","bom",
    grid(select("item_id","制成品",itemOptions(state.items.filter(row=>row.type==="product")))+input("version","BOM 版本",{placeholder:"例如 A.01",maxlength:40}))
    + rowEditor("bom","组件与单位用量")+rowEditor("steps","工序顺序")+help("已有版本保留供历史工单追溯。工序允许为空，填写后须按顺序报工。"),
    "保存 BOM",(values,form)=>({item_id:form.querySelector('[name="item_id"]').value,version:values.version,lines:collectRows(form,"bom"),steps:collectRows(form,"steps")}),
    result=>openBOM(result.id));
  withRows(form,"bom");
  withRows(form,"steps",0);
}

function newWork() {
  formDialog("新建生产工单","work",
    grid(select("bom_id","BOM 及版本",pick(state.boms,row=>row.code+" · "+row.name+" / "+row.version))
    +select("site_id","生产仓",siteOptions(state.sites.filter(row=>row.type==="factory")))
    +quantity("计划产量")+dueInput("计划完工日期"))+memo(),"保存草稿",
    values=>values,result=>openDocument(result.id));
}

async function openBOM(id) {
  const version=++dialogGeneration;
  const model=await request("/api/bom/"+encodeURIComponent(id));
  if (version!==dialogGeneration) return;
  const bom=state.boms.find(row=>row.id===id);
  openDialog("物料清单 · "+(bom?.name||model.version),
    `<div class="detail-meta">版本 ${html(model.version)} · ${html(timestamp(model.created))}</div>`
    + section("组件",table(["物料","单位成品用量"],model.lines,row=>[item(row.name,row.code),numeric(qty(row.quantity)+" "+row.unit)]))
    + section("工序",table(["顺序","工序名称"],model.steps,row=>[numeric(row.step_no),text(row.name)])));
}

function newMaster(entity) {
  const isItem=entity==="items";
  const title={items:"物料",sites:"仓库",partners:"往来单位"}[entity];
  const types={items:["material","product","medical"],sites:["factory","central","clinical"],partners:["vendor","customer","both"]}[entity];
  const basics=input("code",title+"编码",{maxlength:48})+input("name",title+"名称")
    + select("type","分类",types.map(key=>[key,kindText[key]]));
  const detail=isItem?input("unit","计量单位",{maxlength:12,placeholder:"例如 件、kg、盒"})
    + input("minimum","补货点",{type:"number",value:"0",min:"0",step:"0.001"})
    + input("gtin","GTIN（14 位）",{required:false,maxlength:14})
    + checkbox("quality","到货需质检")+checkbox("tracked","一物一码")
    : entity==="partners"?input("contact","联系信息",{required:false}):"";
  formDialog("新增"+title,"master",grid(basics+detail)+(isItem?help("一物一码仅用于医疗耗材。普通包装码可留空 GTIN，GS1 编码需绑定 GTIN。"):""),
    "保存资料",values=>({...values,entity,quality:values.quality==="1",tracked:values.tracked==="1"}));
}

async function openDocument(id) {
  const version=++dialogGeneration;
  const model=await request("/api/document/"+encodeURIComponent(id));
  if (version!==dialogGeneration) return;
  const reviewable=["draft","approved"].includes(model.status);
  const tradable=model.kind!=="work" && ["approved","partial"].includes(model.status);
  const action=model.kind==="purchase"?"receive":"ship";
  const header=`<div class="detail-meta">${cfgLabel(docStatus,model.status)}<span>${html(model.site_name)}</span>${model.partner_name?`<span>${html(model.partner_name)}</span>`:""}<span>计划日期 ${clean(model.due)}</span>${model.version?`<span>BOM ${html(model.version)}</span>`:""}</div>`;
  const actions=[];
  if (reviewable && allowed("approve")) {
    if (model.status==="draft") actions.push(button("审核通过","review",id,"primary"));
    actions.push(button("取消单据","cancelDoc",id,"danger"));
  }
  if (model.status==="approved" && model.kind==="work" && allowed("start")) actions.push(button("领料并开工","startWork",id,"primary"));
  if (model.status==="running" && allowed("finish")) actions.push(button("完工待检","finishWork",id,"primary"));
  const work=model.kind==="work";
  const lines=section("明细",table(["物料","计划","已处理",...(work?[]:["单价"]),...(tradable&&allowed(action)?["处理"]:[])],model.lines,row=>[
    item(row.name,row.code),numeric(qty(row.quantity)+" "+row.unit),numeric(qty(row.fulfilled)+" "+row.unit),
    ...(work?[]:[numeric(money.format(row.price/100))]),
    ...(tradable&&allowed(action)?[row.fulfilled<row.quantity?button(action==="receive"?"收货":"发货",action,id+"|"+row.id,"small"):"—"]:[]),
  ]));
  const sections=[];
  if (model.note) sections.push(`<p class="detail-note">${html(model.note)}</p>`);
  sections.push(lines);
  if (work && model.plan.length) sections.push(section("单阶缺料试算",help("按当前工单计算，库存未按其他订单预留。预计在途包含到期日内以及未登记到期日的已审核采购。")
    + table(["组件","需求","当前可用","预计在途","当前缺料","预计净缺料"],model.plan,row=>[
      item(row.name,row.code),numeric(qty(row.required)),numeric(qty(row.available)),numeric(qty(row.incoming)),numeric(qty(row.shortage)),numeric(qty(row.net)),
    ])));
  if (work && model.steps.length) {
    const next=model.steps.find(row=>row.minutes===null)?.id;
    sections.push(section("工序报工",table(["工序","工时","记录人","处理"],model.steps,row=>[
      bold(row.step_no+" · "+row.name),row.minutes===null?"—":text(row.minutes+" 分钟"),clean(row.actor),
      row.id===next&&model.status==="running"&&allowed("report")?button("报工","reportStep",id+"|"+row.id,"small"):"—",
    ])));
  }
  if (model.movements.length) sections.push(section("库存流水",recentMovement(model.movements)));
  openDialog(kindText[model.kind]+" · "+model.ref,header
    +(actions.length?`<div class="actions">${actions.join("")}</div>`:"")+sections.join(""));
}

async function tradeLine(kind,serial) {
  const [id,lineId]=serial.split("|");
  const model=await request("/api/document/"+encodeURIComponent(id));
  const line=model.lines.find(row=>row.id===lineId);
  if (!line) throw new Error("单据行不存在");
  const receive=kind==="receive";
  const available=line.quantity-line.fulfilled;
  const receiveFields=receive?input("lot","收货批号",{maxlength:64})+input("expiry","效期",{type:"date",required:line.type==="medical",min:state.today}):"";
  const codes=receive&&line.tracked?memo("codes","包装码（一行一码）",true,"扫描枪或手动输入，每件一个唯一包装码",12000):"";
  formDialog((receive?"采购收货":"销售发货")+" · "+line.name,kind,
    help("待处理 "+qty(available)+" "+line.unit+(receive?"":"。将优先使用近期到期的已放行批次。"))
    +grid(input("quantity","本次数量",{type:"number",min:line.tracked?"1":"0.001",step:line.tracked?"1":"0.001",max:String(available/1000)})+receiveFields)
    +codes+memo(),receive?"确认收货":"确认发货",
    values=>({...values,id,line_id:lineId}),()=>openDocument(id),id);
}

function reviewDocument(id,decision) {
  const title=decision==="approve"?"审核通过":"取消单据";
  formDialog(title,"approve",memo("note",decision==="approve"?"审核意见":"取消原因",decision==="cancel"),title,
    values=>({...values,id,decision}),()=>openDocument(id),id);
}

function startWork(id) {
  formDialog("领料并开工","start",help("按当前已放行批次与效期顺序领料。库存不足时本次领料将整体撤回。"),
    "确认开工",()=>({id}),()=>openDocument(id),id);
}

function reportStep(serial) {
  const [id,step_id]=serial.split("|");
  formDialog("工序报工","report",input("minutes","用时（分钟）",{type:"number",min:"1",max:"100000",step:"1"})+memo(),
    "保存报工",values=>({...values,id,step_id}),()=>openDocument(id),id);
}

function finishWork(id) {
  formDialog("生产完工","finish",grid(input("lot","新成品批号",{maxlength:64})+input("expiry","效期",{type:"date",min:state.today,required:false}))+memo()+help("完工后成品进入待检状态，需放行后才可发货。"),
    "提交完工",values=>({...values,id}),()=>openDocument(id),id);
}

function inspectLot(id) {
  const lot=state.lots.find(row=>row.id===id);
  if (!lot) throw new Error("批次不存在");
  formDialog("质检与冻结 · "+lot.code,"inspect",
    select("verdict","处置结果",pairs(lotStatus,x=>x[0]).filter(([key])=>key!==lot.status))
    +memo("note","检验结论或冻结原因",true)+help("状态会影响该批次在所有仓库的发货、调拨、生产及耗用。"),
    "保存处置",values=>({...values,lot_id:id}));
}

function transferStock(clinical=false) {
  const onlyScan=clinical || state.account.role==="clinical";
  const regularLots=state.lots.filter(row=>!row.tracked);
  const mode=onlyScan?"":select("mode","方式",[["batch","按批次数量"],["scan","按单个包装码"]],"batch");
  const scan=`<div id="scan-fields"${onlyScan?"":" hidden"}>${input("code","包装码",{maxlength:220,required:onlyScan})}</div>`;
  const batch=onlyScan?"":`<div id="batch-fields">${grid(select("lot_id","批次",lotOptions(regularLots))+quantity("调拨数量"))}</div>`;
  const form=formDialog("仓库调拨","transfer",mode
    +grid(select("from_id","调出仓",siteOptions(),onlyScan?"central":"")+select("to_id","调入仓",siteOptions(),onlyScan?"clinical":""))
    +batch+scan+help("调拨成功后，同一事务登记出库与入库。"),"确认调拨",
    values=>({from_id:values.from_id,to_id:values.to_id,...(onlyScan||values.mode==="scan"?{code:values.code}:{lot_id:values.lot_id,quantity:values.quantity})}));
  if (!onlyScan) form.elements.mode.addEventListener("change",()=>{
    const scanning=form.elements.mode.value==="scan";
    $("scan-fields").hidden=!scanning;
    $("batch-fields").hidden=scanning;
    form.elements.code.required=scanning;
    form.elements.quantity.required=!scanning;
    form.elements.lot_id.required=!scanning;
  });
}

function useStock() {
  const form=formDialog("扫码登记耗用","use",
    input("code","包装码",{maxlength:220,placeholder:"扫描手术室二级库的耗材包装"})
    +input("case_ref","手术／业务号",{maxlength:80})+memo()+help("登记后该包装码扣减库存并进入待对账。同一码不能重复耗用。"),"确认耗用");
  form.elements.code.addEventListener("keydown",event=>{
    if (event.key==="Enter") {event.preventDefault();form.elements.case_ref.focus();}
  });
}

function billingForm(id) {
  const row=state.clinical.find(record=>record.id===id);
  const form=formDialog("计费回执 · "+(row?.ref||""),"billing",
    select("decision","处理结果",pairs(billingStatus,row=>row[0]).filter(([key])=>key!=="pending"&&key!==row?.status),"confirmed")
    +input("billing_ref","外部费用回执号",{maxlength:100})+memo("note","对账备注"),
    "保存回执",values=>({...values,id}));
  form.elements.decision.addEventListener("change",()=>{
    const rejected=form.elements.decision.value==="rejected";
    form.elements.billing_ref.required=!rejected;
    form.elements.note.required=rejected;
  });
}

function newUser() {
  formDialog("新建账号","user",grid(input("username","用户名",{maxlength:60})+input("name","姓名")
    +select("role","业务角色",pairs(roleText).filter(([role])=>role!=="admin"))+input("password","初始密码（至少 12 位）",{type:"password",maxlength:160})),
    "创建账号");
}

function passwordForm() {
  formDialog("更改密码","password",input("current","当前密码",{type:"password",maxlength:160})+input("password","新密码（至少 12 位）",{type:"password",maxlength:160}),
    "更改密码");
}

async function searchTrace(query) {
  const requested={...query};
  const model=await request("/api/trace?"+new URLSearchParams(requested).toString());
  traceRecord=model;
  traceQuery=requested;
  if ($("dialog").open) $("dialog").close();
  if (page!=="trace") go("trace");
  else render();
}

async function refreshTrace() {
  const generation={...traceQuery};
  const result=await request("/api/trace?"+new URLSearchParams(generation).toString());
  if (page!=="trace"||generation.lot!==traceQuery.lot||generation.code!==traceQuery.code) return;
  traceRecord=result;
  render();
}

function tab(name,value) {
  filter={...filterDefaults};
  if (name==="workTab") workTab=value;
  if (name==="masterTab") masterTab=value;
  if (name==="stockTab") stockTab=value;
  render();
}

const handlers = {
  ...exerciseHandlers,
  ...exerciseDemoHandlers,
  go:async id=>{go(id);if(id==="exercise"&&page===id) await loadExercise();},goStock:tab=>{stockTab=tab;go("stock");},
  workTab:value=>tab("workTab",value),stockTab:value=>tab("stockTab",value),masterTab:value=>tab("masterTab",value),
  newTrade,newBom:newBOM,newWork,newMaster,newUser,document:openDocument,bomDetail:openBOM,
  receive:value=>tradeLine("receive",value),ship:value=>tradeLine("ship",value),
  review:id=>reviewDocument(id,"approve"),cancelDoc:id=>reviewDocument(id,"cancel"),
  startWork,reportStep,finishWork,inspect:inspectLot,transfer:mode=>transferStock(mode==="clinical"),use:useStock,billing:billingForm,
  lotTrace:id=>searchTrace({lot:id}),codeTrace:code=>searchTrace({code}),closeDialog:()=>$("dialog").close(),
};

function failure(error) {
  if (error.status===401) showLogin();
  notify(error.message,true);
}

document.addEventListener("click",event=>{
  const trigger=event.target.closest("[data-action]");
  if (!trigger || !state) return;
  const handler=handlers[trigger.dataset.action];
  if (handler) Promise.resolve().then(()=>handler(trigger.dataset.value)).catch(failure);
});
document.addEventListener("input",event=>{
  if (event.target.dataset.filter==="q" && state) {
    filter.q=event.target.value;
    updateFiltered();
  }
});
document.addEventListener("change",event=>{
  const filterName=event.target.dataset.filter;
  if (filterName && filterName!=="q" && state) {
    filter[filterName]=event.target.value;
    updateFiltered();
  }
});
document.addEventListener("submit",event=>{
  if (event.target.id!=="trace-form") return;
  event.preventDefault();
  const form=Object.fromEntries(new FormData(event.target));
  if (!form.code.trim()&&!form.lot) {notify("请先选择批次或扫描包装码",true);return;}
  searchTrace(form.code.trim()?{code:form.code.trim()}:{lot:form.lot}).catch(failure);
});
$("dialog-close").addEventListener("click",()=>$("dialog").close());
$("dialog").addEventListener("close",()=>{if (!$("dialog").open) dialogGeneration+=1;});
$("account").addEventListener("click",passwordForm);
$("refresh").addEventListener("click",async ()=>{
  try {
    await loadState();
    if (page==="trace"&&traceRecord) await refreshTrace();
    if (page==="exercise") await loadExercise();
    notify("数据已刷新");
  } catch (error) {failure(error);}
});
$("navigation-toggle").addEventListener("click",()=>{
  const open=$("sidebar").classList.toggle("open");
  $("navigation-toggle").setAttribute("aria-expanded",String(open));
});
$("logout").addEventListener("click",()=>request("/api/logout",{}).then(showLogin).catch(failure));
$("demo-fill").addEventListener("click",()=>{
  const fields=$("login-form").elements;
  fields.username.value="admin";
  fields.username.focus();
});
$("login-form").addEventListener("submit",async event=>{
  event.preventDefault();
  const form=event.currentTarget;
  const button=form.querySelector('button[type="submit"]');
  button.disabled=true;
  $("login-error").hidden=true;
  try {
    await request("/api/login",Object.fromEntries(new FormData(form)));
    await loadState();
    form.reset();
  } catch (error) {
    $("login-error").textContent=error.message;
    $("login-error").hidden=false;
  } finally {button.disabled=false;}
});
(async ()=>{
  try {
    demo=(await request("/api/meta")).demo;
    await loadState();
  } catch (error) {
    if (error.status===401) showLogin();
    else $("starting").textContent=error.message;
  }
})();
