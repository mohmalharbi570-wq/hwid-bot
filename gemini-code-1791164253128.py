import discord
from discord import app_commands
from discord.ext import commands, tasks

from datetime import datetime
from zoneinfo import ZoneInfo

import sqlite3
import os
import json
import math
import re


# ============================================================
#                         الإعدادات
# ============================================================

# 🔴 يتم سحب التوكن أوتوماتيكياً من إعدادات البيئة في رندر
TOKEN = os.getenv("DISCORD_TOKEN")

# 🟣 ID السيرفر
SERVER_ID = 1527032282039456016

# 🇸🇦 توقيت السعودية
SAUDI_TIMEZONE = ZoneInfo("Asia/Riyadh")


# ============================================================
#                    قاعدة بيانات SQLite (القفويات والاقتراحات)
# ============================================================

DB_PATH = "bot_database.db"
db = sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    cursor = db.cursor()
    # جدول القفويات
    cursor.execute("""CREATE TABLE IF NOT EXISTS giveaways (
        message_id TEXT PRIMARY KEY,
        channel_id TEXT,
        guild_id TEXT,
        prize TEXT,
        winner_count INTEGER,
        required_invites INTEGER,
        keys TEXT,
        ends_at INTEGER,
        ended INTEGER DEFAULT 0,
        host_id TEXT
    )""")

    # جدول المشاركين في القفوي
    cursor.execute("""CREATE TABLE IF NOT EXISTS participants (
        message_id TEXT,
        user_id TEXT,
        PRIMARY KEY (message_id, user_id)
    )""")

    # جدول تتبع الدعوات
    cursor.execute("""CREATE TABLE IF NOT EXISTS invites_tracker (
        guild_id TEXT,
        user_id TEXT,
        inviter_id TEXT,
        PRIMARY KEY (guild_id, user_id)
    )""")

    # جدول إعدادات الاقتراحات
    cursor.execute("""CREATE TABLE IF NOT EXISTS suggestion_setup (
        guild_id TEXT PRIMARY KEY,
        channel_id TEXT
    )""")
    db.commit()

init_db()


# ============================================================
#                    تخزين مؤقت للدعوات
# ============================================================

guild_invites = {}


# ============================================================
#                         إعداد البوت
# ============================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.invites = True
bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

TARGET_GUILD = discord.Object(id=SERVER_ID)


# ============================================================
#                    التحقق من السيرفر والصلاحيات
# ============================================================

def check_server(interaction: discord.Interaction):
    if interaction.guild is None:
        return False
    return interaction.guild.id == SERVER_ID

def is_admin(interaction: discord.Interaction):
    if interaction.guild is None:
        return False
    return interaction.user.guild_permissions.administrator


# ============================================================
#                    تشغيل البوت
# ============================================================

@bot.event
async def on_ready():
    print("=" * 60)
    print(f"✅ البوت اشتغل بنجاح: {bot.user}")
    print(f"🏠 Server ID: {SERVER_ID}")
    print("=" * 60)

    for guild in bot.guilds:
        try:
            firstInvites = await guild.invites()
            guild_invites[guild.id] = {invite.code: invite.uses for invite in firstInvites}
        except Exception as err:
            print(f"❌ لا يمكن جلب دعوات السيرفر: {guild.name}")

    if not giveaway_checker.is_running():
        giveaway_checker.start()


# ============================================================
#                    تتبع الدعوات
# ============================================================

@bot.event
async def on_member_add(member):
    try:
        guild = member.guild
        cachedInvites = guild_invites.get(guild.id, {})
        newInvites = await guild.invites()

        usedInvite = None
        for invite in newInvites:
            cachedUses = cachedInvites.get(invite.code, 0)
            if invite.uses > cachedUses:
                usedInvite = invite
                break

        guild_invites[guild.id] = {inv.code: inv.uses for inv in newInvites}

        if usedInvite and usedInvite.inviter:
            cursor = db.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO invites_tracker (guild_id, user_id, inviter_id) VALUES (?, ?, ?)",
                (str(guild.id), str(member.id), str(usedInvite.inviter.id))
            )
            db.commit()
    except Exception as err:
        print('خطأ في تتبع الدعوات:', err)

