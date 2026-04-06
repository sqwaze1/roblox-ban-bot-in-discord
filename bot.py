import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ROBLOX_UNIVERSE_ID = os.getenv("ROBLOX_UNIVERSE_ID")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

ROBLOX_API_KEY = os.getenv("ROBLOX_API_KEY")

ALLOWED_ROLE_NAME = "OG"

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


@bot.event
async def on_ready():
    print("Bot ready: {}".format(bot.user))
    guild = discord.Object(id=GUILD_ID)
    bot.tree.clear_commands(guild=guild)
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync(guild=None)

    @bot.tree.command(name="rban", description="Ban a Roblox player from your game", guild=guild)
    @app_commands.describe(
        method="user-id or user-name",
        value="Player Roblox ID or username",
        reason="Reason for the ban"
    )
    @app_commands.choices(method=[
        app_commands.Choice(name="user-id", value="user-id"),
        app_commands.Choice(name="user-name", value="user-name"),
    ])
    async def rban_command(
        interaction: discord.Interaction,
        method: app_commands.Choice[str],
        value: str,
        reason: str = "Rule violation"
    ):
        await interaction.response.defer()

        if not any(r.name == ALLOWED_ROLE_NAME for r in interaction.user.roles):
            await interaction.followup.send("You do not have permission to use this command.")
            return

        user_id = None
        display_name = ""

        if method.value == "user-id":
            if not value.isdigit():
                await interaction.followup.send("Invalid format: user-id must be a number.")
                return
            user_id = int(value)
            display_name = "ID `{}`".format(user_id)

        elif method.value == "user-name":
            async with aiohttp.ClientSession() as session:
                url = "https://users.roblox.com/v1/usernames/users"
                payload = {"usernames": [value], "excludeBannedUsers": False}
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        users = data.get("data", [])
                        if users:
                            user_id = users[0]["id"]
            if not user_id:
                await interaction.followup.send("User **{}** was not found on Roblox.".format(value))
                return
            display_name = "**{}** (ID `{}`)".format(value, user_id)

        async with aiohttp.ClientSession() as session:
            url = "https://apis.roblox.com/cloud/v2/universes/{}/user-restrictions/{}".format(
                ROBLOX_UNIVERSE_ID, user_id
            )
            headers = {
                "x-api-key": ROBLOX_API_KEY,
                "Content-Type": "application/json",
            }
            payload = {
                "gameJoinRestriction": {
                    "active": True,
                    "duration": None,
                    "privateReason": reason,
                    "displayReason": reason,
                    "excludeAltAccounts": False,
                }
            }
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status in (200, 201):
                    embed = discord.Embed(title="Roblox Player Banned", color=discord.Color.red())
                    embed.add_field(name="Player", value=display_name, inline=False)
                    embed.add_field(name="Reason", value=reason, inline=False)
                    embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
                    await interaction.followup.send(embed=embed)
                else:
                    error = await resp.text()
                    await interaction.followup.send("Ban failed: ```{}```".format(error))

    await bot.tree.sync(guild=guild)
    print("Commands synced to guild {}.".format(GUILD_ID))


bot.run(DISCORD_TOKEN)
