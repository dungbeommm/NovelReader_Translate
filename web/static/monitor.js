/* Runtime monitor: real server samples only; missing/stale values are never zero. */
(()=>{'use strict';
const el=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const resources=[['cpu','CPU','#5e9fe8'],['gpu','GPU','#bf8eda'],['vram','VRAM','#de9255'],['ram','RAM','#4fb9c9'],['disk','Đĩa','#eac26b']];
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
 el('resource-cards').innerHTML=resources.map(([key,label,hue])=>{const x=r?.[key]||{},p=old?null:x.percent;return `<article class="resource-card" style="--hue:${hue}"><h3>${label}</h3><div class="resource-value">${pct(p)}</div><p>${key==='cpu'?`${x.logical_cores||'—'} CPU logic`:key==='gpu'?'GPU đo được':`${bytes(old?null:x.used_bytes)} / ${bytes(x.total_bytes)}`}</p></article>`}).join('');
 el('gpu-devices').innerHTML=r?.gpus?.length?r.gpus.map(g=>`<div class="gpu-device"><strong>GPU ${esc(g.index)} · ${esc(g.name)}</strong><p>Tải ${pct(old?null:g.percent)} · VRAM ${bytes(old?null:g.used_bytes)} / ${bytes(g.total_bytes)}</p></div>`).join(''):`<p class="monitor-note">${esc(r?.gpu_note||'Đang kiểm tra NVIDIA…')}</p>`;
 const disks=(r?.disks||[]).slice(1).map(d=>`${d.label}: ${bytes(old?null:d.used_bytes)} / ${bytes(d.total_bytes)}`).join(' · ');
 el('resource-peaks').textContent='Đỉnh phiên · '+resources.map(([key,label])=>`${label} ${pct(r?.[key]?.peak_percent)}`).join(' · ');
 el('resource-scope').textContent=`${r?.note||''}${r?.ram?.scope==='container'?' RAM đang theo hạn mức container.':''}${r?.process_rss_bytes?` Riêng tiến trình Web: ${bytes(r.process_rss_bytes)} RAM.`:''}${disks?' '+disks:''}`;
}
function renderTasks(t,j){
 const tr=t?.translation, rows=t?.audio||[], running=rows.filter(a=>a.state==='running'),done=rows.filter(a=>a.state==='done').length;
 el('task-freshness').textContent=stale?'Mất kết nối · đang hiển thị số liệu cũ':`${running.length&&!j?.active?'Đang tạo audio':stateLabel[j?.status]||j?.status||'Sẵn sàng'} · phiên đo ${duration(t?.session_seconds)}`;
 el('translation-scope').textContent=j?`${j.done}/${j.total} chương trong phạm vi`:'';
 const trState=tr?.state==='running'&&j?.status==='paused'?'paused':tr?.state==='running'&&j?.status==='stopping'?'stopped':tr?.state;
 el('translation-detail').innerHTML=tr?`<article class="translation-panel"><div class="task-row-heading"><strong title="${esc(tr.title)}">Chương ${tr.position} · ${esc(tr.title)}</strong><span class="task-state">${esc(stateLabel[trState]||trState)} · ${pct(tr.percent)}</span></div>${bar(tr.percent,'Chương dịch')}<dl class="task-metrics">${metric('Tốc độ suy luận',`${num(tr.chars_per_second)} ký tự/s`)}${metric('Thời gian chương',duration(tr.elapsed_seconds))}${metric('Còn lại ≈',trState==='running'?duration(tr.eta_seconds):'—')}</dl><p class="task-subnote">${num(tr.completed)} / ${num(tr.total)} ký tự nguồn · thời gian chương gồm cả chờ/tạm dừng</p></article>`:'<p class="empty-monitor">Chưa có lượt dịch trong phiên này.</p>';
 el('audio-scope').textContent=rows.length?`${done}/${rows.length} hoàn tất · ${running.length} đang tạo`:'Chưa có lượt tạo';
 el('audio-task-list').innerHTML=rows.length?rows.map(a=>`<li class="audio-task" data-state="${esc(a.state)}"><div class="task-row-heading"><strong title="${esc(a.title)}">Chương ${a.position} · ${esc(a.title)}</strong><span class="task-state">${esc(stageLabel[a.stage]||stateLabel[a.state]||a.state)} · ${pct(a.percent)}</span></div>${bar(valid(a.percent)?a.percent:0,'Audio chương '+a.position)}<dl class="task-metrics">${metric('Tốc độ tạo',valid(a.audio_per_second)?`${num(a.audio_per_second)}× thời gian thực`:'—')}${metric(a.state==='done'?'Tạo xong trong':'Đã xử lý',duration(a.elapsed_seconds))}${metric(a.state==='done'?'Độ dài audio':'Đã tổng hợp',duration(a.audio_seconds||null))}</dl><p class="task-subnote">${valid(a.chars_per_second)?num(a.chars_per_second)+' ký tự/s · ':''}${valid(a.rtf)?'RTF '+num(a.rtf)+' · ':''}${a.finished_at?'Kết thúc '+esc(new Date(a.finished_at).toLocaleTimeString('vi-VN')):a.total?`${num(a.completed)}/${num(a.total)} ký tự`:a.state==='queued'?'Đợi worker khả dụng':'Chờ nhóm TTS đầu tiên'}</p></li>`).join(''):'<li class="empty-monitor">Chưa có lượt tạo audio trong phiên này.</li>';
}
function redraw(){renderResources(last?.resources);renderTasks(last?.tasks,last?.job)}
async function poll(){
 if(document.hidden){setTimeout(poll,2000);return}
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),7000);
 try{const res=await fetch('/api/monitor',{signal:controller.signal,cache:'no-store'});if(!res.ok)throw Error('monitor');last=await res.json();successAt=Date.now();stale=false;redraw()}
 catch(e){stale=true;redraw()}finally{clearTimeout(timer);setTimeout(poll,2000)}
}
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&Date.now()-successAt>10000){stale=true;redraw()}});
redraw();poll();
})();
