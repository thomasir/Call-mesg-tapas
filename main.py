import logging
import asyncio
import datetime
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, ChatMemberHandler
from telegram.error import BadRequest, RetryAfter
from database import (
    init_db, add_user, get_user, update_stats, get_all_users,
    add_redeem_code, use_redeem_code, mark_channel_verified, is_channel_verified,
    gift_premium_to_user, is_secondary_owner, add_owner, set_setting, get_setting
)
from config import BOT_TOKEN, OWNER_ID, CHANNEL_USERNAME, CHANNEL_LINK, LOG_CHANNEL_ID
from owner_handlers import handle_owner_callbacks
from tapas import start_bombing, API_COUNT, SMS_COUNT, WHATSAPP_COUNT, CALL_COUNT
import tapas

logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Telegram Log Channel Handler ─────────────────────────────────────────────

import html as _html

_LOG_WHITELIST = ("tapas", "__main__", "main")


class TelegramLogHandler(logging.Handler):
    def __init__(self, bot, channel_id: int):
        super().__init__()
        self.bot = bot
        self.channel_id = channel_id
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task = None

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._drain())

    def emit(self, record: logging.LogRecord) -> None:
        top = record.name.split(".")[0]
        if top not in _LOG_WHITELIST:
            return
        try:
            self._queue.put_nowait(self.format(record))
        except Exception:
            pass

    async def _drain(self) -> None:
        while True:
            await asyncio.sleep(2)
            if self._queue.empty():
                continue
            lines = []
            while not self._queue.empty():
                lines.append(self._queue.get_nowait())
            chunk = ""
            for line in lines:
                if len(chunk) + len(line) + 1 > 3800:
                    await self._send(chunk)
                    chunk = line
                else:
                    chunk = (chunk + "\n" + line) if chunk else line
            if chunk:
                await self._send(chunk)

    async def _send(self, text: str) -> None:
        try:
            safe = _html.escape(text)
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=f"<pre>{safe}</pre>",
                parse_mode="HTML",
            )
        except Exception:
            pass


_tg_handler: TelegramLogHandler | None = None

# ─── State keys ───────────────────────────────────────────────────────────────
WAITING_PHONE     = "waiting_phone"
WAITING_COUNT     = "waiting_count"
WAITING_GIFT_USER = "waiting_gift_user"
WAITING_ADD_OWNER = "waiting_add_owner"
WAITING_START_PIC = "waiting_start_pic"

# ─── Helper: safe message edit ────────────────────────────────────────────────
async def safe_edit(msg, text):
    try:
        await msg.edit_text(text)
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after + 0.5)
        try:
            await msg.edit_text(text)
        except Exception:
            pass
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            pass
        elif "message to edit not found" in str(e).lower():
            pass
        else:
            raise

# ─── Helper: check if user is owner (primary or secondary) ───────────────────
async def is_owner(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    return await is_secondary_owner(user_id)

# ─── Keyboard Layouts ─────────────────────────────────────────────────────────
def get_main_menu(user_id: int, owner_flag: bool = False):
    keyboard = [
        [KeyboardButton("💣 START BOMB")],
        [KeyboardButton("👤 PROFILE"), KeyboardButton("🔗 REFERRAL")],
        [KeyboardButton("🎁 REDEEM CODE INFO")],
    ]
    if owner_flag:
        keyboard.append([KeyboardButton("👑 OWNER PANEL")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_count_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("10 💥",  callback_data="bomb_10"),
            InlineKeyboardButton("50 💥",  callback_data="bomb_50"),
        ],
        [
            InlineKeyboardButton("100 💥", callback_data="bomb_100"),
            InlineKeyboardButton("200 💥", callback_data="bomb_200"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="bomb_cancel")],
    ])

def get_join_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ I've Joined — Verify", callback_data="verify_join")],
    ])

def get_owner_panel_keyboard(is_primary: bool = False):
    """Build owner panel inline keyboard. Extra buttons for primary owner only."""
    rows = [
        [InlineKeyboardButton("📊 Stats",        callback_data="owner_stats"),
         InlineKeyboardButton("👥 Users",        callback_data="owner_users")],
        [InlineKeyboardButton("🎟 PRO Code",     callback_data="owner_gencode_PRO_30"),
         InlineKeyboardButton("👑 VIP Code",     callback_data="owner_gencode_VIP_60")],
        [InlineKeyboardButton("🎁 Gift Premium", callback_data="owner_gift")],
        [InlineKeyboardButton("📦 Backup",       callback_data="owner_backup"),
         InlineKeyboardButton("🔄 Sync GitHub",  callback_data="owner_sync")],
    ]
    if is_primary:
        rows.append([
            InlineKeyboardButton("➕ Add New Owner",  callback_data="owner_add_owner"),
            InlineKeyboardButton("🗑 Remove Owner",   callback_data="owner_remove_owner"),
        ])
        rows.append([
            InlineKeyboardButton("🖼 Set Start Pic",  callback_data="owner_set_pic"),
            InlineKeyboardButton("🚫 Remove Pic",     callback_data="owner_remove_pic"),
        ])
    return InlineKeyboardMarkup(rows)

