"use strict";

const demoMinutesPerSecond=180;
const demoSpeeds=[0.5,1,2,4];
const demoClockFormatter=new Intl.DateTimeFormat("zh-CN",{
  timeZone:"Asia/Shanghai",month:"long",day:"numeric",weekday:"short",hour:"2-digit",minute:"2-digit",hourCycle:"h23",
});
let exerciseDemo=null;
let exerciseDemoFrame=0;
let exerciseDemoRequest=0;
let exerciseDemoLoading=false;

function demoClock(demo,minute) {
  return demoClockFormatter.format(Date.parse(demo.data.start)+Math.floor(minute)*60000);
}

function demoDuration(minute) {
  const whole=Math.max(0,Math.ceil(minute));
  const days=Math.floor(whole/1440), hours=Math.floor(whole%1440/60), mins=whole%60;
  return [[days,"天"],[hours,"小时"],[mins,"分钟"]].filter(([value])=>value).map(([value,unit])=>value+" "+unit).join(" ") || "0 分钟";
}

function demoPosition(demo) {
  const {events}=demo.data;
  const next=events.findIndex(event=>event.end>demo.minute);
  const complete=next<0?events.length:next;
  return {
    complete,
    last:events[complete-1],
    next:events[complete],
    active:events.slice(complete).filter(event=>event.start<=demo.minute),
    snapshot:events[complete-1]?.snapshot||demo.data.snapshot,
  };
}

function tickDemo(demo,now) {
  if (!demo.playing) return;
  const elapsed=Math.max(0,now-demo.lastTick)/1000;
  demo.minute=Math.min(demo.data.duration,demo.minute+elapsed*demoMinutesPerSecond*demo.speed);
  demo.lastTick=now;
  if (demo.minute>=demo.data.duration) demo.playing=false;
}

function demoStep(demo) {
  const next=demoPosition(demo).next;
  if (next) demo.minute=next.end;
  demo.playing=false;
}

function demoTaskList(demo,position) {
  if (!position.active.length) {
    return `<p class="demo-empty">${position.next?"当前处于排程间隔，时钟继续前进。":"已完成全部演示步骤。"}</p>`;
  }
  return position.active.map(event=>`<article class="demo-task">
    <div><strong>${html(event.title)}</strong> ${sub(event.team+" · 用时 "+demoDuration(event.end-event.start))}</div>
    <p>${html(event.detail)}</p><small>预计完成 ${html(demoClock(demo,event.end))}</small>
  </article>`).join("");
}

function demoLatest(position) {
  const event=position.last;
  if (!event) return '<p>正在核对客户需求。完成后会在这里显示结果和单据。</p>';
  return `${event.blocked ? cfgLabel({stopped:["已拦截","red"]},"stopped") : cfgLabel({done:["已完成","green"]},"done")}
    <strong>${html(event.title)}</strong><p>${html(event.outcome || event.detail)}</p>`;
}

function demoBusinessState(demo,value) {
  const {quantity}=demo.data;
  const payable=value.payable;
  const ar=value.receivable;
  const cards=[
    ["已验收",value.accepted+" / "+quantity+" 套"],
    ["确认版本",value.confirmed_version?"V"+value.confirmed_version:"待确认"],
    ["采购应付",payable.confirmed?"已确认":payable.invoiced!==payable.accepted?"数量待核":"待确认"],
    ["销售剩余应收",ar?money.format(ar.balance/100):"待开票"],
  ];
  const metrics=`<div class="demo-stats">${cards.map(([label,result])=>`<div><small>${html(label)}</small><strong>${html(result)}</strong></div>`).join("")}</div>`;
  const deliveries=table(["交付批次","套数","计划到达","状态","发运日期","验收日期"],
    value.deliveries.map((row,index)=>({...row,index})),row=>[
      text("第 "+(row.index+1)+" 批"),numeric(row.qty),text(row.arrival),cfgLabel(exerciseStages,row.status),
      clean(row.actual.shipped),clean(row.actual.accepted),
    ],"等待客户确认交付方案。");
  const materials=table(["物料","现货可用（件）","本单预留（件）","未锁需求（件）","采购状态"],value.materials,row=>[
    item(row.name,row.code),numeric(row.available),numeric(row.reserved),numeric(row.need),row.po?cfgLabel(exercisePO,row.state):"—",
  ]);
  return metrics+section("交付状态",deliveries)+section("物料可用量",materials);
}

