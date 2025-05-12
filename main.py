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
    def __init__(self, chat_id: ChatID, title: str, is_active: bool = True):
        self.chat_id = chat_id
        self.title = title
        self.is_active = is_active
        self.last_activity = datetime.now()

class BotData:
    def __init__(self):
        self.admin_ids: List[UserID] = []
        self.groups: Dict[ChatID, GroupConfig] = {}
        self.user_context: Dict[UserID, Dict] = {}

# 初始化机器人数据
bot_data = BotData()

async def init_bot_data(context: CallbackContext):
    """初始化机器人数据"""
    admin_ids = os.getenv('ADMIN_IDS', '').split(',')
    if admin_ids:
        bot_data.admin_ids = [int(uid.strip()) for uid in admin_ids if uid.strip()]

async def start(update: Update, context: CallbackContext):
    """处理/start命令"""
    user = update.effective_user
    if user.id in bot_data.admin_ids:
        await update.message.reply_text(
            "👋 管理员你好！我是群聊转发机器人\n\n"
            "只需将我以管理员身份添加到群组，我就能自动转发消息\n\n"
            "可用命令:\n"
            "/groups - 查看所有群组\n"
            "/toggle [群组ID] - 启用/禁用群组\n"
            "/addadmin [用户ID] - 添加管理员\n"
            "/help - 查看帮助"
        )
    else:
        await update.message.reply_text("❌ 你没有权限使用此机器人")

async def handle_new_chat_members(update: Update, context: CallbackContext):
    """处理机器人被加入群组"""
    chat = update.effective_chat
    for user in update.message.new_chat_members:
        if user.id == context.bot.id:
            await process_bot_added_to_group(chat, context)

async def process_bot_added_to_group(chat: Chat, context: CallbackContext):
    """处理机器人被添加到群组"""
    group_id = chat.id
    
    # 检查机器人是否群组管理员
    try:
        bot_member = await chat.get_member(context.bot.id)
        if not bot_member.status == "administrator":
            await context.bot.send_message(
                chat_id=group_id,
                text="⚠️ 我需要管理员权限才能工作，请将我设为管理员！"
            )
            return
    except Exception as e:
        logger.error(f"检查管理员权限失败: {e}")
        return

    # 添加群组到管理列表
    if group_id not in bot_data.groups:
        bot_data.groups[group_id] = GroupConfig(group_id, chat.title)
        logger.info(f"新群组添加: {chat.title} (ID: {group_id})")
        
        # 通知所有管理员
        for admin_id in bot_data.admin_ids:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🤖 已加入新群组: {chat.title} (ID: {group_id})"
                )
            except Exception as e:
                logger.error(f"通知管理员失败: {e}")

