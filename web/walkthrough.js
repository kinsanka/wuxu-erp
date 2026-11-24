"use strict";

const walkthroughSteps = [
  {page:"master", title:"产品与 BOM", note:"从成品料号查 BOM 版本、库存和相关业务单据。"},
  {page:"sale", document:"sale", title:"销售接单", note:"核对客户、订购数量和计划日期。"},
  {page:"purchase", document:"purchase", title:"采购收货", note:"对照采购数量、实收数量和入库批次。"},
  {page:"work", document:"work", title:"生产工单", note:"查看 BOM 版本、工序报工和完工入库流水。"},
  {page:"people", title:"人员与工时", note:"核对工序派工、班组及报工记录。"},
  {page:"stock", title:"批次质检", note:"检查成品批次是否放行，决定它能否用于发货。"},
  {page:"counts", title:"库存盘点", note:"按仓库和批次核对账面实物，查看盘点差异和调整流水。"},
  {page:"sale", document:"sale", title:"销售发货", note:"回到原销售单，核对发货数量和已处理数量。"},
  {page:"transport", title:"运输与签收", note:"已发货的订单可以登记承运运单，再录入签收凭证。"},
  {page:"finance", title:"应收与应付", note:"从签收或合格收货记录登记发票，并核对收付款凭证。"},
  {page:"trace", title:"批次追溯", note:"从成品批次回查上游物料、完工记录和发货流水。"},
];

const practiceSteps = [
  {page:"master",title:"产品与 BOM",note:"打开产品 BOM，核对每套成品需要 2 件毛坯。"},
  {page:"sale",document:"sale",check:"sale",title:"销售审核",note:"确认 4 套支架的原销售单并审核通过。"},
  {page:"purchase",document:"purchase",check:"purchase",title:"采购收货",note:"审核采购单，按行实收 8 件毛坯，填写真实演示批号。"},
  {page:"stock",check:"raw",title:"来料质检",note:"对本案例的收货批次登记检验放行。待检库存无法用于工单领料。"},
  {page:"people",check:"people",title:"班组人员",note:"点击新增人员，用预填工号登记本案例的操作人员。"},
  {page:"work",document:"work",check:"work",title:"派工、生产和完工",note:"审核工单，给两道工序派工，领料开工、依次报工，再登记成品批号。"},
  {page:"stock",check:"quality",title:"成品质检",note:"打开成品批次，填写检验结论并放行。"},
  {page:"counts",check:"counts",title:"库存盘点",note:"登记成品实盘数量。无差异的示例请填写 4 套，补充盘点依据。"},
  {page:"sale",document:"sale",check:"ship",title:"销售发货",note:"从原销售单按行发货 4 套，查看实际扣减的批次。"},
  {page:"transport",check:"transport",title:"承运与签收",note:"登记承运商和运单号，然后用签收凭证确认客户到货。"},
  {page:"finance",document:"purchase",check:"finance_purchase",title:"采购应付",note:"为 8 件毛坯登记发票，再登记付款单并完成核销。"},
  {page:"finance",document:"sale",check:"finance_sale",title:"销售应收",note:"为签收的 4 套成品登记发票，再登记收款单并完成核销。"},
  {page:"trace",title:"批次追溯",note:"从本案例成品回查来料批次、完工工单和发货记录。"},
];

let walkthrough = null;
let launchingPractice = false;

function walkthroughDocument() {
  const step = walkthrough.steps[walkthrough.index];
  return step?.page===page && step.page!=="finance" ? walkthrough.targets[step.document]?.id : null;
}

function renderWalkthrough() {
  const step = walkthrough?.steps[walkthrough.index];
  let content = "";
  if (step) {
    const {index, loading, steps} = walkthrough;
    const last = index===steps.length-1;
    const ready = !step.check || walkthrough.targets.ready?.[step.check];
    const result = step.check ? (ready?" · 已完成":" · 待办理") : "";
    content = `<div class="walkthrough-copy" aria-live="polite"><strong>${index+1}/${steps.length} · ${html(step.title+result)}</strong><p>${html(step.note)}</p></div>
      <div class="actions">
        <button type="button" class="button" data-action="walkthroughPrevious"${index===0||loading?" disabled":""}>上一步</button>
        ${last?button("结束演示","walkthroughEnd","","primary"):`<button type="button" class="button primary" data-action="walkthroughNext"${loading||!ready?" disabled":""}>下一步</button>${button("退出演示","walkthroughEnd")}`}
      </div>`;
  }
  for (const id of ["walkthrough", "dialog-walkthrough"]) {
    const region = $(id);
    if (!region) continue;
    region.hidden = !step;
    region.innerHTML = content;
  }
}

