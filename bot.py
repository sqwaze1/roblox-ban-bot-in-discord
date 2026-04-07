import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
import re
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
ROBLOX_API_KEY = os.getenv("ROBLOX_API_KEY")

ALLOWED_ROLES = [
    "Owner",
    "Developer",
    "Community Manager",
    "Community Helper",
]

UNIVERSE_IDS = []
i = 1
while True:
    uid = os.getenv("UNIVERSE_ID_{}".format(i), "")
    if not uid:
        break
    UNIVERSE_IDS.append(uid)
    i += 1

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


def parse_duration(duration_str):
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
    url = "https://users.roblox.com/v1/users/{}".format(user_id)
    async with session.get(url) as resp:
        if resp.status == 200:
            return await resp.json()
        return None


async def get_roblox_user_avatar(session, user_id):
    url = "https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={}&size=150x150&format=Png".format(user_id)
    async with session.get(url) as resp:
        if resp.status == 200:
            data = await resp.json()
            items = data.get("data", [])
            if items:
                return items[0].get("imageUrl")
    return None


async def get_roblox_friends_count(session, user_id):
    url = "https://friends.roblox.com/v1/users/{}/friends/count".format(user_id)
    async with session.get(url) as resp:
        if resp.status == 200:
            return (await resp.json()).get("count", 0)
    return 0


async def get_roblox_followers_count(session, user_id):
    url = "https://friends.roblox.com/v1/users/{}/followers/count".format(user_id)
    async with session.get(url) as resp:
        if resp.status == 200:
            return (await resp.json()).get("count", 0)
    return 0


async def get_roblox_following_count(session, user_id):
    url = "https://friends.roblox.com/v1/users/{}/followings/count".format(user_id)
    async with session.get(url) as resp:
        if resp.status == 200:
            return (await resp.json()).get("count", 0)
    return 0


async def get_user_id_by_name(session, username):
    url = "https://users.roblox.com/v1/usernames/users"
    payload = {"usernames": [username], "excludeBannedUsers": False}
    async with session.post(url, json=payload) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        users = data.get("data", [])
        return users[0]["id"] if users else None


async def ban_in_universe(session, user_id, reason, duration_seconds, universe_id):
    url = "https://apis.roblox.com/cloud/v2/universes/{}/user-restrictions/{}".format(
        universe_id, user_id
    )
    headers = {
        "x-api-key": ROBLOX_API_KEY,
        "Content-Type": "application/json",
    }
    restriction = {
        "active": True,
        "privateReason": reason,
        "displayReason": reason,
        "excludeAltAccounts": False,
        "duration": "{}s".format(duration_seconds) if duration_seconds is not None else None,
    }
    async with session.patch(url, headers=headers, json={"gameJoinRestriction": restriction}) as resp:
        if resp.status in (200, 201):
            return True, None
        return False, await resp.text()


async def unban_in_universe(session, user_id, universe_id):
    url = "https://apis.roblox.com/cloud/v2/universes/{}/user-restrictions/{}".format(
        universe_id, user_id
    )
    headers = {
        "x-api-key": ROBLOX_API_KEY,
        "Content-Type": "application/json",
    }
    restriction = {
        "active": False,
        "privateReason": "",
        "displayReason": "",
        "excludeAltAccounts": False,
        "duration": None,
    }
    async with session.patch(url, headers=headers, json={"gameJoinRestriction": restriction}) as resp:
        if resp.status in (200, 201):
            return True, None
        return False, await resp.text()


async def fetch_user_data(session, user_id):
    user_info = await get_roblox_user_info(session, user_id)
    avatar_url = await get_roblox_user_avatar(session, user_id)
    friends = await get_roblox_friends_count(session, user_id)
    followers = await get_roblox_followers_count(session, user_id)
    following = await get_roblox_following_count(session, user_id)
    username = user_info.get("name", "Unknown") if user_info else "Unknown"
    display_name = user_info.get("displayName", username) if user_info else username
    return username, display_name, avatar_url, friends, followers, following