async def handle_group_message(update: Update, context: CallbackContext):
    """处理群组消息"""
    message = update.message
    group_id = message.chat.id
    
    # 检查群组是否被管理
    if group_id not in bot_data.groups:
        return
    
    group_config = bot_data.groups[group_id]
    
    # 检查群组是否活跃
    if not group_config.is_active:
        return
    
    # 更新最后活动时间
    group_config.last_activity = datetime.now()
    
    # 创建回复按钮
    keyboard = [
        [
            InlineKeyboardButton("📨 回复群组", callback_data=f"reply_{group_id}"),
            InlineKeyboardButton("🔄 切换状态", callback_data=f"toggle_{group_id}")
        ]
    ]
    
    if message.from_user:
        keyboard.append([
            InlineKeyboardButton(
                f"👤 回复@{message.from_user.username or message.from_user.first_name}",
                callback_data=f"reply_user_{group_id}_{message.message_id}"
            )
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 转发消息给管理员
    try:
        forwarded = await message.forward(bot_data.admin_ids[0])
        await context.bot.send_message(
            chat_id=bot_data.admin_ids[0],
            text=f"来自群组: {group_config.title}",
            reply_to_message_id=forwarded.message_id,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"转发消息失败: {e}")

async def handle_private_message(update: Update, context: CallbackContext):
    """处理私聊消息"""
    message = update.message
    user = update.effective_user
    
    if user.id not in bot_data.admin_ids:
        await message.reply_text("❌ 你没有权限使用此机器人")
        return
    
    # 处理回复消息
    if message.reply_to_message and user.id in bot_data.user_context:
        await handle_admin_reply(message, context)
        return
    
    await message.reply_text("请回复你要回复的群组消息")

async def handle_admin_reply(message: Message, context: CallbackContext):
    """处理管理员回复"""
    user_id = message.from_user.id
    context_data = bot_data.user_context[user_id]
    group_id = context_data['group_id']
    reply_to_id = context_data.get('replying_to')
    
    try:
        await context.bot.send_message(
            chat_id=group_id,
            text=message.text,
            reply_to_message_id=reply_to_id
        )
        await message.reply_text("✅ 消息已发送到群组")
        del bot_data.user_context[user_id]
    except Exception as e:
        await message.reply_text(f"❌ 发送失败: {str(e)}")

async def list_groups(update: Update, context: CallbackContext):
    """列出所有群组"""
    if update.effective_user.id not in bot_data.admin_ids:
        await update.message.reply_text("❌ 你没有权限执行此操作")
        return
    
    if not bot_data.groups:
        await update.message.reply_text("机器人尚未加入任何群组")
        return
    
    text = "📋 管理的群组列表:\n\n"
    for group_id, group in bot_data.groups.items():
        status = "✅ 活跃" if group.is_active else "❌ 禁用"
        text += f"🏷️ {group.title}\n🆔 {group_id}\n📊 {status}\n━━━━━━━━━━━━━━\n"
    
    await update.message.reply_text(text)

async def toggle_group(update: Update, context: CallbackContext):
    """切换群组状态"""
    if update.effective_user.id not in bot_data.admin_ids:
        await update.message.reply_text("❌ 你没有权限执行此操作")
        return
    
    if not context.args:
        await update.message.reply_text("请提供群组ID，例如: /toggle 123456789")
        return
    
    try:
        group_id = int(context.args[0])
        if group_id in bot_data.groups:
            bot_data.groups[group_id].is_active = not bot_data.groups[group_id].is_active
            status = "已激活" if bot_data.groups[group_id].is_active else "已禁用"
            await update.message.reply_text(f"🔄 {status}群组: {bot_data.groups[group_id].title}")
        else:
            await update.message.reply_text("找不到指定的群组")
    except ValueError:
        await update.message.reply_text("无效的群组ID")

async def add_admin(update: Update, context: CallbackContext):
    """添加管理员"""
    if update.effective_user.id not in bot_data.admin_ids:
        await update.message.reply_text("❌ 你没有权限执行此操作")
        return
    
    if not context.args:
        await update.message.reply_text("请提供用户ID，例如: /addadmin 987654321")
        return
    
    try:
        new_admin_id = int(context.args[0])
        if new_admin_id not in bot_data.admin_ids:
            bot_data.admin_ids.append(new_admin_id)
            await update.message.reply_text(f"✅ 已添加用户 {new_admin_id} 为管理员")
        else:
            await update.message.reply_text("该用户已经是管理员")
    except ValueError:
        await update.message.reply_text("无效的用户ID")

async def button_callback(update: Update, context: CallbackContext):
    """处理按钮回调"""
    query = update.callback_query
    user = query.from_user
    
    if user.id not in bot_data.admin_ids:
        await query.answer("❌ 需要管理员权限")
        return
    
    data = query.data
    
    if data.startswith('reply_user_'):
        _, _, group_id, message_id = data.split('_')
        bot_data.user_context[user.id] = {
            'group_id': int(group_id),
            'replying_to': int(message_id)
        }
        await query.answer("请输入你的回复...")
    
    elif data.startswith('reply_'):
        group_id = int(data.split('_')[1])
        bot_data.user_context[user.id] = {'group_id': group_id}
        await query.answer("请输入要发送的消息...")
    
    elif data.startswith('toggle_'):
        group_id = int(data.split('_')[1])
        if group_id in bot_data.groups:
            bot_data.groups[group_id].is_active = not bot_data.groups[group_id].is_active
            status = "已激活" if bot_data.groups[group_id].is_active else "已禁用"
            await query.answer(f"{status}群组: {bot_data.groups[group_id].title}")
    
    await query.delete_message()

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
        CommandHandler('toggle', toggle_group),
        CommandHandler('addadmin', add_admin),
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_chat_members),
        MessageHandler(filters.ChatType.GROUPS, handle_group_message),
        MessageHandler(filters.ChatType.PRIVATE, handle_private_message),
        CallbackQueryHandler(button_callback)
    ]
    
    for handler in handlers:
        application.add_handler(handler)
    
    application.run_polling()

if __name__ == '__main__':
    main()
