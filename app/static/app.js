const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let P=0;const api=async(m,u,b)=>{P++;try{const r=await fetch(u,{method:m,headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});
 const j=await r.json().catch(()=>({}));if(!r.ok){alert(j.detail||r.statusText);throw new Error(j.detail||r.statusText)}return j}finally{P--}};
const tm=x=>x?new Date(x*1000).toLocaleString():'—';
const fmt=s=>{for(const[u,n]of[['hours',3600],['minutes',60]])if(s%n===0)return `${s/n} ${u}`;return `${s} seconds`};
let S,first=true;
function render(){const b=S.broadcast,a=S.accounts,g=S.groups;
 const st=!b.enabled?'Stopped':b.paused?'Paused':'Running';
 $('b-start').classList.toggle('on',b.enabled&&!b.paused);$('b-pause').classList.toggle('on',b.enabled&&b.paused);$('b-stop').classList.toggle('on',!b.enabled);
 const c=(k,v)=>`<div class="card"><b>${k}</b>${esc(v)}</div>`;
 $('dash').innerHTML=c('Accounts connected',`${a.filter(x=>x.status==='connected').length}/${a.length}`)+c('Groups (enabled/managed)',`${g.filter(x=>x.enabled).length}/${g.length}`)
  +c('Scheduler',st)+c('Repeat delay',fmt(b.delay_seconds))+c('Last broadcast',`${tm(b.last_run)} ${b.last_status?'· '+b.last_status:''}`)
  +c('Next broadcast',b.enabled&&!b.paused?tm(b.next_run)||'now':'—')+c('AI',`${S.settings.ai_enabled?'on':'off'} · ${S.settings.model}`)+c('Last broadcast error',b.last_error||'none');
 $('events').innerHTML=S.events.map(e=>`<div class="${e.level==='error'?'err':''}">${tm(e.t)} ${esc(e.msg)}</div>`).join('')||'No activity yet.';
 $('accounts').innerHTML=a.map(x=>`<div class="row"><b>${esc(x.name)}</b> ${esc(x.tg_name||'')} ${x.username?'@'+esc(x.username):''} ${x.tg_id?'#'+x.tg_id:''} <span class="${x.status==='connected'?'ok':'err'}">${x.status}</span>
  <button onclick="acc('reconnect','${x.name}')">Reconnect</button><button onclick="acc('disconnect','${x.name}')">Disconnect</button><button class="d" onclick="delAcc('${x.name}')">Remove</button></div>`).join('')||'<p class="hint">No accounts yet.</p>';
 const sel=$('sel'),cur=sel.value;sel.innerHTML=a.map(x=>`<option>${esc(x.name)}</option>`).join('');if(cur)sel.value=cur;
 $('groups').innerHTML=g.map(x=>`<div class="g row"><label class="inline"><input type="checkbox" ${x.enabled?'checked':''} onchange="tog('${x.account}',${x.id},this.checked)"> <b>${esc(x.title)}</b></label> <small>[${esc(x.account)}]</small>
  <small class="err">${esc(x.last_error||'')}</small><button onclick="test('${x.account}',${x.id})">Send test</button><button class="d" onclick="delG('${x.account}',${x.id})">Remove</button></div>`).join('')||'<p class="hint">No groups added.</p>';
 if(first){first=false;const s=S.settings;mlist(b.messages.length?b.messages:b.message?[b.message]:['']);
  const u=b.delay_seconds%3600===0?['hours',3600]:b.delay_seconds%60===0?['minutes',60]:['seconds',1];$('bval').value=b.delay_seconds/u[1];$('bunit').value=u[0];
  $('ai').checked=s.ai_enabled;$('gon').checked=s.greeting_enabled;$('greeting').value=s.greeting;$('prompt').value=s.system_prompt;$('prompt').placeholder=S.default_prompt;
  $('url').value=s.ollama_url;$('model').value=s.model;$('hist').value=s.history_limit;
  $('key').textContent=S.ollama_key_set?'Ollama API key: set in .env':'Ollama API key: not set in .env (required for Ollama Cloud)'}}
