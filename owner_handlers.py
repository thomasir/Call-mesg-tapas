import os
import shutil
import asyncio
import random
import string
import datetime
from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import GITHUB_REPO, GITHUB_TOKEN, DB_NAME, OWNER_ID
from database import (
    get_all_users, add_redeem_code, gift_premium_to_user,
    add_owner, remove_owner, get_owners, set_setting, get_setting
)

async def handle_owner_callbacks(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    data = query.data
    acting_user = query.from_user.id

    # ── Gift Premium ──────────────────────────────────────────────────────────
    if data == "owner_gift":
        context.user_data['state'] = 'waiting_gift_user'
        await query.message.reply_text(
            "🎁 𝗚𝗜𝗙𝗧 𝗣𝗥𝗘𝗠𝗜𝗨𝗠\n"
            "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            "◈ Send the User ID you want to gift premium:\n\n"
            "⊳ Example: 123456789\n"
            "⊳ /cancel to abort"
        )
        return

    # ── Apply Gift after plan selected ────────────────────────────────────────
    if data.startswith("owner_gift_apply_"):
        parts = data.split("_")
        try:
            target_id  = int(parts[3])
            plan_type  = parts[4]
            duration   = int(parts[5])
        except (IndexError, ValueError):
            await query.message.reply_text("❌ Invalid gift data.")
            return

        success = await gift_premium_to_user(target_id, plan_type, duration)
        if success:
            emoji = "👑" if plan_type == "VIP" else "⭐"
            await query.message.reply_text(
                f"✅ 𝗣𝗥𝗘𝗠𝗜𝗨𝗠 𝗚𝗜𝗙𝗧𝗘𝗗!\n"
                f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
                f"◈ 𝗨𝘀𝗲𝗿 𝗜𝗗  ➤ {target_id}\n"
                f"◈ 𝗣𝗹𝗮𝗻     ➤ {emoji} {plan_type}\n"
                f"◈ 𝗗𝘂𝗿𝗮𝘁𝗶𝗼𝗻  ➤ {duration} days\n"
                f"◈ 𝗟𝗶𝗺𝗶𝘁    ➤ {'200' if plan_type == 'VIP' else '50'} attacks/day\n\n"
                f"🎉 User has been upgraded!"
            )
        else:
            await query.message.reply_text(
                f"❌ User ID `{target_id}` not found in database!\n"
                "Make sure the user has started the bot first.",
                parse_mode='Markdown'
            )
        return

    # ── Stats ────────────────────────────────────────────────────────────────
    if data == "owner_stats":
        users = await get_all_users()
        total = len(users)
        free  = sum(1 for u in users if u['plan'] == 'FREE')
        paid  = total - free
        today = datetime.date.today().isoformat()
        active_today = sum(1 for u in users if u['last_attack_date'] == today)
        owners = await get_owners()
        await query.message.reply_text(
            f"📊 𝗧𝗔𝗣𝗔𝗦 𝗖𝗢𝗡𝗧𝗥𝗢𝗟 𝗣𝗔𝗡𝗘𝗟 — 𝗦𝗧𝗔𝗧𝗦\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"◈ 𝗧𝗼𝘁𝗮𝗹 𝗨𝘀𝗲𝗿𝘀    ➤ {total}\n"
            f"◈ 𝗙𝗿𝗲𝗲 𝗣𝗹𝗮𝗻     ➤ {free}\n"
            f"◈ 𝗣𝗮𝗶𝗱 𝗣𝗹𝗮𝗻     ➤ {paid}\n"
            f"◈ 𝗔𝗰𝘁𝗶𝘃𝗲 𝗧𝗼𝗱𝗮𝘆  ➤ {active_today}\n"
            f"◈ 𝗦𝘂𝗯-𝗢𝘄𝗻𝗲𝗿𝘀   ➤ {len(owners)}\n"
        )
        return

    # ── Users list ───────────────────────────────────────────────────────────
    if data == "owner_users":
        users = await get_all_users()
        if not users:
            await query.message.reply_text("No users yet.")
            return
        lines = ["👥 𝗨𝗦𝗘𝗥 𝗟𝗜𝗦𝗧\n┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"]
        for u in users[:50]:
            lines.append(f"• {u['username']} | ID: {u['user_id']} | {u['plan']}")
        if len(users) > 50:
            lines.append(f"...and {len(users)-50} more")
        await query.message.reply_text("\n".join(lines))
        return

    # ── Generate promo/redeem code ────────────────────────────────────────────
    if data.startswith("owner_gencode"):
        parts      = data.split("_")
        plan_type  = parts[2] if len(parts) > 2 else "PRO"
        duration_days = int(parts[3]) if len(parts) > 3 else 30

        code = f"TAPAS-{plan_type}-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        await add_redeem_code(code, plan_type, duration_days)

        emoji = "👑" if plan_type == "VIP" else "🎟"
        await query.message.reply_text(
            f"{emoji} 𝗣𝗥𝗢𝗠𝗢 𝗖𝗢𝗗𝗘 𝗚𝗘𝗡𝗘𝗥𝗔𝗧𝗘𝗗\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"◈ 𝗖𝗼𝗱𝗲     ➤ `{code}`\n"
            f"◈ 𝗣𝗹𝗮𝗻     ➤ {plan_type}\n"
            f"◈ 𝗗𝘂𝗿𝗮𝘁𝗶𝗼𝗻  ➤ {duration_days} days\n"
            f"◈ 𝗟𝗶𝗺𝗶𝘁 +  ➤ +5 attacks/day\n\n"
            f"📤 Share this code with the user.\n"
            f"They redeem via: /redeem {code}",
            parse_mode='Markdown'
        )
        return

    # ── Backup ───────────────────────────────────────────────────────────────
    if data == "owner_backup":
        backup_name = "bot_backup.zip"
        if os.path.exists("temp_backup"):
            shutil.rmtree("temp_backup")
        os.makedirs("temp_backup")

        files_to_backup = [DB_NAME, "main.py", "database.py", "config.py", "owner_handlers.py", "tapas.py"]
        for f in files_to_backup:
            if os.path.exists(f):
                shutil.copy(f, "temp_backup/")

        shutil.make_archive("bot_backup", 'zip', "temp_backup")

        with open(backup_name, 'rb') as f:
            await query.message.reply_document(
                document=f,
                filename=backup_name,
                caption="📦 Tapas Control Panel — Full Backup"
            )

        os.remove(backup_name)
        shutil.rmtree("temp_backup")
        return

    # ── Sync GitHub ───────────────────────────────────────────────────────────
    if data == "owner_sync":
        if not GITHUB_REPO or not GITHUB_TOKEN:
            await query.message.reply_text("❌ GitHub config missing. Set GITHUB_REPO and GITHUB_TOKEN env vars.")
            return

        await query.message.reply_text("🔄 Syncing all data to GitHub...")

        try:
            import subprocess

            commands = [
                ["git", "init"],
                ["git", "config", "user.name", "TapasControlPanel"],
                ["git", "config", "user.email", "bot@tapas.com"],
                ["git", "add", "."],
                ["git", "commit", "-m", f"Tapas CP Auto-Backup — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"],
                ["git", "branch", "-M", "main"],
                ["git", "remote", "remove", "origin"],
                ["git", "remote", "add", "origin", f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"],
                ["git", "push", "-u", "origin", "main", "--force"],
            ]

            for cmd in commands:
                subprocess.run(cmd, capture_output=True)

            await query.message.reply_text("✅ All files and database synced to GitHub successfully!")
        except Exception as e:
            await query.message.reply_text(f"❌ GitHub Sync Failed: {str(e)}")
        return

    # ── Add New Owner (only primary OWNER_ID can do this) ─────────────────────
    if data == "owner_add_owner":
        if acting_user != OWNER_ID:
            await query.message.reply_text("❌ Only the primary owner can add new owners.")
            return
        context.user_data['state'] = 'waiting_add_owner'
        await query.message.reply_text(
            "➕ 𝗔𝗗𝗗 𝗡𝗘𝗪 𝗢𝗪𝗡𝗘𝗥\n"
            "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            "◈ Send the Telegram User ID to add as owner:\n\n"
            "⊳ Example: 123456789\n"
            "⊳ /cancel to abort"
        )
        return

    # ── Remove Owner ──────────────────────────────────────────────────────────
    if data == "owner_remove_owner":
        if acting_user != OWNER_ID:
            await query.message.reply_text("❌ Only the primary owner can remove owners.")
            return
        owners = await get_owners()
        if not owners:
            await query.message.reply_text("❌ No sub-owners added yet.")
            return
        lines = ["🗑 𝗥𝗘𝗠𝗢𝗩𝗘 𝗢𝗪𝗡𝗘𝗥\n┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\nCurrent sub-owners:"]
        buttons = []
        for o in owners:
            lines.append(f"• ID: {o[0]} | Added: {o[1]}")
            buttons.append([InlineKeyboardButton(
                f"🗑 Remove {o[0]}", callback_data=f"owner_rm_{o[0]}"
            )])
        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="gift_cancel")])
        await query.message.reply_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    # ── Confirm remove owner ──────────────────────────────────────────────────
    if data.startswith("owner_rm_"):
        if acting_user != OWNER_ID:
            await query.message.reply_text("❌ Only the primary owner can remove owners.")
            return
        try:
            target_id = int(data.split("_")[2])
        except (IndexError, ValueError):
            await query.message.reply_text("❌ Invalid data.")
            return
        removed = await remove_owner(target_id)
        if removed:
            await query.message.reply_text(f"✅ Owner `{target_id}` removed successfully.", parse_mode='Markdown')
        else:
            await query.message.reply_text(f"❌ Owner `{target_id}` not found.", parse_mode='Markdown')
        return

    # ── Set Start Pic ─────────────────────────────────────────────────────────
    if data == "owner_set_pic":
        if acting_user != OWNER_ID:
            await query.message.reply_text("❌ Only the primary owner can set the start picture.")
            return
        context.user_data['state'] = 'waiting_start_pic'
        await query.message.reply_text(
            "🖼 𝗦𝗘𝗧 𝗦𝗧𝗔𝗥𝗧 𝗣𝗜𝗖𝗧𝗨𝗥𝗘\n"
            "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            "◈ Send me a photo to use as the welcome/start image.\n\n"
            "⊳ This photo will be shown to every new user on /start\n"
            "⊳ /cancel to abort\n\n"
            "📌 Send photo now:"
        )
        return

    # ── Remove Start Pic ─────────────────────────────────────────────────────
    if data == "owner_remove_pic":
        if acting_user != OWNER_ID:
            await query.message.reply_text("❌ Only the primary owner can change the start picture.")
            return
        await set_setting("start_pic", "")
        await query.message.reply_text("✅ Start picture removed. Bot will now send text-only welcome.")
        return
