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
                        ​**​{msg_type: file_id},
                        caption=f"来自: {bot_data.groups[group_id].title}",
                        reply_to_message_id=forwarded.message_id,
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
    """处理管理员回复（支持所有媒体类型）"""
    try:
        user_id = message.from_user.id
        context_data = bot_data.user_context.get(user_id)
        
        if not context_data:
            await message.reply_text("⚠️ 会话已过期，请重新点击回复按钮")
            return
            
        group_id = context_data['group_id']
        if group_id not in bot_data.groups:
            await message.reply_text("⚠️ 目标群组已失效")
            return

        # 获取原始转发消息
        original_msg = context.bot_data.get('original_message')
        
        try:
            # 文本消息回复
            if message.text:
                await context.bot.send_message(
                    chat_id=group_id,
                    text=message.text,
                    reply_to_message_id=context_data.get('message_id')
                )
            
            # 媒体消息回复（图片/文档/视频等）
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
            elif message.audio:
                await context.bot.send_audio(
                    chat_id=group_id,
                    audio=message.audio.file_id,
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
    """处理按钮回调（增强媒体支持）"""
    try:
        query = update.callback_query
        user = query.from_user
        
        if user.id not in bot_data.admin_ids:
            await query.answer("❌ 需要管理员权限")
            return
            
        data = query.data
        logger.info(f"收到按钮回调: {data}")
        
        # 保存原始消息引用
        context.bot_data['original_message'] = query.message.reply_to_message
        
        # 处理群组回复
        if data.startswith('group_reply_'):
            group_id = int(data.split('_')[2])
            bot_data.user_context[user.id] = {
                'group_id': group_id,
                'reply_type': 'group'
            }
            await query.answer("请输入要发送到群组的消息...")
            
        # 处理用户回复
        elif data.startswith('user_reply_'):
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