# ─── Subscription check ───────────────────────────────────────────────────────
async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if await is_owner(user_id):
        return True

    # No channel configured → allow everyone through
    if not CHANNEL_USERNAME:
        return True

    if await is_channel_verified(user_id):
        return True

    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        status = member.status
        logger.info(f"check_subscription: user={user_id} status={status}")
        if status in ('member', 'administrator', 'creator'):
            await mark_channel_verified(user_id)
            return True
    except Exception as e:
        logger.error(f"check_subscription API error for user={user_id}: {e}")

    return False

# ─── Track channel joins ──────────────────────────────────────────────────────
async def track_channel_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if not result:
        return

    if not CHANNEL_USERNAME:
        return

    chat_username = (result.chat.username or "").lower()
    if chat_username != CHANNEL_USERNAME.lstrip("@").lower():
        return

    user_id = result.new_chat_member.user.id
    new_status = result.new_chat_member.status

    if new_status in ('member', 'administrator', 'creator'):
        await mark_channel_verified(user_id)
        logger.info(f"Channel join tracked: user={user_id} status={new_status}")
    elif new_status in ('left', 'kicked', 'banned'):
        logger.info(f"Channel leave tracked: user={user_id} status={new_status}")

# ─── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referred_by = None
    if context.args:
        try:
            referred_by = int(context.args[0].replace('ref_', ''))
            if referred_by == user.id:
                referred_by = None
        except ValueError:
            pass

    context.user_data.clear()

    await add_user(user.id, user.full_name, referred_by)
    is_subscribed = await check_subscription(user.id, context)

    if not is_subscribed:
        await update.message.reply_text(
            "◈━━━━━━━━━━━━━━━━━━━━━━━━━━━━◈\n"
            "🔒 𝗖𝗛𝗔𝗡𝗡𝗘𝗟 𝗩𝗘𝗥𝗜𝗙𝗜𝗖𝗔𝗧𝗜𝗢𝗡 𝗥𝗘𝗤𝗨𝗜𝗥𝗘𝗗\n"
            "◈━━━━━━━━━━━━━━━━━━━━━━━━━━━━◈\n\n"
            "◈ 𝗝𝗼𝗶𝗻 𝗼𝘂𝗿 𝗰𝗵𝗮𝗻𝗻𝗲𝗹 𝘁𝗼 𝘂𝘀𝗲 𝘁𝗵𝗲 𝗯𝗼𝘁 ◈\n"
            "𝘑𝘰𝘪𝘯 𝘵𝘩𝘦𝘯 𝘵𝘢𝘱 ✅ 𝘐'𝘷𝘦 𝘑𝘰𝘪𝘯𝘦𝘥 𝘣𝘦𝘭𝘰𝘸",
            reply_markup=get_join_keyboard()
        )
        return

    await send_welcome(update.message, user, context)

