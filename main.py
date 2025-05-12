# main.py
import logging
import os
from typing import Dict, List, Optional
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Chat,
    User,
    PhotoSize,
    Document,
    Video,
    Voice
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    CallbackContext,
    ContextTypes
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
MessageID = int

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
        self.allowed_group_ids: List[ChatID] = []  # 空列表表示允许所有群组
        self.blocked_group_ids: List[ChatID] = []

# 初始化机器人数据
bot_data = BotData()

async def init_bot_data(context: ContextTypes.DEFAULT_TYPE):
    """初始化机器人数据"""
    # 可以从环境变量加载管理员ID
    admin_ids = os.getenv('ADMIN_IDS', '').split(',')
    if admin_ids:
        bot_data.admin_ids = [int(uid.strip()) for uid in admin_ids if uid.strip()]
    
    # 可以从环境变量加载允许/禁止的群组
    allowed_groups = os.getenv('ALLOWED_GROUP_IDS', '').split(',')
    if allowed_groups:
        bot_data.allowed_group_ids = [int(gid.strip()) for gid in allowed_groups if gid.strip()]
    
    blocked_groups = os.getenv('BLOCKED_GROUP_IDS', '').split(',')
    if blocked_groups:
        bot_data.blocked_group_ids = [int(gid.strip()) for gid in blocked_groups if gid.strip()]

async def start(update: Update, context: CallbackContext):
    """处理/start命令"""
    user = update.effective_user
    if user.id in bot_data.admin_ids:
        await update.message.reply_text(
            "👋 管理员你好！我是高级群聊转发机器人。\n\n"
            "可用命令:\n"
            "/groups - 查看管理的群组\n"
            "/allowgroup [ID] - 允许特定群组\n"
            "/blockgroup [ID] - 禁止特定群组\n"
            "/addadmin [ID] - 添加管理员\n"
            "/toggle [群组ID] - 启用/禁用群组转发\n"
            "/help - 查看帮助"
        )
    else:
        await update.message.reply_text("你没有权限使用此机器人。")

async def help_command(update: Update, context: CallbackContext):
    """显示帮助信息"""
    await update.message.reply_text(
        "🤖 高级群聊转发机器人帮助:\n\n"
        "管理员命令:\n"
        "/groups - 查看所有群组状态\n"
        "/toggle [群组ID] - 切换群组转发状态\n"
        "/allowgroup [ID] - 允许特定群组\n"
        "/blockgroup [ID] - 禁止特定群组\n"
        "/addadmin [ID] - 添加管理员\n\n"
        "普通使用:\n"
        "1. 将机器人添加到群组\n"
        "2. 回复机器人转发的消息来回复群组\n"
        "3. 使用按钮回复特定用户"
    )

async def handle_new_chat_members(update: Update, context: CallbackContext):
    """处理新成员加入事件（主要是机器人自己被加入群组）"""
    chat = update.effective_chat
    for user in update.message.new_chat_members:
        if user.id == context.bot.id:  # 是机器人自己被加入
            await process_bot_added_to_group(chat, context)

async def process_bot_added_to_group(chat: Chat, context: CallbackContext):
    """处理机器人被添加到群组"""
    group_id = chat.id
    
    # 检查群组权限
    if (bot_data.allowed_group_ids and group_id not in bot_data.allowed_group_ids) or \
       (group_id in bot_data.blocked_group_ids):
        await context.bot.send_message(
            chat_id=group_id,
            text="⚠️ 此群组未被授权使用本机器人。机器人将退出。"
        )
        await context.bot.leave_chat(group_id)
        return
    
    # 添加群组到管理列表
    if group_id not in bot_data.groups:
        bot_data.groups[group_id] = GroupConfig(group_id, chat.title)
        
        # 通知所有管理员
        for admin_id in bot_data.admin_ids:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🤖 机器人已加入新群组: {chat.title} (ID: {group_id})"
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
    
    # 转发消息给所有管理员
    await forward_group_message_to_admins(message, group_config, context)

