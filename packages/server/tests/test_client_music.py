import asyncio
import base64
import math
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase,TestCase
import wave
from aihub_server.music import ClientMusic
from aihub_server.music_decode import decode
from aihub_server.session import Session
from aihub_server.store import Store


def song(path,seconds=3,rate=24000):
    with wave.open(str(path),'wb') as out:
        out.setnchannels(2);out.setsampwidth(2);out.setframerate(rate)
        out.writeframes(b''.join(struct.pack('<hh',int(5000*math.sin(i*2*math.pi*440/rate)),0) for i in range(int(seconds*rate))))


class DecodeTests(TestCase):
    def test_resampling_and_resume_offset_preserve_pcm_duration(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'song.wav';song(path,1)
            pcm=b''.join(decode(str(path)));tail=b''.join(decode(str(path),.5))
            self.assertEqual(len(pcm),32000)
            self.assertLessEqual(abs(len(tail)-16000),64)
            self.assertTrue(any(pcm));self.assertEqual(len(tail)%2,0)


class ClientMusicTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.library=self.root/'library';self.library.mkdir();song(self.library/'song.wav')
        self.store=Store(self.root/'history.sqlite3');self.events=[];self.other_events=[]
        self.cfg={'music':True,'music_directory':str(self.library)}
        def pipeline():
            async def speech(text):yield b'\0\0'*320
            async def chat(history):yield '回答。'
            return SimpleNamespace(runtime=SimpleNamespace(data_root=self.root,tool_settings=lambda:self.cfg),speech=speech,chat=chat)
        async def send(event):self.events.append(event)
        async def other(event):self.other_events.append(event)
        self.session=Session('one','fixture',self.store,pipeline(),send,playback_ack=False)
        self.second=Session('two','fixture2',self.store,pipeline(),other,playback_ack=False)

    async def asyncTearDown(self):
        await self.session.close();await self.second.close();self.store.close();self.tmp.cleanup()

    async def wait(self,predicate):
        async with asyncio.timeout(5):
            while not predicate():await asyncio.sleep(.01)

    async def test_queued_music_waits_for_reply_and_is_scoped_to_one_client(self):
        self.session.turn=SimpleNamespace(id='busy')
        result=await self.session.music.call('play')
        self.assertEqual(result['status'],'queued');self.assertNotIn(str(self.root),str(result))
        await asyncio.sleep(.1);self.assertFalse(any(e['type']=='audio.start' for e in self.events))
        self.session.turn=None
        await self.wait(lambda:any(e['type']=='audio.chunk' for e in self.events))
        audio=next(e for e in self.events if e['type']=='audio.start')
        self.assertEqual(audio['purpose'],'music');self.assertEqual(audio['sample_rate'],16000)
        self.assertTrue(audio['turn_id']);self.assertFalse(self.other_events)
        pcm=base64.b64decode(next(e for e in self.events if e['type']=='audio.chunk')['data'])
        self.assertTrue(pcm);self.assertEqual(len(pcm)%2,0)

    async def test_pause_resume_and_disconnect_stop_the_decoder(self):
        await self.session.music.call('play');await self.wait(lambda:self.session.music.position>.1)
        await self.session.music.call('pause');position=self.session.music.position
        self.assertEqual(self.session.music.state,'paused');self.assertIsNone(self.session.music.process)
        await self.session.music.call('resume');await self.wait(lambda:self.session.music.position>position+.04)
        await self.session.close();self.assertIsNone(self.session.music.process)
        count=len(self.events);await asyncio.sleep(.1);self.assertEqual(len(self.events),count)

    async def test_new_question_pauses_music_without_discarding_selected_track(self):
        await self.session.music.call('play');await self.wait(lambda:self.session.music.playing)
        await self.session.submit('新问题')
        self.assertEqual(self.session.music.state,'paused');self.assertIsNotNone(self.session.music.track)
        await self.session.turn.task
        self.assertFalse(self.session.music.playing)

    async def test_outside_symlinks_and_foreign_track_ids_do_not_expose_files(self):
        song(self.root/'private.wav');(self.library/'escape.wav').symlink_to(self.root/'private.wav')
        data=await self.session.music.call('search');self.assertEqual(data['matches'],1)
        self.assertNotIn(str(self.root),str(data))
        self.assertEqual((await self.session.music.call('play',track_id='../private'))['status'],'not_found')

    async def test_disabling_music_stops_future_controls(self):
        self.cfg['music']=False
        with self.assertRaisesRegex(ValueError,'music_disabled'):await self.session.music.call('play')

    async def test_stop_during_decoder_spawn_still_reaps_the_child(self):
        from unittest.mock import patch
        song(self.library/'song.wav',10)
        original=asyncio.create_subprocess_exec;started=asyncio.Event();release=asyncio.Event();children=[]
        async def delayed(*args,**kwargs):
            child=await original(*args,**kwargs);children.append(child);started.set();await release.wait();return child
        with patch('aihub_server.music.asyncio.create_subprocess_exec',side_effect=delayed):
            await self.session.music.call('play');await asyncio.wait_for(started.wait(),5)
            stopping=asyncio.create_task(self.session.music.call('stop'))
            await asyncio.sleep(.01);release.set();await asyncio.wait_for(stopping,5)
        self.assertIsNotNone(children[0].returncode);self.assertIsNone(self.session.music.process)


    async def test_corrupt_audio_is_reported_without_starting_playback_or_leaking_paths(self):
        from aihub_tools.background import Operations
        (self.library/'song.wav').write_bytes(b'not an audio file')
        ops=self.session.operations=Operations(self.root)
        try:
            await self.session.music.call('play')
            await self.wait(lambda:self.session.music.state=='failed' and self.session.music.process is None)
            self.assertFalse(any(e['type']=='audio.start' for e in self.events))
            self.assertTrue(any(e['type']=='music.failed' for e in self.events))
            record=ops.pending('one')[0];self.assertEqual(record['status'],'failed')
            self.assertEqual(record['text'],'这首音乐暂时播放失败。');self.assertNotIn(str(self.root),record['text'])
        finally:await ops.close()


    async def test_next_and_random_choose_another_track(self):
        song(self.library/'second.wav');song(self.library/'third.wav')
        first=await self.session.music.call('play')
        following=await self.session.music.call('next')
        self.assertNotEqual(first['track_id'],following['track_id'])
        for _ in range(4):
            random_track=await self.session.music.call('random')
            self.assertNotEqual(following['track_id'],random_track['track_id']);following=random_track
        await self.session.music.call('stop')

    async def test_web_volume_waits_for_own_client_and_resumes_interrupted_music(self):
        self.session.pipeline.client_type='web'
        await self.session.music.call('play');await self.wait(lambda:self.session.music.playing)
        await self.session.interrupt('new_input')
        change=asyncio.create_task(self.session.music.volume_action({'action':'up'}))
        await self.wait(lambda:any(e['type']=='music.volume' for e in self.events))
        event=next(e for e in self.events if e['type']=='music.volume')
        self.assertFalse(change.done());self.assertEqual(event['volume'],60)
        self.assertFalse(self.second.music.volume_applied(event['request_id'],60))
        self.assertTrue(self.session.music.volume_applied(event['request_id'],60))
        result,sentence=await change
        self.assertEqual(result['volume'],60);self.assertIn('60',sentence)
        await self.wait(lambda:self.session.music.playing)
        self.assertEqual(self.second.music.volume,50)


class LegacyMusicTests(IsolatedAsyncioTestCase):
    async def test_device_ready_handshake_accepts_session_owned_music_and_receives_opus(self):
        from aiohttp import WSMsgType
        from aiohttp.test_utils import TestClient,TestServer
        from aihub_server.app import create_app,HUB
        from aihub_server.audio import AudioCodec
        with tempfile.TemporaryDirectory() as root:
            library=Path(root)/'library';library.mkdir();song(library/'song.wav',1)
            app=create_app(root,pipeline_factory=lambda c,h,r:SimpleNamespace(config=c,runtime=r))
            client=TestClient(TestServer(app));await client.start_server()
            try:
                hub=app[HUB];cfg=hub.config.get();cfg['tools'].update(music=True,music_directory=str(library));hub.config.save(cfg)
                ws=await client.ws_connect('/xiaozhi/v1/',headers={'Authorization':'Bearer '+hub.auth['device_token']})
                await ws.send_json({'type':'hello','version':1,'device_id':'music-device','features':{'playback_ready':True},'audio_params':{'format':'opus','sample_rate':16000,'channels':1,'frame_duration':60}})
                hello=await ws.receive_json();session=hub.sessions[hello['session_id']]
                await session.music.call('play')
                async with asyncio.timeout(6):
                    while True:
                        message=await ws.receive()
                        if message.type==WSMsgType.TEXT:
                            e=message.json()
                            if e.get('type')=='tts' and e.get('state')=='start':
                                await ws.send_json({'type':'tts','state':'ready','turn_id':e['turn_id'],'device_state':6,'output_enabled':True,'rx_audio_packets':0,'dropped_audio_packets':0,'decoded_audio_packets':0,'played_audio_packets':0})
                        elif message.type==WSMsgType.BINARY:
                            pcm=AudioCodec('opus').decode(message.data);self.assertTrue(pcm);break
                self.assertTrue(session.music.playing);self.assertIsNone(session.turn)
                await ws.close()
            finally:await client.close()
