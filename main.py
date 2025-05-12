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

# === 初始化设置 ===
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === 类型定义 ===
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
        self.user_messages: Dict[UserID, int] = {}  # 存储用户最后消息ID

# === 全局数据 ===
bot_data = BotData()

# === 核心功能 ===
async def init_bot_data(context: CallbackContext):
    """初始化机器人数据"""
    try:
        admin_ids = os.getenv('ADMIN_IDS', '').split(',')
        bot_data.admin_ids = [int(uid.strip()) for uid in admin_ids if uid.strip()]
        logger.info(f"初始化完成 - 管理员: {bot_data.admin_ids}")
    except Exception as e:
        logger.error(f"初始化失败: {str(e)}")
        raise

async def start(update: Update, context: CallbackContext):
    """处理/start命令"""
    try:
        user = update.effective_user
        if user.id in bot_data.admin_ids:
            await update.message.reply_text(
                "🤖 群聊转发机器人已就绪\n\n"
                "管理员功能:\n"
                "/send - 给群组发送消息\n"
                "/groups - 查看所有群组\n"
                "/addadmin - 添加管理员\n\n"
                "普通用户:\n"
                "直接发送消息将转发给管理员"
            )
        else:
            await update.message.reply_text(
                "您好！我是群组管理机器人\n"
                "任何消息将转发给我的管理员\n"
                "管理员可以直接回复我的消息与您交流"
            )
    except Exception as e:
        logger.error(f"处理/start命令出错: {str(e)}")

# ... [保持原有的 verify_bot_permissions 和 handle_new_chat_members 函数不变] ...

# === 增强的私聊消息处理 ===
async def forward_private_message(update: Update, context: CallbackContext):
    """转发普通用户消息给管理员并保存上下文"""
    try:
        user = update.effective_user
        message = update.message
        
        # 管理员消息不处理
        if user.id in bot_data.admin_ids:
            return

        # 保存用户最后消息ID
        bot_data.user_messages[user.id] = message.message_id

        # 转发给所有管理员（带回复按钮）
        buttons = [[
            InlineKeyboardButton(
                f"💬 回复用户 {user.first_name}",
                callback_data=f"reply_user_{user.id}"
            )
        ]]

        for admin_id in bot_data.admin_ids:
            try:
                if message.text:
                    forwarded = await message.forward(admin_id)
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=f"👤 来自用户 {user.full_name} (ID: {user.id})",
                        reply_to_message_id=forwarded.message_id,
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                elif message.photo:
                    forwarded = await message.forward(admin_id)
                    await context.bot.send_photo(
                        chat_id=admin_id,
                        photo=message.photo[-1].file_id,
                        caption=f"👤 来自用户 {user.full_name} (ID: {user.id})",
                        reply_to_message_id=forwarded.message_id,
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                elif message.document:
                    forwarded = await message.forward(admin_id)
                    await context.bot.send_document(
                        chat_id=admin_id,
                        document=message.document.file_id,
                        caption=f"👤 来自用户 {user.full_name} (ID: {user.id})",
                        reply_to_message_id=forwarded.message_id,
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
            except Exception as e:
                logger.error(f"转发给管理员 {admin_id} 失败: {str(e)}")

        await message.reply_text("✅ 您的消息已转发给管理员")

    except Exception as e:
        logger.error(f"处理私聊消息异常: {str(e)}")

# === 增强的按钮回调处理 ===
async def handle_button_click(update: Update, context: CallbackContext):
    """处理所有按钮回调"""
    try:
        query = update.callback_query
        user = query.from_user
        
        if user.id not in bot_data.admin_ids:
            await query.answer("❌ 需要管理员权限")
            return
            
        data = query.data
        logger.info(f"收到按钮回调: {data}")
        
        # 处理回复用户
        if data.startswith('reply_user_'):
            user_id = int(data.split('_')[2])
            bot_data.user_context[user.id] = {
                'action': 'reply_to_user',
                'target_user_id': user_id
            }
            await query.answer(f"请输入要回复用户的内容")
            await query.edit_message_reply_markup(reply_markup=None)
            return
            
        # ... [保持原有的其他按钮处理逻辑] ...
        
        await query.answer()
    except Exception as e:
        logger.error(f"按钮处理错误: {str(e)}")
        await query.answer("⚠️ 操作失败")

# === 增强的管理员消息处理 ===
async def handle_admin_private_message(update: Update, context: CallbackContext):
    """处理管理员私聊消息"""
    try:
        user = update.effective_user
        message = update.message
        
        # 检查是否在回复用户模式下
        context_data = bot_data.user_context.get(user.id, {})
        
        if context_data.get('action') == 'reply_to_user':
            target_user_id = context_data['target_user_id']
            try:
                # 发送回复给用户
                if message.text:
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text=f"📨 来自管理员的回复:\n{message.text}"
                    )
                elif message.photo:
                    await context.bot.send_photo(
                        chat_id=target_user_id,
                        photo=message.photo[-1].file_id,
                        caption=f"📨 来自管理员的回复:\n{message.caption or ''}"
                    )
                elif message.document:
                    await context.bot.send_document(
                        chat_id=target_user_id,
                        document=message.document.file_id,
                        caption=f"📨 来自管理员的回复:\n{message.caption or ''}"
                    )
                
                # 通知管理员发送成功
                await message.reply_text(f"✅ 回复已发送给用户")
                
                # 清除上下文
                bot_data.user_context.pop(user.id, None)
                return
            except Exception as e:
                await message.reply_text(f"❌ 回复用户失败: {str(e)}")
                return
        
        # ... [保持原有的其他处理逻辑] ...
        
    except Exception as e:
        logger.error(f"处理管理员消息异常: {str(e)}")

# === 主程序 ===
def main():
    """启动机器人"""
    try:
        token = os.getenv('TELEGRAM_TOKEN')
        if not token:
            raise ValueError("未设置TELEGRAM_TOKEN环境变量")
            
        application = Application.builder().token(token).build()
        application.post_init = init_bot_data
        
        handlers = [
            CommandHandler('start', start),
            CommandHandler('send', send_to_group),
            CommandHandler('groups', list_groups),
            CommandHandler('addadmin', add_admin),
            MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_chat_members),
            MessageHandler(filters.ChatType.GROUPS, handle_group_message),
            MessageHandler(
                filters.ChatType.PRIVATE & ~filters.COMMAND & filters.User(bot_data.admin_ids),
                handle_admin_private_message
            ),
            MessageHandler(
                filters.ChatType.PRIVATE & ~filters.COMMAND,
                forward_private_message
            ),
            CallbackQueryHandler(handle_button_click)
        ]
        
        for handler in handlers:
            application.add_handler(handler)
            
        logger.info("机器人启动中...")
        application.run_polling()
    except Exception as e:
        logger.critical(f"启动失败: {str(e)}")
        raise

if __name__ == '__main__':
    main()
