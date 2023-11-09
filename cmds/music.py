import asyncio
import functools
import itertools
import math
import random

import discord
import youtube_dl
from async_timeout import timeout
from discord.ext import commands

# Silence useless bug reports messages
youtube_dl.utils.bug_reports_message = lambda: ''

class VoiceError(Exception):
    pass

class YTDLError(Exception):
    pass

class YTDLSource(discord.PCMVolumeTransformer):
    YTDL_OPTIONS = {
        'format': 'bestaudio/best',
        'extractaudio': True,
        'audioformat': 'mp3',
        'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0',
    }

    FFMPEG_OPTIONS = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn',
    }

    ytdl = youtube_dl.YoutubeDL(YTDL_OPTIONS)

    def __init__(self, ctx: commands.Context, source: discord.FFmpegPCMAudio, *, data: dict, volume: float = 0.5):
        super().__init__(source, volume)

        self.requester = ctx.author
        self.channel = ctx.channel
        self.data = data

        self.uploader = data.get('uploader')                                    #上傳者
        self.uploader_url = data.get('uploader_url')                            #上傳者網址
        date = data.get('upload_date')                                          #上傳日期
        self.upload_date = date[6:8] + '.' + date[4:6] + '.' + date[0:4]        #?
        self.title = data.get('title')                                          #標題
        self.thumbnail = data.get('thumbnail')                                  #影片縮圖
        self.description = data.get('description')                              #描述
        self.duration = self.parse_duration(int(data.get('duration')))          #影片長度(秒)
        self.tags = data.get('tags')                                            #標籤
        self.url = data.get('webpage_url')                                      #網頁網址
        self.views = data.get('view_count')                                     #觀看次數
        self.likes = data.get('like_count')                                     #喜歡數
        self.dislikes = data.get('dislike_count')                               #不喜歡數
        self.stream_url = data.get('url')                                       #?

    def __str__(self):
        return '**{0.title}** by **{0.uploader}**'.format(self)

    @classmethod
    async def create_source(cls, ctx: commands.Context, search: str, *, loop: asyncio.BaseEventLoop = None):
        loop = loop or asyncio.get_event_loop()

        partial = functools.partial(cls.ytdl.extract_info, search, download=False, process=False)
        data = await loop.run_in_executor(None, partial)

        if data is None:
            raise YTDLError('找不到任何匹配的內容 `{}`'.format(search))

        if 'entries' not in data:
            process_info = data
        else:
            process_info = None
            for entry in data['entries']:
                if entry:
                    process_info = entry
                    break

            if process_info is None:
                raise YTDLError('找不到任何匹配的內容 `{}`'.format(search))

        webpage_url = process_info['webpage_url']
        partial = functools.partial(cls.ytdl.extract_info, webpage_url, download=False)
        processed_info = await loop.run_in_executor(None, partial)

        if processed_info is None:
            raise YTDLError('無法獲取 `{}`'.format(webpage_url))

        if 'entries' not in processed_info:
            info = processed_info
        else:
            info = None
            while info is None:
                try:
                    info = processed_info['entries'].pop(0)
                except IndexError:
                    raise YTDLError('找不到任何匹配項目 `{}`'.format(webpage_url))

        return cls(ctx, discord.FFmpegPCMAudio(info['url'], **cls.FFMPEG_OPTIONS), data=info)

    @staticmethod
    def parse_duration(duration: int):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        duration = []
        if days > 0:
            duration.append('{} days'.format(days))
        if hours > 0:
            duration.append('{} hours'.format(hours))
        if minutes > 0:
            duration.append('{} minutes'.format(minutes))
        if seconds > 0:
            duration.append('{} seconds'.format(seconds))

        return ', '.join(duration)

class Song:
    __slots__ = ('source', 'requester')

    def __init__(self, source: YTDLSource):
        self.source = source
        self.requester = source.requester

    def create_embed(self):
        embed = (discord.Embed(title='現在播放',
                               description='```css\n{0.source.title}\n```'.format(self),
                               color=discord.Color.blurple())
                 .add_field(name='音樂總長', value=self.source.duration)
                 .add_field(name='播放者', value=self.requester.mention)
                 .add_field(name='上傳者', value='[{0.source.uploader}]({0.source.uploader_url})'.format(self))
                 .add_field(name='網址', value='[Click]({0.source.url})'.format(self))
                 .set_thumbnail(url=self.source.thumbnail))

        return embed

