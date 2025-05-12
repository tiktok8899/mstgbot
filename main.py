import logging
import os
from datetime import datetime
from typing import Dict, List, Optional
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

# === 增强的日志配置 ===
logging.basicConfig(
    format='%(asctime)s,%(msecs)03d - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot_debug.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
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
        logger.info(f"新群组注册: {title} ({chat_id})")

class BotData:
    def __init__(self):
        self.admin_ids: List[UserID] = []
        self.groups: Dict[ChatID, GroupConfig] = {}
        self.user_context: Dict[UserID, Dict] = {}
        self.user_messages: Dict[UserID, Dict] = {}
        logger.info("机器人数据初始化完成")

# === 全局数据 ===
bot_data = BotData()

# === 核心功能 ===
async def init_bot_data(context: CallbackContext):
    """增强的初始化函数"""
    try:
        admin_ids = os.getenv('ADMIN_IDS', '').split(',')
        bot_data.admin_ids = [int(uid.strip()) for uid in admin_ids if uid.strip()]
        logger.info(f"管理员ID加载完成: {bot_data.admin_ids}")
    except Exception as e:
        logger.critical(f"初始化失败: {str(e)}")
        raise

async def start(update: Update, context: CallbackContext):
    """增强的start命令处理"""
    try:
        user = update.effective_user
        logger.info(f"收到/start命令 - 用户: {user.id}")
        
        if user.id in bot_data.admin_ids:
            await update.message.reply_text(
                "🤖 增强版群管机器人已就绪\n\n"
                "管理员命令:\n"
                "/send - 主动发送群组消息\n"
                "/groups - 查看管理群组\n"
                "/status - 查看系统状态\n"
                "/addadmin - 添加管理员\n\n"
                "普通用户可直接发送消息给管理员"
            )
        else:
            await update.message.reply_text(
                "👋 您好！消息已转发给管理员\n"
                "请等待管理员回复..."
            )
    except Exception as e:
        logger.error(f"/start处理失败: {str(e)}")

async def verify_bot_permissions(chat: Chat, context: CallbackContext) -> bool:
    """增强的权限检查"""
    try:
        bot_member = await chat.get_member(context.bot.id)
        has_permission = bot_member.status == "administrator"
        logger.info(f"权限检查 - 群组: {chat.title} 结果: {has_permission}")
        return has_permission
    except Exception as e:
        logger.error(f"权限检查异常: {str(e)}")
        return False

async def handle_new_chat_members(update: Update, context: CallbackContext):
    """增强的新成员处理"""
    try:
        chat = update.effective_chat
        for user in update.message.new_chat_members:
            if user.id == context.bot.id:
                logger.info(f"机器人加入新群组: {chat.title} ({chat.id})")
                
                if not await verify_bot_permissions(chat, context):
                    logger.warning(f"权限不足，即将离开群组: {chat.id}")
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text="⚠️ 需要管理员权限才能工作！"
                    )
                    await context.bot.leave_chat(chat.id)
                    return

                bot_data.groups[chat.id] = GroupConfig(chat.id, chat.title)
                
                # 异步通知所有管理员
                for admin_id in bot_data.admin_ids:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"📌 新群组加入:\n名称: {chat.title}\nID: {chat.id}"
                        )
                    except Exception as e:
                        logger.error(f"通知管理员失败 {admin_id}: {str(e)}")

                await context.bot.send_message(
                    chat_id=chat.id,
                    text="✅ 消息转发已激活"
                )
    except Exception as e:
        logger.error(f"新成员处理异常: {str(e)}")

