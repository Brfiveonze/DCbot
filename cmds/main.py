import json
from discord.ext import commands
from core.Mcore import Cog_Extension

with open('setting.json', 'r', encoding='utf8') as j1:
    setting = json.load(j1)

class Main(Cog_Extension):
    @commands.command()
    async def ping(self,ctx):
        await ctx.send(f'此bot延遲為:{round(self.bot.latency * 1000)}ms')
    @commands.command()
    async def add(self,ctx, a: int, b: int):
        await ctx.send(a + b)

    """@commands.command()
    async def 三倍役滿(self,ctx):
        if str(ctx.author) == '(´・ω・`)Brfiveonze#3672':
            await ctx.message.delete()
            await ctx.send(setting['Triple_Yakuman'])
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error,commands.errors.MissingRequiredArgument):
            await ctx.send('缺少必要參數')
        elif isinstance(error,commands.errors.CommandNotFound):
            await ctx.send('無此指令')
        else:
            await ctx.send('發生錯誤')"""
def setup(bot):
    bot.add_cog(Main(bot))