@bot.event
async def on_invite_create(invite):
    if invite.guild.id in guild_invites:
        guild_invites[invite.guild.id][invite.code] = invite.uses

@bot.event
async def on_invite_delete(invite):
    if invite.guild.id in guild_invites:
        guild_invites[invite.guild.id].pop(invite.code, None)


# ============================================================
#                    تسجيل الأوامر الثابتة
# ============================================================

@bot.event
async def setup_hook():
    bot.add_view(GiveawayJoinView())
    bot.add_view(SuggestionPanelView())

    try:
        synced = await bot.tree.sync(guild=TARGET_GUILD)
        print(f"✅ تم تسجيل {len(synced)} أمر سلاش في السيرفر.")
    except Exception as error:
        print(f"❌ خطأ في مزامنة الأوامر: {error}")


# ============================================================
#                 نظام الاقتراحات (Suggestions) - بدون إظهار المرسل
# ============================================================

class SuggestionModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="إرسال اقتراح جديد")

        self.game_name = discord.ui.TextInput(
            label="اسم اللعبة",
            placeholder="اكتب اسم اللعبة",
            required=True,
            max_length=100,
            style=discord.TextStyle.short
        )

        self.suggestion_text = discord.ui.TextInput(
            label="اكتب اقتراحاتك",
            placeholder="صف اقتراحك بالتفصيل",
            required=True,
            max_length=1000,
            style=discord.TextStyle.paragraph
        )

        self.add_item(self.game_name)
        self.add_item(self.suggestion_text)

    async def on_submit(self, interaction: discord.Interaction):
        if not check_server(interaction):
            return await interaction.response.send_message("❌ هذا البوت مخصص لسيرفر محدد.", ephemeral=True)

        target_channel_id = 1556460733418442782
        channel = interaction.guild.get_channel(target_channel_id)

        if not channel:
            return await interaction.response.send_message("❌ روم الاقتراحات المحدد غير موجود أو أن البوت لا يملك صلاحية الوصول إليه.", ephemeral=True)

        embed = discord.Embed(
            title="💡 اقتراح جديد",
            color=0x3498DB,
            timestamp=datetime.now(SAUDI_TIMEZONE)
        )
        embed.add_field(name="🎮 اسم اللعبة", value=self.game_name.value, inline=False)
        embed.add_field(name="📝 الاقتراح", value=self.suggestion_text.value, inline=False)
        embed.set_footer(text="OUT STORE • Anonymous Suggestion")

        # إرسال الاقتراح بشكل سري (بدون اسم المرسل) مع تفاعل التصويت
        msg = await channel.send(embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")

        await interaction.response.send_message("✅ **تم إرسال اقتراحك بشكل سري إلى روم الاقتراحات بنجاح!**", ephemeral=True)


class SuggestionPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="اقتراح جديد",
        emoji="💡",
        style=discord.ButtonStyle.primary,
        custom_id="open_suggestion_modal_button"
    )
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_server(interaction):
            return await interaction.response.send_message("❌ هذا البوت مخصص لسيرفر محدد.", ephemeral=True)
        await interaction.response.send_modal(SuggestionModal())


@bot.tree.command(
    name="setup_suggestion",
    description="تثبيت لوحة وأزرار الاقتراحات في الروم الحالي",
    guild=TARGET_GUILD
)
async def setup_suggestion(interaction: discord.Interaction):
    if not check_server(interaction) or not is_admin(interaction):
        return await interaction.response.send_message("❌ هذا الأمر للإدارة فقط.", ephemeral=True)

    embed = discord.Embed(
        title="💡 لوحة اقتراحات OUT STORE",
        description="هل لديك اقتراح لتحسين الألعاب أو الخدمات؟\nاضغط على الزر بالأسفل لكتابة اقتراحك وسوف يتم نشره **بشكل سري** للتصويت عليه!",
        color=0x3498DB
    )
    embed.set_footer(text="OUT STORE • Suggestions Setup")

    view = SuggestionPanelView()
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ تم تثبيت لوحة الاقتراحات في هذه الروم بنجاح.", ephemeral=True)


# ============================================================
#                 نظام القفويات (Giveaways)
# ============================================================

