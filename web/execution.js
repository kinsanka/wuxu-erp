"use strict";

const commitmentStatus={
  open:["待发货","blue"],transit:["部分发货／待签收","blue"],overdue:["承诺逾期","red"],
  signed:["按期签收","green"],late:["延迟签收","amber"],cancelled:["已撤销",""],
};
let productionView=null;
let capacityDay="";

function clockMinutes(value) {
  return String(Math.floor(value/60)).padStart(2,"0")+":"+String(value%60).padStart(2,"0");
}

async function loadProduction() {
  const day=capacityDay||state.today;
  const result=await request("/api/execution/production?day="+encodeURIComponent(day));
  if(page!=="capacity"||(capacityDay||state.today)!==day) return;
  productionView=result;
  render();
}

function capacityPage() {
  const view=productionView;
  if(!view) return head("产线排程","正在读取生产日历。");
  const manage=allowed("schedule_work");
  const heading=head("产线排程","用工单占用的时段检查同一产线的冲突。",manage?button("＋ 新增产线","newProductionLine","","primary"):"");
  return heading+panel("生产日历",`<div class="toolbar"><div class="filters"><label>排程日期
    <input id="capacity-day" type="date" value="${html(capacityDay||view.day)}"></label></div>
    <div class="actions">${button("查看工单","go","work")}</div></div>`
    +table(["产线","供料仓","生产时段","可用分钟","已排分钟","剩余分钟",...(manage?["日历"]:[])],view.lines,row=>{
      const booked=view.slots.filter(x=>x.line_id===row.id).reduce((total,x)=>total+x.minutes,0);
      return [item(row.name,row.code),text(row.site),row.day_capacity?text(clockMinutes(row.shift_start)+"–"+clockMinutes(row.shift_start+row.day_capacity)):"停产",
        numeric(row.day_capacity),numeric(booked),numeric(row.day_capacity-booked),
        ...(manage?[view.day>=state.today?button("调整当日班次","editProductionCalendar",row.id,"small"):"—"]:[])];
    }))+panel("工单时段",table(["工单","产线","开始","结束","占用分钟","状态","计划完工日"],view.slots,row=>[
      link(row.ref,"document",row.doc_id),text(view.lines.find(x=>x.id===row.line_id)?.name),
      code(clockMinutes(row.start_minute)),code(clockMinutes(row.start_minute+row.minutes)),numeric(row.minutes),cfgLabel(docStatus,row.status),clean(row.due),
    ]));
}

function newProductionLine() {
  formDialog("新增产线","production_line",grid(
    input("code","产线编码",{maxlength:40})+input("name","产线名称",{maxlength:100})
    +select("site_id","供料仓",siteOptions())+input("shift_start","日常班次开始",{type:"time",value:"08:00"})
    +input("capacity","班次可用分钟",{type:"number",min:"1",max:"1440",step:"1",value:"480"})),
    "保存产线");
}

function editProductionCalendar(line_id) {
  const line=productionView.lines.find(row=>row.id===line_id);
  if(!line) return;
  const day=productionView.day;
  formDialog("当日班次 · "+line.name,"line_calendar",
    help(day+" · "+clockMinutes(line.shift_start)+" 开始，填 0 表示停产。")
    +input("capacity","可用分钟",{type:"number",min:"0",max:String(1440-line.shift_start),step:"1",value:String(line.day_capacity)})
    +memo("note","变更依据",true),"保存当日班次",values=>({...values,line_id,day}));
}

function scheduleSection(model) {
  const slot=model.slot;
  const manage=allowed("schedule_work")&&["draft","approved"].includes(model.status);
  return section("产线时段",(slot?help(slot.code+" · "+slot.name+" · "+slot.day+" · "
    +clockMinutes(slot.start_minute)+"–"+clockMinutes(slot.start_minute+slot.minutes)):help("当前工单未排到产线。"))
    +(manage?`<div class="actions">${button(slot?"调整排程":"登记排程","scheduleWork",model.id,"small")}
      ${slot?button("取消排程","clearSchedule",model.id,"small"):""}</div>`:""));
}

async function scheduleWork(id) {
  const order=await request("/api/document/"+encodeURIComponent(id));
  const slot=order.slot;
  const setup=await request("/api/execution/production");
  const lines=setup.lines.filter(line=>line.site_id===order.site_id);
  if(!lines.length) {
    openDialog("登记排程",help("先在产线排程为本工单的供料仓新增产线。")+button("前往产线排程","go","capacity"));
    return;
  }
  const initialStart=walkthrough?.targets.rush?Math.max(lines[0].shift_start,setup.current_minute):lines[0].shift_start;
  const initialMinutes=Math.min(60,1440-initialStart);
  const form=formDialog("工单排程 · "+order.ref,"schedule_work",grid(
    select("line_id","产线",pick(lines,row=>row.code+" · "+row.name),slot?.line_id||lines[0].id)
    +input("day","生产日期",{type:"date",min:state.today,value:slot?.day>=state.today?slot.day:state.today,max:order.due||""})
    +input("start","开工时刻",{type:"time",value:clockMinutes(slot?.start_minute??initialStart)})
    +input("minutes","计划占用分钟",{type:"number",min:"1",max:"1440",step:"1",value:String(slot?.minutes??initialMinutes)}))
    +memo("note","排程依据",true),"保存排程",values=>({...values,id}),()=>openDocument(id),id);
  form.elements.line_id.addEventListener("change",()=>{
    const line=lines.find(row=>row.id===form.elements.line_id.value);
    if(line) form.elements.start.value=clockMinutes(line.shift_start);
  });
}

