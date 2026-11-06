import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,MagicMock
from aihub_tools.music_player import MusicPlayer

class MusicTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.library=self.root/'library';self.library.mkdir()
        self.player=MusicPlayer(self.root/'state',str(self.library))
    def tearDown(self):self.tmp.cleanup()
    def test_library_rejects_outside_symlink_and_never_exposes_paths(self):
        (self.root/'private.mp3').write_bytes(b'test')
        (self.library/'escape.mp3').symlink_to(self.root/'private.mp3')
        (self.library/'loop.mp3').symlink_to(self.library/'loop.mp3')
        (self.library/'Song.mp3').write_bytes(b'test')
        result=self.player.execute('search')
        self.assertEqual(result['matches'],1)
        self.assertNotIn(str(self.root),json.dumps(result))
        self.assertEqual(self.player.execute('play',track_id='../private.mp3')['status'],'not_found')
    def test_ambiguous_song_does_not_play(self):
        for name in ('Song one.mp3','Song two.wav'):(self.library/name).write_bytes(b'test')
        with patch('aihub_tools.music_player.subprocess.Popen',side_effect=AssertionError('Must not play')):
            self.assertEqual(self.player.execute('play',query='Song')['status'],'needs_selection')
    def test_unowned_pid_is_never_signalled(self):
        self.player.state.write_text(json.dumps({'pid':123,'created':0,'path':'/outside'}))
        process=MagicMock();process.create_time.return_value=99
        with patch('aihub_tools.music_player.psutil.Process',return_value=process):
            self.assertEqual(self.player.execute('stop')['status'],'stopped')
        process.terminate.assert_not_called();process.send_signal.assert_not_called()

    def test_failed_ownership_record_stops_the_new_player(self):
        child=MagicMock();child.pid=12345;child.poll.return_value=None
        process=MagicMock();process.create_time.return_value=123.0
        tracks=[{'track_id':'sample','title':'song','_path':'/configured/song.wav'}]
        with patch.object(self.player,'library',return_value=(tracks,False)), \
             patch('aihub_tools.music_player.Path.is_file',return_value=True), \
             patch('aihub_tools.music_player.subprocess.Popen',return_value=child), \
             patch('aihub_tools.music_player.psutil.Process',return_value=process), \
             patch.object(self.player,'_save',side_effect=OSError('test disk failure')):
            with self.assertRaisesRegex(ValueError,'music_playback_failed'):self.player.execute('play')
        child.terminate.assert_called_once();child.wait.assert_called_once()

class ClientMusicToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_uses_the_requesting_session_and_does_not_claim_queued_music_is_playing(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from aihub_tools.tool_chat import chat
        from aihub_tools.tools import catalogue,ToolStatus
        tools={t['name']:True for t in catalogue()};tools.update(planner='rex',default_city='合肥',news_source='chinanews',news_limit=3,timeout_seconds=20,music_directory='')
        music=SimpleNamespace(call=AsyncMock(return_value={'status':'queued','title':'Song','output':'requesting_client'}))
        async def raw(*args,**kwargs):raise AssertionError('music results must not be invented by the model');yield ''
        p=SimpleNamespace(config={'tools':tools,'system_prompt':''},runtime=SimpleNamespace(workflows=None,skills=None,calendar=None,extensions=None,operations=None),music=music,raw_chat=raw)
        values=[v async for v in chat(p,[{'role':'user','content':'播放音乐'}])]
        music.call.assert_awaited_once_with(action='play')
        self.assertEqual(values[-1],'这就播放。')
        self.assertNotIn('正在播放',values[-1])
        self.assertTrue(any(isinstance(v,ToolStatus) and v.phase=='completed' for v in values))

    async def test_stdio_without_a_client_never_starts_host_playback(self):
        from aihub_tools.mcp_tools import music
        with patch.object(music,'load_tool_settings',return_value={'music':True,'music_directory':'/configured'}),patch('aihub_tools.music_player.subprocess.Popen',side_effect=AssertionError('Must not use host audio')):
            with self.assertRaisesRegex(ValueError,'music_session_required'):await music.execute(None,'play')

    async def test_decode_failure_is_not_reported_as_an_empty_library(self):
        from aihub_tools.mcp_tools.music import spoken_summary
        text=spoken_summary({'content':[{'text':'{"status":"failed"}'}]})
        self.assertEqual(text,'这首音乐暂时播放失败。')

    async def test_common_music_controls_are_deterministic_without_a_planner(self):
        from aihub_tools.extension_routing import music_plan
        for text,action in [('换一首','next'),('下一首','next'),('随机播放音乐','random'),('暂停','pause'),('继续','resume')]:
            with self.subTest(text=text):self.assertEqual(music_plan(text,active=True),{'action':action})
        self.assertIsNone(music_plan('暂停',active=False))

    async def test_explicit_music_commands_have_one_short_reply_without_background_notice(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from aihub_tools.tool_chat import chat
        from aihub_tools.tools import catalogue,ToolNotice
        tools={t['name']:True for t in catalogue()};tools.update(planner='rex',default_city='合肥',news_source='chinanews',news_limit=3,timeout_seconds=20,music_directory='')
        async def raw(*args,**kwargs):raise AssertionError('local controls must not wait for a model');yield ''
        for text,action in [('播放音乐','play'),('下一首','next'),('随机播放音乐','random'),('暂停','pause'),('继续播放','resume'),('停止播放','stop')]:
            with self.subTest(text=text):
                music=SimpleNamespace(track={'title':'song'},state='paused',call=AsyncMock(return_value={'status':'queued','title':'A very long artist and track file name that must not be spoken in full','action':action}))
                p=SimpleNamespace(config={'tools':tools,'system_prompt':''},runtime=SimpleNamespace(workflows=None,skills=None,calendar=None,extensions=None,operations=object()),music=music,raw_chat=raw)
                values=[v async for v in chat(p,[{'role':'user','content':text}])]
                self.assertFalse(any(isinstance(v,ToolNotice) for v in values))
                replies=[v for v in values if isinstance(v,str)]
                self.assertEqual(len(replies),1);self.assertLessEqual(len(replies[0]),16)
                music.call.assert_awaited_once_with(action=action)

    async def test_web_volume_never_contacts_the_robot_bridge(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from aihub_tools.tool_chat import chat
        bridge=SimpleNamespace(call=AsyncMock(side_effect=AssertionError('web volume must not contact robot')))
        music=SimpleNamespace(volume_action=AsyncMock(return_value=({'volume':60},'音乐音量调到 60 了。')))
        p=SimpleNamespace(config={'tools':{'device_volume':True}},client_type='web',device=bridge,music=music,runtime=SimpleNamespace(skills=None))
        values=[v async for v in chat(p,[{'role':'user','content':'加大音量'}])]
        music.volume_action.assert_awaited_once_with({'action':'up'})
        bridge.call.assert_not_awaited();self.assertEqual(values[-1],'音乐音量调到 60 了。')