async def forward_group_message_to_admins(message: Message, group_config: GroupConfig, context: CallbackContext):
    """将群组消息转发给所有管理员"""
    try:
        # 创建回复按钮
        keyboard = [
            [
                InlineKeyboardButton("📨 回复群组", callback_data=f"reply_{group_config.chat_id}"),
                InlineKeyboardButton("🔄 切换状态", callback_data=f"toggle_{group_config.chat_id}")
            ]
        ]
        
        # 添加回复用户按钮（如果有发送者）
        if message.from_user:
            user_btn_text = f"👤 回复@{message.from_user.username or message.from_user.first_name}"
            keyboard.append([
                InlineKeyboardButton(
                    user_btn_text,
                    callback_data=f"reply_user_{group_config.chat_id}_{message.message_id}"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 转发不同类型的媒体消息
        caption = f"来自群组: {group_config.title}\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        if message.photo:
            # 照片消息
            photo = message.photo[-1]  # 获取最高质量的图片
            for admin_id in bot_data.admin_ids:
                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=photo.file_id,
                    caption=caption,
                    reply_markup=reply_markup
                )
        
        elif message.document:
            # 文件消息
            doc = message.document
            for admin_id in bot_data.admin_ids:
                await context.bot.send_document(
                    chat_id=admin_id,
                    document=doc.file_id,
                    caption=caption,
                    reply_markup=reply_markup
                )
        
        elif message.video:
            # 视频消息
            video = message.video
            for admin_id in bot_data.admin_ids:
                await context.bot.send_video(
                    chat_id=admin_id,
                    video=video.file_id,
                    caption=caption,
                    reply_markup=reply_markup
                )
        
        elif message.voice:
            # 语音消息
            voice = message.voice
            for admin_id in bot_data.admin_ids:
                await context.bot.send_voice(
                    chat_id=admin_id,
                    voice=voice.file_id,
                    caption=caption,
                    reply_markup=reply_markup
                )
        
        else:
            # 文本消息
            text = f"{caption}\n\n{message.text}" if message.text else caption
            for admin_id in bot_data.admin_ids:
                if message.text:
                    forwarded = await message.forward(admin_id)
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=f"来自群组: {group_config.title}",
                        reply_to_message_id=forwarded.message_id,
                        reply_markup=reply_markup
                    )
                else:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=text,
                        reply_markup=reply_markup
                    )
    
    except Exception as e:
        logger.error(f"转发群组消息失败: {e}")

async def handle_private_message(update: Update, context: CallbackContext):
    """处理私聊消息"""
    message = update.message
    user = update.effective_user
    
    # 检查是否是管理员
    if user.id not in bot_data.admin_ids:
        await message.reply_text("你没有权限使用此机器人。")
        return
    
    # 检查是否是回复消息
    if message.reply_to_message:
        await handle_admin_reply(message, context)
        return
    
    # 处理命令
    if message.text and message.text.startswith('/'):
        return  # 由其他处理器处理
    
    await message.reply_text("请回复你要回复的群组消息，或使用命令管理机器人。")