async def send_welcome(message, user, context):
    user_data  = await get_user(user.id)
    owner_flag = await is_owner(user.id)
    today      = datetime.date.today().isoformat()
    used       = user_data['today_attacks'] if user_data['last_attack_date'] == today else 0

    if owner_flag:
        remaining     = 9999
        limit_display = "∞"
    else:
        remaining     = max(0, user_data['daily_limit'] - used)
        limit_display = str(user_data['daily_limit'])

    plan       = user_data['plan']
    plan_emoji = "👑" if plan == 'VIP' else "⭐" if plan == 'PRO' else "🆓"
    plan_label = plan if plan != 'FREE' else "ꜰʀᴇᴇ"

    welcome_text = (
        f"⚡ 𝗧𝗔𝗣𝗔𝗦 𝗖𝗢𝗡𝗧𝗥𝗢𝗟 𝗣𝗔𝗡𝗘𝗟\n"
        f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        f"👋 𝗛𝗲𝘆, {user.full_name}!\n\n"
        f"◈ 𝗣𝗹𝗮𝗻     ➤ {plan_emoji} {plan_label}\n"
        f"◈ 𝗔𝗣𝗜𝘀     ➤ {API_COUNT} ᴀᴄᴛɪᴠᴇ\n"
        f"◈ 𝗠𝗮𝘅      ➤ {limit_display} ʙᴏᴍʙꜱ\n"
        f"◈ 𝗥𝗲𝗺𝗮𝗶𝗻𝗶𝗻𝗴 ➤ {remaining}/{limit_display} ᴛᴏᴅᴀʏ\n"
        f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        f"💣 𝗧𝗮𝗽 𝗦𝗧𝗔𝗥𝗧 𝗕𝗢𝗠𝗕 𝘁𝗼 𝗹𝗮𝘂𝗻𝗰𝗵!\n\n"
        f"◈ ᴜꜱᴇ ᴛʜᴇ ᴍᴇɴᴜ ʙᴇʟᴏᴡ 👇"
    )

    menu = get_main_menu(user.id, owner_flag=owner_flag)

    # Check if start pic is set
    start_pic = await get_setting("start_pic")
    if start_pic:
        try:
            await message.reply_photo(photo=start_pic, caption=welcome_text, reply_markup=menu)
            return
        except Exception:
            pass  # fallback to text if photo fails

    await message.reply_text(welcome_text, reply_markup=menu)

# ─── /redeem command ──────────────────────────────────────────────────────────
async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "❌ Usage: /redeem <code>\nExample: /redeem TAPAS-PRO-ABC123"
        )
        return

    code   = context.args[0].strip().upper()
    result = await use_redeem_code(code, user_id)

    if result == "not_found":
        await update.message.reply_text("❌ Invalid code! Check and try again.")
    elif result == "already_used":
        await update.message.reply_text("❌ This code has already been used!")
    elif result == "already_redeemed":
        await update.message.reply_text("❌ You have already redeemed a code!")
    else:
        plan_type, duration_days = result
        await update.message.reply_text(
            f"✅ 𝗖𝗢𝗗𝗘 𝗥𝗘𝗗𝗘𝗘𝗠𝗘𝗗!\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"◈ 𝗣𝗹𝗮𝗻     ➤ {plan_type}\n"
            f"◈ 𝗗𝘂𝗿𝗮𝘁𝗶𝗼𝗻  ➤ {duration_days} days\n"
            f"◈ 𝗘𝗻𝗷𝗼𝘆 𝘆𝗼𝘂𝗿 𝘂𝗽𝗴𝗿𝗮𝗱𝗲𝗱 𝗽𝗹𝗮𝗻! 🎉"
        )

# ─── /cancel command ──────────────────────────────────────────────────────────
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id    = update.effective_user.id
    owner_flag = await is_owner(user_id)
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelled.", reply_markup=get_main_menu(user_id, owner_flag=owner_flag))

# ─── Photo handler (for Set Start Pic feature) ────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if context.user_data.get('state') == WAITING_START_PIC and user_id == OWNER_ID:
        photo   = update.message.photo[-1]  # largest size
        file_id = photo.file_id
        await set_setting("start_pic", file_id)
        context.user_data.clear()
        await update.message.reply_text(
            "✅ 𝗦𝗧𝗔𝗥𝗧 𝗣𝗜𝗖𝗧𝗨𝗥𝗘 𝗦𝗘𝗧!\n"
            "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            "◈ This photo will now appear on every /start\n"
            "◈ Use '🚫 Remove Pic' button to reset it."
        )
    else:
        await update.message.reply_text("📷 Photo received. Use the menu buttons to navigate.")