async function load(){S=await api('GET','/api/state');render()}
async function addAcc(){await api('POST','/api/accounts',{name:$('an').value,phone:$('ap').value});alert('Code sent in Telegram');load()}
async function verify(){await api('POST',`/api/accounts/${$('an').value}/verify`,{code:$('ac').value,password:$('apw').value});load()}
async function acc(a,n){await api('POST',`/api/accounts/${n}/${a}`);load()}
async function delAcc(n){if(confirm(`Remove ${n}? This logs out and deletes its session.`)){await api('DELETE','/api/accounts/'+n);load()}}
let D=[];async function loadDialogs(){if(!$('sel').value)return;D=await api('GET',`/api/accounts/${$('sel').value}/dialogs`);
 $('dialogs').innerHTML=D.map((d,i)=>`<label><input type="checkbox" data-i="${i}"> ${esc(d.title)}</label>`).join('')}
async function addSel(){const g=[...document.querySelectorAll('#dialogs input:checked')].map(c=>D[c.dataset.i]);await api('POST','/api/groups',{account:$('sel').value,groups:g});load()}
const tog=async(a,id,e)=>{await api('PUT',`/api/groups/${a}/${id}`,{enabled:e});load()};
const delG=async(a,id)=>{await api('DELETE',`/api/groups/${a}/${id}`);load()};
const test=async(a,id)=>{if(confirm('Send the broadcast message once to this group now?')){await api('POST','/api/broadcast/test',{account:a,group_id:id});alert('Sent')}};
const mlist=l=>{$('bmsgs').innerHTML=l.map(m=>`<div class="row"><textarea class="bm" rows="2">${esc(m)}</textarea><button class="d" onclick="this.parentNode.remove()">Remove</button></div>`).join('')};
const addM=()=>$('bmsgs').insertAdjacentHTML('beforeend','<div class="row"><textarea class="bm" rows="2"></textarea><button class="d" onclick="this.parentNode.remove()">Remove</button></div>');
async function saveB(){await api('PUT','/api/broadcast',{messages:[...document.querySelectorAll('.bm')].map(t=>t.value),delay_value:$('bval').value,delay_unit:$('bunit').value});load()}
async function ctl(a){await api('POST','/api/broadcast/'+a);load()}
async function saveS(){await api('PUT','/api/settings',{ai_enabled:$('ai').checked,greeting_enabled:$('gon').checked,greeting:$('greeting').value,system_prompt:$('prompt').value,ollama_url:$('url').value,model:$('model').value,history_limit:$('hist').value});load()}
async function testO(k){$('ostat').textContent='Testing…';const r=await api('POST','/api/ollama/'+k);$('ostat').className=r.ok?'ok':'err';$('ostat').textContent=r.ok?r.message:r.error}
async function convs(){const l=await api('GET','/api/conversations');
 $('convs').innerHTML=l.map(c=>`<div class="conv" onclick="openConv('${c.key}')"><b>${esc(c.name||c.username||c.user_id)}</b> ${c.username?'@'+esc(c.username):''} #${c.user_id} · ${tm(c.last_activity)} · AI ${c.ai_enabled?'on':'off'}<br><small>User: ${esc(c.latest_message)}<br>Reply: ${esc(c.latest_response)}</small></div>`).join('')||'<p class="hint">No conversations yet.</p>'}
async function openConv(k){const c=await api('GET','/api/conversations/'+k);
 $('conv').innerHTML=`<button onclick="toggleAI('${k}',${!c.ai_enabled})">${c.ai_enabled?'Disable':'Enable'} AI for this user</button>\n`+c.messages.map(m=>`[${tm(m.t)}] ${esc(m.role)}${m.kind!=='message'?' ('+esc(m.kind)+')':''}: ${esc(m.text)}`).join('\n')}
async function toggleAI(k,v){await api('PUT','/api/conversations/'+k,{ai_enabled:v});openConv(k);convs()}
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b||b.disabled)return;b.classList.add('clicked');b.disabled=true;const w=()=>P?setTimeout(w,150):(b.disabled=false,b.classList.remove('clicked'));setTimeout(w,0)});
load();convs();setInterval(()=>{load().catch(()=>{});convs().catch(()=>{})},5000);