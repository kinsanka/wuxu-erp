"use strict";

const $ = id => document.getElementById(id);
const html = value => String(value ?? "").replace(/[&<>"']/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[character]);
const number = new Intl.NumberFormat("zh-CN", {maximumFractionDigits: 3});
const money = new Intl.NumberFormat("zh-CN", {style:"currency",currency:"CNY"});
const qty = value => number.format(value / 1000);
const clean = value => value ? html(value) : "—";
const timestamp = value => value ? new Date(value).toLocaleString("zh-CN", {hour12:false}) : "—";
const roleText = {admin:"管理员",planner:"采购／计划",warehouse:"仓储／质检",viewer:"只读"};
const kindText = {purchase:"采购单",sale:"销售单",work:"生产工单",material:"原料／组件",product:"制成品",factory:"工业仓",vendor:"供应商",customer:"客户",both:"供应商兼客户"};
const docStatus = {draft:["草稿",""],approved:["已审核","blue"],partial:["部分处理","amber"],running:["生产中","blue"],done:["已完成","green"],cancelled:["已取消",""]};
const lotStatus = {pending:["待检／隔离","amber"],released:["已放行","green"],blocked:["已冻结","red"]};
const rights = {
  master:["planner"], purchase:["planner"], sale:["planner"], approve:["planner"], receive:["warehouse"],
  ship:["warehouse"], bom:["planner"], work:["planner"], start:["planner"], report:["planner"], finish:["planner"],
  inspect:["warehouse"], transfer:["warehouse"], expedite:["planner"], revise_delivery:["planner"], user:[],
  reserve_stock:["planner"],schedule_work:["planner"],delivery_commitment:["planner"],
  link_supply:["planner"], assign_step:["planner"],
};
const navigation = [
  ["概览", [["home","工作台","⌂"]]],
  ["订单与交付", [["sale","销售履约","↗"],["expedite","急单处理","!"],["purchase","采购管理","↙"],["transport","运输与签收","→"]]],
  ["计划与生产", [["work","生产与 BOM","▦"],["capacity","产线排程","▥"],["people","人员与工时","◫"]]],
  ["库存管理", [["stock","库存与质检","◇"],["counts","库存盘点","▤"],["trace","批次追溯","◎"]]],
  ["财务与基础资料", [["finance","应收应付","¥"],["master","主数据","≡"],["reports","报表与审计","▤"],["users","账号管理","☷"]]],
];
const pages = Object.fromEntries(navigation.flatMap(([,entries])=>entries.map(([id,label])=>[id,label])));
const filterDefaults = {status:"", site:"", q:""};
let state = null;
let demo = false;
let demoAccount = null;
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
const allowed = action => {
  const account=state?.account;
  if (account?.is_demo && ["user","password"].includes(action)) return false;
  return account?.role === "admin" || (rights[action] || []).includes(account?.role);
};
const showNav = id => {
  if (id==="users") return allowed("user");
  if (Object.hasOwn(industryRoles,id)) return state?.account.role==="admin" || industryRoles[id].includes(state?.account.role);
  return true;
};

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

function recentMovement(records,linkDocuments=true) {
  return table(["业务","物料／批次","仓库","变动","单据","时间"],records,row=>[
    bold(row.kind),item(row.item_name,row.lot),text(row.site_name),numeric((row.quantity>0?"+":"")+qty(row.quantity)+" "+row.unit),
    linkDocuments&&row.doc_id?link(row.ref,"document",row.doc_id):code(row.ref),text(timestamp(row.created)),
  ]);
}

function metric(title,value,hint,target,icon,style="",action="go") {
  return `<button type="button" class="metric" data-action="${html(action)}" data-value="${html(target)}"><span class="metric-top">${html(title)}<span class="metric-icon ${html(style)}" aria-hidden="true">${html(icon)}</span></span><strong>${html(value)}</strong><small>${html(hint)}</small></button>`;
}

function notices(records,render) {
  return records.length ? `<div class="notice-list">${records.map(render).join("")}</div>` : '<p class="empty">暂无预警</p>';
}

function homePage() {
  const model=state.summary;
  const open=model.factory_open;
  const cards = [
    metric("待收货采购",open.purchase||0,"已审核或待收货","purchase","↙"),
    metric("执行中工单",open.work||0,"待领料或生产中","work","▦","blue"),
    metric("待检在库批次",model.factory_pending,"待质检放行","inspection","◇","amber","goStock"),
    metric("待发货销售",open.sale||0,"已审核或部分发货","sale","↗","blue"),
  ].join("");
  const expiry=notices(model.expiry.slice(0,5),row=>`<div class="notice-row"><div>${link(row.name,"lotTrace",row.lot_id)}${sub(row.site_name+" · "+row.lot)}</div>${cfgLabel({e:[row.days_left<0?`过期 ${Math.abs(row.days_left)} 天`:`剩余 ${row.days_left} 天`,row.days_left<0?"red":"amber"]},"e")}</div>`);
  const low=notices(model.low.slice(0,5),row=>`<div class="notice-row"><div>${bold(row.name)}${sub(row.code+" · 补货点 "+qty(row.minimum)+" "+row.unit)}</div>${numeric(qty(row.available)+" "+row.unit)}</div>`);
  return head("工业运营总览","追踪工厂仓的采购、生产、质检与销售交付。",
      allowed("purchase")?button("＋ 新建采购单","newTrade","purchase"):"")
    + `<div class="metrics">${cards}</div><div class="board"><div class="stack">${panel("交期待办",docsTable(model.factory_due,true),"","工厂仓开放单据，按计划日期排序")}${panel("最近单据",docsTable(model.recent,true))}${panel("最近出入库",recentMovement(state.movements.slice(0,6)),button("库存流水","goStock","movements","small"))}</div><div class="stack">${panel("60 天效期预警",expiry,button("查看库存","goStock","stock","small"))}${panel("低于补货点",low,"","按全仓可用批次汇总")}</div></div>`;
}

function workPage() {
  const isDocs = workTab!=="boms";
  const stages={review:"draft",launch:"approved",running:"running",done:"done"};
  const rows = isDocs ? state.documents.filter(row=>row.kind==="work" && (!stages[workTab]||row.status===stages[workTab]) && matches(row.ref,row.site_name,row.version,row.note) && (!filter.status||row.status===filter.status))
    : state.boms.filter(row=>matches(row.code,row.name,row.version));
  const tableView=isDocs ? docsTable(rows) : table(["成品","BOM 版本","创建时间"],rows,row=>[
    item(row.name,row.code),link(row.version,"bomDetail",row.id),text(timestamp(row.created)),
  ]);
  return head("生产与 BOM","管理物料清单版本，核算工单缺料，按工序完成报工。",
    (allowed("bom")?button("＋ 新建 BOM","newBom"):"")+(allowed("work")?button("＋ 新建工单","newWork","","primary"):""))
    + `<section class="panel">${tabs("workTab",workTab,[["docs","生产工单"],["review","待审核"],["launch","待领料开工"],["running","在制工单"],["done","完工工单"],["boms","物料清单"]])}${filters({status:workTab==="docs"?pairs(docStatus,x=>x[0]):[]})}<div id="filtered">${tableView}</div></section>`;
}

function stockPage() {
  const bar = allowed("transfer") ? button("⇄ 库存调拨","transfer","","primary") : "";
  const tabList = [["stock","库存明细"],["inspection","批次质检"],["movements","出入库流水"],["transfers","调拨记录"]];
  let body, params={};
  if (stockTab==="stock") {
    const stocks=state.stock.filter(row=>matches(row.code,row.name,row.lot,row.site_name) && (!filter.site||filter.site===row.site_id) && (!filter.status||filter.status===row.status));
    const countAllowed=showNav("counts");
    body=table(["物料","仓库","批次","实物在库","已锁定","未锁可用","效期","质检状态",...(countAllowed?["盘点"]:[])],stocks,row=>[
      item(row.name,row.code),text(row.site_name),link(row.lot,"lotTrace",row.lot_id),unitQuantity(row.quantity,row.unit),
      unitQuantity(row.reserved,row.unit),unitQuantity(row.status==="released"&&!isExpired(row)?row.quantity-row.reserved:0,row.unit),
      dateText(row),cfgLabel(lotStatus,row.status),
      ...(countAllowed?[button("盘点","inventoryCount",row.lot_id+"|"+row.site_id,"small")]:[]),
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
  } else {
    body=recentMovement(state.movements.filter(row=>(stockTab!=="transfers"||row.kind.startsWith("调拨"))
      &&matches(row.ref,row.lot,row.item_code,row.item_name,row.kind,row.site_name)&&(!filter.site||filter.site===row.site_id)));
    params={sites:true,actions:exportLink("导出完整流水","movements")};
  }
  return head("库存与质检","查看批次、仓库、余量与效期，处理调拨、隔离、放行和冻结。",bar)
    + `<section class="panel">${tabs("stockTab",stockTab,tabList)}${filters(params)}<div id="filtered">${body}</div></section>`;
}

function tracePage() {
  const form = `<form id="trace-form" class="toolbar"><div class="filters"><select id="trace-lot" name="lot" aria-label="选择批次">${options([["","选择物料批次"],...lotOptions()],traceQuery.lot||"")}</select><input type="search" name="code" maxlength="220" aria-label="包装码" value="${html(traceQuery.code||"")}" placeholder="或扫描包装码"></div><button class="button primary">查询追溯</button></form>`;
  const content=[head("批次追溯","查询采购来源、生产投入产出和调拨流向。"),`<section class="panel">${form}</section>`];
  if (!traceRecord) return content.join("");
  const {lot,unit,upstream,downstream,movements,stock,truncated}=traceRecord;
  const related=(label,lots)=>panel(label,table(["批次","物料","状态","效期"],lots,row=>[
    link(row.code,"lotTrace",row.id),item(row.name,row.item_code),cfgLabel(lotStatus,row.status),dateText(row),
  ]));
  const onHand=table(["仓库","余额"],stock,row=>[text(row.site_name),numeric(qty(row.quantity)+" "+row.unit)]);
  const events=unit ? movements.filter(row=>row.detail.includes(unit.code) || row.kind==="收货" || row.kind==="生产完工") : movements;
  content.push(`<div class="panel separate"><div class="panel-heading"><div><h2>${html(lot.code)} · ${html(lot.item_name)}</h2><p>${unit?html(unit.code+" · "+(unit.location||"已耗用")):html(lot.item_code)}</p></div><div class="actions">${cfgLabel(lotStatus,lot.status)}${allowed("inspect")?button("检验／冻结","inspect",lot.id,"small"):""}</div></div>${onHand}</div>`,
    `<div class="board trace-board"><div class="stack">${panel(unit?"包装码和批次流水":"批次流水",recentMovement(events),"","最多显示最近 500 条批次流水")}</div><div class="stack">${related("上游投入批次",upstream)}${related("下游产出批次",downstream)}${truncated?'<p class="form-hint">上游或下游超过 1,000 个批次，结果已截取。</p>':""}</div></div>`);
  return content.join("");
}

function masterPage() {
  const selected = state[masterTab].filter(row=>matches(row.code,row.name,row.type));
  let view;
  if (masterTab==="items") view = table(["物料","分类","单位","补货点","入库质检","一码一物","GTIN"],selected,row=>[
    link(row.name,"itemDetail",row.id)+sub(row.code),text(kindText[row.type]),text(row.unit),numeric(qty(row.minimum)),text(row.quality ? "需要":"—"),text(row.tracked?"启用":"—"),code(row.gtin||"—"),
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
    exportLink("库存","stock")+exportLink("流水","movements")+(allowed("user")?exportLink("审计","audit"):""))
    + `<div class="stack">${panel("分仓库存",counts)}${panel("低库存明细",table(["物料","可用库存","补货点"],model.low,row=>[
      item(row.name,row.code),numeric(qty(row.available)+" "+row.unit),numeric(qty(row.minimum)+" "+row.unit),
    ]))}${allowed("user")?panel("操作审计",auditRows,"","显示最近 200 条，完整数据可导出"):""}</div>`;
}

function usersPage() {
  return head("账号管理","为采购计划和仓储质检岗位分配操作角色。",button("＋ 新建账号","newUser","","primary"))
    + panel("用户列表",table(["姓名","用户名","角色","状态"],state.users,row=>[
      bold(row.name),code(row.username),text(roleText[row.role]),cfgLabel({1:["启用","green"],0:["停用",""]},row.enabled),
    ]));
}

const renderers={home:homePage,purchase:()=>ordersPage("purchase"),sale:()=>ordersPage("sale"),expedite:expeditePage,work:workPage,stock:stockPage,trace:tracePage,master:masterPage,reports:reportsPage,users:usersPage,
  transport:()=>industryPage("transport"),people:()=>industryPage("people"),finance:()=>industryPage("finance"),counts:()=>industryPage("counts"),capacity:capacityPage};

function render() {
  $("crumb").textContent=pages[page];
  $("business-date").textContent=state.today;
  $("mode").hidden=!demo;
  $("account").innerHTML=`<span class="avatar">${html(state.account.name.slice(0,1))}</span><span>${html(state.account.name)}<small>${html(state.account.is_demo?"演示账号":roleText[state.account.role])}</small></span>`;
  $("account").disabled=!!state.account.is_demo;
  $("account").title=state.account.is_demo?"演示账号":"更改密码";
  $("nav").innerHTML=navigation.map(([label,entries])=>`<div class="nav-label">${html(label)}</div>${entries.filter(([id])=>showNav(id)).map(([id,name,icon])=>
    `<button type="button" class="nav-item ${page===id?"active":""}" data-action="go" data-value="${id}"${page===id?' aria-current="page"':""}><span class="nav-icon" aria-hidden="true">${html(icon)}</span>${html(name)}</button>`
  ).join("")}`).join("");
  $("main").innerHTML=renderers[page]();
  $("demo-launch").hidden=!demo||!!walkthrough;
}

function updateFiltered() {
  const target=$("filtered");
  if (!target) return;
  const template=document.createElement("template");
  template.innerHTML=renderers[page]();
  target.innerHTML=template.content.querySelector("#filtered").innerHTML;
}

function go(id,search="") {
  if (!Object.hasOwn(pages,id) || !showNav(id)) return;
  page=id;
  filter={...filterDefaults,q:search};
  $("sidebar").classList.remove("open");
  $("navigation-toggle").setAttribute("aria-expanded","false");
  render();
  window.scrollTo(0,0);
  $("main").focus({preventScroll:true});
}

async function syncPageData() {
  if (page==="capacity") await loadProduction();
  if (Object.hasOwn(orderTabs,page)) await loadOrders(page);
  if (Object.hasOwn(industryRoles,page)) await loadIndustry(page);
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
  endWalkthrough();
  productionView=null;
  capacityDay="";
  for (const module of Object.keys(industryViews)) delete industryViews[module];
  state=null;
  traceRecord=null;
  for(const module of Object.keys(orderViews)) delete orderViews[module];
  traceQuery={};
  page="home";
  filter={...filterDefaults};
  $("starting").hidden=true;
  $("app").hidden=true;
  $("login-screen").hidden=false;
  if ($("dialog").open) $("dialog").close();
  const form=$("login-form");
  form.reset();
  const {username,password}=form.elements;
  $("login-error").hidden=true;
  $("login-title").textContent=demoAccount?"登录演示工作台":"登录工作台";
  username.readOnly=password.readOnly=!!demoAccount;
  if (demoAccount) {
    username.value=demoAccount.username;
    password.value=demoAccount.password;
    form.querySelector('button[type="submit"]').focus();
  } else {
    username.focus();
  }
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
      await syncPageData();
      await refreshWalkthroughProgress();
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
  const sites=state.sites;
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
  openGuidedDetail("物料清单 · "+(bom?.name||model.version),
    `<div class="detail-meta">版本 ${html(model.version)} · ${html(timestamp(model.created))}</div>`
    + section("组件",table(["物料","单位成品用量"],model.lines,row=>[item(row.name,row.code),numeric(qty(row.quantity)+" "+row.unit)]))
    + section("工序",table(["顺序","工序名称"],model.steps,row=>[numeric(row.step_no),text(row.name)])));
}

function newMaster(entity) {
  const isItem=entity==="items";
  const title={items:"物料",sites:"仓库",partners:"往来单位"}[entity];
  const types={items:["material","product"],sites:["factory"],partners:["vendor","customer","both"]}[entity];
  const basics=input("code",title+"编码",{maxlength:48})+input("name",title+"名称")
    + select("type","分类",types.map(key=>[key,kindText[key]]));
  const detail=isItem?input("unit","计量单位",{maxlength:12,placeholder:"例如 件、kg、套"})
    + input("minimum","补货点",{type:"number",value:"0",min:"0",step:"0.001"})
    + checkbox("quality","到货需质检")
    : entity==="partners"?input("contact","联系信息",{required:false}):"";
  formDialog("新增"+title,"master",grid(basics+detail),
    "保存资料",values=>({...values,entity,quality:values.quality==="1"}));
}

async function openDocument(id, isCurrent=()=>true) {
  const version=++dialogGeneration;
  const model=await request("/api/document/"+encodeURIComponent(id));
  if (version!==dialogGeneration || !isCurrent()) return;
  const reviewable=["draft","approved"].includes(model.status);
  const tradable=model.kind!=="work" && ["approved","partial"].includes(model.status);
  const action=model.kind==="purchase"?"receive":"ship";
  const header=`<div class="detail-meta">${cfgLabel(docStatus,model.status)}<span>${html(model.site_name)}</span>${model.partner_name?`<span>${html(model.partner_name)}</span>`:""}<span>计划日期 ${clean(model.due)}</span>${model.version?link("BOM "+model.version,"bomDetail",model.bom_id):""}</div>`;
  const actions=[];
  if (reviewable && allowed("approve")) {
    if (model.status==="draft") actions.push(button("审核通过","review",id,"primary"));
    actions.push(button("取消单据","cancelDoc",id,"danger"));
  }
  if (model.status==="approved" && model.kind==="work" && allowed("start")) actions.push(button("领料并开工","startWork",id,"primary"));
  if (model.status==="running" && allowed("finish")) actions.push(button("完工待检","finishWork",id,"primary"));
  if (model.kind!=="sale" && !["done","cancelled"].includes(model.status) && allowed("revise_delivery"))
    actions.push(button(model.kind==="purchase"?"更新预计到货":"调整计划完工","reviseDelivery",id));
  const work=model.kind==="work";
  const lines=section("明细",table(["物料","计划","已处理",...(work?[]:["单价"]),...(tradable&&allowed(action)?["处理"]:[])],model.lines,row=>[
    item(row.name,row.code),numeric(qty(row.quantity)+" "+row.unit),numeric(qty(row.fulfilled)+" "+row.unit),
    ...(work?[]:[numeric(money.format(row.price/100))]),
    ...(tradable&&allowed(action)?[row.fulfilled<row.quantity?button(action==="receive"?"收货":"发货",action,id+"|"+row.id,"small"):"—"]:[]),
  ]));
  const sections=[];
  if (model.note) sections.push(`<p class="detail-note">${html(model.note)}</p>`);
  sections.push(lines);
  if (work) sections.push(scheduleSection(model));
  if (model.kind!=="purchase") sections.push(reservationSection(model));
  if (work && model.plan.length) sections.push(section("单阶缺料试算",help("基于当前仓库的可用库存试算。预计净缺扣除工单日期窗口内的计划采购量，实际领料以收货放行后的可用量为准。")
    + table(["组件","需求","当前可用","窗口内计划采购","当前缺料","预计净缺料","已请购草稿","处理"],model.plan,row=>[
      item(row.name,row.code),unitQuantity(row.required,row.unit),unitQuantity(row.available,row.unit),unitQuantity(row.incoming,row.unit),
      unitQuantity(row.shortage,row.unit),unitQuantity(row.net,row.unit),unitQuantity(row.draft,row.unit),
      row.net>row.draft&&allowed("purchase")?button("生成采购草稿","purchaseShortage",id+"|"+row.item_id,"small"):"—",
    ])));
  if (work && model.plan.some(row=>row.shortage>0)) {
    const sources=model.plan.filter(row=>row.shortage>0).flatMap(row=>row.purchases.map(source=>({...source,name:row.name,unit:row.unit})));
    const schedules={scheduled:["窗口内计划","green"],late:["晚于工单","amber"],overdue:["采购逾期","red"],undated:["待确认日期","amber"]};
    sections.push(section("缺料采购单",table(["组件","采购单","供应商","待收量","计划到货","交期判断"],sources,row=>[
      bold(row.name),link(row.ref,"document",row.id),text(row.supplier),unitQuantity(row.remaining,row.unit),clean(row.due),cfgLabel(schedules,row.schedule),
    ],"暂无同仓、已审核且有未收余量的采购单。")));
  }
  if (work && model.steps.length) {
    const next=model.steps.find(row=>row.minutes===null)?.id;
    sections.push(section("工序派工与报工",table(["工序","派工人员","实报工时","记录人","处理"],model.steps,row=>[
      bold(row.step_no+" · "+row.name),row.person?item(row.person,row.person_code):"—",row.minutes===null?"—":text(row.minutes+" 分钟"),clean(row.actor),
      `<div class="actions">${row.minutes===null&&["draft","approved","running"].includes(model.status)&&allowed("assign_step")?button(row.person?"调整派工":"派工","assignStep",id+"|"+row.id,"small"):""}
        ${row.id===next&&model.status==="running"&&allowed("report")?button("报工","reportStep",id+"|"+row.id,"small"):""}</div>`,
    ])));
  }
  if (model.kind==="sale") {
    actions.push(button("急单跟进","expediteDetail",id));
    sections.push(salesProgress(model));
    sections.push(commitmentSection(model));
  }
  if (model.kind==="purchase") sections.push(purchaseProgress(model));
  if (model.linked.length || ((work || model.kind==="sale") && allowed("link_supply") && model.status!=="cancelled")) sections.push(supplyChain(model));
  if (model.delivery_revisions.length) sections.push(section("计划日期变更",table(["原日期","新日期","调整依据","记录人","记录时间"],
    model.delivery_revisions,row=>[clean(row.previous_due),text(row.new_due),text(row.reason),text(row.actor),text(timestamp(row.created))])));
  if (model.movements.length) sections.push(section("库存流水",recentMovement(model.movements,false)));
  openGuidedDetail(kindText[model.kind]+" · "+model.ref,header
    +(actions.length?`<div class="actions">${actions.join("")}</div>`:"")+sections.join(""));
}

async function tradeLine(kind,serial) {
  const [id,lineId]=serial.split("|");
  const model=await request("/api/document/"+encodeURIComponent(id));
  const line=model.lines.find(row=>row.id===lineId);
  if (!line) throw new Error("单据行不存在");
  const receive=kind==="receive";
  const available=line.quantity-line.fulfilled;
  const planned=receive?[]:model.commitments.filter(row=>row.line_id===lineId&&!row.cancelled);
  const open=planned.filter(row=>row.quantity>row.shipped);
  if(planned.length&&!open.length) {
    openDialog("销售发货",help("已登记的承诺均已出库。请在原销售单为剩余数量新增交付批次。")
      +button("返回销售单","document",id));
    return;
  }
  const promiseField=open.length?select("commitment_id","交付批次",pick(open,row=>row.ref+" · "+row.due
    +" · 待发 "+qty(row.quantity-row.shipped)+" "+row.unit),open[0].id):"";
  const demoLot=walkthrough?.targets.run_id&&walkthrough.targets.purchase.id===id?walkthrough.targets.code+"-RM01":"";
  const receiveFields=receive?input("lot","收货批号",{maxlength:64,value:demoLot})+input("expiry","效期",{type:"date",required:false,min:state.today}):"";
  const codes=receive&&line.tracked?memo("codes","包装码（一行一码）",true,"扫描枪或手动输入，每件一个唯一包装码",12000):"";
  const form=formDialog((receive?"采购收货":"销售发货")+" · "+line.name,kind,
    help("待处理 "+qty(available)+" "+line.unit+(receive?"":"。先使用本单锁定批次，再按效期使用未锁库存。"))
    +grid(promiseField+input("quantity","本次数量",{type:"number",min:line.tracked?"1":"0.001",step:line.tracked?"1":"0.001",max:String(available/1000)})+receiveFields)
    +codes+memo(),receive?"确认收货":"确认发货",
    values=>({...values,id,line_id:lineId}),()=>openDocument(id),id);
  if(open.length) {
    const limit=()=>{
      const row=open.find(entry=>entry.id===form.elements.commitment_id.value);
      form.elements.quantity.max=String((row?row.quantity-row.shipped:available)/1000);
    };
    form.elements.commitment_id.addEventListener("change",limit);
    limit();
  }
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
  const demoLot=walkthrough?.targets.run_id&&walkthrough.targets.work.id===id?walkthrough.targets.code+"-FG01":"";
  formDialog("生产完工","finish",grid(input("lot","新成品批号",{maxlength:64,value:demoLot})+input("expiry","效期",{type:"date",min:state.today,required:false}))+memo()+help("完工后成品进入待检状态，需放行后才可发货。"),
    "提交完工",values=>({...values,id}),()=>openDocument(id),id);
}

function inspectLot(id) {
  const lot=state.lots.find(row=>row.id===id);
  if (!lot) throw new Error("批次不存在");
  formDialog("质检与冻结 · "+lot.code,"inspect",
    select("verdict","处置结果",pairs(lotStatus,x=>x[0]).filter(([key])=>key!==lot.status))
    +memo("note","检验结论或冻结原因",true)+help("状态会影响该批次在所有仓库的发货、调拨和生产。"),
    "保存处置",values=>({...values,lot_id:id}));
}

function transferStock() {
  const lots=state.lots.filter(row=>!row.tracked);
  formDialog("仓库调拨","transfer",
    grid(select("from_id","调出仓",siteOptions())+select("to_id","调入仓",siteOptions()))
    +grid(select("lot_id","批次",lotOptions(lots))+quantity("调拨数量"))
    +help("调拨成功后，同一事务登记出库与入库。"),"确认调拨");
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

async function searchTrace(query, isCurrent=()=>true) {
  const requested={...query};
  const model=await request("/api/trace?"+new URLSearchParams(requested).toString());
  if (!isCurrent()) return;
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
  ...orderHandlers,
  ...executionHandlers,
  ...walkthroughHandlers,
  ...industryHandlers,
  go:async id=>{
    if (!showNav(id)) return;
    if ($("dialog").open) $("dialog").close();
    go(id);
    await syncPageData();
  },goStock:tab=>{stockTab=tab;go("stock");},
  workTab:value=>tab("workTab",value),stockTab:value=>tab("stockTab",value),masterTab:value=>tab("masterTab",value),
  industryTab:value=>{industryTabs[page]=value;filter={...filterDefaults};render();},
  newTrade,newBom:newBOM,newWork,newMaster,newUser,document:openDocument,bomDetail:openBOM,
  receive:value=>tradeLine("receive",value),ship:value=>tradeLine("ship",value),
  review:id=>reviewDocument(id,"approve"),cancelDoc:id=>reviewDocument(id,"cancel"),
  startWork,reportStep,finishWork,inspect:inspectLot,transfer:transferStock,
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
  if(event.target.id==="capacity-day"&&state&&event.target.value) {
    capacityDay=event.target.value;
    loadProduction().catch(failure);
    return;
  }
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
    await syncPageData();
    await refreshWalkthroughProgress();
    notify("数据已刷新");
  } catch (error) {failure(error);}
});
$("navigation-toggle").addEventListener("click",()=>{
  const open=$("sidebar").classList.toggle("open");
  $("navigation-toggle").setAttribute("aria-expanded",String(open));
});
$("logout").addEventListener("click",()=>request("/api/logout",{}).then(showLogin).catch(failure));

$("login-form").addEventListener("submit",async event=>{
  event.preventDefault();
  const form=event.currentTarget;
  const button=form.querySelector('button[type="submit"]');
  if (button.disabled) return;
  button.disabled=true;
  $("login-error").hidden=true;
  try {
    await request("/api/login",Object.fromEntries(new FormData(form)));
    await loadState();
    form.reset();
  } catch (error) {
    $("login-error").textContent=error.message;
    $("login-error").hidden=false;
  } finally {
    button.disabled=false;
  }
});
(async ()=>{
  try {
    const meta=await request("/api/meta");
    demo=meta.demo;
    demoAccount=meta.demo_account||null;
    await loadState();
  } catch (error) {
    if (error.status===401) showLogin();
    else $("starting").textContent=error.message;
  }
})();