# ─── Message handler ──────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text      = update.message.text
    user      = update.effective_user
    user_id   = user.id
    user_data = await get_user(user_id)

    if not user_data:
        await update.message.reply_text("⚠️ Send /start first to use the bot!")
        return

    owner_flag = await is_owner(user_id)

    # ── GIFT PREMIUM: Owner sends target User ID ──────────────────────────────
    if context.user_data.get('state') == WAITING_GIFT_USER and owner_flag:
        try:
            target_id = int(text.strip())
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid User ID! Send numbers only.\nExample: 123456789"
            )
            return

        context.user_data.clear()

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⭐ PRO  30 days", callback_data=f"owner_gift_apply_{target_id}_PRO_30"),
                InlineKeyboardButton("⭐ PRO  90 days", callback_data=f"owner_gift_apply_{target_id}_PRO_90"),
            ],
            [
                InlineKeyboardButton("👑 VIP  30 days", callback_data=f"owner_gift_apply_{target_id}_VIP_30"),
                InlineKeyboardButton("👑 VIP  60 days", callback_data=f"owner_gift_apply_{target_id}_VIP_60"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="gift_cancel")],
        ])
        await update.message.reply_text(
            f"🎁 𝗚𝗜𝗙𝗧 𝗣𝗥𝗘𝗠𝗜𝗨𝗠\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"◈ 𝗨𝘀𝗲𝗿 𝗜𝗗 ➤ {target_id}\n\n"
            f"Choose a plan to gift:",
            reply_markup=kb
        )
        return

    # ── ADD NEW OWNER: Primary owner sends target User ID ─────────────────────
    if context.user_data.get('state') == WAITING_ADD_OWNER and user_id == OWNER_ID:
        try:
            target_id = int(text.strip())
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid User ID! Send numbers only.\nExample: 123456789"
            )
            return

        context.user_data.clear()

        if target_id == OWNER_ID:
            await update.message.reply_text("❌ You are already the primary owner!")
            return

        added = await add_owner(target_id, OWNER_ID)
        if added:
            await update.message.reply_text(
                f"✅ 𝗡𝗘𝗪 𝗢𝗪𝗡𝗘𝗥 𝗔𝗗𝗗𝗘𝗗!\n"
                f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
                f"◈ 𝗨𝘀𝗲𝗿 𝗜𝗗 ➤ `{target_id}`\n"
                f"◈ They now have access to the Owner Panel.\n\n"
                f"🔑 They must send /start to see the panel button.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"⚠️ User `{target_id}` is already an owner.",
                parse_mode='Markdown'
            )
        return

    # ── /cancel via text ─────────────────────────────────────────────────────
    if text.lower() in ("/cancel", "cancel", "❌ cancel"):
        if context.user_data.get('state'):
            context.user_data.clear()
            await update.message.reply_text("❌ Cancelled.", reply_markup=get_main_menu(user_id, owner_flag=owner_flag))
        else:
            await update.message.reply_text("Nothing to cancel.", reply_markup=get_main_menu(user_id, owner_flag=owner_flag))
        return

    # ── Waiting for phone number ──────────────────────────────────────────────
    if context.user_data.get('state') == WAITING_PHONE:
        phone = text.strip().replace(" ", "").replace("-", "").replace("+91", "").lstrip("0")
        if not phone.isdigit() or len(phone) != 10:
            await update.message.reply_text(
                "❌ 𝗜𝗻𝘃𝗮𝗹𝗶𝗱 𝗡𝘂𝗺𝗯𝗲𝗿!\n\n"
                "◈ Send 10-digit number only\n"
                "◈ Example: 9876543210\n"
                "◈ Do NOT include +91 or 0"
            )
            return

        context.user_data['target_phone'] = phone
        context.user_data['state'] = WAITING_COUNT

        today     = datetime.date.today().isoformat()
        used      = user_data['today_attacks'] if user_data['last_attack_date'] == today else 0
        remaining = max(0, user_data['daily_limit'] - used)

        await update.message.reply_text(
            "╔━━━━━━━━━━━━━━━━━━━━━━━━━╗\n"
            "║  🎯  ꜱᴇʟᴇᴄᴛ ʙᴏᴍʙ ᴄᴏᴜɴᴛ\n"
            "╚━━━━━━━━━━━━━━━━━━━━━━━━━╝\n\n"
            f"  📱 ᴛᴀʀɢᴇᴛ  → +91{phone}\n"
            f"  💥 ᴍᴀx     → {remaining} (today's remaining)\n"
            f"  🌐 ᴀᴘɪꜱ    → {API_COUNT} ᴀᴄᴛɪᴠᴇ\n\n"
            "  👇 ᴄʜᴏᴏꜱᴇ ʜᴏᴡ ᴍᴀɴʏ ʀᴏᴜɴᴅꜱ:",
            reply_markup=get_count_keyboard()
        )
        return

    # ── Waiting for count (user typed instead of tapping button) ─────────────
    if context.user_data.get('state') == WAITING_COUNT:
        phone = context.user_data.get('target_phone', 'N/A')
        await update.message.reply_text(
            "⚠️ Please select a bomb count using the buttons above!\n\n"
            f"📱 Target: +91{phone}\n\n"
            "Or tap ❌ Cancel to go back.",
            reply_markup=get_count_keyboard()
        )
        return

    # ── PROFILE ──────────────────────────────────────────────────────────────
    if text == "👤 PROFILE":
        today     = datetime.date.today().isoformat()
        used      = user_data['today_attacks'] if user_data['last_attack_date'] == today else 0
        remaining = max(0, user_data['daily_limit'] - used)
        plan_emoji = "👑" if user_data['plan'] == 'VIP' else "⭐" if user_data['plan'] == 'PRO' else "🆓"
        profile_text = (
            f"👤 𝗠𝗬 𝗣𝗥𝗢𝗙𝗜𝗟𝗘\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"◈ 𝗡𝗮𝗺𝗲   ➤ {user_data['username']}\n"
            f"◈ 𝗜𝗗     ➤ {user_data['user_id']}\n"
            f"◈ 𝗝𝗼𝗶𝗻𝗲𝗱 ➤ {user_data['joined_date']}\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"🏷 𝗣𝗟𝗔𝗡\n"
            f"⊳ 𝗧𝘆𝗽𝗲   ➤ {plan_emoji} {user_data['plan']}\n"
            f"⊳ 𝗘𝘅𝗽𝗶𝗿𝘆 ➤ {user_data['expiry']}\n"
            f"⊳ 𝗔𝗣𝗜𝘀   ➤ {API_COUNT} ᴀᴄᴛɪᴠᴇ\n"
            f"⊳ 𝗟𝗶𝗺𝗶𝘁  ➤ {user_data['daily_limit']} ᴀᴛᴛᴀᴄᴋꜱ/ᴅᴀʏ\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"📊 𝗦𝗧𝗔𝗧𝗦\n"
            f"⊳ 𝗧𝗼𝘁𝗮𝗹 𝗔𝘁𝘁𝗮𝗰𝗸𝘀  ➤ {user_data['total_attacks']}\n"
            f"⊳ 𝗦𝘂𝗰𝗰𝗲𝘀𝘀         ➤ {user_data['success_attacks']}\n"
            f"⊳ 𝗧𝗼𝗱𝗮𝘆 𝗨𝘀𝗲𝗱      ➤ {used}/{user_data['daily_limit']}\n"
            f"⊳ 𝗥𝗲𝗺𝗮𝗶𝗻𝗶𝗻𝗴       ➤ {remaining}\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"👥 𝗥𝗘𝗙𝗘𝗥𝗥𝗔𝗟𝗦\n"
            f"⊳ 𝗥𝗲𝗳𝗲𝗿𝗿𝗲𝗱 ➤ {user_data['referral_count']} ᴜꜱᴇʀꜱ\n"
        )
        await update.message.reply_text(profile_text)
        return

    # ── REFERRAL ─────────────────────────────────────────────────────────────
    if text == "🔗 REFERRAL":
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
        ref_text = (
            f"🔗 𝗬𝗢𝗨𝗥 𝗥𝗘𝗙𝗘𝗥𝗥𝗔𝗟 𝗟𝗜𝗡𝗞\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"◈ Share this link with friends!\n\n"
            f"`{ref_link}`\n\n"
            f"◈ 𝗥𝗲𝘄𝗮𝗿𝗱: +1 extra attack/day per referral\n"
            f"◈ 𝗥𝗲𝗳𝗲𝗿𝗿𝗲𝗱 𝘀𝗼 𝗳𝗮𝗿: {user_data['referral_count']} users\n"
        )
        await update.message.reply_text(ref_text, parse_mode='Markdown')
        return

    # ── REDEEM INFO ───────────────────────────────────────────────────────────
    if text == "🎁 REDEEM CODE INFO":
        await update.message.reply_text(
            "🎁 𝗥𝗘𝗗𝗘𝗘𝗠 𝗖𝗢𝗗𝗘𝗦\n"
            "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            "◈ Use /redeem <code> to activate a plan\n"
            "◈ Get codes from channel events\n"
            f"◈ Channel: {CHANNEL_LINK}"
        )
        return

    # ── OWNER PANEL ───────────────────────────────────────────────────────────
    if text == "👑 OWNER PANEL" and owner_flag:
        is_prim = (user_id == OWNER_ID)
        await update.message.reply_text(
            "👑 𝗧𝗔𝗣𝗔𝗦 𝗖𝗢𝗡𝗧𝗥𝗢𝗟 𝗣𝗔𝗡𝗘𝗟\n"
            "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            "Select an option below:",
            reply_markup=get_owner_panel_keyboard(is_primary=is_prim)
        )
        return

    # ── START BOMB ────────────────────────────────────────────────────────────
    if text == "💣 START BOMB":
        is_subscribed = await check_subscription(user_id, context)
        if not is_subscribed:
            await update.message.reply_text(
                "❌ Join our channel first to use the bot!",
                reply_markup=get_join_keyboard()
            )
            return

        today     = datetime.date.today().isoformat()
        used      = user_data['today_attacks'] if user_data['last_attack_date'] == today else 0

        if owner_flag:
            remaining = 9999
        else:
            remaining = max(0, user_data['daily_limit'] - used)

        if remaining <= 0:
            await update.message.reply_text(
                "⚠️ 𝗗𝗮𝗶𝗹𝘆 𝗟𝗶𝗺𝗶𝘁 𝗥𝗲𝗮𝗰𝗵𝗲𝗱!\n\n"
                "◈ Come back tomorrow 🕛\n"
                "◈ Or redeem a code to upgrade your plan!"
            )
            return

        context.user_data['state'] = WAITING_PHONE

        plan       = user_data['plan']
        plan_emoji = "👑" if plan == 'VIP' else "⭐" if plan == 'PRO' else "🆓"

        await update.message.reply_text(
            "╔━━━━━━━━━━━━━━━━━━━━━━━━━╗\n"
            "║  📱  ᴇɴᴛᴇʀ ᴛᴀʀɢᴇᴛ ɴᴜᴍʙᴇʀ\n"
            "╚━━━━━━━━━━━━━━━━━━━━━━━━━╝\n\n"
            f"  ⊳ 𝘌𝘹𝘢𝘮𝘱𝘭𝘦: 9876543210\n"
            f"  ⊳ 𝘞𝘪𝘵𝘩𝘰𝘶𝘵 +91 𝘰𝘳 0\n\n"
            f"  ◈ {plan_emoji} 𝗣𝗹𝗮𝗻      ➤  {plan}\n"
            f"  ◈ 𝗔𝗣𝗜𝘀        ➤  {API_COUNT} ᴀᴄᴛɪᴠᴇ\n"
            f"  ◈ 𝗥𝗲𝗺𝗮𝗶𝗻𝗶𝗻𝗴  ➤  {remaining}/{user_data['daily_limit']} ᴛᴏᴅᴀʏ\n"
            "• • • • • • • • • • • • • • • • • • • •\n\n"
            "  ⊳ Type /cancel to abort"
        )
        return

    # ── Unknown message ───────────────────────────────────────────────────────
    await update.message.reply_text(
        "❓ Use the menu buttons below to navigate.\n"
        "Or send /start to restart.",
        reply_markup=get_main_menu(user_id, owner_flag=owner_flag)
    )

