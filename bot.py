import asyncio
import os
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
ROBLOX_API_KEY = os.getenv("ROBLOX_API_KEY")

if not DISCORD_TOKEN:
    raise ValueError("Missing DISCORD_TOKEN in environment variables.")

if not ROBLOX_API_KEY:
    raise ValueError("Missing ROBLOX_API_KEY in environment variables.")

if not GUILD_ID:
    raise ValueError("Missing or invalid GUILD_ID in environment variables.")

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


def has_allowed_role(member):
    return any(role.name in ALLOWED_ROLES for role in getattr(member, "roles", []))


def trim_embed_value(text, limit=1024):
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def chunk_lines(lines, limit=1024):
    chunks = []
    current = []

    for line in lines:
        candidate = "\n".join(current + [line])
        if len(candidate) > limit and current:
            chunks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)

    if current:
        chunks.append("\n".join(current))

    return chunks


def restriction_user_id(restriction):
    path = restriction.get("path", "")
    if path:
        return path.rstrip("/").split("/")[-1]

    user = restriction.get("user")
    if isinstance(user, str) and "/" in user:
        return user.rstrip("/").split("/")[-1]

    user_restriction_id = restriction.get("userRestrictionId")
    if user_restriction_id:
        return str(user_restriction_id)

    return None


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


async def get_universe_info(session, universe_id):
    url = "https://develop.roblox.com/v1/universes/{}".format(universe_id)
    async with session.get(url) as resp:
        if resp.status != 200:
            return {
                "name": "Universe {}".format(universe_id),
                "url": "https://www.roblox.com/discover#/",
            }

        data = await resp.json()
        name = data.get("name") or "Universe {}".format(universe_id)
        root_place_id = data.get("rootPlaceId")

        if root_place_id:
            url = "https://www.roblox.com/games/{}".format(root_place_id)
        else:
            url = "https://www.roblox.com/discover#/"

        return {
            "name": name,
            "url": url,
        }


async def list_user_restrictions(session, universe_id):
    url = "https://apis.roblox.com/cloud/v2/universes/{}/user-restrictions".format(universe_id)
    headers = {"x-api-key": ROBLOX_API_KEY}
    restrictions = []
    page_token = None

    while True:
        params = {"maxPageSize": 100}
        if page_token:
            params["pageToken"] = page_token

        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                return None, await resp.text()

            data = await resp.json()
            restrictions.extend(data.get("userRestrictions", []))
            page_token = data.get("nextPageToken")

            if not page_token:
                break

    return restrictions, None


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
        "privateReason": reason or "Reason not provided",
        "displayReason": "You have been banned from Murder Mystery 2.",
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