class GiveawayJoinView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="مشاركة 🎉", style=discord.ButtonStyle.success, custom_id="join_giveaway_button")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        messageId = str(interaction.message.id)
        userId = str(interaction.user.id)

        cursor = db.cursor()
        cursor.execute("SELECT * FROM giveaways WHERE message_id = ? AND ended = 0", (messageId,))
        giveaway = cursor.fetchone()
        if not giveaway:
            return await interaction.response.send_message("❌ هذا القفوي منتهي أو غير موجود.", ephemeral=True)

        try:
            cursor.execute("INSERT INTO participants (message_id, user_id) VALUES (?, ?)", (messageId, userId))
            db.commit()
            return await interaction.response.send_message("🎉 تم تسجيل مشاركتك بنجاح في القفوي!", ephemeral=True)
        except sqlite3.IntegrityError:
            return await interaction.response.send_message("⚠️ أنت مشارك بالفعل في هذا القفوي!", ephemeral=True)


@bot.tree.command(
    name="setup_giveaway",
    description="إنشاء قفوي جديد",
    guild=TARGET_GUILD
)
@app_commands.describe(
    prize="اسم الجائزة",
    duration="مدة القفوي (مثال: 1h, 30m, 1d)",
    winner_count="عدد الفائزين المطلوب",
    required_invites="عدد الدعوات المطلوبة للفوز",
    keys="مفتاح أو مفاتيح الجوائز مفصولة بـ |"
)
async def setup_giveaway(
    interaction: discord.Interaction,
    prize: str,
    duration: str,
    winner_count: int,
    required_invites: int,
    keys: str
):
    if not check_server(interaction) or not is_admin(interaction):
        return await interaction.response.send_message("❌ هذا الأمر للإدارة فقط في السيرفر المخصص.", ephemeral=True)

    keys_list = [k.strip() for k in keys.split('|')]
    if len(keys_list) < winner_count:
        return await interaction.response.send_message(f"❌ عدد المفاتيح ({len(keys_list)}) أقل من عدد الفائزين المطلوب ({winner_count})!", ephemeral=True)

    ms = parse_duration(duration)
    if not ms:
        return await interaction.response.send_message("❌ صيغة المدة غير صحيحة. استخدم: `1h`, `30m`, `1d`.", ephemeral=True)

    ends_at = int(datetime.now().timestamp() * 1000) + ms

    embed = discord.Embed(
        title="🎁 قفوي جديد!",
        description=f"اضغط على الزر أدناه للمشاركة!\n\n**الجائزة:** {prize}\n**عدد الفائزين:** {winner_count}\n**شرط الدعوات:** {required_invites}\n**ينتهي في:** <t:{math.floor(ends_at / 1000)}:R>",
        color=0xFF73FA
    )
    embed.set_footer(text=f"أنشئ بواسطة {interaction.user}")

    view = GiveawayJoinView()
    await interaction.response.send_message("✅ تم إنشاء القفوي بنجاح!", ephemeral=True)
    message = await interaction.channel.send(embed=embed, view=view)

    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO giveaways (message_id, channel_id, guild_id, prize, winner_count, required_invites, keys, ends_at, host_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(message.id), str(interaction.channel.id), str(interaction.guild.id), prize, winner_count, required_invites, json.dumps(keys_list), ends_at, str(interaction.user.id))
    )
    db.commit()


@bot.tree.command(
    name="دعواتي",
    description="عرض عدد دعواتك الحالية في السيرفر",
    guild=TARGET_GUILD
)
async def my_invites(interaction: discord.Interaction):
    if not check_server(interaction):
        return await interaction.response.send_message("❌ هذا البوت مخصص لسيرفر محدد.", ephemeral=True)

    user_id = str(interaction.user.id)
    validInvites = await get_valid_invites_count(interaction.guild, user_id)
    await interaction.response.send_message(f"📊 عدد دعواتك الناجحة الحالية في هذا السيرفر هي: **{validInvites}**", ephemeral=True)


# ============================================================
#            دوال مساعدة للقفويات
# ============================================================

async def check_user_qualifications(guild, userId, requiredInvites):
    validInvites = await get_valid_invites_count(guild, userId)
    return validInvites >= requiredInvites