async def handle_admin_reply(message: Message, context: CallbackContext):
    """处理管理员的回复"""
    user_id = message.from_user.id
    
    if user_id not in bot_data.user_context:
        await message.reply_text("无法确定你要回复的群组。请使用按钮回复。")
        return
    
    context_data = bot_data.user_context[user_id]
    group_id = context_data.get('group_id')
    reply_to_id = context_data.get('replying_to')
    
    if group_id not in bot_data.groups:
        await message.reply_text("目标群组不再有效。")
        del bot_data.user_context[user_id]
        return
    
    # 发送消息到群组
    try:
        if message.photo:
            photo = message.photo[-1]
            sent_msg = await context.bot.send_photo(
                chat_id=group_id,
                photo=photo.file_id,
                caption=message.caption,
                reply_to_message_id=reply_to_id
            )
        elif message.document:
            doc = message.document
            sent_msg = await context.bot.send_document(
                chat_id=group_id,
                document=doc.file_id,
                caption=message.caption,
                reply_to_message_id=reply_to_id
            )
        elif message.video:
            video = message.video
            sent_msg = await context.bot.send_video(
                chat_id=group_id,
                video=video.file_id,
                caption=message.caption,
                reply_to_message_id=reply_to_id
            )
        elif message.voice:
            voice = message.voice
            sent_msg = await context.bot.send_voice(
                chat_id=group_id,
                voice=voice.file_id,
                caption=message.caption,
                reply_to_message_id=reply_to_id
            )
        else:
            sent_msg = await context.bot.send_message(
                chat_id=group_id,
                text=message.text,
                reply_to_message_id=reply_to_id
            )
        
        await message.reply_text(f"✅ 消息已发送到群组: {bot_data.groups[group_id].title}")
        del bot_data.user_context[user_id]
    
    except Exception as e:
        logger.error(f"发送消息到群组失败: {e}")
        await message.reply_text(f"发送失败: {str(e)}")

async def list_groups(update: Update, context: CallbackContext):
    """列出所有群组"""
    if update.effective_user.id not in bot_data.admin_ids:
        await update.message.reply_text("你没有权限执行此操作。")
        return
    
    if not bot_data.groups:
        await update.message.reply_text("机器人尚未加入任何群组。")
        return
    
    text = "📋 管理的群组列表:\n\n"
    for group_id, group_config in bot_data.groups.items():
        status = "✅ 活跃" if group_config.is_active else "❌ 禁用"
        last_active = group_config.last_activity.strftime('%Y-%m-%d %H:%M') if group_config.last_activity else "从未"
        text += (
            f"🏷️ 名称: {group_config.title}\n"
            f"🆔 ID: {group_id}\n"
            f"📊 状态: {status}\n"
            f"⏱️ 最后活动: {last_active}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
        )
    
    await update.message.reply_text(text)

async def toggle_group(update: Update, context: CallbackContext):
    """切换群组状态"""
    user = update.effective_user
    if user.id not in bot_data.admin_ids:
        await update.message.reply_text("你没有权限执行此操作。")
        return
    
    if not context.args:
        await update.message.reply_text("请提供群组ID，例如: /toggle 123456789")
        return
    
    try:
        group_id = int(context.args[0])
        if group_id not in bot_data.groups:
            await update.message.reply_text("找不到指定的群组。")
            return
        
        group_config = bot_data.groups[group_id]
        group_config.is_active = not group_config.is_active
        status = "已激活" if group_config.is_active else "已禁用"
        
        await update.message.reply_text(
            f"已{status}群组: {group_config.title} (ID: {group_id})"
        )
    except ValueError:
        await update.message.reply_text("无效的群组ID。")

async def allow_group(update: Update, context: CallbackContext):
    """允许特定群组使用机器人"""
    user = update.effective_user
    if user.id not in bot_data.admin_ids:
        await update.message.reply_text("你没有权限执行此操作。")
        return
    
    if not context.args:
        await update.message.reply_text("请提供群组ID，例如: /allowgroup 123456789")
        return
    
    try:
        group_id = int(context.args[0])
        if group_id in bot_data.blocked_group_ids:
            bot_data.blocked_group_ids.remove(group_id)
        if group_id not in bot_data.allowed_group_ids:
            bot_data.allowed_group_ids.append(group_id)
        
        await update.message.reply_text(f"已允许群组ID: {group_id} 使用机器人。")
    except ValueError:
        await update.message.reply_text("无效的群组ID。")

