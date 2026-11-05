// PCM capture and playback are independent from management UI and API modules.
export class ClientAudio {
  constructor(send, packet) { this.send=send; this.packet=packet; this.sources=new Set(); this.next=0; }
  async ready() {
    this.context ||= new AudioContext();
    await this.context.resume();
  }
  async microphone() {
    if (!globalThis.isSecureContext || !navigator.mediaDevices?.getUserMedia)
      throw Error('麦克风需要 localhost 或 HTTPS 安全连接。');
    if (this.stream) return;
    this.stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,channelCount:1},video:false});
    try {
      await this.ready();
      await this.context.audioWorklet.addModule('/demo/assets/capture.js');
      this.input=this.context.createMediaStreamSource(this.stream);
      this.capture=new AudioWorkletNode(this.context,'aihub-capture');
      this.mute=this.context.createGain(); this.mute.gain.value=0;
      this.input.connect(this.capture).connect(this.mute).connect(this.context.destination);
      this.capture.port.onmessage=e=>{if(e.data instanceof ArrayBuffer)this.packet(e.data);};
    } catch(error) { this.stopMic(); throw error; }
  }
  stopMic() {
    this.stream?.getTracks().forEach(t=>t.stop()); this.stream=null;
    this.capture?.disconnect(); this.input?.disconnect(); this.mute?.disconnect();
    if(this.capture)this.capture.port.onmessage=null;
    this.capture=this.input=this.mute=null;
  }
  clear() {
    clearTimeout(this.endTimer); this.turn=null;
    for(const source of this.sources) { try{source.stop();}catch{} }
    this.sources.clear(); this.next=0;
  }
  async event(e) {
    if(e.type==='playback.clear'){this.clear();return;}
    if(e.type==='audio.start'){this.clear();this.turn=e.turn_id;this.rate=e.sample_rate||16000;}
    if(e.type==='audio.chunk'&&e.turn_id===this.turn){
      await this.ready();
      const raw=Uint8Array.from(atob(e.data),c=>c.charCodeAt(0));
      if(raw.length%2)throw Error('收到无效 PCM 音频。');
      const pcm=new DataView(raw.buffer), buffer=this.context.createBuffer(1,raw.length/2,this.rate);
      const samples=buffer.getChannelData(0);
      for(let i=0;i<samples.length;i++)samples[i]=pcm.getInt16(i*2,true)/32768;
      if(this.next-this.context.currentTime>.5){this.clear();this.send({type:'interrupt'});return;}
      const source=this.context.createBufferSource(); source.buffer=buffer;source.connect(this.context.destination);
      this.next=Math.max(this.next,this.context.currentTime+.015);source.start(this.next);this.next+=buffer.duration;
      this.sources.add(source);source.onended=()=>this.sources.delete(source);
    }
    if(e.type==='audio.end'&&e.turn_id===this.turn){
      const turn=e.turn_id;
      this.endTimer=setTimeout(()=>{if(this.turn===turn)this.send({type:'playback.done',turn_id:turn});},Math.max(0,(this.next-(this.context?.currentTime||0))*1000)+60);
    }
  }
}