function demoHistory(demo,position) {
  const events=demo.data.events.slice(0,position.complete).reverse();
  return table(["模拟完成时间","步骤","责任岗位","用时","处理结果"],events,row=>[
    text(demoClock(demo,row.end)),bold(row.title),text(row.team),text(demoDuration(row.end-row.start)),
    (row.blocked?cfgLabel({stopped:["已拦截","red"]},"stopped")+" ":"")+text(row.outcome||row.detail),
  ],"步骤完成后会出现在这里。");
}

function exerciseDemoPage() {
  const demo=exerciseDemo;
  const position=demoPosition(demo);
  const total=demo.data.events.length;
  const finished=!position.next;
  return head("急单协同自动演示",`${demo.data.ref} · 客户要求 ${demo.data.quantity} 套于 ${demo.data.requested} 到达`,
    button("返回手动演练","exerciseCloseDemo")) + `<div class="stack">
    <section class="panel demo-player" aria-label="演示播放器">
      <div class="demo-player-top"><div><span class="demo-kicker">模拟时钟 · 北京时间</span>
      <strong id="demo-clock">${html(demoClock(demo,demo.minute))}</strong></div>
      <span id="demo-status" class="status ${finished?"green":demo.playing?"blue":"amber"}">
        ${finished?"已完成":demo.playing?"播放中":"已暂停"}</span></div>
      <div class="demo-progress-label"><span id="demo-completed">${position.complete} / ${total} 步</span>
        <span id="demo-percent">${Math.floor(demo.minute/demo.data.duration*100)}%</span></div>
      <progress id="demo-progress" aria-label="模拟时间进度" max="${demo.data.duration}" value="${demo.minute}"></progress>
      <div class="demo-progress-label muted"><span id="demo-elapsed">已模拟 ${html(demoDuration(Math.floor(demo.minute)))}</span>
        <span>总时长 ${html(demoDuration(demo.data.duration))}</span></div>
      <div class="demo-controls">
        ${button(finished?"已完成":demo.playing?"暂停":"继续播放","exerciseDemoToggle","","primary")}
        ${button("下一步","exerciseDemoStep")}${button("从头播放","exerciseDemoRestart")}
        ${select("demo_speed","播放倍速",demoSpeeds.map(rate=>[String(rate),rate+"×"]),String(demo.speed))}
        <small id="demo-rate">播放 1 秒 = 模拟 ${html(demoDuration(demoMinutesPerSecond*demo.speed))}</small>
      </div>
      <p class="demo-disclosure">业务耗时为演示设定，按模拟时钟推进。排队、审批、运输和周末等待会消耗模拟时间。</p>
    </section>
    <div class="demo-live">
      ${panel("当前处理",`<div id="demo-current" class="demo-current" data-active="${html(position.active.map(x=>x.title).join("|"))}" aria-live="polite">${demoTaskList(demo,position)}</div>`)}
      ${panel("下一完成节点",`<div class="demo-next"><strong id="demo-next-title">${html(position.next?.title||"演示结束")}</strong>
      <p id="demo-next-time">${position.next?"还需 "+html(demoDuration(position.next.end-demo.minute)):"全部步骤已处理"}</p></div>
      <div id="demo-latest" class="demo-latest" aria-live="polite">${demoLatest(position)}</div>`)}
    </div>
    ${panel("实时业务状态",`<div id="demo-business" class="demo-panel-content" data-complete="${position.complete}">${demoBusinessState(demo,position.snapshot)}</div>`)}
    ${panel("已完成的步骤",`<div id="demo-history">${demoHistory(demo,position)}</div>`)}
  </div>`;
}

function demoSetText(id,value) {
  const element=$(id);
  if (element.textContent!==value) element.textContent=value;
}