async def handle_group_message(update: Update, context: CallbackContext):
    """增强的群组消息处理"""
    try:
        message = update.message
        group_id = message.chat.id
        logger.info(f"收到群组消息 - 群组ID: {group_id} 类型: {message.content_type}")
        
        if group_id not in bot_data.groups:
            logger.warning(f"忽略未注册群组消息: {group_id}")
            return
            
        bot_data.groups[group_id].last_activity = datetime.now()
        
        buttons = [
            [
                InlineKeyboardButton(
                    "💬 回复群组", 
                    callback_data=f"group_reply_{group_id}"
                ),
                InlineKeyboardButton(
                    f"👤 回复@{message.from_user.username or message.from_user.first_name}",
                    callback_data=f"user_reply_{group_id}_{message.message_id}"
                )
            ]
        ]

        # 异步转发给所有管理员
        for admin_id in bot_data.admin_ids:
            try:
                forwarded = await message.forward(admin_id)
                
                if message.text:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=f"来自: {bot_data.groups[group_id].title}",
                        reply_to_message_id=forwarded.message_id,
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                else:
                    media_type = message.content_type
                    media = getattr(message, media_type)
                    file_id = media.file_id if media_type == 'document' else media[-1].file_id
                    
                    await getattr(context.bot, f"send_{media_type}")(
                        chat_id=admin_id,
                        **{media_type: file_id},
                        caption=f"来自: {bot_data.groups[group_id].title}",
                        reply_to_message_id=forwarded.message_id,
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
            except Exception as e:
                logger.error(f"转发给管理员 {admin_id} 失败: {str(e)}")
    except Exception as e:
        logger.error(f"群组消息处理异常: {str(e)}")

async def forward_private_message(update: Update, context: CallbackContext):
    """增强的用户私聊处理"""
    try:
        user = update.effective_user
        message = update.message
        logger.info(f"收到用户消息 - 用户ID: {user.id} 类型: {message.content_type}")
        
        if user.id in bot_data.admin_ids:
            return

        bot_data.user_messages[user.id] = {
            'name': user.full_name,
            'username': user.username,
            'last_message': message.message_id,
            'timestamp': datetime.now()
        }

        buttons = [[
            InlineKeyboardButton(
                f"💬 回复 {user.first_name}",
                callback_data=f"reply_user_{user.id}"
            )
        ]]

        for admin_id in bot_data.admin_ids:
            try:
                forwarded = await message.forward(admin_id)
                
                if message.text:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=f"👤 来自用户 {user.full_name} (ID: {user.id})",
                        reply_to_message_id=forwarded.message_id,
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                else:
                    media_type = message.content_type
                    media = getattr(message, media_type)
                    file_id = media.file_id if media_type == 'document' else media[-1].file_id
                    
                    await getattr(context.bot, f"send_{media_type}")(
                        chat_id=admin_id,
                        **{media_type: file_id},
                        caption=f"👤 来自用户 {user.full_name} (ID: {user.id})",
                        reply_to_message_id=forwarded.message_id,
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
            except Exception as e:
                logger.error(f"转发给管理员 {admin_id} 失败: {str(e)}")

        await message.reply_text("✅ 您的消息已转发给管理员")
    except Exception as e:
        logger.error(f"私聊消息处理异常: {str(e)}")

async def handle_button_click(update: Update, context: CallbackContext):
    """增强的按钮回调处理"""
    try:
        query = update.callback_query
        user = query.from_user
        data = query.data
        logger.info(f"按钮回调 - 用户: {user.id} 数据: {data}")
        
        if user.id not in bot_data.admin_ids:
            await query.answer("❌ 需要管理员权限")
            return
            
        if data.startswith('reply_user_'):
            target_user_id = int(data.split('_')[2])
            bot_data.user_context[user.id] = {
                'action': 'reply_to_user',
                'target_user_id': target_user_id,
                'timestamp': datetime.now()
            }
            logger.info(f"管理员 {user.id} 准备回复用户 {target_user_id}")
            await query.answer("请输入回复内容...")
            await query.edit_message_reply_markup(reply_markup=None)
            
        elif data.startswith('group_reply_'):
            group_id = int(data.split('_')[2])
            bot_data.user_context[user.id] = {
                'group_id': group_id,
                'reply_type': 'group',
                'timestamp': datetime.now()
            }
            logger.info(f"管理员 {user.id} 准备回复群组 {group_id}")
            await query.answer("请输入要发送到群组的消息...")
            
        elif data.startswith('user_reply_'):
            parts = data.split('_')
            if len(parts) >= 4:
                group_id = int(parts[2])
                message_id = int(parts[3])
                original_msg = query.message.reply_to_message
                
                content_type = next(
                    (t for t in ['photo', 'document', 'video', 'audio', 'voice'] 
                     if getattr(original_msg, t, None)),
                    None
                )
                
                bot_data.user_context[user.id] = {
                    'group_id': group_id,
                    'message_id': message_id,
                    'reply_type': 'user',
                    'content_type': content_type,
                    'file_id': (getattr(original_msg, content_type).file_id 
                               if content_type == 'document' else 
                               getattr(original_msg, content_type)[-1].file_id if content_type else None),
                    'timestamp': datetime.now()
                }
                logger.info(f"管理员 {user.id} 准备回复群组 {group_id} 的消息 {message_id}")
                await query.answer("请输入回复内容...")
            else:
                logger.error(f"无效的回调数据: {data}")
                await query.answer("⚠️ 操作失败")
                
        await query.delete_message()
    except Exception as e:
        logger.error(f"按钮处理异常: {str(e)}")
        await query.answer("⚠️ 操作失败")

async def process_admin_reply(message: Message, context: CallbackContext):
    """增强的管理员回复处理"""
    try:
        user_id = message.from_user.id
        context_data = bot_data.user_context.get(user_id, {})
        logger.info(f"处理管理员回复 - 用户: {user.id} 上下文: {context_data}")
        
        if not context_data:
            await message.reply_text("⚠️ 会话已过期")
            return
            
        if context_data.get('action') == 'reply_to_user':
            target_user_id = context_data['target_user_id']
            user_info = bot_data.user_messages.get(target_user_id, {})
            
            try:
                if message.text:
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text=f"📨 来自管理员的回复:\n{message.text}"
                    )
                    logger.info(f"已发送文本回复给用户 {target_user_id}")
                elif message.photo:
                    await context.bot.send_photo(
                        chat_id=target_user_id,
                        photo=message.photo[-1].file_id,
                        caption=f"📨 来自管理员的回复:\n{message.caption or ''}"
                    )
                    logger.info(f"已发送图片回复给用户 {target_user_id}")
                elif message.document:
                    await context.bot.send_document(
                        chat_id=target_user_id,
                        document=message.document.file_id,
                        caption=f"📨 来自管理员的回复:\n{message.caption or ''}"
                    )
                    logger.info(f"已发送文件回复给用户 {target_user_id}")
                    
                await message.reply_text(f"✅ 回复已发送给用户 {user_info.get('name', '未知用户')}")
            except Exception as e:
                logger.error(f"回复用户失败: {str(e)}")
                await message.reply_text(f"❌ 发送失败: {str(e)}")
            finally:
                bot_data.user_context.pop(user_id, None)
            return
            
        group_id = context_data.get('group_id')
        if group_id not in bot_data.groups:
            await message.reply_text("⚠️ 目标群组已失效")
            return

        try:
            reply_to_id = context_data.get('message_id')
            
            if message.text:
                await context.bot.send_message(
                    chat_id=group_id,
                    text=message.text,
                    reply_to_message_id=reply_to_id
                )
                logger.info(f"已发送文本消息到群组 {group_id}")
            elif message.photo:
                await context.bot.send_photo(
                    chat_id=group_id,
                    photo=message.photo[-1].file_id,
                    caption=message.caption,
                    reply_to_message_id=reply_to_id
                )
                logger.info(f"已发送图片到群组 {group_id}")
            elif message.document:
                await context.bot.send_document(
                    chat_id=group_id,
                    document=message.document.file_id,
                    reply_to_message_id=reply_to_id
                )
                logger.info(f"已发送文件到群组 {group_id}")
                
            await message.reply_text(f"✅ 消息已发送到群组")
        except Exception as e:
            logger.error(f"发送到群组失败: {str(e)}")
            await message.reply_text(f"❌ 发送失败: {str(e)}")
        finally:
            bot_data.user_context.pop(user_id, None)
    except Exception as e:
        logger.error(f"回复处理异常: {str(e)}")

async def send_to_group(update: Update, context: CallbackContext):
    """增强的主动发送消息功能"""
    try:
        user = update.effective_user
        logger.info(f"收到/send命令 - 用户: {user.id}")
        
        if user.id not in bot_data.admin_ids:
            await update.message.reply_text("❌ 需要管理员权限")
            return

        if not context.args:
            if not bot_data.groups:
                await update.message.reply_text("❌ 没有可用的群组")
                return

            keyboard = [
                [InlineKeyboardButton(
                    f"{group.title} (ID: {group.chat_id})",
                    callback_data=f"select_group_{group.chat_id}"
                )]
                for group in bot_data.groups.values()
            ]
            
            await update.message.reply_text(
                "请选择目标群组:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        try:
            group_id = int(context.args[0])
            if group_id not in bot_data.groups:
                await update.message.reply_text("❌ 无效的群组ID")
                return

            message_text = ' '.join(context.args[1:])
            await context.bot.send_message(
                chat_id=group_id,
                text=message_text
            )
            logger.info(f"管理员 {user.id} 主动发送消息到群组 {group_id}")
            await update.message.reply_text(f"✅ 消息已发送到群组 {bot_data.groups[group_id].title}")
        except ValueError:
            await update.message.reply_text("❌ 群组ID必须是数字")
    except Exception as e:
        logger.error(f"/send处理失败: {str(e)}")
        await update.message.reply_text(f"❌ 发送失败: {str(e)}")

async def list_groups(update: Update, context: CallbackContext):
    """增强的群组列表功能"""
    try:
        user = update.effective_user
        logger.info(f"收到/groups命令 - 用户: {user.id}")
        
        if user.id not in bot_data.admin_ids:
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
        logger.error(f"/groups处理失败: {str(e)}")

async def add_admin(update: Update, context: CallbackContext):
    """增强的管理员添加功能"""
    try:
        user = update.effective_user
        logger.info(f"收到/addadmin命令 - 用户: {user.id}")
        
        if user.id not in bot_data.admin_ids:
            await update.message.reply_text("❌ 需要管理员权限")
            return
            
        if not context.args:
            await update.message.reply_text("用法: /addadmin <用户ID>")
            return
            
        try:
            new_admin_id = int(context.args[0])
            if new_admin_id not in bot_data.admin_ids:
                bot_data.admin_ids.append(new_admin_id)
                logger.info(f"新增管理员: {new_admin_id}")
                await update.message.reply_text(f"✅ 已添加用户 {new_admin_id} 为管理员")
            else:
                await update.message.reply_text("ℹ️ 该用户已是管理员")
        except ValueError:
            await update.message.reply_text("❌ 无效的用户ID")
    except Exception as e:
        logger.error(f"/addadmin处理失败: {str(e)}")

async def check_message_status(update: Update, context: CallbackContext):
    """增强的系统状态检查"""
    try:
        user = update.effective_user
        logger.info(f"收到/status命令 - 用户: {user.id}")
        
        if user.id not in bot_data.admin_ids:
            return
            
        # 显示系统状态
        status = [
            f"🔄 系统状态报告 [{datetime.now().strftime('%Y-%m-%d %H:%M')}]",
            f"活跃群组: {len(bot_data.groups)}",
            f"待处理上下文: {len(bot_data.user_context)}",
            f"用户消息缓存: {len(bot_data.user_messages)}",
            f"最后活跃群组: {max((g.last_activity for g in bot_data.groups.values()), default='无')}"
        ]
        
        await update.message.reply_text("\n".join(status))
        
        # 显示最近日志
        try:
            with open('bot_debug.log', 'r', encoding='utf-8') as f:
                lines = f.readlines()[-10:]
                await update.message.reply_text(
                    "📜 最近日志:\n" + "".join(lines),
                    parse_mode=None
                )
        except Exception as e:
            logger.warning(f"日志读取失败: {str(e)}")
            await update.message.reply_text("⚠️ 无法读取日志文件")
    except Exception as e:
        logger.error(f"/status处理失败: {str(e)}")

async def handle_admin_private_message(update: Update, context: CallbackContext):
    """增强的管理员私聊处理"""
    try:
        message = update.message
        user = message.from_user
        logger.info(f"处理管理员消息 - 用户: {user.id} 类型: {message.content_type}")
        
        context_data = bot_data.user_context.get(user.id, {})
        
        if context_data.get('action') == 'reply_to_user':
            await process_admin_reply(message, context)
            return
            
        if context_data.get('action') == 'send_to_group':
            group_id = context_data['group_id']
            try:
                if message.text:
                    await context.bot.send_message(
                        chat_id=group_id,
                        text=message.text
                    )
                    logger.info(f"管理员主动发送文本到群组 {group_id}")
                elif message.photo:
                    await context.bot.send_photo(
                        chat_id=group_id,
                        photo=message.photo[-1].file_id,
                        caption=message.caption
                    )
                    logger.info(f"管理员主动发送图片到群组 {group_id}")
                elif message.document:
                    await context.bot.send_document(
                        chat_id=group_id,
                        document=message.document.file_id
                    )
                    logger.info(f"管理员主动发送文件到群组 {group_id}")
                
                await message.reply_text(f"✅ 消息已发送到群组")
                bot_data.user_context.pop(user.id, None)
            except Exception as e:
                logger.error(f"主动发送到群组失败: {str(e)}")
                await message.reply_text(f"❌ 发送失败: {str(e)}")
            return
        
        if message.reply_to_message and user.id in bot_data.user_context:
            await process_admin_reply(message, context)
            return
            
        await message.reply_text("ℹ️ 请使用命令或回复消息进行互动")
    except Exception as e:
        logger.error(f"管理员消息处理异常: {str(e)}")

# === 主程序 ===
def main():
    """增强的主程序入口"""
    try:
        token = os.getenv('TELEGRAM_TOKEN')
        if not token:
            raise ValueError("未设置TELEGRAM_TOKEN环境变量")
            
        logger.info("🤖 机器人启动中...")
        
        application = Application.builder().token(token).build()
        application.post_init = init_bot_data
        
        handlers = [
            CommandHandler('start', start),
            CommandHandler('send', send_to_group),
            CommandHandler('groups', list_groups),
            CommandHandler('status', check_message_status),
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
            
        logger.info("✅ 处理器注册完成")
        logger.info("🔄 开始轮询消息...")
        application.run_polling()
    except Exception as e:
        logger.critical(f"⛔ 启动失败: {str(e)}")
        raise

if __name__ == '__main__':
    main()