class SongQueue(asyncio.Queue):
    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(itertools.islice(self._queue, item.start, item.stop, item.step))
        else:
            return self._queue[item]

    def __iter__(self):
        return self._queue.__iter__()

    def __len__(self):
        return self.qsize()

    def clear(self):
        self._queue.clear()

    def shuffle(self):
        random.shuffle(self._queue)

    def remove(self, index: int):
        del self._queue[index]

class VoiceState:
    #建構函式
    def __init__(self, bot: commands.Bot, ctx: commands.Context):
        self.bot = bot
        self._ctx = ctx

        self.current = None
        self.voice = None
        self.next = asyncio.Event()
        self.songs = SongQueue()

        self._loop = False
        self._volume = 0.5
        self.skip_votes = set()

        self.audio_player = bot.loop.create_task(self.audio_player_task())
    #解構函式
    def __del__(self):
        self.audio_player.cancel()

    @property
    def loop(self):
        return self._loop

    @loop.setter
    def loop(self, value: bool):
        self._loop = value

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = value

    @property
    def is_playing(self):
        return self.voice and self.current

    async def audio_player_task(self):
        while True:
            self.next.clear()

            if not self.loop:
                #未加入任何曲目將會因為性能問題在1分鐘後斷線
                try:
                    async with timeout(60):  # 1 minutes
                        self.current = await self.songs.get()
                except asyncio.TimeoutError:
                    self.bot.loop.create_task(self.stop())
                    return

            self.current.source.volume = self._volume
            self.voice.play(self.current.source, after=self.play_next_song)
            await self.current.source.channel.send(embed=self.current.create_embed())
            await self.next.wait()

    def play_next_song(self, error=None):
        if error:
            raise VoiceError(str(error))
        self.next.set()

    def skip(self):
        self.skip_votes.clear()

        if self.is_playing:
            self.voice.stop()

    async def stop(self):
        self.songs.clear()

        if self.voice:
            await self.voice.disconnect()
            self.voice = None

