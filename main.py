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
        self.user_messages: Dict[UserID, Dict] = {}  # 存储用户消息上下文

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
        
        # 检查群组注册状态
        if group_id not in bot_data.groups:
            logger.warning(f"未注册的群组消息: {group_id}")
            return
            
        # 更新活动时间
        bot_data.groups[group_id].last_activity = datetime.now()
        
        # 确定消息类型
        msg_type = next(
            (t for t in ['text', 'photo', 'document', 'video', 'audio', 'voice'] 
             if getattr(message, t, None)),
            'unknown'
        )
        logger.info(f"收到群组消息 | 群组: {message.chat.title} | 类型: {msg_type}")

        # 构建回复按钮
        buttons = [
            [
                InlineKeyboardButton("💬 回复群组", callback_data=f"group_reply_{group_id}"),
                InlineKeyboardButton(
                    f"👤 回复@{message.from_user.username or message.from_user.first_name}",
                    callback_data=f"user_reply_{group_id}_{message.message_id}"
                )
            ]
        ]

        # 转发消息给管理员（保留原始消息类型）
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
                elif msg_type in ['photo', 'document', 'video', 'audio', 'voice']:
                    media = getattr(message, msg_type)
                    file_id = media[-1].file_id if msg_type != 'document' else media.file_id
                    
                    forwarded = await message.forward(admin_id)
                    await getattr(context.bot, f"send_{msg_type}")(
                        chat_id=admin_id,
                        **{msg_type: file_id},
                        caption=f"来自: {bot_data.groups[group_id].title}",
                        reply_to_message_id=forwarded.message_id,
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
            except Exception as e:
                logger.error(f"转发消息失败 {admin_id}: {str(e)}")
    except Exception as e:
        logger.error(f"处理群消息异常: {str(e)}")

async def forward_private_message(update: Update, context: CallbackContext):
    """转发普通用户消息给管理员并保存上下文"""
    try:
        user = update.effective_user
        message = update.message
        
        # 管理员消息不处理
        if user.id in bot_data.admin_ids:
            return

        # 保存用户消息上下文
        bot_data.user_messages[user.id] = {
            'name': user.full_name,
            'username': user.username,
            'last_message_id': message.message_id
        }

        # 转发给所有管理员（带回复按钮）
        buttons = [[
            InlineKeyboardButton(
                f"💬 回复 {user.first_name}",
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

async def process_admin_reply(message: Message, context: CallbackContext):
    """处理管理员回复（支持所有消息类型）"""
    try:
        user_id = message.from_user.id
        context_data = bot_data.user_context.get(user_id)
        
        if not context_data:
            await message.reply_text("⚠️ 会话已过期，请重新点击回复按钮")
            return
            
        # 处理回复用户消息
        if context_data.get('action') == 'reply_to_user':
            target_user_id = context_data['target_user_id']
            user_info = bot_data.user_messages.get(target_user_id, {})
            
            try:
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
                await message.reply_text(
                    f"✅ 回复已发送给用户 {user_info.get('name', '未知用户')}"
                )
                
                # 清除上下文
                bot_data.user_context.pop(user_id, None)
                return
            except Exception as e:
                await message.reply_text(f"❌ 回复用户失败: {str(e)}")
                return
        
        # 处理群组消息回复
        group_id = context_data.get('group_id')
        if group_id not in bot_data.groups:
            await message.reply_text("⚠️ 目标群组已失效")
            return

        try:
            # 文本消息回复
            if message.text:
                await context.bot.send_message(
                    chat_id=group_id,
                    text=message.text,
                    reply_to_message_id=context_data.get('message_id')
                )
            
            # 媒体消息回复
            elif message.photo:
                await context.bot.send_photo(
                    chat_id=group_id,
                    photo=message.photo[-1].file_id,
                    caption=message.caption,
                    reply_to_message_id=context_data.get('message_id')
                )
            elif message.document:
                await context.bot.send_document(
                    chat_id=group_id,
                    document=message.document.file_id,
                    reply_to_message_id=context_data.get('message_id')
                )
            elif message.video:
                await context.bot.send_video(
                    chat_id=group_id,
                    video=message.video.file_id,
                    caption=message.caption,
                    reply_to_message_id=context_data.get('message_id')
                )
                
            await message.reply_text(f"✅ 回复已发送到群组")
            
        except Exception as e:
            await message.reply_text(f"❌ 发送失败: {str(e)}")
            logger.error(f"回复处理失败: {str(e)}", exc_info=True)
        finally:
            bot_data.user_context.pop(user_id, None)
            
    except Exception as e:
        logger.error(f"处理回复异常: {str(e)}", exc_info=True)

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
            target_user_id = int(data.split('_')[2])
            bot_data.user_context[user.id] = {
                'action': 'reply_to_user',
                'target_user_id': target_user_id
            }
            await query.answer(f"请输入要回复用户的内容")
            await query.edit_message_reply_markup(reply_markup=None)
            return
            
        # 处理群组选择
        if data.startswith('select_group_'):
            group_id = int(data.split('_')[2])
            bot_data.user_context[user.id] = {
                'action': 'send_to_group',
                'group_id': group_id
            }
            await query.edit_message_text(
                f"已选择群组: {bot_data.groups[group_id].title}\n"
                "请直接发送要发送的消息内容"
            )
            return
            
        # 处理群组回复
        if data.startswith('group_reply_'):
            group_id = int(data.split('_')[2])
            bot_data.user_context[user.id] = {
                'group_id': group_id,
                'reply_type': 'group'
            }
            await query.answer("请输入要发送到群组的消息...")
            return
            
        # 处理用户回复
        if data.startswith('user_reply_'):
            parts = data.split('_')
            if len(parts) >= 4:
                group_id = int(parts[2])
                message_id = int(parts[3])
                
                # 检测原始消息类型
                original_msg = query.message.reply_to_message
                content_type = next(
                    (t for t in ['photo', 'document', 'video', 'audio', 'voice'] 
                     if getattr(original_msg, t, None)),
                    None
                )
                
                # 保存上下文
                bot_data.user_context[user.id] = {
                    'group_id': group_id,
                    'message_id': message_id,
                    'reply_type': 'user',
                    'content_type': content_type,
                    'file_id': (getattr(original_msg, content_type)[-1].file_id 
                               if content_type and content_type != 'document' 
                               else getattr(original_msg, content_type).file_id if content_type else None)
                }
                await query.answer("请输入回复内容...")
            else:
                logger.error(f"无效的回调数据格式: {data}")
                await query.answer("⚠️ 操作失败，数据格式错误")
        
        await query.delete_message()
    except Exception as e:
        logger.error(f"按钮处理错误: {str(e)}", exc_info=True)
        await query.answer("⚠️ 操作失败")

async def send_to_group(update: Update, context: CallbackContext):
    """发送消息到群组命令"""
    try:
        user = update.effective_user
        if user.id not in bot_data.admin_ids:
            await update.message.reply_text("❌ 需要管理员权限")
            return

        if not context.args:
            # 显示群组选择键盘
            if not bot_data.groups:
                await update.message.reply_text("❌ 没有可用的群组")
                return

            keyboard = []
            for group in bot_data.groups.values():
                keyboard.append([
                    InlineKeyboardButton(
                        f"{group.title} (ID: {group.chat_id})",
                        callback_data=f"select_group_{group.chat_id}"
                    )
                ])
            
            await update.message.reply_text(
                "请选择目标群组:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # 直接发送消息格式: /send 群组ID 消息内容
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
            await update.message.reply_text(f"✅ 消息已发送到群组 {bot_data.groups[group_id].title}")
        except ValueError:
            await update.message.reply_text("❌ 群组ID必须是数字")

    except Exception as e:
        logger.error(f"发送到群组出错: {str(e)}")
        await update.message.reply_text(f"❌ 发送失败: {str(e)}")

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

async def handle_admin_private_message(update: Update, context: CallbackContext):
    """处理管理员私聊消息"""
    try:
        user = update.effective_user
        message = update.message
        
        # 检查是否在回复用户模式下
        context_data = bot_data.user_context.get(user.id, {})
        
        if context_data.get('action') == 'reply_to_user':
            await process_admin_reply(message, context)
            return
            
        # 检查是否在发送到群组模式下
        if context_data.get('action') == 'send_to_group':
            group_id = context_data['group_id']
            try:
                if message.text:
                    await context.bot.send_message(
                        chat_id=group_id,
                        text=message.text
                    )
                elif message.photo:
                    await context.bot.send_photo(
                        chat_id=group_id,
                        photo=message.photo[-1].file_id,
                        caption=message.caption
                    )
                elif message.document:
                    await context.bot.send_document(
                        chat_id=group_id,
                        document=message.document.file_id
                    )
                
                await message.reply_text(f"✅ 消息已发送到群组 {bot_data.groups[group_id].title}")
                bot_data.user_context.pop(user.id, None)
                return
            except Exception as e:
                await message.reply_text(f"❌ 发送失败: {str(e)}")
                return
        
        # 处理回复消息
        if message.reply_to_message and user.id in bot_data.user_context:
            await process_admin_reply(message, context)
            return
            
        # 默认回复
        await message.reply_text("ℹ️ 请使用命令或回复消息进行互动")
        
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
