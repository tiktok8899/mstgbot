import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_USER_ID"))
GROUP_ID = int(os.getenv("GROUP_ID"))

# 群 -> 管理员
async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id == GROUP_ID:
        if update.message:
            if update.message.text:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"[群消息] {update.message.from_user.full_name}：\n{update.message.text}"
                )
            else:
                await update.message.forward(chat_id=ADMIN_ID)

# 管理员 -> 群
async def admin_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        if update.message:
            if update.message.text:
                await context.bot.send_message(
                    chat_id=GROUP_ID,
                    text=update.message.text
                )
            else:
                await update.message.forward(chat_id=GROUP_ID)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, forward_to_admin))
    app.add_handler(MessageHandler(filters.ALL, admin_to_group))
    app.run_polling()
