import discord.guild
from discord.ext import commands
from core.Mcore import Cog_Extension

class developers(Cog_Extension):
    @commands.command()
    async def test(self,ctx):
        if str(ctx.author) == '(´・ω・`)Brfiveonze#3672':
            await ctx.send('test OK!')
    @commands.command()
    async def showGuilds(self, ctx):
        print('此機器人所存在的伺服器列表')
        for i in self.bot.guilds:
            print(i)
        #async for guild in self.bot.fetch_guilds(limit=150):
            #print(guild.name) 與上方相同
    @commands.command()
    async def showVoiceChanel(self, ctx):
        print('可使用輸入此指令的伺服器的語音頻道')
        for i in self.bot.guilds:
            print(i)
            for j in i.channels:
                if type(j) == discord.guild.VoiceChannel:
                    print('\tVoice Channel:' + j.name)
                elif type(j) == discord.guild.TextChannel:
                    print('\tText Channel:' + j.name)
def setup(bot):
    bot.add_cog(developers(bot))