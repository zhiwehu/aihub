"""Local music search and playback; the configured directory is never a model argument."""
import asyncio
import json
import os
from pathlib import Path
from ..music_player import MusicPlayer
from ..settings import data_root, load_tool_settings

SCHEMA=('搜索和播放管理员配置目录中的本地音乐，支持暂停、继续、停止和播放状态。声音输出在后端电脑。',{
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
    return await asyncio.to_thread(player.execute,action,query,track_id)