class music(commands.Cog):
    #建構函式
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}
    #回傳使用指令的訊息
    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state
        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('這個指令無法在DM頻道上使用')

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.voice_state = self.get_voice_state(ctx)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        await ctx.send('發生錯誤: {}'.format(str(error)))

    @commands.command(name='join', invoke_without_subcommand=True)
    async def _join(self, ctx: commands.Context):
        """加入到輸入者的語音頻道"""

        destination = ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            await ctx.send("Bot已移動到: {}".format(destination))
            return
        self.JoinAndPlay_ctx = ctx
        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='summon')
    #@commands.has_permissions(manage_guild=True)
    async def _summon(self, ctx: commands.Context, *, channel: discord.VoiceChannel = None):
        """召喚到所指定的語音頻道 如果未指定 將加入輸入者的的語音頻道中
        """

        if not channel and not ctx.author.voice:
            raise VoiceError('你沒有加入任何語音頻道 也沒有指定加入的頻道')

        destination = channel or ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()
    @commands.command(name='leave', aliases=['disconnect'])
    #@commands.has_permissions(manage_guild=True)
    async def _leave(self, ctx: commands.Context):
        """清除清單並離開語音"""

        if not ctx.voice_state.voice:
            return await ctx.send('尚未連接語音頻道')

        await ctx.voice_state.stop()
        del self.voice_states[ctx.guild.id]

    @commands.command(name='volume')
    async def _volume(self, ctx: commands.Context, *, volume: int):
        """設定播放音量
        $volume (數值)"""

        if not ctx.voice_state.is_playing:
            return await ctx.send('沒有撥放的歌曲')

        if 0 > volume > 100:
            return await ctx.send('音量設定必須設置於0~100間')

        ctx.voice_state.volume = volume / 100
        await ctx.send('下一首歌曲後音量調整為{}%'.format(volume))

    @commands.command(name='now', aliases=['current', 'playing'])
    async def _now(self, ctx: commands.Context):
        """現在撥放歌曲的資訊"""

        await ctx.send(embed=ctx.voice_state.current.create_embed())

    @commands.command(name='pause')
    #@commands.has_permissions(manage_guild=True)
    async def _pause(self, ctx: commands.Context):
        """暫停歌曲"""

        """if not ctx.voice_state.is_playing and ctx.voice_state.voice.is_playing():
            ctx.voice_state.voice.pause()
            await ctx.message.add_reaction('⏯')"""
        if ctx.voice_state.voice.is_playing():
            ctx.voice_state.voice.pause()
            await ctx.message.add_reaction('⏯')

    @commands.command(name='resume')
    #@commands.has_permissions(manage_guild=True)
    async def _resume(self, ctx: commands.Context):
        """恢復播放歌曲"""

        if ctx.voice_state.voice.is_paused():
            ctx.voice_state.voice.resume()
            await ctx.message.add_reaction('⏯')

    @commands.command(name='stop')
    #@commands.has_permissions(manage_guild=True)
    async def _stop(self, ctx: commands.Context):
        """停止歌曲並清除清單"""

        ctx.voice_state.songs.clear()

        if not ctx.voice_state.is_playing:
            ctx.voice_state.voice.stop()
            await ctx.message.add_reaction('⏹')

    @commands.command(name='skip')
    async def _skip(self, ctx: commands.Context):
        """跳過當前歌曲 如果不是撥放者點播 那累計人數超過三人即可跳過(輸入$skip)
        """

        if not ctx.voice_state.is_playing:
            return await ctx.send('音樂還未撥放')

        voter = ctx.message.author
        if voter == ctx.voice_state.current.requester:
            await ctx.message.add_reaction('⏭')
            ctx.voice_state.skip()

        elif voter.id not in ctx.voice_state.skip_votes:
            ctx.voice_state.skip_votes.add(voter.id)
            total_votes = len(ctx.voice_state.skip_votes)

            if total_votes >= 3:
                await ctx.message.add_reaction('⏭')
                ctx.voice_state.skip()
            else:
                await ctx.send('想跳過歌曲的人數 **{}/3**'.format(total_votes))

        else:
            await ctx.send('你已投票跳過該歌曲')

    @commands.command(name='queue')
    async def _queue(self, ctx: commands.Context, *, page: int = 1):
        """顯示清單內容 可以指令所想看的頁面
        $queue
        $queue (頁數)
        """

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('沒有待播歌曲')
        items_per_page = 10
        pages = math.ceil(len(ctx.voice_state.songs) / items_per_page)
        start = (page - 1) * items_per_page
        end = start + items_per_page

        queue = ''
        for i, song in enumerate(ctx.voice_state.songs[start:end], start=start):
            queue += '`{0}.` [**{1.source.title}**]({1.source.url})\n'.format(i + 1, song)

        embed = (discord.Embed(description='**{} 曲目:**\n\n{}'.format(len(ctx.voice_state.songs), queue))
                 .set_footer(text='查看頁面 {}/{}'.format(page, pages)))
        await ctx.send(embed=embed)
    @commands.command(name='shuffle')
    async def _shuffle(self, ctx: commands.Context):
        """隨機排序播放順序"""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('沒有待播歌曲')

        ctx.voice_state.songs.shuffle()
        await ctx.message.add_reaction('✅')

    @commands.command(name='remove')
    async def _remove(self, ctx: commands.Context, index: int):
        """移除某一首歌曲
        $remove (歌曲順位)"""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('沒有待播歌曲')

        ctx.voice_state.songs.remove(index - 1)
        await ctx.message.add_reaction('✅')

    """@commands.command(name='loop')
    async def _loop(self, ctx: commands.Context):
        循環撥放當前的歌曲 再次使用取消循環

        if not ctx.voice_state.is_playing:
            return await ctx.send('目前沒有正在撥放的內容')

        # Inverse boolean value to loop and unloop.
        ctx.voice_state.loop = not ctx.voice_state.loop
        await ctx.message.add_reaction('✅')"""

    @commands.command(name='play')
    async def _play(self, ctx: commands.Context, *, search: str):
        """撥放歌曲 一次只能加入一首 使用方式$play URL
        如果清單中有歌曲那將會排在最後面
        如果沒有提供URL那將從站點搜尋
        站點列表https://rg3.github.io/youtube-dl/supportedsites.html

        $play (URL)
        """
        if not ctx.voice_state.voice:
            await ctx.invoke(self._join)

        async with ctx.typing():
            try:
                source = await YTDLSource.create_source(ctx, search, loop=self.bot.loop)
            except YTDLError as e:
                await ctx.send('處理該請求時發生錯誤: {}'.format(str(e)))
            else:
                song = Song(source)

                await ctx.voice_state.songs.put(song)
                await ctx.send('加入待播歌曲 {}'.format(str(source)))

    @_join.before_invoke
    @_play.before_invoke
    async def ensure_voice_state(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise commands.CommandError('你必須先連接一個語音頻道')
        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise commands.CommandError('Bot已在語音頻道中。')

def setup(bot):
    bot.add_cog(music(bot))