function refreshExerciseDemo() {
  const demo=exerciseDemo;
  const progress=$("demo-progress");
  if (!demo || !progress) return;
  const position=demoPosition(demo);
  const total=demo.data.events.length;
  const finished=!position.next;
  progress.value=demo.minute;
  demoSetText("demo-clock",demoClock(demo,demo.minute));
  demoSetText("demo-completed",`${position.complete} / ${total} 步`);
  demoSetText("demo-percent",`${Math.floor(demo.minute/demo.data.duration*100)}%`);
  demoSetText("demo-elapsed","已模拟 "+demoDuration(Math.floor(demo.minute)));
  demoSetText("demo-next-title",position.next?.title||"演示结束");
  demoSetText("demo-next-time",position.next?"还需 "+demoDuration(position.next.end-demo.minute):"全部步骤已处理");
  demoSetText("demo-rate","播放 1 秒 = 模拟 "+demoDuration(demoMinutesPerSecond*demo.speed));
  demoSetText("demo-status",finished?"已完成":demo.playing?"播放中":"已暂停");
  const statusClass="status "+(finished?"green":demo.playing?"blue":"amber");
  if ($("demo-status").className!==statusClass) $("demo-status").className=statusClass;

  const play=document.querySelector('[data-action="exerciseDemoToggle"]');
  const step=document.querySelector('[data-action="exerciseDemoStep"]');
  const playLabel=finished?"已完成":demo.playing?"暂停":"继续播放";
  if (play.textContent!==playLabel) play.textContent=playLabel;
  if (play.disabled!==finished) play.disabled=finished;
  if (step.disabled!==finished) step.disabled=finished;
  const current=$("demo-current");
  const active=position.active.map(event=>event.title).join("|");
  if (current.dataset.active!==active) {
    current.dataset.active=active;
    current.innerHTML=demoTaskList(demo,position);
  }
  const business=$("demo-business");
  if (business.dataset.complete!==String(position.complete)) {
    business.dataset.complete=String(position.complete);
    business.innerHTML=demoBusinessState(demo,position.snapshot);
    $("demo-history").innerHTML=demoHistory(demo,position);
    $("demo-latest").innerHTML=demoLatest(position);
  }
}

function animateExerciseDemo(now) {
  exerciseDemoFrame=0;
  if (!exerciseDemo?.playing || page!=="exercise") return;
  tickDemo(exerciseDemo,now);
  refreshExerciseDemo();
  if (exerciseDemo.playing) exerciseDemoFrame=requestAnimationFrame(animateExerciseDemo);
}

function playExerciseDemo() {
  if (!exerciseDemo || exerciseDemo.minute>=exerciseDemo.data.duration || exerciseDemo.playing) return;
  exerciseDemo.lastTick=performance.now();
  exerciseDemo.playing=true;
  refreshExerciseDemo();
  exerciseDemoFrame=requestAnimationFrame(animateExerciseDemo);
}

function pauseExerciseDemo() {
  if (!exerciseDemo?.playing) return;
  tickDemo(exerciseDemo,performance.now());
  exerciseDemo.playing=false;
  cancelAnimationFrame(exerciseDemoFrame);
  exerciseDemoFrame=0;
  refreshExerciseDemo();
}

function stopExerciseDemo() {
  exerciseDemoRequest+=1;
  exerciseDemoLoading=false;
  cancelAnimationFrame(exerciseDemoFrame);
  exerciseDemoFrame=0;
  exerciseDemo=null;
}

async function openExerciseDemo() {
  if (exerciseDemo || exerciseDemoLoading) return;
  exerciseDemoLoading=true;
  const attempt=++exerciseDemoRequest;
  const trigger=document.querySelector('[data-action="exerciseOpenDemo"]');
  if (trigger) trigger.disabled=true;
  try {
    const data=await request("/api/exercise/demo");
    if (attempt!==exerciseDemoRequest || page!=="exercise") return;
    exerciseDemo={data,minute:0,speed:1,playing:false,lastTick:0};
    render();
    window.scrollTo(0,0);
    $("main").focus({preventScroll:true});
    if (!document.hidden) playExerciseDemo();
  } catch (error) {
    if (attempt===exerciseDemoRequest && page==="exercise") throw error;
  } finally {
    if (trigger) trigger.disabled=false;
    if (attempt===exerciseDemoRequest) exerciseDemoLoading=false;
  }
}

const exerciseDemoHandlers={
  exerciseOpenDemo:openExerciseDemo,
  exerciseCloseDemo:()=>{stopExerciseDemo();render();window.scrollTo(0,0);$("main").focus({preventScroll:true});},
  exerciseDemoToggle:()=>{if (exerciseDemo?.playing) pauseExerciseDemo();else playExerciseDemo();},
  exerciseDemoStep:()=>{pauseExerciseDemo();if (exerciseDemo) demoStep(exerciseDemo);refreshExerciseDemo();},
  exerciseDemoRestart:()=>{if (exerciseDemo) {pauseExerciseDemo();exerciseDemo.minute=0;playExerciseDemo();}},
};

document.addEventListener("visibilitychange",()=>{if (document.hidden) pauseExerciseDemo();});
document.addEventListener("change",event=>{
  if (event.target.name!=="demo_speed" || !exerciseDemo) return;
  const speed=Number(event.target.value);
  if (!demoSpeeds.includes(speed)) return;
  tickDemo(exerciseDemo,performance.now());
  exerciseDemo.speed=speed;
  refreshExerciseDemo();
});