function clearSchedule(id) {
  formDialog("取消排程","schedule_work",memo("note","取消依据",true),"取消排程",
    values=>({...values,id,clear:true}),()=>openDocument(id),id);
}

function reservationSection(order) {
  if(order.kind==="purchase"||!["draft","approved","partial"].includes(order.status)) return "";
  const manage=allowed("reserve_stock")&&order.status!=="draft";
  return section(order.kind==="work"?"生产组件锁料":"销售批次锁料",
    table(["物料","批次","批次状态","本单锁定","未锁库存",...(manage?["操作"]:[])],order.reservations,row=>[
      item(row.name,row.item_code),link(row.code,"lotTrace",row.id),row.usable?cfgLabel(lotStatus,row.status):bold("暂不可领发"),
      unitQuantity(row.own,row.unit),unitQuantity(row.usable?row.free:0,row.unit),
      ...(manage?[button(row.own?"调整／释放":"锁定批次","reserveBatch",order.id+"|"+row.id,"small")]:[]),
    ],"当前没有可锁定批次。来料或成品通过质检放行后，可在此锁定。"));
}

async function reserveBatch(value) {
  const [id,lot_id]=value.split("|");
  const order=await request("/api/document/"+encodeURIComponent(id));
  const row=order.reservations.find(entry=>entry.id===lot_id);
  if(!row) throw new Error("该批次当前没有可调整的预留");
  formDialog("批次锁料 · "+row.code,"reserve_stock",help("本单锁定量，填 0 可释放。")
    +input("quantity","调整后的数量（"+row.unit+"）",{type:"number",min:"0",max:String(row.maximum/1000),step:"0.001",
      value:String((row.usable?(row.own||row.maximum):0)/1000)})
    +memo("note","锁料依据",true),"保存锁料",values=>({...values,id,lot_id}),()=>openDocument(id),id);
}

function remainingPromise(order,line,exclude="") {
  const pledged=order.commitments.filter(row=>row.line_id===line.id&&!row.cancelled&&row.id!==exclude)
    .reduce((sum,row)=>sum+row.quantity-row.shipped,0);
  return line.quantity-line.fulfilled-pledged;
}

function commitmentSection(order,readonly=false) {
  const manage=!readonly&&allowed("delivery_commitment")&&["draft","approved","partial"].includes(order.status);
  const canAdd=manage&&order.lines.some(line=>remainingPromise(order,line)>0);
  return section("分批交付承诺",table(["批次","物料","承诺量","承诺签收","已发","已签收","状态",...(manage?["操作"]:[])],
    order.commitments,row=>[
      code(row.ref),item(row.name,row.code),unitQuantity(row.quantity,row.unit),text(row.due),unitQuantity(row.shipped,row.unit),
      unitQuantity(row.signed,row.unit),cfgLabel(commitmentStatus,row.status),
      ...(manage?[row.shipped||row.cancelled?"—":button("调整","editCommitment",order.id+"|"+row.id,"small")
        +button("撤销","cancelCommitment",[order.id,row.line_id,row.id].join("|"),"small")]:[]),
    ],"当前销售单未登记分批交付承诺。")
    +(canAdd?`<div class="actions">${button("＋ 新增交付批次","editCommitment",order.id,"small")}</div>`:""));
}

async function editCommitment(value) {
  const [id,commitment_id=""]=value.split("|");
  const order=await request("/api/document/"+encodeURIComponent(id));
  const existing=order.commitments.find(row=>row.id===commitment_id);
  const lines=order.lines.filter(line=>existing?line.id===existing.line_id:remainingPromise(order,line)>0);
  if(!lines.length) throw new Error("没有可承诺的销售明细");
  const form=formDialog(existing?"调整交付承诺":"新增交付批次","delivery_commitment",grid(
    select("line_id","销售明细",pick(lines,line=>line.code+" · "+line.name),lines[0].id)
    +input("quantity","承诺数量",{type:"number",min:"0.001",step:"0.001"})
    +input("due","承诺签收日期",{type:"date",min:state.today,value:existing?.due||""}))
    +memo("note","承诺依据",true),"保存承诺",values=>({...values,id,commitment_id}),()=>openDocument(id),id);
  const setAmount=()=>{
    const line=lines.find(row=>row.id===form.elements.line_id.value);
    const max=line?remainingPromise(order,line,commitment_id)/1000:0;
    form.elements.quantity.max=String(max);
    form.elements.quantity.value=max?String(existing?existing.quantity/1000:max):"";
  };
  form.elements.line_id.addEventListener("change",setAmount);
  setAmount();
}

function cancelCommitment(value) {
  const [id,line_id,commitment_id]=value.split("|");
  formDialog("撤销交付承诺","delivery_commitment",memo("note","撤销依据",true),"撤销承诺",
    values=>({...values,id,line_id,commitment_id,cancel:true}),()=>openDocument(id),id);
}

const executionHandlers={newProductionLine,editProductionCalendar,scheduleWork,clearSchedule,reserveBatch,editCommitment,cancelCommitment};
