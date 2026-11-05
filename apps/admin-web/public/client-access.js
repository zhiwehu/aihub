import {failureMessage, readBody} from './api-response.mjs';
const $=id=>document.getElementById(id);
async function api(path,options={},root='/api/client-credentials'){
  const response=await fetch(root+path,options),{value,parsed}=await readBody(response);
  if(!response.ok||!parsed)throw Error(value?.error?.message||failureMessage(response));return value;
}
function show(error){$('client-access-result').textContent=error.message;}
async function refresh(){
  const data=await api('');$('client-access-list').replaceChildren();
  for(const client of data.clients){
    const row=document.createElement('p');row.append(document.createTextNode(client.name+' · '+client.id.slice(0,8)+' '));
    const revoke=document.createElement('button');revoke.type='button';revoke.textContent='撤销凭证';
    revoke.onclick=async()=>{try{await api('/'+client.id,{method:'DELETE'});await refresh();}catch(e){show(e);}};
    row.append(revoke);$('client-access-list').append(row);
  }
}
$('client-access-form').onsubmit=async event=>{
  event.preventDefault();try{
    const data=await api('',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('client-access-name').value.trim()})});
    $('client-access-token').value=data.token;$('client-access-secret').hidden=false;
    $('client-access-result').textContent='凭证仅显示这一次，请复制到独立客户端页面。';await refresh();
  }catch(e){show(e);}
};
$('client-access-refresh').onclick=()=>refresh().catch(show);
window.addEventListener('aihub:view',event=>{if(event.detail==='connections')refresh().catch(show);});

const deviceApi=(path,options)=>api(path,options,'/api/device-credentials');
async function refreshDevices(){
  const data=await deviceApi('');$('device-access-list').replaceChildren();
  for(const device of data.devices){
    const row=document.createElement('p');row.append(document.createTextNode(device.device_id+' · '+device.id.slice(0,8)+' '));
    const revoke=document.createElement('button');revoke.type='button';revoke.textContent='撤销设备凭证';
    revoke.onclick=async()=>{try{await deviceApi('/'+device.id,{method:'DELETE'});await refreshDevices();$('device-access-result').textContent='凭证已撤销，使用它的连接已关闭。';}catch(e){$('device-access-result').textContent=e.message;}};
    row.append(revoke);$('device-access-list').append(row);
  }
}
$('device-access-form').onsubmit=async event=>{
  event.preventDefault();try{
    const data=await deviceApi('',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device_id:$('device-access-id').value.trim()})});
    $('device-access-token').value=data.token;$('device-access-secret').hidden=false;
    $('device-access-ota').value=data.ota_url||'';$('device-access-ota-wrap').hidden=!data.ota_url;
    $('device-access-result').textContent='仅显示一次。请先将新凭证写入设备并验证连接，再撤销旧凭证。';await refreshDevices();
  }catch(e){$('device-access-result').textContent=e.message;}
};
$('device-access-refresh').onclick=()=>refreshDevices().catch(e=>{$('device-access-result').textContent=e.message;});
window.addEventListener('aihub:view',event=>{if(event.detail==='connections')refreshDevices().catch(e=>{$('device-access-result').textContent=e.message;});});
