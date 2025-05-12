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

# === 全局数据 ===
bot_data = BotData()

# === 核心函数 ===
async def init_bot_data(context: CallbackContext):
    """初始化机器人数据"""
    try:
        admin_ids = os.getenv('ADMIN_IDS', '').split(',')
        bot_data.admin_ids = [int(uid.strip()) for uid in admin_ids if uid.strip()]
        logger.info(f"初始化完成 - 管理员: {bot_data.admin_ids}")
    except Exception as e:
        logger.error(f"初始化失败: {str(e)}")
        raise

async def verify_bot_permissions(chat: Chat, context: CallbackContext) -> bool:
    """检查机器人权限"""
    try:
        bot_member = await chat.get_member(context.bot.id)
        logger.info(f"权限检查结果 - 状态: {bot_member.status} 权限: {bot_member.to_dict()}")
        return bot_member.status == "administrator"
    except Exception as e:
        logger.error(f"权限检查异常: {str(e)}")
        return False

async def handle_new_chat_members(update: Update, context: CallbackContext):
    """处理新成员加入事件"""
    try:
        chat = update.effective_chat
        for user in update.message.new_chat_members:
            if user.id == context.bot.id:
                logger.info(f"机器人被添加到群组: {chat.title}({chat.id})")
                
                if not await verify_bot_permissions(chat, context):
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text="⚠️ 需要管理员权限才能工作！\n"
                             "请授予我：\n"
                             "• 发送消息\n"
                             "• 读取消息历史\n"
                             "• 管理消息权限"
                    )
                    await context.bot.leave_chat(chat.id)
                    return

                # 注册群组
                bot_data.groups[chat.id] = GroupConfig(chat.id, chat.title)
                logger.info(f"群组注册成功: {chat.title}({chat.id})")

                # 通知管理员
                for admin_id in bot_data.admin_ids:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"📌 新群组加入:\n"
                                 f"名称: {chat.title}\n"
                                 f"ID: {chat.id}"
                        )
                    except Exception as e:
                        logger.error(f"通知管理员失败 {admin_id}: {str(e)}")

                # 发送欢迎消息
                await context.bot.send_message(
                    chat_id=chat.id,
                    text="✅ 消息转发已激活\n"
                         "• 群聊消息将转发给管理员\n"
                         "• 回复转发的消息即可互动"
                )
    except Exception as e:
        logger.error(f"处理新成员事件异常: {str(e)}")

async def handle_group_message(update: Update, context: CallbackContext):
    """处理群组消息转发"""
    try:
        message = update.message
        group_id = message.chat.id
        
        if group_id not in bot_data.groups:
            logger.warning(f"未注册的群组消息: {group_id}")
            return
            
        bot_data.groups[group_id].last_activity = datetime.now()
        
        msg_type = next(
            (t for t in ['text', 'photo', 'document', 'video'] 
             if getattr(message, t, None)),
            'unknown'
        )
        logger.info(f"收到群组消息 | 群组: {message.chat.title} | 类型: {msg_type}")

        buttons = [[
            InlineKeyboardButton(
                f"👤 回复@{message.from_user.username or message.from_user.first_name}",
                callback_data=f"reply_{group_id}_{message.message_id}"
            )
        ]]

        for admin_id in bot_data.admin_ids:
            try:
                if msg_type == 'text':
                    forwarded = await message.forward(admin_id)
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=f"来自: {bot_data.groups[group_id].title}",
                        reply_to_message_id=forwarded.message_id,
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                elif msg_type in ['photo', 'document', 'video']:
                    media = getattr(message, msg_type)
                    await getattr(context.bot, f"send_{msg_type}")(
                        chat_id=admin_id,
                        ​**​{msg_type: media[-1].file_id},
                        caption=f"来自: {bot_data.groups[group_id].title}",
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
            except Exception as e:
                logger.error(f"转发消息失败 {admin_id}: {str(e)}")
    except Exception as e:
        logger.error(f"处理群消息异常: {str(e)}")

async def handle_private_message(update: Update, context: CallbackContext):
    """处理管理员私聊消息"""
    try:
        message = update.message
        user = update.effective_user
        
        # 权限检查
        if user.id not in bot_data.admin_ids:
            await message.reply_text("❌ 需要管理员权限")
            return
            
        # 处理回复消息
        if message.reply_to_message and user.id in bot_data.user_context:
            await process_admin_reply(message, context)
            return
            
        await message.reply_text("ℹ️ 请回复转发的消息进行互动")
    except Exception as e:
        logger.error(f"处理私聊消息异常: {str(e)}")

async def process_admin_reply(message: Message, context: CallbackContext):
    """处理管理员回复"""
    try:
        user_id = message.from_user.id
        context_data = bot_data.user_context[user_id]
        group_id = context_data['group_id']
        reply_to_id = context_data.get('message_id')
        
        # 验证群组有效性
        if group_id not in bot_data.groups:
            await message.reply_text("⚠️ 目标群组已失效")
            return
            
        # 发送消息到群组
        try:
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
            elif message.document:
                await context.bot.send_document(
                    chat_id=group_id,
                    document=message.document.file_id,
                    reply_to_message_id=reply_to_id
                )
                
            await message.reply_text(f"✅ 已发送到群组: {bot_data.groups[group_id].title}")
        except Exception as e:
            await message.reply_text(f"❌ 发送失败: {str(e)}")
        finally:
            bot_data.user_context.pop(user_id, None)
    except Exception as e:
        logger.error(f"处理管理员回复异常: {str(e)}")

# === 管理命令 ===
async def list_groups(update: Update, context: CallbackContext):
    """查看群组列表"""
    try:
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
    except Exception as e:
        logger.error(f"执行/groups命令异常: {str(e)}")

async def add_admin(update: Update, context: CallbackContext):
    """添加管理员"""
    try:
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
    except Exception as e:
        logger.error(f"执行/addadmin命令异常: {str(e)}")

# === 按钮处理 ===
async def handle_button_click(update: Update, context: CallbackContext):
    """处理按钮回调"""
    try:
        query = update.callback_query
        user = query.from_user
        
        # 权限检查
        if user.id not in bot_data.admin_ids:
            await query.answer("❌ 需要管理员权限")
            return
            
        # 处理回复按钮
        if query.data.startswith('reply_'):
            _, group_id, message_id = query.data.split('_')
            bot_data.user_context[user.id] = {
                'group_id': int(group_id),
                'message_id': int(message_id)
            }
            await query.answer("请输入回复内容...")
        
        await query.delete_message()
    except Exception as e:
        logger.error(f"处理按钮回调异常: {str(e)}")
        await query.answer("⚠️ 操作失败")

# === 主程序 ===
def main():
    """启动机器人"""
    try:
        # 配置
        token = os.getenv('TELEGRAM_TOKEN')
        if not token:
            raise ValueError("未设置TELEGRAM_TOKEN环境变量")
            
        # 创建应用
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
            
        # 启动
        logger.info("机器人启动中...")
        application.run_polling()
    except Exception as e:
        logger.critical(f"启动失败: {str(e)}")
        raise

if __name__ == '__main__':
    main()
