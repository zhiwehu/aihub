import {failureMessage, readBody} from './api-response.mjs';
const $=id=>document.getElementById(id);
async function api(path,options={},root='/api/client-credentials'){
  const response=await fetch(root+path,options),{value,parsed}=await readBody(response);
  if(!response.ok||!parsed)throw Error(value?.error?.message||failureMessage(response));return value;
}
function message(text){$('client-access-result').textContent=text;}
function entry(value){
  const link=$('client-access-open');link.removeAttribute('href');link.setAttribute('aria-disabled','true');
  if(!value)return;
  const url=new URL(value,location.href);
  if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.search||url.hash)return;
  link.href=url.href;link.setAttribute('aria-disabled','false');
}
function row(target,name,action,remove){
  const item=document.createElement('div');item.className='access-entry';
  const title=document.createElement('span');title.textContent=name;
  const button=document.createElement('button');button.type='button';button.className='text-button';button.textContent=action;button.onclick=remove;
  item.append(title,button);target.append(item);
}
async function refresh(){
  const data=await api('');entry(data.client_url);$('client-access-list').replaceChildren();
  if(!data.clients.length)$('client-access-list').textContent='还没有添加网页，按上方两步开始即可。';
  for(const client of data.clients)row($('client-access-list'),client.name,'取消连接权限',async()=>{
    try{await api('/'+client.id,{method:'DELETE'});await refresh();message('已取消这个网页的连接权限，已有记录保留。');}catch(e){message(e.message);}
  });
}
$('client-access-form').onsubmit=async event=>{
  event.preventDefault();const button=$('client-access-create');if(button.disabled)return;
  button.disabled=true;button.textContent='正在生成…';
  try{
    const data=await api('',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('client-access-name').value.trim()||'这台电脑的网页'})});
    $('client-access-token').value=data.token;$('client-access-secret').hidden=false;$('client-access-copy').disabled=false;
    message('连接码已生成。下一步：复制连接码，再打开聊天网页。');await refresh();
  }catch(e){message(e.message);}finally{button.disabled=false;button.textContent='生成连接码';}
};
$('client-access-copy').onclick=async()=>{
  const value=$('client-access-token').value;if(!value)return;
  if(window.isSecureContext&&navigator.clipboard?.writeText){
    try{await navigator.clipboard.writeText(value);message('已复制。打开聊天网页后，粘贴到“连接码”一栏即可。');return;}catch{}
  }
  // HTTP on a LAN address has no Clipboard API; select the value and use the
  // legacy command, leaving it visible when even that is blocked.
  const input=$('client-access-token'),type=input.type;
  input.type='text';input.focus();input.select();
  let copied=false;try{copied=document.execCommand('copy');}catch{}
  if(copied){input.type=type;message('已复制。打开聊天网页后，粘贴到“连接码”一栏即可。');}
  else message('无法自动复制，连接码已显示并选中，请按 Ctrl+C（Mac 用 Cmd+C）。');
};
$('client-access-refresh').onclick=()=>refresh().catch(e=>message(e.message));
const deviceApi=(path,options)=>api(path,options,'/api/device-credentials');
async function refreshDevices(){
  const data=await deviceApi('');$('device-access-list').replaceChildren();
  if(!data.devices.length)$('device-access-list').textContent='尚未添加手动接入的设备。';
  for(const device of data.devices)row($('device-access-list'),device.device_id,'取消此设备权限',async()=>{
    try{await deviceApi('/'+device.id,{method:'DELETE'});await refreshDevices();$('device-access-result').textContent='已取消此设备的连接权限。';}
    catch(e){$('device-access-result').textContent=e.message;}
  });
}
$('device-access-form').onsubmit=async event=>{
  event.preventDefault();try{
    const data=await deviceApi('',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device_id:$('device-access-id').value.trim()})});
    $('device-access-token').value=data.token;$('device-access-secret').hidden=false;
    $('device-access-ota').value=data.ota_url||'';$('device-access-ota-wrap').hidden=!data.ota_url;
    $('device-access-result').textContent='设备连接码已生成。先确认设备能连接，再取消旧连接码的权限。';await refreshDevices();
  }catch(e){$('device-access-result').textContent=e.message;}
};
$('device-access-refresh').onclick=()=>refreshDevices().catch(e=>{$('device-access-result').textContent=e.message;});
async function refreshAll(){
  await Promise.allSettled([refresh().catch(e=>message(e.message)),refreshDevices().catch(e=>{$('device-access-result').textContent=e.message;})]);
}
window.addEventListener('aihub:view',event=>{if(event.detail==='connections')return refreshAll();});
// The first view event may precede this independent module's loading.
if(location.hash==='#connections')refreshAll();