async def apply_restriction_in_universe(session, user_id, restriction, universe_id):
    url = "https://apis.roblox.com/cloud/v2/universes/{}/user-restrictions/{}".format(
        universe_id, user_id
    )
    headers = {
        "x-api-key": ROBLOX_API_KEY,
        "Content-Type": "application/json",
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
        color=color,
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

    @bot.tree.command(
        name="unban",
        description="Unban a Roblox player from your game",
        guild=guild,
    )
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
    async def unban_command(
        interaction: discord.Interaction,
        method: app_commands.Choice[str],
        value: str
    ):
        await interaction.response.defer()

        if not has_allowed_role(interaction.user):
            await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
            return

        async with aiohttp.ClientSession() as session:
            if method.value == "user-id":
                if not value.isdigit():
                    await interaction.followup.send("Invalid format: user-id must be a number.", ephemeral=True)
                    return
                user_id = int(value)
            else:
                user_id = await get_user_id_by_name(session, value)
                if not user_id:
                    await interaction.followup.send("User **{}** was not found on Roblox.".format(value), ephemeral=True)
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
            0x57F287 if not failed else 0xE74C3C
        )
        embed.add_field(name="🛡 Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="🎮 Places", value="{}/{} unbanned".format(len(results) - len(failed), len(results)), inline=True)

        if failed:
            embed.add_field(
                name="⚠️ Failed",
                value=trim_embed_value("\n".join(["Universe `{}`: {}".format(uid, err) for uid, err in failed])),
                inline=False
            )

        await interaction.followup.send(embed=embed)

    @bot.tree.command(
        name="ban",
        description="Permanently ban a Roblox exploiter from your game",
        guild=guild,
    )
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
    async def ban_command(
        interaction: discord.Interaction,
        method: app_commands.Choice[str],
        value: str,
        evidence: str = None
    ):
        await interaction.response.defer()

        if not has_allowed_role(interaction.user):
            await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
            return

        async with aiohttp.ClientSession() as session:
            if method.value == "user-id":
                if not value.isdigit():
                    await interaction.followup.send("Invalid format: user-id must be a number.", ephemeral=True)
                    return
                user_id = int(value)
            else:
                user_id = await get_user_id_by_name(session, value)
                if not user_id:
                    await interaction.followup.send("User **{}** was not found on Roblox.".format(value), ephemeral=True)
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
            0x99AAB5 if not failed else 0xE74C3C
        )
        embed.add_field(name="⏱ Duration", value="Permanent", inline=True)
        embed.add_field(name="🛡 Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="🎮 Places", value="{}/{} banned".format(len(results) - len(failed), len(results)), inline=True)

        if evidence:
            embed.add_field(name="🔗 Proof", value=evidence, inline=False)

        if failed:
            embed.add_field(
                name="⚠️ Failed",
                value=trim_embed_value("\n".join(["Universe `{}`: {}".format(uid, err) for uid, err in failed])),
                inline=False
            )

        await interaction.followup.send(embed=embed)

    @bot.tree.command(
        name="syncbans",
        description="Sync missing bans between all configured universes",
        guild=guild,
    )
    async def syncbans_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        if not has_allowed_role(interaction.user):
            await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
            return

        if not UNIVERSE_IDS:
            await interaction.followup.send(
                "I couldn't find any universe IDs in your config yet.",
                ephemeral=True,
            )
            return

        async with aiohttp.ClientSession() as session:
            universe_bans = {}
            all_bans = {}
            source_errors = []

            for universe_id in UNIVERSE_IDS:
                restrictions, source_err = await list_user_restrictions(session, universe_id)
                if restrictions is None:
                    source_errors.append((universe_id, source_err))
                    continue

                current_bans = {}
                for item in restrictions:
                    game_join = item.get("gameJoinRestriction") or {}
                    if game_join.get("active") is not True:
                        continue

                    user_id = restriction_user_id(item)
                    if not user_id or not str(user_id).isdigit():
                        continue

                    current_bans[str(user_id)] = game_join

                    if str(user_id) not in all_bans:
                        all_bans[str(user_id)] = {
                            "restriction": game_join,
                            "source_universe_id": universe_id,
                        }

                universe_bans[universe_id] = current_bans

            if not all_bans and not source_errors:
                await interaction.followup.send(
                    "Right now there are no active bans to sync.",
                    ephemeral=True,
                )
                return

            results = []
            already_synced = []

            for target_universe_id in UNIVERSE_IDS:
                if target_universe_id not in universe_bans:
                    continue

                target_bans = universe_bans[target_universe_id]

                for user_id, item in all_bans.items():
                    if user_id in target_bans:
                        already_synced.append((user_id, target_universe_id))
                        continue

                    game_join = item["restriction"]
                    ok, sync_err = await apply_restriction_in_universe(
                        session, user_id, game_join, target_universe_id
                    )
                    results.append((user_id, item["source_universe_id"], target_universe_id, ok, sync_err))

            universe_info = {}
            for universe_id in UNIVERSE_IDS:
                universe_info[universe_id] = await get_universe_info(session, universe_id)

        migrated = [
            (user_id, source_universe_id, target_universe_id)
            for user_id, source_universe_id, target_universe_id, ok, _ in results
            if ok
        ]
        failed = [
            (user_id, source_universe_id, target_universe_id, sync_err)
            for user_id, source_universe_id, target_universe_id, ok, sync_err in results
            if not ok
        ]

        if not migrated and not failed:
            await interaction.followup.send(
                "Everything is already synced. Nothing new to add.",
                ephemeral=True,
            )
            return

        updates_by_universe = {}
        for _, _, target_universe_id in migrated:
            updates_by_universe[target_universe_id] = updates_by_universe.get(target_universe_id, 0) + 1

        embed = discord.Embed(
            title="syncbans finished",
            color=0x57F287 if not failed else 0xE67E22,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="🛡 Moderator", value=interaction.user.mention, inline=True)

        if updates_by_universe:
            update_lines = []
            for universe_id, added_count in sorted(updates_by_universe.items(), key=lambda item: item[1], reverse=True):
                info = universe_info.get(universe_id, {})
                place_name = info.get("name", "Universe {}".format(universe_id))
                place_url = info.get("url", "https://www.roblox.com/discover#/")
                update_lines.append("**[{}]({})** - {} new ban(s)".format(place_name, place_url, added_count))

            chunks = chunk_lines(update_lines)
            for index, chunk in enumerate(chunks, start=1):
                field_name = "📥 Updated places" if index == 1 else "📥 Updated places ({})".format(index)
                embed.add_field(name=field_name, value=chunk, inline=False)

        if failed:
            embed.add_field(
                name="⚠️ Failed users",
                value=trim_embed_value(
                    "\n".join(
                        [
                            "User `{}` from `{}` to `{}`: {}".format(
                                user_id, source_universe_id, target_universe_id, sync_err
                            )
                            for user_id, source_universe_id, target_universe_id, sync_err in failed[:10]
                        ]
                    )
                ),
                inline=False,
            )

        if source_errors:
            embed.add_field(
                name="⚠️ Some universes couldn't be read",
                value=trim_embed_value(
                    "\n".join(
                        [
                            "Universe `{}`: {}".format(source_universe_id, source_err)
                            for source_universe_id, source_err in source_errors[:10]
                        ]
                    )
                ),
                inline=False,
            )

        await interaction.followup.send(embed=embed)

    await bot.tree.sync(guild=guild)
    print("Commands synced to guild {}.".format(GUILD_ID))


async def main():
    retry_delay = 60

    while True:
        try:
            async with bot:
                await bot.start(DISCORD_TOKEN)
        except discord.HTTPException as e:
            if e.status == 429:
                print("Discord rate limited the bot login. Waiting {} seconds before retry.".format(retry_delay))
                await asyncio.sleep(retry_delay)
            else:
                raise
        except Exception as e:
            print("Bot crashed: {}".format(e))
            await asyncio.sleep(retry_delay)


asyncio.run(main())
