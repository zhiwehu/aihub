import {failureMessage, readBody} from './api-response.mjs';
const $=id=>document.getElementById(id);
async function api(path,options={}){
  const response=await fetch('/api/client-credentials'+path,options),{value,parsed}=await readBody(response);
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