async def block_group(update: Update, context: CallbackContext):
    """禁止特定群组使用机器人"""
    user = update.effective_user
    if user.id not in bot_data.admin_ids:
        await update.message.reply_text("你没有权限执行此操作。")
        return
    
    if not context.args:
        await update.message.reply_text("请提供群组ID，例如: /blockgroup 123456789")
        return
    
    try:
        group_id = int(context.args[0])
        if group_id in bot_data.allowed_group_ids:
            bot_data.allowed_group_ids.remove(group_id)
        if group_id not in bot_data.blocked_group_ids:
            bot_data.blocked_group_ids.append(group_id)
        
        # 如果机器人正在该群组中，则退出
        if group_id in bot_data.groups:
            try:
                await context.bot.send_message(
                    chat_id=group_id,
                    text="⚠️ 此群组已被管理员禁止使用本机器人。机器人将退出。"
                )
                await context.bot.leave_chat(group_id)
                del bot_data.groups[group_id]
            except Exception as e:
                logger.error(f"退出群组失败: {e}")
        
        await update.message.reply_text(f"已禁止群组ID: {group_id} 使用机器人。")
    except ValueError:
        await update.message.reply_text("无效的群组ID。")

async def add_admin(update: Update, context: CallbackContext):
    """添加管理员"""
    user = update.effective_user
    if user.id not in bot_data.admin_ids:
        await update.message.reply_text("你没有权限执行此操作。")
        return
    
    if not context.args:
        await update.message.reply_text("请提供用户ID，例如: /addadmin 987654321")
        return
    
    try:
        new_admin_id = int(context.args[0])
        if new_admin_id not in bot_data.admin_ids:
            bot_data.admin_ids.append(new_admin_id)
            await update.message.reply_text(f"已添加用户ID {new_admin_id} 为管理员。")
        else:
            await update.message.reply_text("该用户已经是管理员。")
    except ValueError:
        await update.message.reply_text("无效的用户ID。")

async def button_callback(update: Update, context: CallbackContext):
    """处理按钮回调"""
    query = update.callback_query
    user = query.from_user
    data = query.data
    
    if user.id not in bot_data.admin_ids:
        await query.answer("你没有权限执行此操作。")
        return
    
    try:
        if data.startswith('reply_'):
            # 回复群组
            group_id = int(data.split('_')[1])
            if group_id in bot_data.groups:
                bot_data.user_context[user.id] = {'group_id': group_id}
                await query.answer("现在发送你的消息，它将发送到群组。")
            else:
                await query.answer("群组不再有效。")
        
        elif data.startswith('reply_user_'):
            # 回复群组中的特定用户
            _, _, group_id, message_id = data.split('_')
            group_id = int(group_id)
            message_id = int(message_id)
            if group_id in bot_data.groups:
                bot_data.user_context[user.id] = {
                    'group_id': group_id,
                    'replying_to': message_id
                }
                await query.answer("现在发送你的消息，它将作为回复发送到群组。")
            else:
                await query.answer("群组不再有效。")
        
        elif data.startswith('toggle_'):
            # 切换群组状态
            group_id = int(data.split('_')[1])
            if group_id in bot_data.groups:
                group_config = bot_data.groups[group_id]
                group_config.is_active = not group_config.is_active
                status = "已激活" if group_config.is_active else "已禁用"
                await query.answer(f"{status}群组: {group_config.title}")
            else:
                await query.answer("群组不再有效。")
        
        await query.delete_message()
    
    except Exception as e:
        logger.error(f"处理按钮回调失败: {e}")
        await query.answer("操作失败，请重试。")

def main():
    """启动机器人"""
    # 从环境变量获取Telegram token
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        raise ValueError("未设置TELEGRAM_TOKEN环境变量")
    
    # 创建应用
    application = Application.builder().token(token).build()
    
    # 初始化数据
    application.post_init = init_bot_data
    
    # 添加处理器
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('groups', list_groups))
    application.add_handler(CommandHandler('toggle', toggle_group))
    application.add_handler(CommandHandler('allowgroup', allow_group))
    application.add_handler(CommandHandler('blockgroup', block_group))
    application.add_handler(CommandHandler('addadmin', add_admin))
    
    application.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS,
        handle_new_chat_members
    ))
    application.add_handler(MessageHandler(
        filters.ChatType.GROUPS,
        handle_group_message
    ))
    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE,
        handle_private_message
    ))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # 启动机器人
    application.run_polling()

if __name__ == '__main__':
    main()