function endWalkthrough() {
  walkthrough = null;
  renderWalkthrough();
}

function openGuidedDetail(title,body) {
  const active=walkthrough?.index>=0;
  const guide=active?'<section id="dialog-walkthrough" class="walkthrough" aria-label="逐步演示"></section>':"";
  openDialog(title,guide+body);
  if (active) renderWalkthrough();
}

async function startWalkthrough() {
  if (walkthrough || launchingPractice) return;
  const targets = await request("/api/walkthrough");
  if (!targets.practice_allowed) {
    await beginWalkthrough(targets);
    return;
  }
  openDialog("工业实操演示",help("每个新案例使用独立演示仓、料号和单据。审核、收货、领料、报工等操作在相应模块提交。")
    +`<div class="form-actions">${targets.latest?button("继续上次实操","resumePractice",targets.latest.id):""}${button("新建实操案例","launchPractice","","primary")}</div>`);
}

async function beginWalkthrough(targets,resume=false) {
  const steps = (targets.run_id?practiceSteps:walkthroughSteps).filter(step=>showNav(step.page));
  walkthrough = {index:-1,targets,steps,loading:false};
  const next = resume?steps.findIndex(step=>step.check&&!targets.ready[step.check]):0;
  await moveWalkthrough(next<0?steps.length-1:next);
}

async function refreshWalkthroughProgress() {
  const session = walkthrough;
  if (!session?.targets.run_id) return;
  const targets = await request("/api/walkthrough?run="+encodeURIComponent(session.targets.run_id));
  if (walkthrough!==session) return;
  session.targets=targets;
  renderWalkthrough();
}

async function launchPractice(id="") {
  if (launchingPractice || walkthrough) return;
  launchingPractice = true;
  try {
    const run = id || (await request("/api/action/practice",{},requestKey())).id;
    const targets = await request("/api/walkthrough?run="+encodeURIComponent(run));
    await loadState();
    await beginWalkthrough(targets,!!id);
  } finally {
    launchingPractice = false;
  }
}

async function moveWalkthrough(index) {
  const session = walkthrough;
  const step = session?.steps[index];
  if (!session || session.loading || !step) return;
  session.loading = true;
  renderWalkthrough();
  try {
    const dialog = $("dialog");
    if (dialog.open) {
      const closed = new Promise(resolve=>dialog.addEventListener("close",resolve,{once:true}));
      dialog.close();
      await closed;
    }
    if (walkthrough!==session) return;
    session.index = index;
    const {batch, product, raw, sale, worker_code} = session.targets;
    if (step.page==="master") masterTab = "items";
    if (step.page==="work") workTab = "docs";
    if (step.page==="stock") stockTab = "inspection";
    if (step.page==="trace") {
      traceRecord = null;
      traceQuery = {};
    }
    const searches = {
      stock:step.check==="raw"?raw?.code:batch?.code,master:product?.code,
      people:worker_code,counts:batch?.code,transport:session.targets.run_id?sale?.ref:undefined,
      finance:session.targets[step.document]?.ref,
    };
    go(step.page,searches[step.page]);
    renderWalkthrough();
    const isCurrent = ()=>walkthrough===session && page===step.page;
    const id = walkthroughDocument();
    if (id) await openDocument(id,isCurrent);
    if (step.page==="master" && product) await itemDetail(product.id,isCurrent);
    if (step.page==="trace" && batch) await searchTrace({lot:batch.id},isCurrent);
    if (Object.hasOwn(industryRoles,step.page)) await loadIndustry(step.page);
  } finally {
    if (walkthrough===session) {
      session.loading = false;
      renderWalkthrough();
    }
  }
}

const walkthroughHandlers = {
  walkthroughStart: startWalkthrough,
  launchPractice: ()=>launchPractice(),
  resumePractice: launchPractice,
  walkthroughPrevious: ()=>moveWalkthrough(walkthrough?.index-1),
  walkthroughNext: ()=>{
    const step=walkthrough?.steps[walkthrough.index];
    if (!step?.check || walkthrough.targets.ready[step.check]) return moveWalkthrough(walkthrough?.index+1);
  },
  walkthroughEnd: ()=>{
    endWalkthrough();
    if (page==="home" || page==="exercise") render();
  },
};
