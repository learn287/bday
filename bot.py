import asyncio
import datetime
import json
import logging
import os
import time
import pytz
import yt_dlp
from telegram import (
    BotCommand,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.error import BadRequest, NetworkError, TimedOut
from telegram.ext import (
    ApplicationBuilder,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- Configuration ---
BOT_TOKEN = "8291162968:AAHoM1rpmuVe18oWzYb30nYHpo1zrCfyS28"
TIMEZONE = "Asia/Kolkata"
CHATS_FILE = "registered_chats.json"

# Live GitHub Pages URL
GITHUB_WEBAPP_URL = "https://learn287.github.io/bday/"

LOCAL_MEDIA_FILE = "gift.gif"
GIFT_ANIMATION_URL = "https://media.giphy.com/media/l4KibWpBGWchSqCRy/giphy.gif"
DELETE_DELAY_SECONDS = 600


# --- Chat Persistence ---
def load_chats() -> set:
  if os.path.exists(CHATS_FILE):
    try:
      with open(CHATS_FILE, "r") as f:
        return set(json.load(f))
    except Exception:
      return set()
  return set()


def save_chat(chat_id: int):
  chats = load_chats()
  chats.add(chat_id)
  with open(CHATS_FILE, "w") as f:
    json.dump(list(chats), f)


async def track_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
  chat = update.effective_chat
  if chat and chat.type in ["group", "supergroup"]:
    save_chat(chat.id)


# --- Birthday Feature ---
async def delete_after_delay(context: ContextTypes.DEFAULT_TYPE):
  if not context.job or not context.job.data:
    return
  chat_id, message_id = context.job.data
  try:
    await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
  except Exception:
    pass


async def deliver_gift(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
  # Fresh timestamp prevents cached files
  fresh_game_url = f"{GITHUB_WEBAPP_URL}?t={int(time.time())}"

  # Single button that opens the working GitHub project directly
  keyboard = [[InlineKeyboardButton("🎁 Tap me", url="https://t.me/Snoffy_1_Bot/bday")]]
  reply_markup = InlineKeyboardMarkup(keyboard)
  caption_text = "🎉 A special surprise has arrived! Tap below to open:"
  sent_msg = None

  if os.path.exists(LOCAL_MEDIA_FILE):
    try:
      with open(LOCAL_MEDIA_FILE, "rb") as media:
        sent_msg = await context.bot.send_animation(
            chat_id=chat_id,
            animation=media,
            caption=caption_text,
            reply_markup=reply_markup,
        )
    except Exception as e:
      logging.warning(f"Local animation send failed: {e}")

  if not sent_msg and GIFT_ANIMATION_URL:
    try:
      sent_msg = await context.bot.send_animation(
          chat_id=chat_id,
          animation=GIFT_ANIMATION_URL,
          caption=caption_text,
          reply_markup=reply_markup,
      )
    except Exception as e:
      logging.warning(f"Remote GIF send failed: {e}")

  if not sent_msg:
    try:
      sent_msg = await context.bot.send_message(
          chat_id=chat_id,
          text=f"🎈 *Happy Birthday Saran!* ✨\n\n{caption_text}",
          reply_markup=reply_markup,
          parse_mode="Markdown",
      )
    except Exception as e:
      logging.error(f"Fallback text message send failed: {e}")
      return

  if sent_msg and context.job_queue:
    context.job_queue.run_once(
        delete_after_delay,
        when=DELETE_DELAY_SECONDS,
        data=(chat_id, sent_msg.message_id),
    )


async def test_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
  chat_id = update.effective_chat.id
  save_chat(chat_id)
  await deliver_gift(chat_id, context)


async def scheduled_birthday_broadcast(context: ContextTypes.DEFAULT_TYPE):
  for chat_id in load_chats():
    try:
      await deliver_gift(chat_id, context)
    except Exception as e:
      logging.error(f"Broadcast failed for {chat_id}: {e}")


# --- Command Menu Registration & Help ---
async def post_init(application):
  commands = [
      BotCommand("help", "Open help & commands menu"),
      BotCommand("test", "Preview birthday surprise card"),
      BotCommand("play", "Play and download music"),
      BotCommand("ban", "Ban a user (Admin only)"),
      BotCommand("kick", "Kick a user (Admin only)"),
      BotCommand("mute", "Mute a user (Admin only)"),
      BotCommand("unmute", "Unmute a user (Admin only)"),
      BotCommand("pin", "Pin replied message (Admin only)"),
  ]
  await application.bot.set_my_commands(commands)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  help_text = (
      "🤖 *Snoffy Bot Command Menu*\n\n"
      "🎉 *Celebration*\n"
      "• `/test` - Preview the birthday surprise overlay\n"
      "• `/bday` - Alternate trigger for birthday card\n\n"
      "🎵 *Music*\n"
      "• `/play <song name>` - Search & download MP3 audio\n\n"
      "🛡️ *Admin Moderation (Reply to user)*\n"
      "• `/ban` - Ban user from group\n"
      "• `/kick` - Kick user from group\n"
      "• `/mute` - Restrict user messaging\n"
      "• `/unmute` - Restore user messaging\n"
      "• `/pin` - Pin replied message\n\n"
      "💬 *Chat*\n"
      "• Tag me or reply to my message in groups to talk with me!"
  )
  await update.message.reply_text(help_text, parse_mode="Markdown")
  # --- Group Management ---
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
  if update.effective_chat.type not in ["group", "supergroup"]:
    return False
  member = await context.bot.get_chat_member(
      update.effective_chat.id, update.effective_user.id
  )
  return member.status in ["administrator", "creator"]


async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if update.effective_chat.type not in ["group", "supergroup"]:
    await update.message.reply_text("This command can only be used in groups.")
    return
  if not await is_admin(update, context):
    await update.message.reply_text("❌ Admin permissions required.")
    return
  if not update.message.reply_to_message:
    await update.message.reply_text(
        "Reply to a user's message with /ban to ban them."
    )
    return

  target = update.message.reply_to_message.from_user
  try:
    await context.bot.ban_chat_member(update.effective_chat.id, target.id)
    await update.message.reply_text(f"🚫 {target.first_name} has been banned.")
  except BadRequest as e:
    await update.message.reply_text(f"Failed to ban: {e.message}")


async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if update.effective_chat.type not in ["group", "supergroup"]:
    await update.message.reply_text("This command can only be used in groups.")
    return
  if not await is_admin(update, context):
    await update.message.reply_text("❌ Admin permissions required.")
    return
  if not update.message.reply_to_message:
    await update.message.reply_text(
        "Reply to a user's message with /kick to kick them."
    )
    return

  target = update.message.reply_to_message.from_user
  try:
    await context.bot.unban_chat_member(update.effective_chat.id, target.id)
    await update.message.reply_text(f"👢 {target.first_name} has been kicked.")
  except BadRequest as e:
    await update.message.reply_text(f"Failed to kick: {e.message}")


async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if update.effective_chat.type not in ["group", "supergroup"]:
    await update.message.reply_text("This command can only be used in groups.")
    return
  if not await is_admin(update, context):
    await update.message.reply_text("❌ Admin permissions required.")
    return
  if not update.message.reply_to_message:
    await update.message.reply_text(
        "Reply to a user's message with /mute to mute them."
    )
    return

  target = update.message.reply_to_message.from_user
  no_permissions = ChatPermissions(can_send_messages=False)
  try:
    await context.bot.restrict_chat_member(
        update.effective_chat.id, target.id, permissions=no_permissions
    )
    await update.message.reply_text(f"🔇 {target.first_name} has been muted.")
  except BadRequest as e:
    await update.message.reply_text(f"Failed to mute: {e.message}")


async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if update.effective_chat.type not in ["group", "supergroup"]:
    await update.message.reply_text("This command can only be used in groups.")
    return
  if not await is_admin(update, context):
    await update.message.reply_text("❌ Admin permissions required.")
    return
  if not update.message.reply_to_message:
    await update.message.reply_text("Reply to a user's message with /unmute.")
    return

  target = update.message.reply_to_message.from_user
  all_permissions = ChatPermissions(
      can_send_messages=True,
      can_send_media_messages=True,
      can_send_other_messages=True,
  )
  try:
    await context.bot.restrict_chat_member(
        update.effective_chat.id, target.id, permissions=all_permissions
    )
    await update.message.reply_text(f"🔊 {target.first_name} unmuted.")
  except BadRequest as e:
    await update.message.reply_text(f"Failed to unmute: {e.message}")


async def pin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if update.effective_chat.type not in ["group", "supergroup"]:
    return
  if not await is_admin(update, context):
    return
  if update.message.reply_to_message:
    await context.bot.pin_chat_message(
        update.effective_chat.id, update.message.reply_to_message.message_id
    )


# --- Non-blocking Music Player ---
def _download_song(query: str):
  ydl_opts = {
      "format": "bestaudio/best",
      "default_search": "ytsearch1:",
      "outtmpl": "downloads/%(id)s.%(ext)s",
      "postprocessors": [{
          "key": "FFmpegExtractAudio",
          "preferredcodec": "mp3",
          "preferredquality": "192",
      }],
      "quiet": True,
      "no_warnings": True,
  }
  with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(query, download=True)
    if "entries" in info:
      info = info["entries"][0]
    title = info.get("title", "Audio Track")
    filename = f"downloads/{info['id']}.mp3"
    return title, filename


async def play_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not context.args:
    await update.message.reply_text(
        "Usage: `/play <song name or YouTube URL>`", parse_mode="Markdown"
    )
    return

  query = " ".join(context.args)
  status_msg = await update.message.reply_text(
      f"🔍 Searching: `{query}`...", parse_mode="Markdown"
  )

  try:
    title, filename = await asyncio.to_thread(_download_song, query)

    await status_msg.edit_text("⬆️ Uploading track...")
    with open(filename, "rb") as audio_file:
      await update.message.reply_audio(
          audio=audio_file,
          title=title,
          caption=f"🎶 **{title}**",
          parse_mode="Markdown",
      )

    await status_msg.delete()
    if os.path.exists(filename):
      os.remove(filename)

  except Exception as e:
    logging.error(f"Music error: {e}")
    await status_msg.edit_text("❌ Could not download or process that track.")


# --- Conversational Handler ---
async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not update.effective_message or not update.effective_message.text:
    return

  user_text = update.effective_message.text.strip()
  bot_username = (await context.bot.get_me()).username
  is_mentioned = f"@{bot_username}" in user_text
  is_reply_to_bot = (
      update.effective_message.reply_to_message
      and update.effective_message.reply_to_message.from_user.id
      == context.bot.id
  )

  if update.effective_chat.type in ["group", "supergroup"] and not (
      is_mentioned or is_reply_to_bot
  ):
    return

  clean_text = user_text.replace(f"@{bot_username}", "").strip().lower()
  if any(greet in clean_text for greet in ["hi", "hello", "hey"]):
    response = (
        "Hey! Use /help to see all my features, including music and group"
        " tools."
    )
  else:
    response = (
        f"Received: '{user_text}'. (Send /test for the birthday overlay!)"
    )

  await update.effective_message.reply_text(response)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
  if isinstance(context.error, (NetworkError, TimedOut)):
    logging.warning(
        "Network connection dropped temporarily. Auto-reconnecting..."
    )
  else:
    logging.error(f"Exception occurred: {context.error}")


def main():
  os.makedirs("downloads", exist_ok=True)
  custom_request = HTTPXRequest(
      connect_timeout=30.0,
      read_timeout=30.0,
      write_timeout=30.0,
      pool_timeout=30.0,
  )

  app = (
      ApplicationBuilder()
      .token(BOT_TOKEN)
      .request(custom_request)
      .post_init(post_init)
      .build()
  )

  # Core & Help
  app.add_handler(
      ChatMemberHandler(track_groups, ChatMemberHandler.MY_CHAT_MEMBER)
  )
  app.add_handler(CommandHandler("help", help_command))
  app.add_handler(CommandHandler(["test", "bday"], test_trigger))

  # Moderation
  app.add_handler(CommandHandler("ban", ban_user))
  app.add_handler(CommandHandler("kick", kick_user))
  app.add_handler(CommandHandler("mute", mute_user))
  app.add_handler(CommandHandler("unmute", unmute_user))
  app.add_handler(CommandHandler("pin", pin_message))

  # Music & Chat
  app.add_handler(CommandHandler("play", play_music))
  app.add_handler(
      MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler)
  )

  # Error handling
  app.add_error_handler(error_handler)

  # Birthday broadcast schedule (Sept 17, 2026 Midnight IST)
  tz = pytz.timezone(TIMEZONE)
  target_time = tz.localize(datetime.datetime(2026, 9, 17, 0, 0, 0))
  app.job_queue.run_once(scheduled_birthday_broadcast, when=target_time)

  print(">>> Snoffy Bot is live! Single tap direct GitHub link ready! <<<")
  app.run_polling()


if __name__ == "__main__":
  main()