# ─── Callback handler ─────────────────────────────────────────────────────────
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    data    = query.data
    user    = query.from_user
    user_id = user.id

    owner_flag = await is_owner(user_id)

    # ── Verify join ──────────────────────────────────────────────────────────
    if data == "verify_join":
        is_subscribed = await check_subscription(user_id, context)

        if not is_subscribed:
            await mark_channel_verified(user_id)

        await query.answer("✅ Verified! Welcome!")
        await add_user(user_id, user.full_name)
        user_data = await get_user(user_id)
        today     = datetime.date.today().isoformat()
        used      = user_data['today_attacks'] if user_data['last_attack_date'] == today else 0

        if owner_flag:
            remaining     = 9999
            limit_display = "∞"
        else:
            remaining     = max(0, user_data['daily_limit'] - used)
            limit_display = str(user_data['daily_limit'])

        plan       = user_data['plan']
        plan_emoji = "👑" if plan == 'VIP' else "⭐" if plan == 'PRO' else "🆓"
        plan_label = plan if plan != 'FREE' else "ꜰʀᴇᴇ"

        welcome_text = (
            f"⚡ 𝗧𝗔𝗣𝗔𝗦 𝗖𝗢𝗡𝗧𝗥𝗢𝗟 𝗣𝗔𝗡𝗘𝗟\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"👋 𝗛𝗲𝘆, {user.full_name}!\n\n"
            f"◈ 𝗣𝗹𝗮𝗻     ➤ {plan_emoji} {plan_label}\n"
            f"◈ 𝗔𝗣𝗜𝘀     ➤ {API_COUNT} ᴀᴄᴛɪᴠᴇ\n"
            f"◈ 𝗠𝗮𝘅      ➤ {limit_display} ʙᴏᴍʙꜱ\n"
            f"◈ 𝗥𝗲𝗺𝗮𝗶𝗻𝗶𝗻𝗴 ➤ {remaining}/{limit_display} ᴛᴏᴅᴀʏ\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"💣 𝗧𝗮𝗽 𝗦𝗧𝗔𝗥𝗧 𝗕𝗢𝗠𝗕 𝘁𝗼 𝗹𝗮𝘂𝗻𝗰𝗵!\n\n"
            f"◈ ᴜꜱᴇ ᴛʜᴇ ᴍᴇɴᴜ ʙᴇʟᴏᴡ 👇"
        )
        try:
            await query.edit_message_text(
                "◈━━━━━━━━━━━━━━━━━━━━━━━━━━━━◈\n"
                "✅ 𝗩𝗘𝗥𝗜𝗙𝗜𝗖𝗔𝗧𝗜𝗢𝗡 𝗦𝗨𝗖𝗖𝗘𝗦𝗦𝗙𝗨𝗟\n"
                "◈━━━━━━━━━━━━━━━━━━━━━━━━━━━━◈"
            )
        except Exception:
            pass
        await query.message.reply_text(welcome_text, reply_markup=get_main_menu(user_id, owner_flag=owner_flag))
        return

    # All other callbacks — answer immediately
    await query.answer()

    # ── Bomb count selection ──────────────────────────────────────────────────
    if data.startswith("bomb_"):
        if data == "bomb_cancel":
            context.user_data.clear()
            try:
                await query.edit_message_text("❌ Attack cancelled. Tap 💣 START BOMB to try again.")
            except Exception:
                pass
            return

        try:
            rounds = int(data.split("_")[1])
        except (IndexError, ValueError):
            await query.edit_message_text("❌ Invalid selection. Try again.")
            return

        phone = context.user_data.get('target_phone')
        if not phone:
            try:
                await query.edit_message_text("❌ Session expired. Press 💣 START BOMB again.")
            except Exception:
                pass
            context.user_data.clear()
            return

        user_data = await get_user(user_id)
        today     = datetime.date.today().isoformat()
        used      = user_data['today_attacks'] if user_data['last_attack_date'] == today else 0

        if owner_flag:
            remaining = 9999
        else:
            remaining = max(0, user_data['daily_limit'] - used)

        if remaining <= 0:
            try:
                await query.edit_message_text("⚠️ Daily limit reached! Come back tomorrow. 🕛")
            except Exception:
                pass
            return

        # Cap rounds to remaining limit (skip cap for owner)
        if not owner_flag:
            rounds = min(rounds, remaining)

        context.user_data.clear()

        total_hits = rounds * API_COUNT

        try:
            await query.edit_message_text(
                f"🚀 ʟᴀᴜɴᴄʜɪɴɢ ᴀᴛᴛᴀᴄᴋ...\n\n"
                f"  📱 ꜱᴍꜱ: {SMS_COUNT}  💬 ᴡᴀ: {WHATSAPP_COUNT}  📞 ᴄᴀʟʟ: {CALL_COUNT}\n"
                f"  💣 ʀᴏᴜɴᴅꜱ: {rounds} × {API_COUNT} = {total_hits} ʜɪᴛꜱ\n"
                f"  ⏳ ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ..."
            )
        except Exception:
            pass

        prog_msg = await query.message.reply_text(
            f"🔥 𝗔𝗧𝗧𝗔𝗖𝗞 𝗦𝗧𝗔𝗥𝗧𝗜𝗡𝗚...\n"
            f"🎯 ᴛᴀʀɢᴇᴛ  →  +91{phone}\n"
            f"📱 ꜱᴍꜱ     →  {SMS_COUNT}  💬 ᴡᴀ  →  {WHATSAPP_COUNT}  📞 ᴄᴀʟʟ  →  {CALL_COUNT}\n"
            f"💣 ʀᴏᴜɴᴅꜱ  →  {rounds}\n"
            f"⏳ ɪɴɪᴛɪᴀʟɪᴢɪɴɢ..."
        )

        last_edit = [0.0]

        async def progress_callback(round_num, total_rounds, success, failed,
                                    done, total, pct, bar, speed,
                                    sms_ok=0, wa_ok=0, call_ok=0):
            now = time.monotonic()
            if now - last_edit[0] < 3.0 and pct < 100:
                return
            last_edit[0] = now
            await safe_edit(
                prog_msg,
                f"🔥 𝗔𝗧𝗧𝗔𝗖𝗞 𝗜𝗡 𝗣𝗥𝗢𝗚𝗥𝗘𝗦𝗦\n"
                f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
                f"🎯 ᴛᴀʀɢᴇᴛ  →  +91{phone}\n"
                f"🔄 ʀᴏᴜɴᴅ   →  {round_num}/{total_rounds}\n"
                f"⚡ ꜱᴘᴇᴇᴅ   →  {speed}\n"
                f"[ {bar} ] {pct}%\n"
                f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
                f"📱 ꜱᴍꜱ       →  {sms_ok}\n"
                f"💬 ᴡʜᴀᴛꜱᴀᴘᴘ  →  {wa_ok}\n"
                f"📞 ᴄᴀʟʟ      →  {call_ok}\n"
                f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
                f"✅ ᴛᴏᴛᴀʟ     →  {success}\n"
                f"❌ ꜰᴀɪʟᴇᴅ   →  {failed}\n"
                f"📈 ʀᴀᴛᴇ     →  {int(success/max(done,1)*100)}%\n"
                f"⚡ 𝗧𝗔𝗣𝗔𝗦 𝗖𝗢𝗡𝗧𝗥𝗢𝗟 𝗣𝗔𝗡𝗘𝗟"
            )

        try:
            success_count, failed_count, sms_ok, wa_ok, call_ok = await start_bombing(
                phone, rounds, progress_callback
            )
        except Exception as e:
            logger.error(f"Bombing error: {e}")
            await safe_edit(prog_msg, f"❌ Attack failed due to an error.\n{e}")
            return

        await update_stats(user_id, rounds, success_count > 0)

        rate = int(success_count / max(success_count + failed_count, 1) * 100)
        await safe_edit(
            prog_msg,
            f"✅ 𝗔𝗧𝗧𝗔𝗖𝗞 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘𝗗\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"🎯 ᴛᴀʀɢᴇᴛ      →  +91{phone}\n"
            f"💣 ʀᴏᴜɴᴅꜱ      →  {rounds}\n"
            f"🌐 ᴀᴘɪꜱ        →  {API_COUNT}\n"
            f"💥 ᴛᴏᴛᴀʟ ʜɪᴛꜱ  →  {total_hits}\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"📱 ꜱᴍꜱ         →  {sms_ok}\n"
            f"💬 ᴡʜᴀᴛꜱᴀᴘᴘ   →  {wa_ok}\n"
            f"📞 ᴄᴀʟʟ        →  {call_ok}\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"✅ ꜱᴜᴄᴄᴇꜱꜱ    →  {success_count}\n"
            f"❌ ꜰᴀɪʟᴇᴅ      →  {failed_count}\n"
            f"📈 ʀᴀᴛᴇ        →  {rate}%\n"
            f"[ {'▰'*14} ] 100%\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"⚡ 𝗧𝗔𝗣𝗔𝗦 𝗖𝗢𝗡𝗧𝗥𝗢𝗟 𝗣𝗔𝗡𝗘𝗟 ✔️"
        )
        return

    # ── Gift cancel ───────────────────────────────────────────────────────────
    if data == "gift_cancel":
        context.user_data.clear()
        try:
            await query.edit_message_text("❌ Cancelled.")
        except Exception:
            pass
        return

    # ── Owner callbacks ───────────────────────────────────────────────────────
    if data.startswith("owner_") and owner_flag:
        await handle_owner_callbacks(query, context)
        return

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    async def post_init(app):
        global _tg_handler
        await init_db()
        logger.info("DB initialized.")

        _tg_handler = TelegramLogHandler(app.bot, LOG_CHANNEL_ID)
        _tg_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S"
        ))
        _tg_handler.setLevel(logging.INFO)
        _tg_handler.start()

        root = logging.getLogger()
        root.addHandler(_tg_handler)
        logging.getLogger("tapas").setLevel(logging.INFO)
        logging.getLogger("bomber").setLevel(logging.INFO)

        bot_info    = await app.bot.get_me()
        startup_msg = (
            f"🤖 TAPAS CONTROL PANEL — BOT STARTED\n"
            f"Name    : {bot_info.full_name}\n"
            f"Username: @{bot_info.username}\n"
            f"APIs    : {API_COUNT}\n"
            f"Log ch  : {LOG_CHANNEL_ID}\n"
            f"Time    : {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"{'─'*40}\n"
            f"Watching ALL bot events from here ✅"
        )
        try:
            await app.bot.send_message(
                chat_id=LOG_CHANNEL_ID,
                text=f"<pre>{startup_msg}</pre>",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Could not send startup log to channel: {e}")

        logger.info(f"Bot @{bot_info.username} ready | APIs={API_COUNT}")
        asyncio.create_task(tapas.refresh_proxy_pool())

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(ChatMemberHandler(track_channel_join, ChatMemberHandler.CHAT_MEMBER))

    logger.info(f"Bot started! APIs loaded: {API_COUNT}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
