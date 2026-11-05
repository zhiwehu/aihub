"""Local music search and playback; the configured directory is never a model argument."""
import asyncio
import json
import os
from pathlib import Path
from ..music_player import MusicPlayer
from ..settings import data_root, load_tool_settings

SCHEMA=('搜索和播放管理员配置目录中的本地音乐，支持暂停、继续、停止和播放状态。声音输出到发起请求的网页或语音设备。',{
    'action':{'type':'string','enum':['search','play','pause','resume','stop','status']},
    'query':{'type':'string','maxLength':80,'description':'歌名关键词，可选；多首匹配时先让用户选择。'},
    'track_id':{'type':'string','maxLength':20,'description':'搜索返回的歌曲标识，可选。'}})
REQUIRED=['action']
ACKNOWLEDGEMENT='我来处理本地音乐，请稍等。'
READ_ONLY=False

async def execute(http,action,query='',track_id=''):
    root=data_root()
    config=load_tool_settings(root)
    if not config.get('music'):raise ValueError('music_disabled')
    player=MusicPlayer(root,config.get('music_directory',''))
    if action!='search':raise ValueError('music_session_required')
    return await asyncio.to_thread(player.execute,action,query,track_id)


def spoken_summary(result):
    value=json.loads(result['content'][0]['text']);status=value.get('status');title=value.get('title','')
    track='《'+title+'》' if title else '音乐'
    if status=='queued':return '准备播放'+track+'。'
    if status=='playing':return '正在播放'+track+'。'
    if status=='paused':return '已暂停'+track+'。'
    if status=='stopped':return '音乐已停止。'
    if status=='failed':return '这首音乐暂时播放失败。'
    if status=='not_found':return '曲库里没有找到匹配的歌曲。'
    if status=='needs_selection':return '找到多首歌曲，请选一首：'+'、'.join(t['title'] for t in value['tracks'])+'。'
    tracks=value.get('tracks',[])
    return '找到的歌曲：'+'、'.join(t['title'] for t in tracks)+'。' if tracks else '曲库里没有找到匹配的歌曲。'
