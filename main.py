import logging
import os
from datetime import datetime
from typing import Dict, List
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Chat,
    User
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    CallbackContext
)

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 类型定义
ChatID = int
UserID = int

class GroupConfig:
    def __init__(self, chat_id: ChatID, title: str):
        self.chat_id = chat_id
        self.title = title
        self.last_activity = datetime.now()

class BotData:
    def __init__(self):
        self.admin_ids: List[UserID] = []
        self.groups: Dict[ChatID, GroupConfig] = {}
        self.user_context: Dict[UserID, Dict] = {}

# 全局数据
bot_data = BotData()

async def init_bot_data(context: CallbackContext):
    """初始化机器人数据"""
    admin_ids = os.getenv('ADMIN_IDS', '').split(',')
    if admin_ids:
        bot_data.admin_ids = [int(uid.strip()) for uid in admin_ids if uid.strip()]
    logger.info(f"机器人初始化完成，管理员数量: {len(bot_data.admin_ids)}")

async def start(update: Update, context: CallbackContext):
    """处理/start命令"""
    user = update.effective_user
    if user.id in bot_data.admin_ids:
        await update.message.reply_text(
            "🤖 群聊转发机器人已就绪\n\n"
            "使用说明:\n"
            "1. 将机器人以管理员身份添加到群组\n"
            "2. 群组消息会自动转发到此聊天\n"
            "3. 回复消息即可与群组互动\n\n"
            "管理命令:\n"
            "/groups - 查看所有群组\n"
            "/addadmin [用户ID] - 添加管理员"
        )
    else:
        await update.message.reply_text("❌ 需要管理员权限")

async def handle_new_chat_members(update: Update, context: CallbackContext):
    """处理机器人被加入群组"""
    chat = update.effective_chat
    for user in update.message.new_chat_members:
        if user.id == context.bot.id:
            logger.info(f"机器人被添加到群组: {chat.title}({chat.id})")
            await verify_and_add_group(chat, context)

async def verify_and_add_group(chat: Chat, context: CallbackContext):
    """验证权限并添加群组"""
    try:
        # 检查管理员权限
        bot_member = await chat.get_member(context.bot.id)
        if bot_member.status != "administrator":
            await context.bot.send_message(
                chat_id=chat.id,
                text="⚠️ 需要管理员权限才能工作！"
            )
            return

        # 添加到群组列表
        if chat.id not in bot_data.groups:
            bot_data.groups[chat.id] = GroupConfig(chat.id, chat.title)
            logger.info(f"新群组注册成功: {chat.title}")

            # 通知管理员
            for admin_id in bot_data.admin_ids:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"📌 新群组加入:\n名称: {chat.title}\nID: {chat.id}"
                )

        # 发送欢迎消息
        await context.bot.send_message(
            chat_id=chat.id,
            text="✅ 消息转发功能已激活\n"
                 "群组消息将自动转发给管理员"
        )
    except Exception as e:
        logger.error(f"添加群组出错: {str(e)}")

async def handle_group_message(update: Update, context: CallbackContext):
    """处理群组消息转发"""
    message = update.message
    group_id = message.chat.id
    
    # 检查是否已注册群组
    if group_id not in bot_data.groups:
        return
    
    group = bot_data.groups[group_id]
    group.last_activity = datetime.now()
    
    # 创建回复按钮
    buttons = [[
        InlineKeyboardButton(
            f"👤 回复@{message.from_user.username or message.from_user.first_name}",
            callback_data=f"reply_{group_id}_{message.message_id}"
        )
    ]]
    
    # 转发消息给所有管理员
    for admin_id in bot_data.admin_ids:
        try:
            if message.text:
                forwarded = await message.forward(admin_id)
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"来自: {group.title}",
                    reply_to_message_id=forwarded.message_id,
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            elif message.photo:
                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=message.photo[-1].file_id,
                    caption=f"来自: {group.title}",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
        except Exception as e:
            logger.error(f"转发消息失败: {str(e)}")

