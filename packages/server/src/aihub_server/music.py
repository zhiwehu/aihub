"""One client owns one music stream; no shared host audio device or public files."""
import asyncio
import base64
import contextlib
import sys
import secrets
import time
import uuid
from pathlib import Path
from aihub_tools.music_player import MusicPlayer


class ClientMusic:
    def __init__(self,session,root,settings):
        self.session,self.root,self.settings=session,root,settings
        self.track=None;self.position=0;self.state='stopped';self.task=None;self.process=None
        self.audio_active=False;self.closed=False
        self.lock=asyncio.Lock()
        self.volume=50;self.volume_before_mute=50;self.resume_after_control=False
        self.volume_pending={};self.volume_lock=asyncio.Lock()

    @property
    def playing(self):return self.state=='playing'

    async def event(self,reason=None):
        await self.session.emit('music.state',state=self.state,position=round(self.position,2),reason=reason,
                                **({k:v for k,v in self.track.items() if not k.startswith('_')} if self.track else {}))

    async def call(self,action,query='',track_id=''):
        async with self.lock:
            if self.closed or self.session.closed:raise ValueError('music_session_closed')
            cfg=self.settings()
            if not cfg.get('music'):raise ValueError('music_disabled')
            self.resume_after_control=False
            self.last_action=action
            if action in ('pause','stop'):
                await self.pause(stop=action=='stop',reason=action);return self.result()
            if action=='status':return self.result()
            if action=='resume':
                if self.track and self.state=='paused':await self.schedule()
                return self.result()
            if action not in ('search','play','next','random'):raise ValueError('music_action_invalid')
            if not isinstance(query,str) or len(query)>80 or not isinstance(track_id,str) or len(track_id)>20:raise ValueError('music_query_invalid')
            rows,truncated=await asyncio.to_thread(MusicPlayer(self.root,cfg.get('music_directory','')).library)
            rows=[t for t in rows if (not query or query.casefold() in t['title'].casefold()) and (not track_id or t['track_id']==track_id)]
            public=lambda t:{k:v for k,v in t.items() if not k.startswith('_')}
            if action=='search':return {'tracks':[public(t) for t in rows[:20]],'matches':len(rows),'truncated':truncated}
            if not rows:return {'status':'not_found'}
            if len(rows)>1 and (query or track_id) and action=='play':return {'status':'needs_selection','tracks':[public(t) for t in rows[:10]]}
            selected=rows[0]
            if action=='next' and self.track:
                index=next((i for i,t in enumerate(rows) if t['track_id']==self.track['track_id']),-1)
                selected=rows[(index+1)%len(rows)]
            elif action=='random':selected=secrets.choice([t for t in rows if not self.track or t['track_id']!=self.track['track_id']] or rows)
            await self.pause(stop=True,reason=action)
            self.track=selected;self.position=0
            await self.schedule();return self.result()

    def result(self):
        return {'status':self.state,'action':getattr(self,'last_action','status'),'position':round(self.position,2),'output':'requesting_client',
                **({k:v for k,v in self.track.items() if not k.startswith('_')} if self.track else {})}

    async def schedule(self):
        self.state='queued';self.task=asyncio.create_task(self.stream());await self.event()

    async def pause(self,*,stop=False,reason='control'):
        task,self.task=self.task,None
        if task:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
        active,self.audio_active=self.audio_active,False
        if active:await self.session.emit('playback.clear',media_turn_id=getattr(self,'playback_id',None),reason='music_stop' if stop else 'music_pause')
        self.state='stopped' if stop or not self.track else 'paused'
        if stop:self.position=0;self.track=None
        if active:
            self.session.streaming=False
            await self.session.transition('listening')
        await self.event(reason)

    async def stream(self):
        session=self.session;process=None
        try:
            while session.turn or session.input_active or session.recording is not None or session.notification_ids:
                if self.closed or session.closed:return
                await asyncio.sleep(.05)
            if self.closed or session.closed:return
            cfg=self.settings();base=Path(cfg.get('music_directory','')).expanduser().resolve();path=Path(self.track['_path']).resolve()
            if not cfg.get('music') or not path.is_relative_to(base) or not path.is_file():raise ValueError('music_directory_unavailable')
            self.playback_id=uuid.uuid4().hex
            spawning=asyncio.create_task(asyncio.create_subprocess_exec(sys.executable,'-m','aihub_server.music_decode',str(path),'--offset',str(self.position),
                    stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,limit=12800))
            try:process=self.process=await asyncio.shield(spawning)
            except asyncio.CancelledError:
                process=self.process=await spawning
                raise
            first=await asyncio.wait_for(process.stdout.read(1280),10)
            if not first:raise ValueError('music_decode_failed')
            self.audio_active=True
            await session.emit('audio.start',media_turn_id=self.playback_id,purpose='music',sample_rate=16000,format='pcm_s16le',channels=1)
            session.streaming=True;self.state='playing';await session.transition('speaking');await self.event()
            deadline=time.monotonic()-.08;pending=first
            while pending:
                size=len(pending)//2*2
                if size:
                    block=pending[:size];pending=pending[size:]
                    await asyncio.sleep(max(0,deadline-time.monotonic()))
                    await session.emit('audio.chunk',media_turn_id=self.playback_id,purpose='music',data=base64.b64encode(block).decode())
                    duration=len(block)/32000;self.position+=duration;deadline=max(deadline,time.monotonic()-.08)+duration
                    session.last_activity=time.monotonic()
                    if self.position>=10800:raise ValueError('music_duration_limit')
                pending+=await asyncio.wait_for(process.stdout.read(1280),10)
                if len(pending)==1 and process.stdout.at_eof():raise ValueError('music_decode_failed')
            if await process.wait():raise ValueError('music_decode_failed')
            await session.emit('audio.end',media_turn_id=self.playback_id,purpose='music',drain_ms=max(0,round((deadline+.08-time.monotonic())*1000)))
            await asyncio.sleep(max(0,deadline+.08-time.monotonic()))
            self.audio_active=False;self.state='stopped';session.streaming=False
            await session.transition('listening');await self.event()
        except asyncio.CancelledError:raise
        except Exception as exc:
            self.state='failed';session.streaming=False
            if self.audio_active:
                await session.emit('playback.clear',reason='music_failed');self.audio_active=False
            with contextlib.suppress(Exception):
                await session.transition('listening');await self.event()
                await session.emit('music.failed',code='music_decode_failed',error_class=type(exc).__name__)
                if session.operations and not self.closed and not session.closed:
                    session.operations.notify(getattr(self,'playback_id',uuid.uuid4().hex),session.id,'音乐播放','这首音乐暂时播放失败。',kind='music_failure',status='failed')
        finally:
            if process and process.returncode is None:
                with contextlib.suppress(ProcessLookupError):process.terminate()
                try:await asyncio.wait_for(process.wait(),2)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):process.kill()
                    await process.wait()
            if self.process is process:self.process=None

    def volume_applied(self,identity,volume):
        pending=self.volume_pending.get(identity)
        if not pending or type(volume) is not int or volume!=pending[1]:return False
        self.volume=volume;pending[0].set();return True

    def manual_volume(self,volume):
        if type(volume) is not int or not 0<=volume<=100:raise ValueError('invalid_music_volume')
        self.volume=volume

    async def volume_action(self,arguments):
        from aihub_tools.errors import DeviceMCPError
        async with self.volume_lock:
            action=arguments.get('action','status');value=arguments.get('value')
            if action=='status':return {'volume':self.volume},f'音乐音量是 {self.volume}。'
            if action=='set' and (type(value) is not int or not 0<=value<=100):raise DeviceMCPError('volume_value_required')
            if action=='set':target=value
            elif action in ('up','down'):
                step=value if type(value) is int and value>0 else 10
                target=max(0,min(100,self.volume+(step if action=='up' else -step)))
            elif action=='mute':
                if self.volume:self.volume_before_mute=self.volume
                target=0
            elif action=='unmute':target=self.volume_before_mute or 50
            else:raise DeviceMCPError('invalid_volume_action')
            identity=uuid.uuid4().hex;done=asyncio.Event();self.volume_pending[identity]=(done,target)
            try:
                await self.session.emit('music.volume',request_id=identity,volume=target)
                try:await asyncio.wait_for(done.wait(),2)
                except TimeoutError:raise DeviceMCPError('client_volume_timeout') from None
            finally:self.volume_pending.pop(identity,None)
            if self.resume_after_control and self.track and self.state=='paused':
                self.resume_after_control=False;await self.schedule()
            return {'volume':target,'output':'requesting_client'},f'音乐音量调到 {target} 了。'

    async def close(self):
        self.closed=True;await self.pause(stop=True)
