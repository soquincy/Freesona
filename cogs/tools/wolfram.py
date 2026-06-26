# cogs/tools/wolfram.py: Wolfram Alpha query solution

import os
import aiohttp
import logging
import re
import discord
from discord.ext import commands
from discord import app_commands
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()

WOLFRAM_SHORT_APPID = os.getenv("WOLFRAM_APPID_SHORT")
WOLFRAM_LLM_APPID = os.getenv("WOLFRAM_APPID_LLM")

# Formatting function
class WolframCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def format_wolfram_text(self, text: str) -> str:
        if not text:
            return "No result found."

        # 1. Strip absolute noise
        text = re.sub(r'(?i)Wolfram Language code:.*', '', text)
        text = re.sub(r'(?i)Wolfram\s*\|\s*Alpha website result.*', '', text)
        
        # 2. Focus on core content
        if "Input interpretation" in text:
            text = text[text.find("Input interpretation"):]

        # 3. Improved Result Capture
        text = re.sub(r'(?i)Result:\s*\n*(.+)', r'**Result:** `\1`', text)
        
        # 4. Clean up metadata URLs but keep text
        text = re.sub(r'(?i)(plot|image|url):\s*https?://\S+', '', text)
        text = re.sub(r'https?://\S+', '', text)
        
        # 5. Bold table headers
        text = re.sub(r'(?m)^([^:\n|]+)\s*\|\s*([^\n]+)', r'**\1** | \2', text)
        
        # 6. Collapse gaps
        text = re.sub(r'\n\s*\n', '\n', text)
        
        return text.strip()

    def create_embed(self, title: str, content: str, query: str) -> discord.Embed:
        formatted_content = self.format_wolfram_text(content)
        
        embed = discord.Embed(
            title=title,
            description=formatted_content[:4096],
            color=0xDA5B40 
        )

        # identify math for LaTeX image rendering
        math_match = re.search(r'\*\*Result:\*\*\s*`([^`]+)`', formatted_content)
        if math_match:
            raw_math = math_match.group(1)
            if any(char in raw_math for char in '0123456789=+-*/^()√π∫'):
                latex_math = raw_math.replace('≈', r'\approx').replace('integral', r'\int')
                encoded_math = quote(latex_math)
                latex_url = fr"https://latex.codecogs.com/png.image?\dpi{{150}}\bg{{white}}{encoded_math}"
                embed.set_image(url=latex_url)

        embed.set_footer(text=f"Query: {query}")
        return embed

    # Math command
    @commands.hybrid_command(name="math", aliases=['wa', 'wolfram', 'mq'], help="Answers math queries using Wolfram Alpha.")
    @app_commands.describe(query="The math problem or question you want to solve.")
    async def math(self, ctx, *, query: str):
        # Mandatory for slash commands
        await ctx.defer()
        
        logging.info(f"Processing query: {query}")
        
        # Try short answer API first
        short_result = await self.query_short_answer(query)
        
        if short_result and "did not understand" not in short_result.lower():
            logging.info(f"Short API succeeded")
            embed = self.create_embed("Wolfram Alpha Result", short_result, query)
            await ctx.send(embed=embed)
            return
        
        # If short answer fails, try full LLM API
        full_result = await self.query_llm_api(query)
        
        if full_result:
            logging.info(f"Full API succeeded")
            embed = self.create_embed("Wolfram Alpha Result", full_result, query)
            await ctx.send(embed=embed)
        else:
            logging.warning("Both APIs failed")
            await ctx.send("Sorry, I couldn't find an answer to your query.")

    async def query_short_answer(self, query: str) -> str | None:
        if not WOLFRAM_SHORT_APPID:
            return None
        
        url = "http://api.wolframalpha.com/v1/result"
        params = {"appid": WOLFRAM_SHORT_APPID, "i": query, "units": "metric"}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        return await resp.text()
                    return None
        except Exception as e:
            logging.error(f"Error in short answer: {e}")
            return None

    async def query_llm_api(self, query: str) -> str | None:
        if not WOLFRAM_LLM_APPID:
            return None
        
        url = "https://www.wolframalpha.com/api/v1/llm-api"
        params = {"appid": WOLFRAM_LLM_APPID, "input": query, "units": "metric"}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        content_type = resp.headers.get('content-type', '').lower()
                        if 'application/json' in content_type:
                            data = await resp.json()
                            return str(data.get("result"))
                        return await resp.text()
                    return None
        except Exception as e:
            logging.error(f"Error in LLM API: {e}")
            return None

async def setup(bot):
    await bot.add_cog(WolframCog(bot))