async def handle_private_message(update: Update, context: CallbackContext):
    """处理管理员私聊消息"""
    message = update.message
    user = update.effective_user
    
    if user.id not in bot_data.admin_ids:
        await message.reply_text("❌ 需要管理员权限")
        return
    
    # 处理回复消息
    if message.reply_to_message and user.id in bot_data.user_context:
        await process_admin_reply(message, context)
        return
    
    await message.reply_text("ℹ️ 请回复转发的消息进行互动")

async def process_admin_reply(message: Message, context: CallbackContext):
    """处理管理员回复"""
    user_id = message.from_user.id
    context_data = bot_data.user_context[user_id]
    group_id = context_data['group_id']
    reply_to_id = context_data.get('message_id')
    
    try:
        # 发送消息到群组
        if message.text:
            await context.bot.send_message(
                chat_id=group_id,
                text=message.text,
                reply_to_message_id=reply_to_id
            )
        elif message.photo:
            await context.bot.send_photo(
                chat_id=group_id,
                photo=message.photo[-1].file_id,
                caption=message.caption,
                reply_to_message_id=reply_to_id
            )
            
        await message.reply_text(f"✅ 已发送到群组: {bot_data.groups[group_id].title}")
    except Exception as e:
        await message.reply_text(f"❌ 发送失败: {str(e)}")
    finally:
        bot_data.user_context.pop(user_id, None)

async def list_groups(update: Update, context: CallbackContext):
    """查看群组列表"""
    if update.effective_user.id not in bot_data.admin_ids:
        await update.message.reply_text("❌ 需要管理员权限")
        return
    
    if not bot_data.groups:
        await update.message.reply_text("尚未加入任何群组")
        return
    
    text = "📋 当前管理的群组:\n\n"
    for group in bot_data.groups.values():
        text += (
            f"🏷️ {group.title}\n"
            f"ID: <code>{group.chat_id}</code>\n"
            f"最后活动: {group.last_activity.strftime('%m-%d %H:%M')}\n"
            "━━━━━━━━━━━━━━\n"
        )
    
    await update.message.reply_text(text, parse_mode="HTML")

async def add_admin(update: Update, context: CallbackContext):
    """添加管理员"""
    if update.effective_user.id not in bot_data.admin_ids:
        await update.message.reply_text("❌ 需要管理员权限")
        return
    
    if not context.args:
        await update.message.reply_text("用法: /addadmin <用户ID>")
        return
    
    try:
        new_admin_id = int(context.args[0])
        if new_admin_id not in bot_data.admin_ids:
            bot_data.admin_ids.append(new_admin_id)
            await update.message.reply_text(f"✅ 已添加用户 {new_admin_id} 为管理员")
        else:
            await update.message.reply_text("ℹ️ 该用户已是管理员")
    except ValueError:
        await update.message.reply_text("❌ 无效的用户ID")

async def handle_button_click(update: Update, context: CallbackContext):
    """处理回复按钮点击"""
    query = update.callback_query
    user = query.from_user
    
    if user.id not in bot_data.admin_ids:
        await query.answer("❌ 需要管理员权限")
        return
    
    try:
        if query.data.startswith('reply_'):
            _, group_id, message_id = query.data.split('_')
            bot_data.user_context[user.id] = {
                'group_id': int(group_id),
                'message_id': int(message_id)
            }
            await query.answer("请输入回复内容...")
        
        await query.delete_message()
    except Exception as e:
        logger.error(f"按钮处理出错: {str(e)}")
        await query.answer("⚠️ 操作失败")

def main():
    """启动机器人"""
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        raise ValueError("未设置TELEGRAM_TOKEN环境变量")
    
    application = Application.builder().token(token).build()
    application.post_init = init_bot_data
    
    # 添加处理器
    handlers = [
        CommandHandler('start', start),
        CommandHandler('groups', list_groups),
        CommandHandler('addadmin', add_admin),
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_chat_members),
        MessageHandler(filters.ChatType.GROUPS, handle_group_message),
        MessageHandler(filters.ChatType.PRIVATE, handle_private_message),
        CallbackQueryHandler(handle_button_click)
    ]
    
    for handler in handlers:
        application.add_handler(handler)
    
    logger.info("机器人启动中...")
    application.run_polling()

if __name__ == '__main__':
    main()
