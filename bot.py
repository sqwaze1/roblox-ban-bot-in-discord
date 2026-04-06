import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
import re
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


def parse_duration(duration_str):
    """
    Parses duration string like '1d 3h 10m' into total seconds.
    Returns None for permanent ban (-1).
    """
    if duration_str.strip() == "-1":
        return None

    total_seconds = 0
    pattern = re.findall(r"(\d+)\s*([dhm])", duration_str.lower())
    for value, unit in pattern:
        value = int(value)
        if unit == "d":
            total_seconds += value * 86400
        elif unit == "h":
            total_seconds += value * 3600
        elif unit == "m":
            total_seconds += value * 60

    return total_seconds if total_seconds > 0 else None


def format_duration(duration_str):
    """Returns a human-readable duration string."""
    if duration_str.strip() == "-1":
        return "Permanent"
    parts = []
    pattern = re.findall(r"(\d+)\s*([dhm])", duration_str.lower())
    for value, unit in pattern:
        if unit == "d":
            parts.append("{} day{}".format(value, "s" if int(value) != 1 else ""))
        elif unit == "h":
            parts.append("{} hour{}".format(value, "s" if int(value) != 1 else ""))
        elif unit == "m":
            parts.append("{} minute{}".format(value, "s" if int(value) != 1 else ""))
    return ", ".join(parts) if parts else "Unknown"


async def get_roblox_user_info(session, user_id):
    """Fetches Roblox user info by user ID."""
    url = "https://users.roblox.com/v1/users/{}".format(user_id)
    async with session.get(url) as resp:
        if resp.status == 200:
            return await resp.json()
        return None


async def get_roblox_user_avatar(session, user_id):
    """Fetches Roblox user avatar thumbnail URL."""
    url = "https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={}&size=150x150&format=Png".format(user_id)
    async with session.get(url) as resp:
        if resp.status == 200:
            data = await resp.json()
            items = data.get("data", [])
            if items:
                return items[0].get("imageUrl")
    return None


async def get_roblox_followers(session, user_id):
    """Fetches Roblox user follower count."""
    url = "https://friends.roblox.com/v1/users/{}/followers/count".format(user_id)
    async with session.get(url) as resp:
        if resp.status == 200:
            data = await resp.json()
            return data.get("count", 0)
    return 0


async def get_user_id_by_name(session, username):
    """Fetches userId by username."""
    url = "https://users.roblox.com/v1/usernames/users"
    payload = {"usernames": [username], "excludeBannedUsers": False}
    async with session.post(url, json=payload) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        users = data.get("data", [])
        if users:
            return users[0]["id"]
        return None


async def ban_roblox_user(session, user_id, reason, duration_seconds):
    """Bans a user via Roblox Open Cloud API."""
    url = "https://apis.roblox.com/cloud/v2/universes/{}/user-restrictions/{}".format(
        ROBLOX_UNIVERSE_ID, user_id
    )
    headers = {
        "x-api-key": ROBLOX_API_KEY,
        "Content-Type": "application/json",
    }

    game_join_restriction = {
        "active": True,
        "privateReason": reason,
        "displayReason": reason,
        "excludeAltAccounts": False,
    }

    if duration_seconds is not None:
        game_join_restriction["duration"] = "{}s".format(duration_seconds)
    else:
        game_join_restriction["duration"] = None

    payload = {"gameJoinRestriction": game_join_restriction}

    async with session.patch(url, headers=headers, json=payload) as resp:
        if resp.status in (200, 201):
            return True, "OK"
        error = await resp.text()
        return False, error


@bot.event
async def on_ready():
    print("Bot ready: {}".format(bot.user))
    guild = discord.Object(id=GUILD_ID)
    bot.tree.clear_commands(guild=guild)
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync(guild=None)

    @bot.tree.command(name="rban", description="Ban a Roblox player from your game", guild=guild)
    @app_commands.describe(
        method="How to find the player: user-id or user-name",
        value="Player Roblox ID or username",
        reason="Reason for the ban",
        duration="Duration: e.g. 1d 3h 10m or -1 for permanent",
        evidence="Optional link to forum post or evidence"
    )
    @app_commands.choices(method=[
        app_commands.Choice(name="user-id", value="user-id"),
        app_commands.Choice(name="user-name", value="user-name"),
    ])
    async def rban_command(
        interaction: discord.Interaction,
        method: app_commands.Choice[str],
        value: str,
        reason: str,
        duration: str,
        evidence: str = None
    ):
        await interaction.response.defer()

        if not any(r.name == ALLOWED_ROLE_NAME for r in interaction.user.roles):
            await interaction.followup.send("You do not have permission to use this command.")
            return

        
        duration_seconds = parse_duration(duration)
        if duration_seconds is None and duration.strip() != "-1":
            await interaction.followup.send(
                "Invalid duration format. Use `1d 3h 10m` or `-1` for permanent."
            )
            return

        async with aiohttp.ClientSession() as session:
            
            user_id = None
            if method.value == "user-id":
                if not value.isdigit():
                    await interaction.followup.send("Invalid format: user-id must be a number.")
                    return
                user_id = int(value)
            elif method.value == "user-name":
                user_id = await get_user_id_by_name(session, value)
                if not user_id:
                    await interaction.followup.send("User **{}** was not found on Roblox.".format(value))
                    return

            
            user_info = await get_roblox_user_info(session, user_id)
            avatar_url = await get_roblox_user_avatar(session, user_id)
            followers = await get_roblox_followers(session, user_id)

            username = user_info.get("name", "Unknown") if user_info else "Unknown"
            display_name = user_info.get("displayName", username) if user_info else username

            
            success, error = await ban_roblox_user(session, user_id, reason, duration_seconds)

        if success:
            embed = discord.Embed(
                title="🔨 Player Banned",
                color=discord.Color.red()
            )

            if avatar_url:
                embed.set_thumbnail(url=avatar_url)

            embed.add_field(
                name="👤 Player",
                value="**{}** (@{})\nID: `{}`".format(display_name, username, user_id),
                inline=False
            )
            embed.add_field(
                name="👥 Followers",
                value="{:,}".format(followers),
                inline=True
            )
            embed.add_field(
                name="⏱ Duration",
                value=format_duration(duration),
                inline=True
            )
            embed.add_field(
                name="📋 Reason",
                value=reason,
                inline=False
            )
            embed.add_field(
                name="🛡 Moderator",
                value=interaction.user.mention,
                inline=True
            )
            if evidence:
                embed.add_field(
                    name="🔗 Evidence",
                    value=evidence,
                    inline=False
                )

            embed.set_footer(text="Roblox Ban System")
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send("Ban failed: ```{}```".format(error))

    await bot.tree.sync(guild=guild)
    print("Commands synced to guild {}.".format(GUILD_ID))


bot.run(DISCORD_TOKEN)