def build_user_embed(user_id, display_name, username, avatar_url, friends, followers, following, color):
    profile_url = "https://www.roblox.com/users/{}/profile".format(user_id)
    friends_url = "https://www.roblox.com/users/{}/friends".format(user_id)
    followers_url = "https://www.roblox.com/users/{}/followers".format(user_id)
    following_url = "https://www.roblox.com/users/{}/following".format(user_id)
    desc = "[**{}**]({}) Friends  **|**  [**{:,}**]({}) Followers  **|**  [**{}**]({}) Following".format(
        friends, friends_url, followers, followers_url, following, following_url
    )
    embed = discord.Embed(
        title="**{} (@{})**".format(display_name, username),
        url=profile_url,
        description=desc,
        timestamp=datetime.now(timezone.utc),
        color=color
    )
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    embed.set_footer(text="ID: {}".format(user_id))
    return embed


@bot.event
async def on_ready():
    print("Bot ready: {}".format(bot.user))
    print("Loaded {} universe(s)".format(len(UNIVERSE_IDS)))

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
    @app_commands.choices(
        method=[
            app_commands.Choice(name="user-id", value="user-id"),
            app_commands.Choice(name="user-name", value="user-name"),
        ]
    )
    async def rban_command(
        interaction: discord.Interaction,
        method: app_commands.Choice[str],
        value: str,
        reason: str,
        duration: str,
        evidence: str = None
    ):
        await interaction.response.defer()

        user_role_names = [r.name for r in interaction.user.roles]
        if not any(role in ALLOWED_ROLES for role in user_role_names):
            await interaction.followup.send("You do not have permission to use this command.")
            return

        duration_seconds = parse_duration(duration)
        if duration_seconds is None and duration.strip() != "-1":
            await interaction.followup.send("Invalid duration. Use `1d 3h 10m` or `-1` for permanent.")
            return

        async with aiohttp.ClientSession() as session:
            if method.value == "user-id":
                if not value.isdigit():
                    await interaction.followup.send("Invalid format: user-id must be a number.")
                    return
                user_id = int(value)
            else:
                user_id = await get_user_id_by_name(session, value)
                if not user_id:
                    await interaction.followup.send("User **{}** was not found on Roblox.".format(value))
                    return

            username, display_name, avatar_url, friends, followers, following = await fetch_user_data(session, user_id)

            results = []
            for uid in UNIVERSE_IDS:
                ok, err = await ban_in_universe(session, user_id, reason, duration_seconds, uid)
                results.append((uid, ok, err))

        failed = [(uid, err) for uid, ok, err in results if not ok]
        embed = build_user_embed(
            user_id, display_name, username, avatar_url,
            friends, followers, following,
            0x99aab5 if not failed else 0xe74c3c
        )
        embed.add_field(name="⏱ Duration", value=format_duration(duration), inline=True)
        embed.add_field(name="🛡 Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="🎮 Places", value="{}/{} banned".format(len(results) - len(failed), len(results)), inline=True)
        embed.add_field(name="📋 Reason", value=reason, inline=False)
        if evidence:
            embed.add_field(name="🔗 Evidence", value=evidence, inline=False)
        if failed:
            embed.add_field(
                name="⚠️ Failed",
                value="\n".join(["Universe `{}`: {}".format(uid, err) for uid, err in failed]),
                inline=False
            )
        await interaction.followup.send(embed=embed)

    @bot.tree.command(name="runban", description="Unban a Roblox player from your game", guild=guild)
    @app_commands.describe(
        method="How to find the player: user-id or user-name",
        value="Player Roblox ID or username"
    )
    @app_commands.choices(
        method=[
            app_commands.Choice(name="user-id", value="user-id"),
            app_commands.Choice(name="user-name", value="user-name"),
        ]
    )
    async def runban_command(
        interaction: discord.Interaction,
        method: app_commands.Choice[str],
        value: str
    ):
        await interaction.response.defer()

        user_role_names = [r.name for r in interaction.user.roles]
        if not any(role in ALLOWED_ROLES for role in user_role_names):
            await interaction.followup.send("You do not have permission to use this command.")
            return

        async with aiohttp.ClientSession() as session:
            if method.value == "user-id":
                if not value.isdigit():
                    await interaction.followup.send("Invalid format: user-id must be a number.")
                    return
                user_id = int(value)
            else:
                user_id = await get_user_id_by_name(session, value)
                if not user_id:
                    await interaction.followup.send("User **{}** was not found on Roblox.".format(value))
                    return

            username, display_name, avatar_url, friends, followers, following = await fetch_user_data(session, user_id)

            results = []
            for uid in UNIVERSE_IDS:
                ok, err = await unban_in_universe(session, user_id, uid)
                results.append((uid, ok, err))

        failed = [(uid, err) for uid, ok, err in results if not ok]
        embed = build_user_embed(
            user_id, display_name, username, avatar_url,
            friends, followers, following,
            0x57f287 if not failed else 0xe74c3c
        )
        embed.add_field(name="🛡 Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="🎮 Places", value="{}/{} unbanned".format(len(results) - len(failed), len(results)), inline=True)
        if failed:
            embed.add_field(
                name="⚠️ Failed",
                value="\n".join(["Universe `{}`: {}".format(uid, err) for uid, err in failed]),
                inline=False
            )
        await interaction.followup.send(embed=embed)

    @bot.tree.command(name="explban", description="Permanently ban a Roblox exploiter from your game", guild=guild)
    @app_commands.describe(
        method="How to find the player: user-id or user-name",
        value="Player Roblox ID or username",
        evidence="Optional link to forum post or evidence"
    )
    @app_commands.choices(
        method=[
            app_commands.Choice(name="user-id", value="user-id"),
            app_commands.Choice(name="user-name", value="user-name"),
        ]
    )
    async def explban_command(
        interaction: discord.Interaction,
        method: app_commands.Choice[str],
        value: str,
        evidence: str = None
    ):
        await interaction.response.defer()

        user_role_names = [r.name for r in interaction.user.roles]
        if not any(role in ALLOWED_ROLES for role in user_role_names):
            await interaction.followup.send("You do not have permission to use this command.")
            return

        async with aiohttp.ClientSession() as session:
            if method.value == "user-id":
                if not value.isdigit():
                    await interaction.followup.send("Invalid format: user-id must be a number.")
                    return
                user_id = int(value)
            else:
                user_id = await get_user_id_by_name(session, value)
                if not user_id:
                    await interaction.followup.send("User **{}** was not found on Roblox.".format(value))
                    return

            username, display_name, avatar_url, friends, followers, following = await fetch_user_data(session, user_id)

            results = []
            for uid in UNIVERSE_IDS:
                ok, err = await ban_in_universe(session, user_id, "Exploits.", None, uid)
                results.append((uid, ok, err))

        failed = [(uid, err) for uid, ok, err in results if not ok]
        embed = build_user_embed(
            user_id, display_name, username, avatar_url,
            friends, followers, following,
            0x99aab5 if not failed else 0xe74c3c
        )
        embed.add_field(name="⏱ Duration", value="Permanent", inline=True)
        embed.add_field(name="🛡 Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="🎮 Places", value="{}/{} banned".format(len(results) - len(failed), len(results)), inline=True)
        embed.add_field(name="📋 Reason", value="Exploits.", inline=False)
        if evidence:
            embed.add_field(name="🔗 Evidence", value=evidence, inline=False)
        if failed:
            embed.add_field(
                name="⚠️ Failed",
                value="\n".join(["Universe `{}`: {}".format(uid, err) for uid, err in failed]),
                inline=False
            )
        await interaction.followup.send(embed=embed)

    await bot.tree.sync(guild=guild)
    print("Commands synced to guild {}.".format(GUILD_ID))


bot.run(DISCORD_TOKEN)