async def get_valid_invites_count(guild, userId):
    cursor = db.cursor()
    cursor.execute("SELECT user_id FROM invites_tracker WHERE guild_id = ? AND inviter_id = ?", (str(guild.id), str(userId)))
    rows = cursor.fetchall()
    if not rows:
        return 0
    count = 0
    for row in rows:
        try:
            member = await guild.fetch_member(int(row[0]))
            if member:
                count += 1
        except Exception:
            pass
    return count

async def end_giveaway(giveaway, client):
    cursor = db.cursor()
    cursor.execute("UPDATE giveaways SET ended = 1 WHERE message_id = ?", (giveaway["message_id"],))
    db.commit()

    try:
        guild = client.get_guild(int(giveaway["guild_id"])) or await client.fetch_guild(int(giveaway["guild_id"]))
        channel = guild.get_channel(int(giveaway["channel_id"])) or await guild.fetch_channel(int(giveaway["channel_id"]))
        message = await channel.fetch_message(int(giveaway["message_id"])) if channel else None

        cursor.execute("SELECT user_id FROM participants WHERE message_id = ?", (giveaway["message_id"],))
        participants = cursor.fetchall()
        qualifiedUsers = []

        for p in participants:
            if await check_user_qualifications(guild, p[0], giveaway["required_invites"]):
                qualifiedUsers.append(p[0])

        import random
        random.shuffle(qualifiedUsers)

        keys = json.loads(giveaway["keys"])
        winnersCount = min(giveaway["winner_count"], len(qualifiedUsers))
        selectedWinners = qualifiedUsers[:winnersCount]

        winnerAnnouncement = f"🏆 **انتهى القفوي!**\n🎁 **الجائزة:** {giveaway['prize']}\n👥 **عدد الفائزين المطلوب:** {giveaway['winner_count']}\n\n"
        medals = ['🥇', '🥈', '🥉', '🏅', '🏅']

        for i in range(len(selectedWinners)):
            winnerId = selectedWinners[i]
            winnerUser = await client.fetch_user(int(winnerId))
            key = keys[i] if i < len(keys) else 'لا توجد مفاتيح كافية'

            try:
                await winnerUser.send(f"🎉 **مبروك!**\nلقد فزت في القفوي.\n🎁 **الجائزة:** {giveaway['prize']}\n🔑 **مفتاحك:**\n`{key}`")
            except Exception:
                pass

            winnerAnnouncement += f"{medals[i] if i < len(medals) else '🏆'} **الفائز رقم {i + 1}:** {winnerUser.mention}\n"

        if len(selectedWinners) == 0:
            winnerAnnouncement += "❌ لم يحقق أي شخص شروط القفوي، لذلك لا يوجد فائزين."

        if channel:
            await channel.send(winnerAnnouncement)

        if message:
            disabledView = discord.ui.View()
            disabledView.add_item(discord.ui.Button(label="انتهى القفوي ❌", style=discord.ButtonStyle.secondary, disabled=True, custom_id="ended"))
            await message.edit(view=disabledView)

    except Exception as e:
        print('خطأ عند إنهاء القفوي:', e)


@tasks.loop(seconds=10)
async def giveaway_checker():
    now = int(datetime.now().timestamp() * 1000)
    cursor = db.cursor()
    cursor.execute("SELECT * FROM giveaways WHERE ended = 0 AND ends_at <= ?", (now,))
    rows = cursor.fetchall()
    for row in rows:
        giveaway = {
            "message_id": row[0], "channel_id": row[1], "guild_id": row[2],
            "prize": row[3], "winner_count": row[4], "required_invites": row[5],
            "keys": row[6], "ends_at": row[7], "ended": row[8], "host_id": row[9]
        }
        await end_giveaway(giveaway, bot)


def parse_duration(duration):
    match = re.match(r"^(\d+)([mhd])$", duration)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    if unit == 'm':
        return value * 60 * 1000
    if unit == 'h':
        return value * 60 * 60 * 1000
    if unit == 'd':
        return value * 24 * 60 * 60 * 1000
    return None


# ============================================================
#                       التشغيل
# ============================================================

if __name__ == "__main__":
    if not TOKEN:
        print("❌ لم يتم العثور على توكن البوت في متغيرات البيئة.")
    else:
        bot.run(TOKEN)