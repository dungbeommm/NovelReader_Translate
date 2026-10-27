/* Runtime monitor: real server samples only; missing/stale values are never zero. */
(()=>{'use strict';
const el=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const resources=[['cpu','CPU','microchip'],['gpu','GPU','chart-histogram'],['vram','VRAM','microchip'],['ram','RAM','disk'],['disk','Đĩa','database']];
const valid=n=>typeof n==='number'&&Number.isFinite(n), num=n=>valid(n)?new Intl.NumberFormat('vi-VN',{maximumFractionDigits:1}).format(n):'—', pct=n=>valid(n)?`${Math.round(n)}%`:'—';
const bytes=n=>{if(!valid(n))return '—';return n>=1024**3?`${num(n/1024**3)} GiB`:`${num(n/1024**2)} MiB`};
const duration=n=>{if(!valid(n))return '—';if(n<10)return `${num(n)}s`;n=Math.floor(n);return n>=3600?`${Math.floor(n/3600)}g ${Math.floor(n%3600/60)}p`:n>=60?`${Math.floor(n/60)}p ${n%60}s`:`${n}s`};
const stateLabel={ready:'Sẵn sàng',stopping:'Đang dừng',running:'Đang chạy',done:'Hoàn tất',queued:'Đang chờ',error:'Có lỗi',stopped:'Đã dừng',cancelled:'Đã hủy',paused:'Tạm dừng',loading:'Đang nạp'};
const stageLabel={loading:'Nạp model',waiting:'Chờ bộ đọc',synthesizing:'Tổng hợp',encoding:'Mã hóa',queued:'Đang chờ',done:'Hoàn tất',error:'Có lỗi',cancelled:'Đã hủy'};
let last=null,successAt=0,stale=true;
function bar(value,label){return `<progress max="100" ${valid(value)?`value="${Math.max(0,Math.min(100,value))}"`:''} aria-label="${esc(label)}"></progress>`}
function metric(label,value){return `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`}
function renderResources(r){
 const old=!r||!valid(r.age_seconds)||r.age_seconds>10||stale;
 el('resource-freshness').textContent=old?'Chưa có số liệu mới':`Cập nhật mỗi 2 giây · mẫu cách đây ${num(r.age_seconds)}s`;
 el('resource-cards').innerHTML=resources.map(([key,label,icon])=>{const x=r?.[key]||{},p=old?null:x.percent;return `<article class="resource-card"><span class="resource-icon" aria-hidden="true"><i class="fi fi-br-${icon}"></i></span><div class="resource-copy"><h3>${label}</h3><div class="resource-value">${pct(p)}</div><p>${key==='cpu'?`${x.logical_cores||'—'} CPU logic`:key==='gpu'?'GPU đo được':`${bytes(old?null:x.used_bytes)} / ${bytes(x.total_bytes)}`}</p>${bar(p,`${label} sử dụng`)}</div></article>`}).join('');
}
function renderTasks(t,j){
 const tr=t?.translation, rows=t?.audio||[], running=rows.filter(a=>a.state==='running'),done=rows.filter(a=>a.state==='done').length;
 const trState=tr?.state==='running'&&j?.status==='paused'?'paused':tr?.state==='running'&&j?.status==='stopping'?'stopped':tr?.state;
 el('task-freshness').textContent=stale?'Mất kết nối · đang hiển thị số liệu cũ':`${running.length&&!j?.active?'Đang tạo audio':stateLabel[j?.status]||j?.status||'Sẵn sàng'} · phiên đo ${duration(t?.session_seconds)}`;
 const queued=rows.filter(a=>a.state==='queued').length;
 el('monitor-summary').innerHTML=[['Chương hoàn tất',j?`${num(j.done)} / ${num(j.total)}`:'—','Theo phạm vi hiện tại'],['Dịch chương',tr?`Chương ${num(tr.position)}`:'Không hoạt động',tr?stateLabel[trState]||trState:'Chưa có tác vụ'],['Đang tạo audio',num(running.length),running.length?'Tác vụ đang chạy':'Không có tác vụ'],['Audio đang chờ',num(queued),`${num(done)} hoàn tất trong phiên`]].map(([label,value,note])=>`<article class="monitor-summary-item"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></article>`).join('');
 const start=el('monitor-start'),pause=el('monitor-pause'),stop=el('monitor-stop');
 start.disabled=el('start').disabled;
 pause.disabled=el('pause').disabled;
 pause.innerHTML=j?.status==='paused'?'<i class="fi fi-br-play" aria-hidden="true"></i> Tiếp tục':'<i class="fi fi-br-pause" aria-hidden="true"></i> Tạm dừng';
 stop.disabled=el('stop').disabled;
 el('translation-scope').textContent=j?`${j.done}/${j.total} chương trong phạm vi`:'';
 el('translation-detail').innerHTML=tr?`<article class="translation-panel"><div class="task-row-heading"><strong title="${esc(tr.title)}">Chương ${tr.position} · ${esc(tr.title)}</strong><span class="task-state">${esc(stateLabel[trState]||trState)} · ${pct(tr.percent)}</span></div>${bar(tr.percent,'Chương dịch')}<dl class="task-metrics">${metric('Tốc độ suy luận',`${num(tr.chars_per_second)} ký tự/s`)}${metric('Thời gian chương',duration(tr.elapsed_seconds))}${metric('Còn lại ≈',trState==='running'?duration(tr.eta_seconds):'—')}</dl><p class="task-subnote">${num(tr.completed)} / ${num(tr.total)} ký tự nguồn · thời gian chương gồm cả chờ/tạm dừng</p></article>`:'<p class="empty-monitor">Chưa có lượt dịch trong phiên này.</p>';
 el('audio-scope').textContent=rows.length?`${done}/${rows.length} hoàn tất · ${running.length} đang tạo · hiển thị ${Math.min(2,rows.length)} mới nhất`:'Chưa có lượt tạo';
 const recent=rows.slice(0,2);
 el('audio-task-list').innerHTML=recent.length?recent.map(a=>`<li class="audio-task" data-state="${esc(a.state)}"><div class="task-row-heading"><strong title="${esc(a.title)}">Chương ${a.position} · ${esc(a.title)}</strong><span class="task-state">${esc(stageLabel[a.stage]||stateLabel[a.state]||a.state)} · ${pct(a.percent)}</span></div>${bar(valid(a.percent)?a.percent:0,'Audio chương '+a.position)}<dl class="task-metrics">${metric('Tốc độ tạo',valid(a.audio_per_second)?`${num(a.audio_per_second)}× thời gian thực`:'—')}${metric(a.state==='done'?'Tạo xong trong':'Đã xử lý',duration(a.elapsed_seconds))}${metric(a.state==='done'?'Độ dài audio':'Đã tổng hợp',duration(a.audio_seconds||null))}</dl><p class="task-subnote">${valid(a.chars_per_second)?num(a.chars_per_second)+' ký tự/s · ':''}${valid(a.rtf)?'RTF '+num(a.rtf)+' · ':''}${a.finished_at?'Kết thúc '+esc(new Date(a.finished_at).toLocaleTimeString('vi-VN')):a.total?`${num(a.completed)}/${num(a.total)} ký tự`:a.state==='queued'?'Đợi worker khả dụng':'Chờ nhóm TTS đầu tiên'}</p></li>`).join(''):'<li class="empty-monitor">Chưa có lượt tạo audio trong phiên này.</li>';
}
function redraw(){renderResources(last?.resources);renderTasks(last?.tasks,last?.job)}
async function poll(){
 if(document.hidden){setTimeout(poll,2000);return}
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),7000);
 try{const res=await fetch('/api/monitor',{signal:controller.signal,cache:'no-store'});if(!res.ok)throw Error('monitor');last=await res.json();successAt=Date.now();stale=false;redraw()}
 catch(e){stale=true;redraw()}finally{clearTimeout(timer);setTimeout(poll,2000)}
}
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&Date.now()-successAt>10000){stale=true;redraw()}});
el('monitor-start').addEventListener('click',()=>el('start').click());
el('monitor-pause').addEventListener('click',()=>el('pause').click());
el('monitor-stop').addEventListener('click',()=>el('stop').click());
redraw();poll();
})();
