import {ClientAudio} from './audio.js';
const $=id=>document.getElementById(id);
let base=location.origin, token='', socket, sid, resume, ready=false, recording=null, selected=null, audioURL=null, ping, poll;
const audio=new ClientAudio(send, packet=>{
  if(ready&&socket?.readyState===WebSocket.OPEN){
    if(socket.bufferedAmount>64000){disconnect();error(Error('音频上传积压，请重新连接。'));return;}
    socket.send(packet);
  }
});
$('server').value=base;
function error(e){$('error').textContent=e.message||String(e);}
function send(value){if(ready&&socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify(value));}
async function api(path, options={}){
  const response=await fetch(base+'/client/v1/'+path,{...options,credentials:'omit',headers:{Authorization:'Bearer '+token,...(options.body?{'Content-Type':'application/json'}:{}),...options.headers}});
  if(!response.ok){let data;try{data=await response.json();}catch{}throw Error(data?.error?.message||data?.error?.code||'请求失败（'+response.status+'）');}
  return response.json();
}
function controls(){
  for(const id of ['send','mic','interrupt','refresh-recordings'])$(id).disabled=!ready;
  $('disconnect').disabled=!socket;
  $('start-recording').disabled=!ready||!!recording;
  $('pause-recording').disabled=!ready||!recording;
  $('stop-recording').disabled=!ready||!recording;
  $('pause-recording').textContent=recording?.paused?'继续':'暂停';
  $('send').disabled=!ready||!!recording;
  $('recording-state').textContent=recording?(recording.paused?'已暂停':'录音中'):'尚未开始 / 已结束';
}
function disconnect(){
  ready=false;clearInterval(ping);clearInterval(poll);audio.clear();audio.stopMic();socket?.close();socket=null;recording=null;
  controls();$('status').textContent='已断开；录音状态请重新连接后刷新确认。';
}
async function history(){
  if(!sid)return;
  const rows=await api('sessions/'+sid+'/messages');
  $('messages').replaceChildren();
  for(const row of rows){const p=document.createElement('p'), who=document.createElement('strong');who.textContent=row.role==='user'?'你':'声桥';p.append(who,document.createTextNode(row.content));$('messages').append(p);}
  $('messages').scrollTop=$('messages').scrollHeight;
}
async function recordings(){
  const data=await api('recordings');$('recordings').replaceChildren();
  recording=data.recordings.find(r=>r.session_id===sid&&r.status==='active')||null;controls();
  if(!data.recordings.length)$('recordings').textContent='还没有录音。';
  for(const row of data.recordings){const b=document.createElement('button');b.textContent=new Date(row.started_at*1000).toLocaleString()+' · '+(row.status==='active'?(row.paused?'已暂停':'录音中'):(row.samples?'已保存':'已结束 · 无音频'));
    b.onclick=()=>openRecording(row).catch(error);$('recordings').append(b);}
}
async function openRecording(row){
  selected=row;$('detail').hidden=false;$('detail-title').textContent='录音 · '+new Date(row.started_at*1000).toLocaleString();
  $('player').pause();$('player').removeAttribute('src');if(audioURL)URL.revokeObjectURL(audioURL);audioURL=null;
  if(row.status!=='active'){
    const response=await fetch(base+'/client/v1/recordings/'+row.id+'/audio',{credentials:'omit',headers:{Authorization:'Bearer '+token}});
    if(response.ok){audioURL=URL.createObjectURL(await response.blob());$('player').src=audioURL;}
  }
  const transcript=await api('recordings/'+row.id+'/transcript');$('transcript').textContent=transcript.text||'暂无可用转写。';
  $('minutes-generate').disabled=row.status==='active';
  try{const data=await api('meeting-templates');$('templates').replaceChildren();for(const t of data.templates){const option=document.createElement('option');option.value=t.template_id;option.textContent=t.name;$('templates').append(option);}}catch(e){error(e);}
  await minutes();
}
async function minutes(){
  if(!selected)return;
  const data=await api('recordings/'+selected.id+'/minutes');
  if(!data.jobs?.length){$('minutes').textContent='尚未生成纪要。';return;}
  const job=await api('recordings/'+selected.id+'/minutes/'+data.jobs[0].id);
  $('minutes').textContent=job.job?.result?(job.job.edited_markdown||job.job.result.markdown||JSON.stringify(job.job.result,null,2)):('状态：'+(job.job?.status||'未知')+(job.job?.error?' · '+JSON.stringify(job.job.error):''));
}
$('connection').onsubmit=async event=>{
  event.preventDefault();$('error').textContent='';disconnect();
  try{
    const next=new URL($('server').value);
    if(!['http:','https:'].includes(next.protocol)||next.username||next.password||next.search||next.hash)throw Error('请输入无凭证的 HTTP/HTTPS 服务端地址。');
    if(base!==next.origin||token!==$('token').value.trim()){sid=resume=null;selected=null;}
    base=next.origin;token=$('token').value.trim();
    await api('sessions');await audio.ready();
    const ws=socket=new WebSocket(base.replace(/^http/,'ws')+'/ws');controls();$('status').textContent='正在连接…';
    ws.onopen=()=>{if(socket!==ws)return;ws.send(JSON.stringify({type:'hello',version:1,token,wake_mode:'manual',...(sid?{session_id:sid,resume_token:resume}:{}),audio:{format:'pcm_s16le',sample_rate:16000},capabilities:{echo_cancellation:true}}));};
    ws.onmessage=async event=>{if(socket!==ws)return;try{
      const e=JSON.parse(event.data);
      if(e.type==='hello'){sid=e.session_id;resume=e.resume_token;ready=true;controls();await history();await recordings();ping=setInterval(()=>send({type:'ping'}),20000);poll=setInterval(()=>recordings().catch(error),5000);$('status').textContent='已连接';}
      if(e.type==='error'){if(e.code==='invalid_resume'){sid=resume=null;}throw Error(e.message||e.code);}
      if(e.type==='session.state')$('status').textContent={standby:'已连接 · 待机',listening:'聆听中',thinking:'思考中',speaking:'回复中',recording:'录音中'}[e.state]||e.state;
      if(e.type==='reply.delta')$('partial').textContent+=e.text;
      if(['message.user','reply.final','turn.completed','playback.clear'].includes(e.type)){if(e.type!=='message.user')$('partial').textContent='';await history();}
      if(e.type.startsWith('recording.')){if(e.recording)recording=e.recording.status==='active'?e.recording:null;controls();await recordings();if(e.message)$('error').textContent=e.message;}
      await audio.event(e);
    }catch(e){error(e);}};
    ws.onclose=()=>{if(socket!==ws)return;ready=false;clearInterval(ping);clearInterval(poll);audio.clear();audio.stopMic();controls();$('status').textContent='连接已断开，请重新连接。';};
    ws.onerror=()=>{if(socket===ws)error(Error('连接失败，请检查服务端地址和凭证。'));};
  }catch(e){error(e);}
};
$('disconnect').onclick=disconnect;
$('text-form').onsubmit=event=>{event.preventDefault();const text=$('text').value.trim();if(text&&ready&&!recording){send({type:'input.text',text});$('text').value='';}};
$('mic').onclick=async()=>{try{await audio.microphone();send({type:'session.activate'});$('mic').textContent='语音已开启';}catch(e){error(e);}};
$('interrupt').onclick=()=>{audio.clear();send({type:'interrupt'});};
$('start-recording').onclick=async()=>{try{await audio.microphone();send({type:'recording.start'});}catch(e){error(e);}};
$('pause-recording').onclick=()=>send({type:recording?.paused?'recording.resume':'recording.pause'});
$('stop-recording').onclick=()=>send({type:'recording.stop'});
$('refresh-recordings').onclick=()=>recordings().catch(error);
$('minutes-refresh').onclick=()=>minutes().catch(error);
$('minutes-generate').onclick=async()=>{if(!selected)return;try{await api('recordings/'+selected.id+'/minutes',{method:'POST',body:JSON.stringify({template_id:$('templates').value})});await minutes();}catch(e){error(e);}};
window.addEventListener('pagehide',()=>{disconnect();if(audioURL)URL.revokeObjectURL(audioURL);});
