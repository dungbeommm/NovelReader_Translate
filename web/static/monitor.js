
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
 el('resource-rings').innerHTML=resources.map(([key,label,hue])=>{
   const value=old?null:r[key]?.percent;
   return `<span class="resource-gauge" title="${label}: ${valid(value)?pct(value):'—'}"><span class="resource-pill" style="--hue:${hue}"><b class="resource-dot"></b><span class="resource-name">${label}</span><span class="resource-val">${valid(value)?Math.round(value)+'%':'—'}</span></span></span>`;
 }).join('');
 el('open-resources').title=old?'Tài nguyên: đang chờ hoặc mất kết nối':'Mức sử dụng (%) · bấm để xem chi tiết';
 el('resource-freshness').textContent=old?'Chưa có mẫu mới · không hiển thị số cũ như số hiện tại':`Cập nhật mỗi 2 giây · mẫu cách đây ${num(r.age_seconds)}s`;
 el('resource-cards').innerHTML=resources.map(([key,label,hue])=>{const x=r?.[key]||{},p=old?null:x.percent;return `<article class="resource-card" style="--hue:${hue}"><h3>${label}</h3><div class="resource-value">${pct(p)}</div><p>${key==='cpu'?`${x.logical_cores||'—'} CPU logic`:key==='gpu'?'GPU đo được':`${bytes(old?null:x.used_bytes)} / ${bytes(x.total_bytes)}`}</p><p>Đỉnh phiên ${pct(x.peak_percent)}</p></article>`}).join('');
 el('gpu-devices').innerHTML=r?.gpus?.length?r.gpus.map(g=>`<div class="gpu-device"><strong>GPU ${esc(g.index)} · ${esc(g.name)}</strong><p>Tải ${pct(old?null:g.percent)} · VRAM ${bytes(old?null:g.used_bytes)} / ${bytes(g.total_bytes)}</p></div>`).join(''):`<p class="monitor-note">${esc(r?.gpu_note||'Đang kiểm tra NVIDIA…')}</p>`;
 const disks=(r?.disks||[]).slice(1).map(d=>`${d.label}: ${bytes(old?null:d.used_bytes)} / ${bytes(d.total_bytes)}`).join(' · ');
 el('resource-scope').textContent=`${r?.note||''}${r?.ram?.scope==='container'?' RAM đang theo hạn mức container.':''}${r?.process_rss_bytes?` Riêng tiến trình Web: ${bytes(r.process_rss_bytes)} RAM.`:''}${disks?' '+disks:''}`;
}
function renderTasks(t,j){
 const tr=t?.translation, rows=t?.audio||[], running=rows.filter(a=>a.state==='running'),done=rows.filter(a=>a.state==='done').length, completed=rows.reduce((s,a)=>s+(a.state==='done'?100:a.percent||0),0),audioPercent=rows.length?Math.round(completed/rows.length):0;
 el('dock-translation').textContent=stale?'Mất kết nối':tr?`${pct(tr.percent)}${valid(tr.chars_per_second)?' · '+(tr.chars_per_second>=1000?num(tr.chars_per_second/1000)+'k':num(tr.chars_per_second))+'/s':''}`:'Sẵn sàng';
 el('dock-audio').textContent=stale?'—':rows.length?(running.length?`${running.length} chạy · ${done}/${rows.length}`:`${done}/${rows.length} xong`):'Sẵn sàng';
 el('dock-translation-bar').value=stale?0:(tr?.percent||0);el('dock-audio-bar').value=stale?0:audioPercent;

 if (el('trans-elapsed-time')) el('trans-elapsed-time').textContent = tr?.elapsed_seconds ? duration(tr.elapsed_seconds) : (j?.active ? 'Đang chạy' : '—');
 if (el('trans-eta-time')) el('trans-eta-time').textContent = (tr?.state === 'running' && valid(tr?.eta_seconds)) ? duration(tr.eta_seconds) : '—';
 if (el('trans-speed-rate')) el('trans-speed-rate').textContent = (valid(tr?.chars_per_second) && tr.chars_per_second > 0) ? `${num(tr.chars_per_second)} k/tự/s` : '—';
 if (el('workflow-trans-state')) el('workflow-trans-state').textContent = stateLabel[j?.status] || 'Sẵn sàng';

 const activeAudio = running[0] || rows[0];
 if (el('audio-progress-text')) el('audio-progress-text').textContent = rows.length ? `${done} / ${rows.length} chương audio` : '0 / 0 chương audio';
 if (el('audio-percent')) el('audio-percent').textContent = `${audioPercent}%`;
 if (el('audio-progress-bar')) el('audio-progress-bar').value = audioPercent;
 if (el('audio-speed-rate')) el('audio-speed-rate').textContent = (activeAudio && valid(activeAudio.audio_per_second)) ? `${num(activeAudio.audio_per_second)}× realtime` : (running.length ? 'Đang tạo...' : '—');
 if (el('audio-elapsed-time')) el('audio-elapsed-time').textContent = (activeAudio && valid(activeAudio.elapsed_seconds)) ? duration(activeAudio.elapsed_seconds) : '—';
 if (el('audio-eta-time')) el('audio-eta-time').textContent = (activeAudio?.state === 'running' && valid(activeAudio.audio_seconds) && valid(activeAudio.audio_per_second) && activeAudio.audio_per_second > 0) ? duration(Math.max(0, (activeAudio.audio_seconds - (activeAudio.elapsed_seconds || 0)) / activeAudio.audio_per_second)) : (running.length ? 'Đang tính...' : '—');
 if (el('workflow-audio-state')) el('workflow-audio-state').textContent = running.length ? 'Đang tạo audio' : (done && done === rows.length ? 'Hoàn tất' : (rows.length ? 'Tạm dừng' : 'Chưa có'));

 el('task-freshness').textContent=stale?'Mất kết nối · thông tin bên dưới là mẫu cuối, không phải tiến trình trực tiếp':`${running.length&&!j?.active?'Đang tạo audio':stateLabel[j?.status]||j?.status||'Sẵn sàng'} · phiên đo ${duration(t?.session_seconds)}`;
 el('translation-scope').textContent=j?`${j.done}/${j.total} chương trong phạm vi`:'';
 const trState=tr?.state==='running'&&j?.status==='paused'?'paused':tr?.state==='running'&&j?.status==='stopping'?'stopped':tr?.state;
 el('translation-detail').innerHTML=tr?`<article class="translation-panel"><div class="task-row-heading"><strong title="${esc(tr.title)}">Chương ${tr.position} · ${esc(tr.title)}</strong><span class="task-state">${esc(stateLabel[trState]||trState)} · ${pct(tr.percent)}</span></div>${bar(tr.percent,'Chương dịch')}<dl class="task-metrics">${metric('Tốc độ suy luận',`${num(tr.chars_per_second)} ký tự/s`)}${metric('Thời gian chương',duration(tr.elapsed_seconds))}${metric('Còn lại ≈',trState==='running'?duration(tr.eta_seconds):'—')}</dl><p class="task-subnote">${num(tr.completed)} / ${num(tr.total)} ký tự nguồn · thời gian chương gồm cả chờ/tạm dừng</p></article>`:'<p class="empty-monitor">Chưa đo lượt dịch nào trong phiên này. Bắt đầu dịch để xem tốc độ.</p>';
 el('audio-scope').textContent=rows.length?`${done}/${rows.length} hoàn tất · ${running.length} đang tạo`:'Chưa có lượt tạo';
 el('audio-task-list').innerHTML=rows.length?rows.map(a=>`<li class="audio-task" data-state="${esc(a.state)}"><div class="task-row-heading"><strong title="${esc(a.title)}">Chương ${a.position} · ${esc(a.title)}</strong><span class="task-state">${esc(stageLabel[a.stage]||stateLabel[a.state]||a.state)} · ${pct(a.percent)}</span></div>${bar(valid(a.percent)?a.percent:0,'Audio chương '+a.position)}<dl class="task-metrics">${metric('Tốc độ tạo',valid(a.audio_per_second)?`${num(a.audio_per_second)}× thời gian thực`:'—')}${metric(a.state==='done'?'Tạo xong trong':'Đã xử lý',duration(a.elapsed_seconds))}${metric(a.state==='done'?'Độ dài audio':'Đã tổng hợp',duration(a.audio_seconds||null))}</dl><p class="task-subnote">${valid(a.chars_per_second)?num(a.chars_per_second)+' ký tự/s · ':''}${valid(a.rtf)?'RTF '+num(a.rtf)+' · ':''}${a.finished_at?'Kết thúc '+esc(new Date(a.finished_at).toLocaleTimeString('vi-VN')):a.total?`${num(a.completed)}/${num(a.total)} ký tự`:a.state==='queued'?'Đợi worker khả dụng':'Chờ nhóm TTS đầu tiên'}</p></li>`).join(''):'<li class="empty-monitor">Chưa đo lượt tạo audio nào trong phiên này. Audio cũ không có thời gian đo sẽ không được gán số giả.</li>';
}
function redraw(){renderResources(last?.resources);renderTasks(last?.tasks,last?.job)}
async function poll(){
 if(document.hidden){setTimeout(poll,2000);return}
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),7000);
 try{const res=await fetch('/api/monitor',{signal:controller.signal,cache:'no-store'});if(!res.ok)throw Error('monitor');last=await res.json();successAt=Date.now();stale=false;redraw()}
 catch(e){stale=true;redraw()}finally{clearTimeout(timer);setTimeout(poll,2000)}
}
for(const [trigger,popup] of [['open-resources','resource-popup'],['open-task-monitor','task-popup']]){
 el(trigger).addEventListener('click',()=>{redraw();if(!el(popup).open){el(popup).showModal();el(popup).querySelector('.monitor-body').scrollTop=0}});
 el(popup).addEventListener('click',e=>{if(e.target===el(popup)){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close()}});
}
document.querySelectorAll('[data-close-monitor]').forEach(b=>b.onclick=()=>el(b.dataset.closeMonitor).close());
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&Date.now()-successAt>10000){stale=true;redraw()}});
redraw();poll();
})();
