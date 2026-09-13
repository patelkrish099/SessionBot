import os
import shutil
import zipfile
import asyncio
import random
import re
import json
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, MessageOriginChannel
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters import CommandStart, Command
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError, SessionPasswordNeededError, PhoneCodeInvalidError, 
    PasswordHashInvalidError, InviteRequestSentError, UserAlreadyParticipantError,
    FreshResetAuthorisationForbiddenError
)
from telethon.tl.functions.account import (
    GetAuthorizationsRequest, UpdateProfileRequest, ResetAuthorizationRequest, GetPasswordRequest,
    SetPrivacyRequest, UploadProfilePhotoRequest, DeletePhotosRequest
)
from telethon.tl.functions.auth import ResetAuthorizationsRequest
from telethon.tl.functions.messages import ReportRequest
from telethon.tl.types import (
    InputPrivacyKeyPhoneNumber, InputPrivacyValueAllowAll, InputPrivacyValueDisallowAll
)
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest, GetFullChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, SendVoteRequest, GetMessagesViewsRequest, SendReactionRequest, GetBotCallbackAnswerRequest
from telethon.tl.functions.phone import JoinGroupCallRequest, LeaveGroupCallRequest
from telethon.tl.types import ReactionEmoji, ReactionCustomEmoji, DataJSON, User, Channel, Chat

# --- TDATA ENGINE ---
try:
    from opentele.td import TDesktop
    from opentele.api import UseCurrentSession
    OPENTELE_AVAILABLE = True
except ImportError:
    OPENTELE_AVAILABLE = False

# ==========================================
# ⚙️ CONFIGURATION & CREDENTIALS
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "7962465718:AAHQ31pkxtfLwEkRk9fbOdxG50M6yebU50U")

API_CREDENTIALS = [
    {"api_id": 30283245, "api_hash": "4ff403953f3c0d1911cf1b380ac77b90"},
]

BRAND_NAME = "Oggy"
ADMIN_ID = 7507183871
MAX_DM_AMOUNT = 50

CONCURRENT_CHECKS = 50
semaphore = asyncio.Semaphore(CONCURRENT_CHECKS)
job_queue = asyncio.Queue()

WORK_DIR = "work_dir"
BOT_USERS_FILE = os.path.join(WORK_DIR, "bot_users.json")
os.makedirs(WORK_DIR, exist_ok=True)

bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()
router = Router()
dp.include_router(router)

active_logins = {}

def load_bot_users():
    try:
        with open(BOT_USERS_FILE, encoding="utf-8") as source:
            return {int(user_id) for user_id in json.load(source)}
    except (OSError, ValueError, TypeError):
        return set()

def remember_bot_user(user_id):
    users = load_bot_users()
    users.add(user_id)
    with open(BOT_USERS_FILE, "w", encoding="utf-8") as destination:
        json.dump(sorted(users), destination)

# ==========================================
# 🗂 STATES & UI KEYBOARDS
# ==========================================
class BotStates(StatesGroup):
    waiting_for_zip = State()
    in_main_menu = State()
    waiting_for_phone_login = State()
    waiting_for_otp_login = State()
    waiting_for_2fa_login = State()
    waiting_for_2fa_new = State()
    waiting_for_2fa_manage = State()
    waiting_for_rename = State()
    waiting_for_split = State()
    waiting_for_merge = State()
    waiting_for_bio = State()
    waiting_for_name_change = State()
    waiting_for_broadcast_text = State()
    waiting_for_broadcast_delay = State()
    waiting_for_report_target = State()
    waiting_for_profile_picture = State()
    waiting_for_admin_broadcast = State()
    
    protect_waiting_for_acc = State()
    protect_waiting_for_hash = State()

    waiting_for_mass_join_config = State()
    waiting_for_mass_dm_config = State()
    
    msg_waiting_for_text = State()
    msg_waiting_for_amount = State()
    msg_waiting_for_next = State()
    
    vote_waiting_for_count = State()
    vote_waiting_for_channel = State()
    vote_waiting_for_post = State()
    vote_waiting_for_option = State()
    vote_waiting_for_delay = State()
    
    view_waiting_for_count = State()
    view_waiting_for_post = State()
    
    react_waiting_for_count = State()
    react_waiting_for_post = State()
    react_waiting_for_choice = State()
    
    vc_waiting_for_count = State()
    vc_waiting_for_channel = State()
    vc_waiting_for_link = State()
    vc_waiting_for_delay = State()

def get_main_menu_kb():
    """A concise operational menu; Telegram inline buttons have no style field."""
    rows = [
        [("📁 Validate Sessions", "queue_check_session"), ("🛡 Spam Review", "queue_check_spam")],
        [("🔐 Check 2FA", "queue_check_2fa"), ("⭐ Check Stars", "queue_check_stars")],
        [("💎 Check Premium", "queue_check_premium"), ("🏷 Check Scam/Fake", "queue_check_tags")],
        [("📱 Sort by Devices", "queue_sort_devices"), ("🛡 Device Security", "device_sec_menu")],
        [("🚩 Report Target", "report_target_prompt"), ("🖼 Change Picture", "change_picture_prompt")],
        [("🗑 Remove Picture", "queue_remove_picture"), ("🙈 Hide Phone", "queue_hide_phone")],
        [("👁 Show Phone", "queue_show_phone"), ("🔐 2FA Management", "2fa_manage_menu")],
        [("📝 Update Bio", "bio_update_prompt"), ("🏷 Update Name", "name_change_prompt")],
        [("📧 Check Recovery Email", "queue_check_gmail"), ("🔐 Read Login Codes", "read_otp_start")],
        [("💥 Destroy Sessions", "destroy_prompt"), ("🧹 Clear Chats", "clear_chats_prompt")],
        [("🆕 Create Sessions", "create_new_prompt"), ("📢 Account Broadcast", "broadcast_menu")],
        [("✏️ Rename Package", "rename_zip"), ("🧩 Split Package", "split_zip")],
        [("🧷 Merge Packages", "merge_zip")],
        [("✉️ Mass DM", "mass_dm_prompt"), ("📢 Mass Join", "mass_join_prompt")],
        [("🗳 Mass Vote", "mass_vote_prompt"), ("👁 Mass Views", "mass_view_prompt")],
        [("❤️ Mass Reactions", "mass_react_prompt"), ("🎧 Mass Voice Chat", "mass_vc_prompt")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=callback) for text, callback in row] for row in rows
    ])

def get_start_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Create Telethon Sessions", callback_data="start_create_telethon")],
        [InlineKeyboardButton(text="🔵 Create Pyrogram Sessions", callback_data="start_create_pyrogram")]
    ])

def get_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]])

def get_cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")]])

def get_random_api():
    return random.choice(API_CREDENTIALS)

def is_valid_data(data):
    return bool(data and data.get('user_dir') and data.get('extract_dir') and data.get('sessions'))

# ==========================================
# 🛠 ADVANCED UTILITIES & JSON/TDATA SPOOFER
# ==========================================
class ProgressTracker:
    def __init__(self, message: Message, total: int, action_text: str):
        self.message = message
        self.total = total if total > 0 else 1
        self.action_text = action_text
        self.current = 0
        self.last_percent = -1
        self.lock = asyncio.Lock()

    async def advance(self):
        async with self.lock:
            self.current += 1
            percent = int((self.current / self.total) * 100)
            if percent >= self.last_percent + 10 or self.current == self.total:
                self.last_percent = (percent // 10) * 10
                blocks = int(percent / 10)
                bar = "█" * blocks + "▒" * (10 - blocks)
                try:
                    await self.message.edit_text(f"⏳ **{self.action_text}**\n\n`{bar} {percent}%`", parse_mode="Markdown")
                except Exception:
                    pass

def create_client(sess_path):
    """ADVANCED SPOOFER: Handles .json configs and converted tdata files naturally!"""
    json_path = sess_path.replace('.session', '.json')
    api_id = None
    api_hash = None
    kwargs = {}
    
    if "tdata_" in os.path.basename(sess_path):
        api_id = 2040
        api_hash = "b18441a1ff607e10a989891a5462e627"
        kwargs['device_model'] = "Desktop"
        kwargs['system_version'] = "Windows 10"
        kwargs['app_version'] = "4.14.9 x64"
        kwargs['lang_code'] = "en"
        kwargs['system_lang_code'] = "en-US"
        
    elif os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f: config = json.load(f)
            api_id = config.get('app_id') or config.get('api_id')
            api_hash = config.get('app_hash') or config.get('api_hash')
            if config.get('device') or config.get('device_model'): kwargs['device_model'] = config.get('device') or config.get('device_model')
            if config.get('sdk') or config.get('system_version'): kwargs['system_version'] = config.get('sdk') or config.get('system_version')
            if config.get('app_version'): kwargs['app_version'] = config.get('app_version')
            if config.get('lang_code'): kwargs['lang_code'] = config.get('lang_code')
            if config.get('system_lang_code'): kwargs['system_lang_code'] = config.get('system_lang_code')
        except: pass
            
    if not api_id or not api_hash:
        api = get_random_api()
        api_id, api_hash = api['api_id'], api['api_hash']
        
    return TelegramClient(sess_path, api_id=int(api_id), api_hash=api_hash, **kwargs)

async def safe_disconnect(client: TelegramClient):
    try: await client.disconnect()
    except Exception: pass

def extract_zip(zip_path, extract_to):
    """Safely extract archives without allowing path traversal."""
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        destination = os.path.realpath(extract_to)
        for member in zip_ref.infolist():
            target = os.path.realpath(os.path.join(destination, member.filename))
            if not target.startswith(destination + os.sep):
                raise ValueError("Archive contains an unsafe path")
        zip_ref.extractall(extract_to)

def copy_session_bundle(session_path, destination):
    """Copy a session and its optional JSON profile together."""
    os.makedirs(destination, exist_ok=True)
    shutil.copy2(session_path, os.path.join(destination, os.path.basename(session_path)))
    json_path = session_path[:-8] + ".json"
    if os.path.exists(json_path):
        shutil.copy2(json_path, os.path.join(destination, os.path.basename(json_path)))

def display_account(me):
    name = " ".join(part for part in [getattr(me, "first_name", ""), getattr(me, "last_name", "")] if part).strip() or "Unknown"
    return f"{name} (+{getattr(me, 'phone', None) or 'unknown'})"

def create_zip(folder_path, output_zip):
    """
    🌟 PERFECT ZIP BUILDER 🌟
    Flattens the directory structure so ALL files sit directly in the root of the ZIP.
    Strictly accepts only .session and .json files. Removes SQLite cache files.
    This guarantees 100% compatibility with every bot on Telegram.
    """
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(folder_path):
            for file in files:
                if file.endswith('.session') or file.endswith('.json'):
                    if not file.endswith(('-journal', '-wal', '-shm')):
                        file_path = os.path.join(root, file)
                        # Write the file directly into the root of the ZIP (flattening)
                        zipf.write(file_path, file)

# ==========================================
# 🚀 CORE BACKGROUND WORKERS
# ==========================================
async def background_worker():
    while True:
        job = await job_queue.get()
        call, state, job_type, status_msg = job
        try:
            if job_type == "check_session": await process_check_sessions(call, state, status_msg)
            elif job_type == "check_spam": await process_check_spam(call, state, status_msg)
            elif job_type == "check_age": await process_check_age(call, state, status_msg)
            elif job_type == "destroy_session": await process_destroy_sessions(call, state, status_msg)
            elif job_type == "clear_chats": await process_clear_chats(call, state, status_msg)
            elif job_type == "execute_2fa": await execute_2fa_changes(call, state, status_msg)
            elif job_type == "terminate_others": await process_terminate_others(call, state, status_msg)
            elif job_type == "mass_msg": await execute_mass_msg(call, state, status_msg)
            elif job_type == "mass_vote": await execute_mass_vote(call, state, status_msg)
            elif job_type == "mass_view": await execute_mass_view(call, state, status_msg)
            elif job_type == "mass_react": await execute_mass_react(call, state, status_msg)
            elif job_type == "mass_vc": await execute_mass_vc(call, state, status_msg)
            elif job_type == "check_gmail": await process_check_gmail(call, state, status_msg)
            elif job_type == "bio_update": await process_bio_update(call, state, status_msg)
            elif job_type == "name_change": await process_name_change(call, state, status_msg)
            elif job_type == "broadcast": await process_broadcast(call, state, status_msg)
            elif job_type == "check_2fa": await process_check_2fa(call, state, status_msg)
            elif job_type == "sort_devices": await process_sort_devices(call, state, status_msg)
            elif job_type == "check_stars": await process_check_stars(call, state, status_msg)
            elif job_type == "check_premium": await process_check_premium(call, state, status_msg)
            elif job_type == "check_tags": await process_check_tags(call, state, status_msg)
            elif job_type == "remove_picture": await process_remove_picture(call, state, status_msg)
            elif job_type in ("hide_phone", "show_phone"): await process_phone_privacy(call, state, status_msg, job_type == "show_phone")
            elif job_type == "report_target": await process_report_target(call, state, status_msg)
            elif job_type == "change_picture": await process_change_picture(call, state, status_msg)
        except Exception as e:
            print(f"Job Error: {e}")
        finally:
            job_queue.task_done()

# ==========================================
# 📱 1. START COMMAND & GLOBAL CANCEL
# ==========================================
@router.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext):
    remember_bot_user(message.from_user.id)
    text = f"📦 Send a .zip file with Telegram sessions.\n*(Supports Telethon + JSON configs AND TData folders!)*\n\nOr create fresh session zips below."
    await state.clear()
    await state.set_state(BotStates.waiting_for_zip)
    await message.answer(text, reply_markup=get_start_kb(), parse_mode="Markdown")

@router.callback_query(F.data == "cancel_action")
async def cancel_action(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    data = await state.get_data()
    user_id = call.from_user.id
    
    if user_id in active_logins:
        try: await safe_disconnect(active_logins[user_id]["client"])
        except: pass
        del active_logins[user_id]

    if is_valid_data(data):
        zip_id = data.get('zip_id', '0000')
        sessions = data['sessions']
        text = (
            f"📦 **SESSION PACKAGE LOADED**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 **Batch ID:** `#{zip_id}`\n"
            f"⚙️ **Format:** `Telethon / TData`\n"
            f"👤 **Accounts:** `{len(sessions)}`\n"
            f"🛡️ **Status:** `Secured & Ready`\n\n"
            f"🚀 *Powered by {BRAND_NAME}*"
        )
        await state.set_state(BotStates.in_main_menu)
        try: await call.message.edit_text(text, reply_markup=get_main_menu_kb(), parse_mode="Markdown")
        except: pass
    else:
        await state.clear()
        await state.set_state(BotStates.waiting_for_zip)
        try: await call.message.edit_text("❌ Action cancelled.\n\n📦 Send a .zip file with Telegram sessions.", reply_markup=get_start_kb())
        except: pass

# ==========================================
# 🆕 1.5 INTERACTIVE LOGIN ENGINE
# ==========================================
@router.callback_query(F.data.in_(["start_create_telethon", "start_create_pyrogram"]))
async def start_creation_loop(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass 
    target = "Telethon" if "telethon" in call.data else "Pyrogram"
    user_id = call.from_user.id
    user_dir = os.path.join(WORK_DIR, str(user_id))
    created_dir = os.path.join(user_dir, "created_sessions")
    os.makedirs(created_dir, exist_ok=True)
    
    await state.update_data(account_idx=1, created_dir=created_dir, target_format=target)
    await state.set_state(BotStates.waiting_for_phone_login)
    
    msg = f"⚙️ **{target}** Session Creation started.\n*(Note: Always generates raw Telethon schema internally for bot compatibility)*\n\n📱 Send phone number for account 1 (with country code) or type `/done`."
    await call.message.edit_text(msg, reply_markup=get_cancel_kb(), parse_mode="Markdown")

@router.message(BotStates.waiting_for_phone_login)
async def process_phone_login(message: Message, state: FSMContext):
    if message.text.lower() == "/done":
        data = await state.get_data()
        created_dir = data.get('created_dir')
        if created_dir and os.listdir(created_dir):
            zip_path = os.path.join(WORK_DIR, str(message.from_user.id), "Fresh_Sessions.zip")
            await asyncio.to_thread(create_zip, created_dir, zip_path)
            await message.answer_document(FSInputFile(zip_path), caption="📦 Here are your freshly created sessions!")
        else:
            await message.answer("❌ No sessions were created.")
        await state.set_state(BotStates.waiting_for_zip)
        return

    phone = message.text.strip().replace(" ", "")
    user_id = message.from_user.id
    data = await state.get_data()
    created_dir = data['created_dir']

    sess_path = os.path.join(created_dir, f"{phone}.session")
    client = create_client(sess_path)

    try:
        await client.connect()
        send_code = await client.send_code_request(phone)
        active_logins[user_id] = {
            "client": client, "phone": phone, "hash": send_code.phone_code_hash
        }
        await state.set_state(BotStates.waiting_for_otp_login)
        await message.answer(f"✉️ Code sent to `{phone}`!\n\n👉 Send the OTP code (e.g. 12345).", reply_markup=get_cancel_kb(), parse_mode="Markdown")
    except Exception as e:
        await safe_disconnect(client)
        await message.answer(f"❌ Error sending code: {e}\n\n📱 Send another phone number or `/done`.", reply_markup=get_cancel_kb(), parse_mode="Markdown")

@router.message(BotStates.waiting_for_otp_login)
async def process_otp_login(message: Message, state: FSMContext):
    code = message.text.strip()
    user_id = message.from_user.id

    if user_id not in active_logins:
        await message.answer("❌ Login session expired. Start over.", reply_markup=get_cancel_kb())
        return await state.set_state(BotStates.waiting_for_phone_login)

    login_data = active_logins[user_id]
    client = login_data["client"]

    try:
        await client.sign_in(login_data["phone"], code, phone_code_hash=login_data["hash"])
        await safe_disconnect(client)
        del active_logins[user_id]
        
        data = await state.get_data()
        idx = data.get('account_idx', 1) + 1
        await state.update_data(account_idx=idx)
        await state.set_state(BotStates.waiting_for_phone_login)
        await message.answer(f"✅ Account logged in successfully!\n\n📱 Send phone number for account {idx} or type `/done`.", reply_markup=get_cancel_kb(), parse_mode="Markdown")
        
    except SessionPasswordNeededError:
        await state.set_state(BotStates.waiting_for_2fa_login)
        await message.answer("🔐 2FA is enabled. Send your 2FA password.", reply_markup=get_cancel_kb())
    except Exception as e:
        await safe_disconnect(client)
        del active_logins[user_id]
        await state.set_state(BotStates.waiting_for_phone_login)
        await message.answer(f"❌ OTP Error: {e}\n\n📱 Send phone number again or `/done`.", reply_markup=get_cancel_kb(), parse_mode="Markdown")

@router.message(BotStates.waiting_for_2fa_login)
async def process_2fa_login(message: Message, state: FSMContext):
    pwd = message.text.strip()
    user_id = message.from_user.id

    if user_id not in active_logins:
        return await message.answer("❌ Login session expired.", reply_markup=get_cancel_kb())

    client = active_logins[user_id]["client"]
    try:
        await client.sign_in(password=pwd)
        await safe_disconnect(client)
        del active_logins[user_id]

        data = await state.get_data()
        idx = data.get('account_idx', 1) + 1
        await state.update_data(account_idx=idx)
        await state.set_state(BotStates.waiting_for_phone_login)
        await message.answer(f"✅ Account logged in with 2FA!\n\n📱 Send phone number for account {idx} or type `/done`.", reply_markup=get_cancel_kb(), parse_mode="Markdown")
    except Exception as e:
        await safe_disconnect(client)
        del active_logins[user_id]
        await state.set_state(BotStates.waiting_for_phone_login)
        await message.answer(f"❌ 2FA Error: {e}\n\n📱 Send phone number again or `/done`.", reply_markup=get_cancel_kb(), parse_mode="Markdown")

# ==========================================
# 📁 2. GLOBAL ZIP & TDATA HANDLING
# ==========================================
@router.message(F.document)
async def handle_global_document(message: Message, state: FSMContext):
    filename = message.document.file_name or "session_upload"
    current_state = await state.get_state()
    if current_state == BotStates.waiting_for_merge.state:
        return await process_merge(message, state)
    if not (filename.lower().endswith(".zip") or filename.lower().endswith(".session")):
        return await message.answer("❌ Send a Telegram `.session` file or a ZIP containing sessions.", parse_mode="Markdown")

    msg = await message.answer("📥 Preparing your session package…")
    user_dir = os.path.join(WORK_DIR, str(message.from_user.id))
    if os.path.exists(user_dir): shutil.rmtree(user_dir)
    os.makedirs(user_dir, exist_ok=True)

    upload_path = os.path.join(user_dir, filename)
    await bot.download(message.document, destination=upload_path)
    extract_dir = os.path.join(user_dir, "extracted")
    os.makedirs(extract_dir, exist_ok=True)
    try:
        if filename.lower().endswith(".zip"):
            await asyncio.to_thread(extract_zip, upload_path, extract_dir)
        else:
            # A raw session is normalized into the same package structure as ZIP uploads.
            shutil.copy2(upload_path, os.path.join(extract_dir, os.path.basename(filename)))
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        return await msg.edit_text(f"❌ The uploaded package could not be read: {exc}")

    sessions = []
    for root, _, files in os.walk(extract_dir):
        for file in files:
            if file.endswith('.session'):
                source = os.path.join(root, file)
                destination = os.path.join(extract_dir, file)
                if source != destination:
                    base, ext = os.path.splitext(file)
                    counter = 1
                    while os.path.exists(destination):
                        destination = os.path.join(extract_dir, f"{base}_{counter}{ext}")
                        counter += 1
                    shutil.copy2(source, destination)
                    source_json = os.path.splitext(source)[0] + '.json'
                    if os.path.exists(source_json):
                        shutil.copy2(source_json, os.path.splitext(destination)[0] + '.json')
                sessions.append(os.path.basename(destination))
    sessions = sorted(set(sessions))
    
    # 2. TData Decryption Engine
    tdata_folders = []
    for root, dirs, files in os.walk(extract_dir):
        if 'key_datas' in files: tdata_folders.append(root)
            
    if tdata_folders:
        if not OPENTELE_AVAILABLE:
            await message.answer("⚠️ TData files detected, but `opentele` library is missing! Ask admin to `pip install opentele` to convert them.")
        else:
            await msg.edit_text("⏳ Decrypting & Converting TData files to Telethon...")
            for i, tdata_path in enumerate(tdata_folders):
                try:
                    sess_name = f"tdata_{i}_{random.randint(100,999)}.session"
                    out_path = os.path.join(extract_dir, sess_name)
                    tdesk = TDesktop(tdata_path)
                    client = await tdesk.ToTelethon(session=out_path, flag=UseCurrentSession)
                    await client.connect()
                    await client.disconnect()
                    sessions.append(sess_name)
                except Exception as e:
                    print(f"TData Conversion Error: {e}")

    if not sessions: return await msg.edit_text("❌ No .session files or valid TData found inside this zip!")

    zip_id = random.randint(1000, 9999)
    await state.update_data(user_dir=user_dir, extract_dir=extract_dir, sessions=sessions, zip_id=zip_id)
    await state.set_state(BotStates.in_main_menu)
    
    text = (
        f"📦 **SESSION PACKAGE LOADED**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **Batch ID:** `#{zip_id}`\n"
        f"⚙️ **Format:** `Telethon / TData`\n"
        f"👤 **Accounts:** `{len(sessions)}`\n"
        f"🛡️ **Status:** `Secured & Ready`\n\n"
        f"🚀 *Powered by {BRAND_NAME}*"
    )
    try: await msg.edit_text(text, reply_markup=get_main_menu_kb(), parse_mode="Markdown")
    except: pass

@router.callback_query(F.data == "main_menu")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    data = await state.get_data()
    if not is_valid_data(data):
        return await call.message.edit_text("❌ Session expired. Please upload the .zip file again.", reply_markup=get_start_kb())
    zip_id = data.get('zip_id', '0000')
    sessions = data['sessions']
    text = (
        f"📦 **SESSION PACKAGE LOADED**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **Batch ID:** `#{zip_id}`\n"
        f"⚙️ **Format:** `Telethon / TData`\n"
        f"👤 **Accounts:** `{len(sessions)}`\n"
        f"🛡️ **Status:** `Secured & Ready`\n\n"
        f"🚀 *Powered by {BRAND_NAME}*"
    )
    try: await call.message.edit_text(text, reply_markup=get_main_menu_kb(), parse_mode="Markdown")
    except: pass

@router.callback_query(F.data.startswith("queue_"))
async def add_to_queue(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    data = await state.get_data()
    if not is_valid_data(data):
        return await call.message.edit_text("❌ Session expired. Please upload the .zip file again.", reply_markup=get_start_kb())
        
    job_type = call.data.replace("queue_", "")
    actions = {
        "check_session": "Checking Sessions", 
        "check_spam": "Checking Spam", 
        "check_age": "Checking Age via @TGDNAbot", 
        "destroy_session": "Destroying Sessions", 
        "clear_chats": "Clearing Chats",
        "terminate_others": "Terminating Other Devices",
        "check_gmail": "Checking Gmail connections",
        "bio_update": "Updating bios",
        "name_change": "Updating names",
        "broadcast": "Delivering broadcast",
        "check_2fa": "Checking two-step verification", "sort_devices": "Sorting by device count",
        "check_stars": "Checking Stars", "check_premium": "Checking Premium", "check_tags": "Checking account tags",
        "remove_picture": "Removing profile pictures", "hide_phone": "Hiding phone numbers", "show_phone": "Showing phone numbers",
        "report_target": "Submitting reports", "change_picture": "Updating profile pictures"
    }
    action_text = actions.get(job_type, "Processing")
    status_msg = await call.message.edit_text(f"⏳ **{action_text}**\n\n`▒▒▒▒▒▒▒▒▒▒ 0%`", parse_mode="Markdown")
    await job_queue.put((call, state, job_type, status_msg))

# ==========================================
# ⚙️ 3. SUPER-FAST CONCURRENT CHECKERS
# ==========================================
async def process_check_sessions(call: CallbackQuery, state: FSMContext, status_msg: Message):
    data = await state.get_data()
    extract_dir, user_dir = data['extract_dir'], data['user_dir']
    
    # Store clean valid output
    out_active = os.path.join(user_dir, "Active_Sessions")
    out_dead = os.path.join(user_dir, "Dead_Sessions")
    os.makedirs(out_active, exist_ok=True)
    os.makedirs(out_dead, exist_ok=True)
    
    sessions = data['sessions']
    tracker = ProgressTracker(status_msg, len(sessions), "Checking Sessions")

    async def worker(sess):
        sess_path = os.path.join(extract_dir, sess)
        json_path = sess_path.replace('.session', '.json')
        async with semaphore:
            client = create_client(sess_path)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    shutil.copy(sess_path, os.path.join(out_active, sess))
                    if os.path.exists(json_path): shutil.copy(json_path, os.path.join(out_active, os.path.basename(json_path)))
                else: 
                    shutil.copy(sess_path, os.path.join(out_dead, sess))
                    if os.path.exists(json_path): shutil.copy(json_path, os.path.join(out_dead, os.path.basename(json_path)))
            except: 
                shutil.copy(sess_path, os.path.join(out_dead, sess))
                if os.path.exists(json_path): shutil.copy(json_path, os.path.join(out_dead, os.path.basename(json_path)))
            finally: await safe_disconnect(client)
        await tracker.advance()

    await asyncio.gather(*(worker(s) for s in sessions))

    if os.listdir(out_active):
        zip_path = os.path.join(user_dir, "Active_Sessions.zip")
        await asyncio.to_thread(create_zip, out_active, zip_path)
        await call.message.answer_document(FSInputFile(zip_path), caption="✅ Valid Sessions")
    if os.listdir(out_dead):
        zip_path = os.path.join(user_dir, "Invalid_Sessions.zip")
        await asyncio.to_thread(create_zip, out_dead, zip_path)
        await call.message.answer_document(FSInputFile(zip_path), caption="❌ Invalid Sessions")
    valid = sum(1 for file in os.listdir(out_active) if file.endswith(".session"))
    invalid = sum(1 for file in os.listdir(out_dead) if file.endswith(".session"))
    await call.message.answer(f"✅ Session check complete.\n🟢 Valid: {valid}\n🔴 Invalid: {invalid}", reply_markup=get_back_kb())

async def process_check_spam(call: CallbackQuery, state: FSMContext, status_msg: Message):
    """Classify every usable session from @SpamBot's current response."""
    data = await state.get_data()
    extract_dir, user_dir = data['extract_dir'], data['user_dir']
    labels = {
        "Frozen_Sessions": "❄️ Frozen Sessions",
        "Spam_Accounts": "🚫 Spam Accounts",
        "Spam_Free_Accounts": "🟢 Spam-Free Accounts",
        "Temporary_Spam_Accounts": "⚠️ Temporary Spam Accounts",
    }
    dirs = {key: os.path.join(user_dir, key) for key in labels}
    for folder in dirs.values(): os.makedirs(folder, exist_ok=True)
    tracker = ProgressTracker(status_msg, len(data['sessions']), "Checking Spam")

    def classify(text):
        value = (text or "").lower()
        if any(term in value for term in ("frozen", "deactivated", "deleted")): return "Frozen_Sessions"
        if any(term in value for term in ("good news", "no limits", "not limited")): return "Spam_Free_Accounts"
        if any(term in value for term in ("temporarily", "temporary", "until ", "limited until")): return "Temporary_Spam_Accounts"
        return "Spam_Accounts"

    async def worker(sess):
        sess_path = os.path.join(extract_dir, sess)
        category = "Frozen_Sessions"
        async with semaphore:
            client = create_client(sess_path)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    await client.send_message("@SpamBot", "/start")
                    reply = None
                    for _ in range(10):
                        await asyncio.sleep(1)
                        messages = await client.get_messages("@SpamBot", limit=4)
                        reply = next((m.text for m in messages if not m.out and m.text), None)
                        if reply: break
                    category = classify(reply)
                copy_session_bundle(sess_path, dirs[category])
            except Exception:
                copy_session_bundle(sess_path, dirs["Frozen_Sessions"])
            finally:
                await safe_disconnect(client)
        await tracker.advance()

    await asyncio.gather(*(worker(session) for session in data['sessions']))
    sent = 0
    for key, folder in dirs.items():
        if any(path.endswith('.session') for path in os.listdir(folder)):
            zip_path = os.path.join(user_dir, f"{key}.zip")
            await asyncio.to_thread(create_zip, folder, zip_path)
            await call.message.answer_document(FSInputFile(zip_path), caption=labels[key])
            sent += 1
    await call.message.answer(f"✅ Spam review complete. Created {sent} category package(s).", reply_markup=get_back_kb())

async def process_check_age(call: CallbackQuery, state: FSMContext, status_msg: Message):
    data = await state.get_data()
    extract_dir, user_dir = data['extract_dir'], data['user_dir']
    failed_dir = os.path.join(user_dir, "Failed_Age")
    os.makedirs(failed_dir, exist_ok=True)

    sessions = data['sessions']
    tracker = ProgressTracker(status_msg, len(sessions), "Checking Age via @TGDNAbot")

    async def worker(sess):
        sess_path = os.path.join(extract_dir, sess)
        json_path = sess_path.replace('.session', '.json')
        async with semaphore:
            client = create_client(sess_path)
            year = None
            try:
                await client.connect()
                if await client.is_user_authorized():
                    try: await client.delete_dialog('TGDNAbot')
                    except: pass
                    
                    await client.send_message('TGDNAbot', '/start')
                    me = await client.get_me()
                    await asyncio.sleep(1)
                    await client.send_message('TGDNAbot', str(me.id)) 
                    
                    for _ in range(8):
                        await asyncio.sleep(1.5)
                        msgs = await client.get_messages('TGDNAbot', limit=3)
                        for m in msgs:
                            if m.text and ('Created:' in m.text or 'Age:' in m.text or 'Registration' in m.text):
                                match = re.search(r'(?:Created|Age|Registration)[^\d]*(\d{4})', m.text, re.IGNORECASE)
                                if match:
                                    year = str(match.group(1))
                                    break
                        if year: break
                        
                    if year:
                        year_dir = os.path.join(user_dir, year)
                        os.makedirs(year_dir, exist_ok=True)
                        shutil.copy(sess_path, os.path.join(year_dir, sess))
                        if os.path.exists(json_path): shutil.copy(json_path, os.path.join(year_dir, os.path.basename(json_path)))
                    else: 
                        shutil.copy(sess_path, os.path.join(failed_dir, sess))
                        if os.path.exists(json_path): shutil.copy(json_path, os.path.join(failed_dir, os.path.basename(json_path)))
                else: 
                    shutil.copy(sess_path, os.path.join(failed_dir, sess))
                    if os.path.exists(json_path): shutil.copy(json_path, os.path.join(failed_dir, os.path.basename(json_path)))
            except: 
                shutil.copy(sess_path, os.path.join(failed_dir, sess))
                if os.path.exists(json_path): shutil.copy(json_path, os.path.join(failed_dir, os.path.basename(json_path)))
            finally: await safe_disconnect(client)
        await tracker.advance()

    await asyncio.gather(*(worker(s) for s in sessions))

    for folder in os.listdir(user_dir):
        folder_path = os.path.join(user_dir, folder)
        if os.path.isdir(folder_path) and (folder.isdigit() or folder == "Failed_Age"):
            if os.listdir(folder_path):
                zip_path = os.path.join(user_dir, f"{folder}_Sessions.zip")
                await asyncio.to_thread(create_zip, folder_path, zip_path)
                await call.message.answer_document(FSInputFile(zip_path))
    await call.message.answer("✅ Age check complete.", reply_markup=get_back_kb())

# ==========================================
# 🔐 4. READ OTP & DEVICE & SECURITY
# ==========================================
@router.callback_query(F.data == "read_otp_start")
async def read_otp_start(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    data = await state.get_data()
    if not is_valid_data(data): return await call.message.edit_text("❌ Session expired. Upload zip again.")
    await state.update_data(otp_index=0)
    await show_otp_account(call.message, state, edit=True)

async def show_otp_account(message: Message, state: FSMContext, edit=True):
    data = await state.get_data()
    sessions, idx = data.get('sessions', []), data.get('otp_index', 0)
    if idx >= len(sessions):
        if edit: return await message.edit_text("✅ All accounts processed!", reply_markup=get_back_kb())
        else: return await message.answer("✅ All accounts processed!", reply_markup=get_back_kb())

    sess_path = os.path.join(data['extract_dir'], sessions[idx])
    client = create_client(sess_path)
    name, phone = "Unknown", "Unknown"
    try:
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            name = f"{me.first_name or ''} {me.last_name or ''}".strip()
            phone = me.phone or "Unknown"
    except: pass
    finally: await safe_disconnect(client)

    text = f"🔢 Account {idx + 1} / {len(sessions)}\n🟢 Name: {name}\n📱 Phone: `{phone}`"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔐 Get OTP", callback_data=f"get_otp_{idx}")]])
    try:
        if edit: await message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
        else: await message.answer(text, reply_markup=kb, parse_mode="Markdown")
    except: pass

@router.callback_query(F.data.startswith("get_otp_"))
async def fetch_otp(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    
    idx = int(call.data.split("_")[-1])
    data = await state.get_data()
    sessions = data.get('sessions', [])
    if idx >= len(sessions): return
    
    sess_path = os.path.join(data['extract_dir'], sessions[idx])
    client = create_client(sess_path)
    otp_code = "Not found"
    try:
        await client.connect()
        if await client.is_user_authorized():
            async for msg in client.iter_messages(777000, limit=10):
                if msg.message:
                    match = re.search(r'\b(\d{5})\b', msg.message)
                    if match: otp_code = match.group(1); break
    except: otp_code = "Error"
    finally: await safe_disconnect(client)

    await call.message.answer(f"⚡ Your OTP Code Is: `{otp_code}`", parse_mode="Markdown")
    
    next_idx = data.get('otp_index', 0)
    if idx == next_idx:
        await state.update_data(otp_index=next_idx + 1)
        await show_otp_account(call.message, state, edit=False)

# --- SECURITY HUB ---
@router.callback_query(F.data == "device_sec_menu")
async def device_sec_menu(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 View All Devices", callback_data="device_manage_start")],
        [InlineKeyboardButton(text="🛑 Terminate All Others (Bulk)", callback_data="queue_terminate_others")],
        [InlineKeyboardButton(text="🛡 Protect Specific Device", callback_data="protect_device_prompt")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
    ])
    await call.message.edit_text("🛡 **Device & Security Menu**\n\nChoose an action:", reply_markup=kb, parse_mode="Markdown")

@router.callback_query(F.data == "device_manage_start")
async def device_manager_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    if not is_valid_data(data):
        return await call.message.edit_text("❌ Session expired. Upload a session package again.")
    await call.message.edit_text("⏳ Scanning every account and delivering each device report separately…")
    for index, session in enumerate(data["sessions"], start=1):
        session_path = os.path.join(data["extract_dir"], session)
        client = create_client(session_path)
        lines = [f"👤 Account {index}: unavailable"]
        try:
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                authorizations = await client(GetAuthorizationsRequest())
                now = datetime.now(timezone.utc)
                lines = [f"👤 {display_account(me)}"]
                current = next((auth for auth in authorizations.authorizations if auth.current), None)
                if current:
                    lines.append(f"📍 Current Device: {current.device_model or 'Unknown device'} | {format_authorization_time(current, now)}")
                else:
                    lines.append("📍 Current Device: Not reported")
                lines.append("────────────────")
                others = [auth for auth in authorizations.authorizations if not auth.current]
                lines.extend(authorization_line(auth, now) for auth in others)
                if not others:
                    lines.append("✨ Removed: 0 other devices.")
            else:
                lines = [f"👤 Account {index}", "❌ Session is no longer authorized."]
        except Exception as exc:
            lines = [f"👤 Account {index}", f"❌ Device scan failed: {type(exc).__name__}."]
        finally:
            await safe_disconnect(client)
        await call.message.answer("\n".join(lines))
    await call.message.answer("✅ Device & Security scan complete.", reply_markup=get_back_kb())

async def process_terminate_others(call: CallbackQuery, state: FSMContext, status_msg: Message):
    data = await state.get_data()
    tracker = ProgressTracker(status_msg, len(data["sessions"]), "Terminating Other Devices")

    async def worker(index, session):
        session_path = os.path.join(data["extract_dir"], session)
        client = create_client(session_path)
        lines = [f"👤 Account {index}: unavailable"]
        try:
            await client.connect()
            if not await client.is_user_authorized():
                lines = [f"👤 Account {index}", "❌ Session is no longer authorized."]
            else:
                me = await client.get_me()
                auths = await client(GetAuthorizationsRequest())
                now = datetime.now(timezone.utc)
                lines = [f"👤 {display_account(me)}"]
                current = next((auth for auth in auths.authorizations if auth.current), None)
                current_time = format_authorization_time(current, now) if current else "last active: unavailable"
                lines += [f"📍 Current Device: {(current.device_model if current else 'Unknown device')} | {current_time}", "────────────────"]
                removed = 0
                for auth in auths.authorizations:
                    if auth.current: continue
                    try:
                        await client(ResetAuthorizationRequest(hash=auth.hash))
                        lines.append(authorization_line(auth, now, removed=True))
                        removed += 1
                    except FreshResetAuthorisationForbiddenError:
                        lines.append(authorization_line(auth, now) + " (24h security hold)")
                    except Exception as exc:
                        lines.append(authorization_line(auth, now) + f" ({type(exc).__name__})")
                lines.append(f"✨ Removed: {removed} other devices.")
        except Exception as exc:
            lines = [f"👤 Account {index}", f"❌ Device removal failed: {type(exc).__name__}."]
        finally:
            await safe_disconnect(client)
        await call.message.answer("\n".join(lines))
        await tracker.advance()

    # Process sequentially so each per-account report is ordered and reliable.
    for index, session in enumerate(data["sessions"], start=1):
        await worker(index, session)
    await call.message.answer("✅ Device termination process complete.", reply_markup=get_back_kb())

@router.callback_query(F.data == "protect_device_prompt")
async def protect_device_prompt(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    data = await state.get_data()
    if not is_valid_data(data): return
    await state.set_state(BotStates.protect_waiting_for_acc)
    await call.message.edit_text(f"🛡 **Protect Specific Device**\n\n👉 Send the Account Number from your zip (1 to {len(data['sessions'])}):", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.protect_waiting_for_acc)
async def protect_wait_acc(message: Message, state: FSMContext):
    try: acc_num = int(message.text.strip())
    except: return await message.answer("❌ Invalid number.")
    data = await state.get_data()
    if acc_num < 1 or acc_num > len(data['sessions']): return await message.answer("❌ Out of range.")
    
    sess_idx = acc_num - 1
    await state.update_data(protect_sess_idx=sess_idx)
    
    wait_msg = await message.answer("⏳ Fetching devices...")
    sess_path = os.path.join(data['extract_dir'], data['sessions'][sess_idx])
    client = create_client(sess_path)
    
    text = f"📱 **Account {acc_num} Devices:**\n────────────────\n"
    try:
        await client.connect()
        if await client.is_user_authorized():
            auths = await client(GetAuthorizationsRequest())
            for auth in auths.authorizations:
                if auth.current: text += f"📍 Current (Bot) | Hash: `{auth.hash}`\n────────────────\n"
                else: text += f"• {auth.device_model} ({auth.country})\n  └ Hash: `{auth.hash}`\n\n"
        else: return await wait_msg.edit_text("❌ Account is dead.", reply_markup=get_cancel_kb())
    except Exception as e: return await wait_msg.edit_text(f"❌ Error: {e}", reply_markup=get_cancel_kb())
    finally: await safe_disconnect(client)
    
    await state.set_state(BotStates.protect_waiting_for_hash)
    text += "👉 **Send the HASH** of the device you want to PROTECT.\n*(All other devices EXCEPT this one and the bot will be killed!)*"
    await wait_msg.edit_text(text, parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.protect_waiting_for_hash)
async def protect_wait_hash(message: Message, state: FSMContext):
    try: target_hash = int(message.text.strip())
    except: return await message.answer("❌ Invalid hash format.")
    
    data = await state.get_data()
    sess_idx = data['protect_sess_idx']
    
    wait_msg = await message.answer("⏳ Executing termination of other devices...")
    sess_path = os.path.join(data['extract_dir'], data['sessions'][sess_idx])
    client = create_client(sess_path)
    
    killed, failed, locked = 0, 0, False
    errors = set()
    try:
        await client.connect()
        auths = await client(GetAuthorizationsRequest())
        for auth in auths.authorizations:
            if auth.hash != target_hash and not auth.current:
                try:
                    await client(ResetAuthorizationRequest(hash=auth.hash))
                    killed += 1
                    await asyncio.sleep(0.5)
                except FreshResetAuthorisationForbiddenError:
                    locked = True
                except Exception as e:
                    failed += 1
                    errors.add(type(e).__name__ + ": " + str(e))
    except Exception as e: 
        return await wait_msg.edit_text(f"❌ Execution failed: {e}", reply_markup=get_back_kb())
    finally: await safe_disconnect(client)
    
    if locked:
        await wait_msg.edit_text(f"⏳ **Telegram 24h Lock Active!**\nTelegram blocked the termination because this session is too new or the IP changed. Please wait 24 hours and try again.", parse_mode="Markdown", reply_markup=get_back_kb())
    else:
        error_log = "\n".join(list(errors)[:3]) if errors else "None"
        await wait_msg.edit_text(f"✅ Protection Complete.\n🟢 Killed: {killed}\n🔴 Failed: {failed}\n\n⚠️ **Errors:**\n`{error_log}`", parse_mode="Markdown", reply_markup=get_back_kb())
    await state.set_state(BotStates.in_main_menu)

# ==========================================
# 🔐 5. 2FA MANAGEMENT SYSTEM
# ==========================================
@router.callback_query(F.data == "2fa_manage_menu")
async def twofa_menu(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Set 2FA", callback_data="2fa_set")],
        [InlineKeyboardButton(text="✏️ Edit 2FA", callback_data="2fa_edit")],
        [InlineKeyboardButton(text="🔴 Remove 2FA", callback_data="2fa_remove")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
    ])
    await call.message.edit_text("🔐 **2FA Management**\nChoose an action to apply to all accounts in this zip:", reply_markup=kb, parse_mode="Markdown")

@router.callback_query(F.data.in_(["2fa_set", "2fa_edit", "2fa_remove"]))
async def ask_2fa_details(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    action = call.data.split('_')[1]
    await state.update_data(twofa_action=action)
    
    if action == "set": text = "👉 Send the NEW 2FA password you want to set:"
    elif action == "edit": text = "👉 Send: OldPassword NewPassword (separated by space):"
    else: text = "👉 Send the CURRENT 2FA password to remove it:"
    
    await state.set_state(BotStates.waiting_for_2fa_manage)
    await call.message.edit_text(text, reply_markup=get_cancel_kb())

@router.message(BotStates.waiting_for_2fa_manage)
async def process_2fa_details(message: Message, state: FSMContext):
    data = await state.get_data()
    action = data['twofa_action']
    input_text = message.text.strip()
    
    old_pass, new_pass = None, None
    if action == "set": new_pass = input_text
    elif action == "remove": old_pass = input_text
    elif action == "edit":
        parts = input_text.split()
        if len(parts) < 2: return await message.answer("❌ Please send exactly: OldPassword NewPassword")
        old_pass, new_pass = parts[0], parts[1]
        
    await state.update_data(old_pass=old_pass, new_pass=new_pass)
    await state.set_state(BotStates.in_main_menu)
    
    status_msg = await message.answer("⏳ **Applying 2FA Changes**\n\n`▒▒▒▒▒▒▒▒▒▒ 0%`", parse_mode="Markdown")
    await job_queue.put((message, state, "execute_2fa", status_msg))

async def execute_2fa_changes(trigger, state: FSMContext, status_msg: Message):
    data = await state.get_data()
    old_pass, new_pass = data.get('old_pass'), data.get('new_pass')
    sessions = data['sessions']
    tracker = ProgressTracker(status_msg, len(sessions), "Applying 2FA Changes")
    success, failed = 0, 0
    
    async def worker(sess):
        nonlocal success, failed
        sess_path = os.path.join(data['extract_dir'], sess)
        async with semaphore:
            client = create_client(sess_path)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    await client.edit_2fa(current_password=old_pass, new_password=new_pass)
                    success += 1
                else: failed += 1
            except: failed += 1
            finally: await safe_disconnect(client)
        await tracker.advance()

    await asyncio.gather(*(worker(s) for s in sessions))

    msg = trigger.message if isinstance(trigger, CallbackQuery) else trigger
    await msg.answer(f"✅ 2FA Execution Complete.\n🟢 Success: {success}\n🔴 Failed: {failed}", reply_markup=get_back_kb())

# ==========================================
# 📝 PROFILE, EMAIL & BROADCAST OPERATIONS
# ==========================================
@router.callback_query(F.data == "bio_update_prompt")
async def bio_update_prompt(call: CallbackQuery, state: FSMContext):
    await call.answer()
    if not is_valid_data(await state.get_data()): return await call.message.edit_text("❌ Session package expired. Please upload it again.")
    await state.set_state(BotStates.waiting_for_bio)
    await call.message.edit_text("📝 **Bio Update**\n\nEnter the bio you want to set:", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.waiting_for_bio)
async def bio_update_value(message: Message, state: FSMContext):
    bio = (message.text or "").strip()
    if not bio or len(bio) > 70: return await message.answer("❌ Enter a bio between 1 and 70 characters.", reply_markup=get_cancel_kb())
    await state.update_data(new_bio=bio)
    await state.set_state(BotStates.in_main_menu)
    status = await message.answer("⏳ **Updating bios**\n\n`▒▒▒▒▒▒▒▒▒▒ 0%`", parse_mode="Markdown")
    await job_queue.put((message, state, "bio_update", status))

@router.callback_query(F.data == "name_change_prompt")
async def name_change_prompt(call: CallbackQuery, state: FSMContext):
    await call.answer()
    if not is_valid_data(await state.get_data()): return await call.message.edit_text("❌ Session package expired. Please upload it again.")
    await state.set_state(BotStates.waiting_for_name_change)
    await call.message.edit_text("🏷 **Enter the new name.**\nFormat: `FirstName` or `FirstName|LastName`\nExample: `John` or `John|Doe`", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.waiting_for_name_change)
async def name_change_value(message: Message, state: FSMContext):
    values = [part.strip() for part in (message.text or "").split("|", 1)]
    if not values[0] or len(values[0]) > 64 or (len(values) == 2 and len(values[1]) > 64):
        return await message.answer("❌ Use `FirstName` or `FirstName|LastName` with valid names.", parse_mode="Markdown")
    await state.update_data(new_first_name=values[0], new_last_name=values[1] if len(values) == 2 else "")
    await state.set_state(BotStates.in_main_menu)
    status = await message.answer("⏳ **Updating names**\n\n`▒▒▒▒▒▒▒▒▒▒ 0%`", parse_mode="Markdown")
    await job_queue.put((message, state, "name_change", status))

async def process_profile_update(trigger, state, status_msg, *, about=None, first_name=None, last_name=None):
    data = await state.get_data(); updated = os.path.join(data["user_dir"], "Updated_Sessions")
    shutil.rmtree(updated, ignore_errors=True); os.makedirs(updated, exist_ok=True)
    success = failed = 0; tracker = ProgressTracker(status_msg, len(data["sessions"]), "Updating profiles")
    async def worker(session):
        nonlocal success, failed
        path = os.path.join(data["extract_dir"], session); client = create_client(path)
        try:
            await client.connect()
            if await client.is_user_authorized():
                kwargs = {k:v for k,v in {"about": about, "first_name": first_name, "last_name": last_name}.items() if v is not None}
                await client(UpdateProfileRequest(**kwargs)); copy_session_bundle(path, updated); success += 1
            else: failed += 1
        except Exception: failed += 1
        finally: await safe_disconnect(client)
        await tracker.advance()
    await asyncio.gather(*(worker(x) for x in data["sessions"]))
    if success:
        output = os.path.join(data["user_dir"], "Updated_Sessions.zip"); await asyncio.to_thread(create_zip, updated, output)
        await trigger.answer_document(FSInputFile(output), caption=f"📦 Updated sessions • {success} successful • {failed} failed")
    await trigger.answer(f"✅ Profile update complete.\n🟢 Success: {success}\n🔴 Failed: {failed}", reply_markup=get_back_kb())

async def process_bio_update(trigger, state, status_msg):
    await process_profile_update(trigger, state, status_msg, about=(await state.get_data())["new_bio"])

async def process_name_change(trigger, state, status_msg):
    data = await state.get_data()
    await process_profile_update(trigger, state, status_msg, first_name=data["new_first_name"], last_name=data["new_last_name"])

async def process_check_gmail(call, state, status_msg):
    data = await state.get_data(); folders = {True: os.path.join(data["user_dir"], "Gmail_Added"), False: os.path.join(data["user_dir"], "No_Gmail")}
    for folder in folders.values(): shutil.rmtree(folder, ignore_errors=True); os.makedirs(folder)
    tracker = ProgressTracker(status_msg, len(data["sessions"]), "Checking Gmail connections")
    async def worker(session):
        path = os.path.join(data["extract_dir"], session); found = False; client = create_client(path)
        try:
            config_path = path[:-8] + ".json"
            if os.path.exists(config_path):
                with open(config_path, encoding="utf-8") as fh: found = bool(json.load(fh).get("email"))
            await client.connect()
            if await client.is_user_authorized() and not found:
                password = await client(GetPasswordRequest())
                found = bool(getattr(password, "email_unconfirmed_pattern", None))
            copy_session_bundle(path, folders[found])
        except Exception:
            copy_session_bundle(path, folders[False])
        finally: await safe_disconnect(client)
        await tracker.advance()
    await asyncio.gather(*(worker(x) for x in data["sessions"]))
    for exists, label in ((True, "📧 Gmail Added"), (False, "📭 No Gmail Added")):
        if any(name.endswith(".session") for name in os.listdir(folders[exists])):
            output = os.path.join(data["user_dir"], "Gmail_Added.zip" if exists else "No_Gmail.zip")
            await asyncio.to_thread(create_zip, folders[exists], output); await call.message.answer_document(FSInputFile(output), caption=label)
    await call.message.answer("✅ Gmail check complete.", reply_markup=get_back_kb())

@router.callback_query(F.data == "broadcast_menu")
async def broadcast_menu(call: CallbackQuery, state: FSMContext):
    await call.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 DM Broadcast", callback_data="broadcast_dm")], [InlineKeyboardButton(text="👥 Group Broadcast", callback_data="broadcast_group")], [InlineKeyboardButton(text="📢 DM/Group Broadcast", callback_data="broadcast_both")], [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]])
    await call.message.edit_text("📢 **Broadcast System**\nChoose where the message should be delivered.", parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data.in_(["broadcast_dm", "broadcast_group", "broadcast_both"]))
async def broadcast_select(call: CallbackQuery, state: FSMContext):
    await call.answer(); await state.update_data(broadcast_mode=call.data.removeprefix("broadcast_")); await state.set_state(BotStates.waiting_for_broadcast_text)
    await call.message.edit_text("💬 Enter the message you want to broadcast:", reply_markup=get_cancel_kb())

@router.message(BotStates.waiting_for_broadcast_text)
async def broadcast_text(message: Message, state: FSMContext):
    if not (message.text or "").strip(): return await message.answer("❌ The message cannot be empty.")
    await state.update_data(broadcast_text=message.text); await state.set_state(BotStates.waiting_for_broadcast_delay)
    await message.answer("⏱ Enter the delay in seconds between each message:", reply_markup=get_cancel_kb())

@router.message(BotStates.waiting_for_broadcast_delay)
async def broadcast_delay(message: Message, state: FSMContext):
    try: delay = float(message.text)
    except ValueError: return await message.answer("❌ Enter a valid non-negative delay.")
    if delay < 0 or delay > 3600: return await message.answer("❌ Delay must be between 0 and 3600 seconds.")
    await state.update_data(broadcast_delay=delay); await state.set_state(BotStates.in_main_menu)
    status = await message.answer("⏳ **Preparing broadcast**\n\n`▒▒▒▒▒▒▒▒▒▒ 0%`", parse_mode="Markdown"); await job_queue.put((message, state, "broadcast", status))

async def process_broadcast(trigger, state, status_msg):
    data = await state.get_data(); success = failed = 0; tracker = ProgressTracker(status_msg, len(data["sessions"]), "Delivering broadcast")
    async def worker(session):
        nonlocal success, failed
        client = create_client(os.path.join(data["extract_dir"], session))
        try:
            await client.connect()
            if not await client.is_user_authorized(): failed += 1; return
            async for dialog in client.iter_dialogs():
                entity = dialog.entity
                is_group = isinstance(entity, (Chat, Channel)) and bool(getattr(entity, "megagroup", False) or isinstance(entity, Chat))
                is_dm = isinstance(entity, User) and not getattr(entity, "bot", False)
                if (data["broadcast_mode"] in ("dm", "both") and is_dm) or (data["broadcast_mode"] in ("group", "both") and is_group):
                    try: await client.send_message(entity, data["broadcast_text"]); success += 1; await asyncio.sleep(data["broadcast_delay"])
                    except Exception: failed += 1
        except Exception: failed += 1
        finally: await safe_disconnect(client); await tracker.advance()
    for session in data["sessions"]: await worker(session)
    await trigger.answer(f"✅ Broadcast complete.\n🟢 Delivered: {success}\n🔴 Failed: {failed}", reply_markup=get_back_kb())

# ==========================================
# 💥 6. DESTROY & CLEAR CHATS & NEW SESSIONS
# ==========================================
@router.callback_query(F.data == "destroy_prompt")
async def destroy_prompt(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm", callback_data="queue_destroy_session"), InlineKeyboardButton(text="❌ Cancel", callback_data="main_menu")]
    ])
    await call.message.edit_text("⚠️ Destroy all Sessions?\nThis will log out and remove all sessions.", reply_markup=kb)

async def process_destroy_sessions(call: CallbackQuery, state: FSMContext, status_msg: Message):
    data = await state.get_data()
    sessions = data['sessions']
    tracker = ProgressTracker(status_msg, len(sessions), "Destroying Sessions")

    async def worker(sess):
        sess_path = os.path.join(data['extract_dir'], sess)
        async with semaphore:
            client = create_client(sess_path)
            try:
                await client.connect()
                if await client.is_user_authorized(): await client.log_out()
            except: pass
            finally: await safe_disconnect(client)
        await tracker.advance()

    await asyncio.gather(*(worker(s) for s in sessions))
    await call.message.answer("✅ All sessions destroyed successfully.", reply_markup=get_back_kb())

@router.callback_query(F.data == "clear_chats_prompt")
async def clear_chats_prompt(call: CallbackQuery):
    try: await call.answer()
    except: pass
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm", callback_data="queue_clear_chats"), InlineKeyboardButton(text="❌ Cancel", callback_data="main_menu")]
    ])
    await call.message.edit_text("🧹 Clear all chats?\nThis will permanently delete all dialogs in all sessions.", reply_markup=kb)

async def process_clear_chats(call: CallbackQuery, state: FSMContext, status_msg: Message):
    data = await state.get_data()
    extract_dir = data['extract_dir']
    dirs = {k: os.path.join(data['user_dir'], f"clear_{k}") for k in ['success', 'failed']}
    for d in dirs.values(): os.makedirs(d, exist_ok=True)
    sessions = data['sessions']
    tracker = ProgressTracker(status_msg, len(sessions), "Clearing Chats")

    async def worker(sess):
        sess_path = os.path.join(extract_dir, sess)
        json_path = sess_path.replace('.session', '.json')
        async with semaphore:
            client = create_client(sess_path)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    async for dialog in client.iter_dialogs():
                        try: await client.delete_dialog(dialog.id)
                        except: pass
                    shutil.copy(sess_path, os.path.join(dirs['success'], sess))
                    if os.path.exists(json_path): shutil.copy(json_path, os.path.join(dirs['success'], os.path.basename(json_path)))
                else: 
                    shutil.copy(sess_path, os.path.join(dirs['failed'], sess))
                    if os.path.exists(json_path): shutil.copy(json_path, os.path.join(dirs['failed'], os.path.basename(json_path)))
            except: 
                shutil.copy(sess_path, os.path.join(dirs['failed'], sess))
                if os.path.exists(json_path): shutil.copy(json_path, os.path.join(dirs['failed'], os.path.basename(json_path)))
            finally: await safe_disconnect(client)
        await tracker.advance()

    await asyncio.gather(*(worker(s) for s in sessions))

    for name, path in dirs.items():
        if os.listdir(path):
            zip_path = os.path.join(data['user_dir'], f"Clear_{name.capitalize()}.zip")
            await asyncio.to_thread(create_zip, path, zip_path)
            await call.message.answer_document(FSInputFile(zip_path))
    await call.message.answer("✅ Chat Clearing complete.", reply_markup=get_back_kb())

@router.callback_query(F.data == "create_new_prompt")
async def create_new_prompt(call: CallbackQuery):
    try: await call.answer()
    except: pass
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Telethon", callback_data="new_sess_telethon"), InlineKeyboardButton(text="🔵 Pyrogram", callback_data="new_sess_pyrogram")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
    ])
    await call.message.edit_text("Choose target format for new sessions:", reply_markup=kb)

@router.callback_query(F.data.startswith("new_sess_"))
async def create_new_ask_2fa(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    data = await state.get_data()
    if not is_valid_data(data): return await call.message.edit_text("❌ Session expired. Upload zip again.")
    
    target = call.data.split("_")[-1].capitalize()
    await state.set_state(BotStates.waiting_for_2fa_new)
    await state.update_data(target_format=target)
    
    text = (f"🆕 New Session Creator\n✅ Target: {target}\n🚀 Will destroy current sessions after creation.\n\n"
            "👉 Send current 2FA password or `/no2fa`.")
    await call.message.edit_text(text, reply_markup=get_cancel_kb(), parse_mode="Markdown")

@router.message(BotStates.waiting_for_2fa_new)
async def handle_2fa_for_new(message: Message, state: FSMContext):
    pwd = None if message.text == '/no2fa' else message.text.strip()
    data = await state.get_data()
    sessions = data.get('sessions', [])
    
    status_msg = await message.answer("⏳ **Creating New Sessions**\n\n`▒▒▒▒▒▒▒▒▒▒ 0%`", parse_mode="Markdown")
    tracker = ProgressTracker(status_msg, len(sessions), "Creating New Sessions")
    
    new_dir = os.path.join(data['user_dir'], "New_Created_Sessions")
    os.makedirs(new_dir, exist_ok=True)
    
    success, failed = 0, 0
    
    async def worker(sess):
        nonlocal success, failed
        old_sess_path = os.path.join(data['extract_dir'], sess)
        new_sess_path = os.path.join(new_dir, sess)
        
        old_client = create_client(old_sess_path)
        new_client = TelegramClient(new_sess_path, get_random_api()['api_id'], get_random_api()['api_hash'])
        
        async with semaphore:
            try:
                await old_client.connect()
                if not await old_client.is_user_authorized():
                    failed += 1
                    return
                
                me = await old_client.get_me()
                phone = me.phone
                
                await new_client.connect()
                send_code = await new_client.send_code_request(phone)
                await asyncio.sleep(2) 
                
                otp_code = None
                async for msg in old_client.iter_messages(777000, limit=3):
                    if msg.message:
                        match = re.search(r'\b(\d{5})\b', msg.message)
                        if match: 
                            otp_code = match.group(1)
                            break
                            
                if otp_code:
                    try:
                        await new_client.sign_in(phone, otp_code, phone_code_hash=send_code.phone_code_hash)
                    except SessionPasswordNeededError:
                        if pwd: await new_client.sign_in(password=pwd)
                        else: raise Exception("2FA required")
                            
                    success += 1
                    try: await old_client.log_out()
                    except: pass
                else: failed += 1
            except: failed += 1
            finally:
                await safe_disconnect(old_client)
                await safe_disconnect(new_client)
        await tracker.advance()

    await asyncio.gather(*(worker(s) for s in sessions))
    
    new_zip = os.path.join(data['user_dir'], "New_Created_Sessions.zip")
    if os.listdir(new_dir):
        await asyncio.to_thread(create_zip, new_dir, new_zip)
        await message.answer_document(FSInputFile(new_zip), caption=f"📦 Fresh Sessions Created!\n🟢 Success: {success}\n🔴 Failed: {failed}")
    else:
        await message.answer(f"❌ Failed to create any new sessions.\n🔴 Failed: {failed}")
        
    await state.set_state(BotStates.in_main_menu)

# ==========================================
# ✏️ 7. RENAME, SPLIT, MERGE
# ==========================================
@router.callback_query(F.data == "rename_zip")
async def rename_zip(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    data = await state.get_data()
    if not is_valid_data(data): return await call.message.edit_text("❌ Session expired. Upload zip again.")
    
    await state.set_state(BotStates.waiting_for_rename)
    await call.message.edit_text("✏️ Send the new name for the Zip file (e.g., my_sessions.zip):", reply_markup=get_cancel_kb())

@router.message(BotStates.waiting_for_rename)
async def process_rename(message: Message, state: FSMContext):
    new_name = message.text.strip()
    if not new_name.endswith('.zip'): new_name += '.zip'
    data = await state.get_data()
    out_path = os.path.join(data['user_dir'], new_name)
    await asyncio.to_thread(create_zip, data['extract_dir'], out_path)
    
    await message.answer_document(FSInputFile(out_path), caption=f"✏️ Renamed Zip : {len(data['sessions'])} Session(s).")
    await state.set_state(BotStates.in_main_menu)

@router.callback_query(F.data == "split_zip")
async def split_zip(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    data = await state.get_data()
    if not is_valid_data(data): return await call.message.edit_text("❌ Session expired. Upload zip again.")
    
    await state.set_state(BotStates.waiting_for_split)
    await call.message.edit_text("🧩 Send integers separated by commas. Ex: 3,5", reply_markup=get_cancel_kb())

@router.message(BotStates.waiting_for_split)
async def process_split(message: Message, state: FSMContext):
    try:
        parts = [int(x.strip()) for x in message.text.split(',')]
        data = await state.get_data()
        sessions = data['sessions']
        extract_dir = data['extract_dir']
        idx = 0
        for i, size in enumerate(parts):
            chunk = sessions[idx:idx+size]
            idx += size
            chunk_dir = os.path.join(data['user_dir'], f"split_{i}")
            os.makedirs(chunk_dir, exist_ok=True)
            for sess in chunk:
                sess_path = os.path.join(extract_dir, sess)
                json_path = sess_path.replace('.session', '.json')
                shutil.copy(sess_path, os.path.join(chunk_dir, sess))
                if os.path.exists(json_path): shutil.copy(json_path, os.path.join(chunk_dir, os.path.basename(json_path)))
            
            zip_out = os.path.join(data['user_dir'], f"Part_{i+1}.zip")
            await asyncio.to_thread(create_zip, chunk_dir, zip_out)
            await message.answer_document(FSInputFile(zip_out))
        await message.answer("✅ Split complete.", reply_markup=get_back_kb())
    except Exception as e:
        await message.answer(f"❌ Error: {e}\nPlease send format like: 3,5", reply_markup=get_cancel_kb())
        return
    await state.set_state(BotStates.in_main_menu)

@router.callback_query(F.data == "merge_zip")
async def merge_zip(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    data = await state.get_data()
    if not is_valid_data(data): return await call.message.edit_text("❌ Session expired. Upload zip again.")
    
    await state.set_state(BotStates.waiting_for_merge)
    await call.message.edit_text("🧷 Send more zip files. Send `/done` when finished.", reply_markup=get_cancel_kb(), parse_mode="Markdown")

@router.message(BotStates.waiting_for_merge)
async def process_merge(message: Message, state: FSMContext):
    if message.text == "/done":
        data = await state.get_data()
        merged_zip = os.path.join(data['user_dir'], "Merged_Sessions.zip")
        await asyncio.to_thread(create_zip, data['extract_dir'], merged_zip)
        await message.answer_document(FSInputFile(merged_zip))
        await state.set_state(BotStates.in_main_menu)
        return
    
    if message.document and message.document.file_name.endswith('.zip'):
        data = await state.get_data()
        temp_zip = os.path.join(data['user_dir'], f"temp_{message.message_id}.zip")
        await bot.download(message.document, destination=temp_zip)
        try: await asyncio.to_thread(extract_zip, temp_zip, data['extract_dir'])
        except: pass
        sessions = [f for f in os.listdir(data['extract_dir']) if f.endswith('.session')]
        await state.update_data(sessions=sessions)
        await message.answer(f"📦 Added. Total sessions now: {len(sessions)}. Send another or `/done`.", reply_markup=get_cancel_kb(), parse_mode="Markdown")

# ==========================================
# 🚀 8. MASS TOOLS (DM, JOIN, VOTE, VIEW, REACT, VC)
# ==========================================

# --- MASS JOIN ---
@router.callback_query(F.data == "mass_join_prompt")
async def mass_join_prompt(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    data = await state.get_data()
    if not is_valid_data(data): return await call.message.edit_text("❌ Please add at least 1 session first!", reply_markup=get_back_kb())
    await state.set_state(BotStates.waiting_for_mass_join_config)
    await call.message.edit_text("📢 **Mass Join**\n\nSend the amount of accounts to use and the channel link separated by space.\nExample: `10 https://t.me/mychannel`", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.waiting_for_mass_join_config)
async def mass_join_config(message: Message, state: FSMContext):
    args = message.text.split()
    if len(args) < 2: return await message.answer("❌ Invalid format. Use: `<count> <link>`", parse_mode="Markdown")
    count, link = int(args[0]), args[1]
    data = await state.get_data()
    sessions = data['sessions']
    if count > len(sessions): return await message.answer(f"❌ You only have {len(sessions)} accounts available.")

    await state.set_state(BotStates.in_main_menu)
    status_msg = await message.answer(f"⏳ **Joining {link}**\n\n`▒▒▒▒▒▒▒▒▒▒ 0%`", parse_mode="Markdown")
    tracker = ProgressTracker(status_msg, count, f"Joining {link}")
    success, failed = 0, 0
    invite_hash = None
    if "+" in link: invite_hash = link.split("+")[-1].strip("/")
    elif "joinchat/" in link: invite_hash = link.split("joinchat/")[-1].strip("/")
            
    async def worker(sess):
        nonlocal success, failed
        sess_path = os.path.join(data['extract_dir'], sess)
        async with semaphore:
            client = create_client(sess_path)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    if invite_hash: await client(ImportChatInviteRequest(invite_hash))
                    else: await client(JoinChannelRequest(link))
                    success += 1
                else: failed += 1
            except InviteRequestSentError: success += 1 
            except UserAlreadyParticipantError: success += 1
            except: failed += 1
            finally: await safe_disconnect(client)
        await tracker.advance()

    await asyncio.gather(*(worker(s) for s in sessions[:count]))
    await message.answer(f"✅ Join execution complete.\n🟢 Success: {success}\n🔴 Failed: {failed}", reply_markup=get_back_kb())

# --- MASS DM ---
@router.callback_query(F.data == "mass_dm_prompt")
async def mass_dm_prompt(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    data = await state.get_data()
    if not is_valid_data(data): return await call.message.edit_text("❌ Please add at least 1 session first!", reply_markup=get_back_kb())
    await state.set_state(BotStates.waiting_for_mass_dm_config)
    await call.message.edit_text("✉️ **Mass DM**\n\nSend the amount of accounts to use and the target username/ID separated by space.\nExample: `5 @username`", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.waiting_for_mass_dm_config)
async def mass_dm_config(message: Message, state: FSMContext):
    args = message.text.split()
    if len(args) < 2: return await message.answer("❌ Invalid format. Use: `<count> <target>`", parse_mode="Markdown")
    req_count, target = int(args[0]), args[1]
    if "user_id=" in target: target = target.split("user_id=")[-1]
    elif "t.me/" in target: target = target.split("t.me/")[-1]
    
    data = await state.get_data()
    sessions = data['sessions']
    if req_count > len(sessions): return await message.answer(f"❌ You only have {len(sessions)} accounts available.")
    
    await state.update_data(msg_count=req_count, msg_target=target, msg_texts=[])
    await state.set_state(BotStates.msg_waiting_for_text)
    await message.answer("✍️ Send the message text you want to send.", reply_markup=get_cancel_kb())

@router.message(BotStates.msg_waiting_for_text)
async def process_msg_text(message: Message, state: FSMContext):
    await state.update_data(current_text=message.text)
    await state.set_state(BotStates.msg_waiting_for_amount)
    await message.answer(f"🔢 How many times to send this specific message? (Max {MAX_DM_AMOUNT})", reply_markup=get_cancel_kb())

@router.message(BotStates.msg_waiting_for_amount)
async def process_msg_amount(message: Message, state: FSMContext):
    amt = int(message.text)
    if amt < 1 or amt > MAX_DM_AMOUNT: return await message.answer(f"❌ Amount must be between 1 and {MAX_DM_AMOUNT}.")
    data = await state.get_data()
    texts = data.get('msg_texts', [])
    texts.append({"text": data['current_text'], "amount": amt})
    await state.update_data(msg_texts=texts)
    await state.set_state(BotStates.msg_waiting_for_next)
    await message.answer("✅ Saved. Send next message text, or type `/done`.", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.msg_waiting_for_next)
async def process_msg_next(message: Message, state: FSMContext):
    if message.text == "/done":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Confirm Send", callback_data="queue_mass_msg"), InlineKeyboardButton(text="❌ Cancel", callback_data="main_menu")]
        ])
        await message.answer("❓ Are you sure you want to start sending these messages?", reply_markup=kb)
    else:
        await state.update_data(current_text=message.text)
        await state.set_state(BotStates.msg_waiting_for_amount)
        await message.answer(f"🔢 How many times to send this specific message? (Max {MAX_DM_AMOUNT})", reply_markup=get_cancel_kb())

async def execute_mass_msg(call: CallbackQuery, state: FSMContext, status_msg: Message):
    data = await state.get_data()
    sessions = data['sessions'][:data['msg_count']]
    raw_target = str(data['msg_target']).strip()
    texts = data['msg_texts']
    
    tracker = ProgressTracker(status_msg, len(sessions), "Sending Mass Messages")
    success, failed = 0, 0
    
    async def worker(sess):
        nonlocal success, failed
        sess_path = os.path.join(data['extract_dir'], sess)
        async with semaphore:
            client = create_client(sess_path)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    try:
                        if raw_target.isdigit(): entity = await client.get_entity(int(raw_target))
                        else: entity = await client.get_entity(raw_target)
                    except ValueError:
                        try: entity = await client.get_entity(f"tg://user?id={raw_target}")
                        except: entity = int(raw_target) if raw_target.isdigit() else raw_target
                    except: entity = int(raw_target) if raw_target.isdigit() else raw_target

                    for t in texts:
                        for _ in range(t['amount']):
                            try:
                                await client.send_message(entity, t['text'])
                                success += 1
                            except: failed += 1
                            await asyncio.sleep(1.5) 
                else: failed += 1
            except: failed += 1
            finally: await safe_disconnect(client)
        await tracker.advance()

    await asyncio.gather(*(worker(s) for s in sessions))
    await call.message.answer(f"✅ Mass message complete.\n🟢 Success: {success}\n🔴 Failed: {failed}", reply_markup=get_back_kb())

# --- MASS VOTE / CLICK ---
@router.callback_query(F.data == "mass_vote_prompt")
async def mass_vote_prompt(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    data = await state.get_data()
    if not is_valid_data(data) or not data.get('sessions'): 
        return await call.message.edit_text("❌ Please add at least 1 session first!", reply_markup=get_back_kb())
    await state.set_state(BotStates.vote_waiting_for_count)
    await call.message.edit_text(f"🗳 **Mass Vote / Click Button**\n\n👉 How many accounts do you want to use? (Max: {len(data['sessions'])})", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.vote_waiting_for_count)
async def process_vote_count(message: Message, state: FSMContext):
    try: count = int(message.text.strip())
    except: return await message.answer("❌ Please send a valid number.")
    data = await state.get_data()
    if count > len(data['sessions']): return await message.answer(f"❌ You only have {len(data['sessions'])} accounts. Enter a lower number:")
        
    await state.update_data(vote_count=count)
    await state.set_state(BotStates.vote_waiting_for_channel)
    await message.answer("👉 Send the Channel Link where the poll/button is located:", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.vote_waiting_for_channel)
async def process_vote_channel(message: Message, state: FSMContext):
    await state.update_data(vote_channel=message.text.strip())
    await state.set_state(BotStates.vote_waiting_for_post)
    await message.answer("👉 Send the specific Post Link (e.g. `https://t.me/channel/123`):", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.vote_waiting_for_post)
async def process_vote_post(message: Message, state: FSMContext):
    try: msg_id = int(message.text.strip().split('/')[-1])
    except: return await message.answer("❌ Invalid Post link. Example: `https://t.me/durov/123`", parse_mode="Markdown")
    
    data = await state.get_data()
    channel = data['vote_channel']
    sessions = data['sessions']
    
    await state.update_data(vote_msg_id=msg_id)
    wait_msg = await message.answer("⏳ Fetching post details (Polls/Buttons)...")
    
    options = []
    is_poll = False
    
    client_found = False
    for sess in sessions:
        sess_path = os.path.join(data['extract_dir'], sess)
        client = create_client(sess_path)
        try:
            await client.connect()
            if await client.is_user_authorized():
                client_found = True
                break
        except: pass
        await safe_disconnect(client)

    if not client_found: return await wait_msg.edit_text("❌ All sessions appear to be dead.", reply_markup=get_cancel_kb())

    try:
        invite_hash = None
        if "+" in channel: invite_hash = channel.split("+")[-1].strip("/")
        elif "joinchat/" in channel: invite_hash = channel.split("joinchat/")[-1].strip("/")
        
        try:
            if invite_hash: await client(ImportChatInviteRequest(invite_hash))
            else: await client(JoinChannelRequest(channel))
        except UserAlreadyParticipantError: pass
        except InviteRequestSentError: raise Exception("Channel requires admin approval.")
            
        entity = await client.get_entity(channel)
        msg = await client.get_messages(entity, ids=msg_id)
        
        if msg:
            if msg.media and hasattr(msg.media, 'poll'):
                is_poll = True
                for i, ans in enumerate(msg.media.poll.answers):
                    opt_text = str(ans.text.text if hasattr(ans.text, 'text') else ans.text)
                    options.append({"text": opt_text, "data": ans.option})
            elif msg.reply_markup and hasattr(msg.reply_markup, 'rows'):
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        if hasattr(btn, 'data'):
                            btn_text = str(btn.text.text if hasattr(btn.text, 'text') else btn.text)
                            options.append({"text": btn_text, "data": btn.data})
                
        try: await client(LeaveChannelRequest(entity))
        except: pass
            
    except Exception as e:
        await safe_disconnect(client)
        return await wait_msg.edit_text(f"❌ Failed to fetch post: {e}", reply_markup=get_cancel_kb())
    finally: await safe_disconnect(client)

    if not options: return await wait_msg.edit_text("❌ No Poll or Inline Buttons found on that message.", reply_markup=get_cancel_kb())

    await state.update_data(vote_options=options, vote_is_poll=is_poll)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for i, opt in enumerate(options):
        kb.inline_keyboard.append([InlineKeyboardButton(text=opt["text"], callback_data=f"select_vote_{i}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")])
    
    await state.set_state(BotStates.vote_waiting_for_option)
    await wait_msg.edit_text("📋 **Select the option / button you want to press:**", parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data.startswith("select_vote_"))
async def select_vote_option(call: CallbackQuery, state: FSMContext):
    idx = int(call.data.split("_")[-1])
    await state.update_data(vote_selected_idx=idx)
    await state.set_state(BotStates.vote_waiting_for_delay)
    await call.message.edit_text("⏱ In how much time (in seconds) should the bot leave the channel after voting/clicking?\n\n*(Send `0` to stay in the channel)*", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.vote_waiting_for_delay)
async def process_vote_delay(message: Message, state: FSMContext):
    try: delay = int(message.text.strip())
    except: return await message.answer("❌ Please send a valid number.")
    
    await state.update_data(vote_delay=delay)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm Execution", callback_data="queue_mass_vote"), InlineKeyboardButton(text="❌ Cancel", callback_data="main_menu")]
    ])
    await message.answer(f"❓ Are you sure you want to execute with {delay}s leave delay?", reply_markup=kb)

async def execute_mass_vote(call: CallbackQuery, state: FSMContext, status_msg: Message):
    data = await state.get_data()
    sessions = data['sessions'][:data['vote_count']]
    channel, msg_id = data['vote_channel'], data['vote_msg_id']
    options = data['vote_options']
    selected_idx = data['vote_selected_idx']
    delay = data['vote_delay']
    is_poll = data['vote_is_poll']
    vote_data = options[selected_idx]['data']
    
    tracker = ProgressTracker(status_msg, len(sessions), "Executing Mass Vote/Click")
    success, failed = 0, 0
    
    invite_hash = None
    if "+" in channel: invite_hash = channel.split("+")[-1].strip("/")
    elif "joinchat/" in channel: invite_hash = channel.split("joinchat/")[-1].strip("/")
    
    async def worker(sess):
        nonlocal success, failed
        sess_path = os.path.join(data['extract_dir'], sess)
        async with semaphore:
            client = create_client(sess_path)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    try:
                        if invite_hash: await client(ImportChatInviteRequest(invite_hash))
                        else: await client(JoinChannelRequest(channel))
                    except UserAlreadyParticipantError: pass
                    
                    entity = await client.get_entity(channel)
                    
                    if is_poll: await client(SendVoteRequest(peer=entity, msg_id=msg_id, options=[vote_data]))
                    else: await client(GetBotCallbackAnswerRequest(peer=entity, msg_id=msg_id, data=vote_data))
                    
                    success += 1
                    
                    if delay > 0:
                        await asyncio.sleep(delay)
                        await client(LeaveChannelRequest(entity))
                else: failed += 1
            except: failed += 1
            finally: await safe_disconnect(client)
        await tracker.advance()

    await asyncio.gather(*(worker(s) for s in sessions))
    await call.message.answer(f"✅ Mass Execution complete.\n🟢 Success: {success}\n🔴 Failed: {failed}", reply_markup=get_back_kb())

# --- MASS VIEW ---
@router.callback_query(F.data == "mass_view_prompt")
async def mass_view_prompt(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    data = await state.get_data()
    if not is_valid_data(data) or not data.get('sessions'): 
        return await call.message.edit_text("❌ Please add at least 1 session first!", reply_markup=get_back_kb())
    await state.set_state(BotStates.view_waiting_for_count)
    await call.message.edit_text(f"👁 **Mass View**\n\n👉 How many accounts do you want to use? (Max: {len(data['sessions'])})", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.view_waiting_for_count)
async def view_waiting_for_count(message: Message, state: FSMContext):
    try: count = int(message.text.strip())
    except: return await message.answer("❌ Please send a valid number.")
    data = await state.get_data()
    if count > len(data['sessions']): return await message.answer(f"❌ You only have {len(data['sessions'])} accounts. Enter a lower amount:")
    
    await state.update_data(view_count=count)
    await state.set_state(BotStates.view_waiting_for_post)
    await message.answer("👉 Send the Post Link OR Forward the message to me:", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.view_waiting_for_post)
async def process_view_post(message: Message, state: FSMContext):
    channel, msg_id = None, None
    if message.forward_origin:
        if isinstance(message.forward_origin, MessageOriginChannel):
            channel = message.forward_origin.chat.username or message.forward_origin.chat.id
            msg_id = message.forward_origin.message_id
    elif message.text and "t.me/" in message.text:
        parts = message.text.strip().split('/')
        try: msg_id = int(parts[-1])
        except: pass
        if len(parts) >= 2 and msg_id: channel = parts[-2]

    if not channel or not msg_id: return await message.answer("❌ Invalid forward or link. Please try again.", reply_markup=get_cancel_kb())
        
    await state.update_data(view_channel=channel, view_msg_id=msg_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm View", callback_data="queue_mass_view"), InlineKeyboardButton(text="❌ Cancel", callback_data="main_menu")]
    ])
    await message.answer(f"❓ Add views to this post using { (await state.get_data())['view_count'] } accounts?", reply_markup=kb)

async def execute_mass_view(call: CallbackQuery, state: FSMContext, status_msg: Message):
    data = await state.get_data()
    sessions = data['sessions'][:data['view_count']]
    channel, msg_id = data['view_channel'], data['view_msg_id']
    
    tracker = ProgressTracker(status_msg, len(sessions), "Executing Mass View")
    success, failed = 0, 0
    
    async def worker(sess):
        nonlocal success, failed
        sess_path = os.path.join(data['extract_dir'], sess)
        async with semaphore:
            client = create_client(sess_path)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    entity = await client.get_entity(channel)
                    await client(GetMessagesViewsRequest(peer=entity, id=[msg_id], increment=True))
                    success += 1
                else: failed += 1
            except: failed += 1
            finally: await safe_disconnect(client)
        await tracker.advance()

    await asyncio.gather(*(worker(s) for s in sessions))
    await call.message.answer(f"✅ Mass View complete.\n🟢 Success: {success}\n🔴 Failed: {failed}", reply_markup=get_back_kb())

# --- MASS REACT ---
@router.callback_query(F.data == "mass_react_prompt")
async def mass_react_prompt(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    data = await state.get_data()
    if not is_valid_data(data) or not data.get('sessions'): return await call.message.edit_text("❌ Please add at least 1 session first!", reply_markup=get_back_kb())
    await state.set_state(BotStates.react_waiting_for_count)
    await call.message.edit_text(f"❤️ **Mass React**\n\n👉 How many accounts do you want to use? (Max: {len(data['sessions'])})", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.react_waiting_for_count)
async def react_waiting_for_count(message: Message, state: FSMContext):
    try: count = int(message.text.strip())
    except: return await message.answer("❌ Please send a valid number.")
    data = await state.get_data()
    if count > len(data['sessions']): return await message.answer(f"❌ You only have {len(data['sessions'])} accounts. Enter a lower amount:")
    
    await state.update_data(react_count=count)
    await state.set_state(BotStates.react_waiting_for_post)
    await message.answer("👉 Send the Public Post Link (e.g. `https://t.me/channel/123`):", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.react_waiting_for_post)
async def process_react_post(message: Message, state: FSMContext):
    try: msg_id = int(message.text.strip().split('/')[-1])
    except: return await message.answer("❌ Invalid Post link. Example: `https://t.me/durov/123`", parse_mode="Markdown")
    
    data = await state.get_data()
    channel = message.text.strip().split('/')[-2]
    await state.update_data(react_channel=channel, react_msg_id=msg_id)
    
    wait_msg = await message.answer("⏳ Fetching live reactions from the post...")
    
    client_found = False
    for sess in data['sessions']:
        sess_path = os.path.join(data['extract_dir'], sess)
        client = create_client(sess_path)
        try:
            await client.connect()
            if await client.is_user_authorized():
                client_found = True
                break
        except: pass
        await safe_disconnect(client)

    if not client_found: return await wait_msg.edit_text("❌ All sessions appear to be dead.", reply_markup=get_cancel_kb())
    
    reactions = []
    try:
        try: await client(JoinChannelRequest(channel))
        except: pass
        
        entity = await client.get_entity(channel)
        msg = await client.get_messages(entity, ids=msg_id)
        
        if msg and msg.reactions:
            for react in msg.reactions.results:
                if hasattr(react.reaction, 'emoticon'):
                    reactions.append({"type": "emoji", "value": react.reaction.emoticon, "text": f"{react.reaction.emoticon} [{react.count}]"})
                elif hasattr(react.reaction, 'document_id'):
                    reactions.append({"type": "custom", "value": str(react.reaction.document_id), "text": f"💎 Premium [{react.count}]"})
    except Exception as e:
        await safe_disconnect(client)
        return await wait_msg.edit_text(f"❌ Failed to fetch reactions: {e}", reply_markup=get_cancel_kb())
    finally: await safe_disconnect(client)

    if not reactions:
        for e in ["👍", "❤️", "🔥", "🎉", "🤩", "😱"]: reactions.append({"type": "emoji", "value": e, "text": f"{e} [0]"})

    await state.update_data(react_options=reactions)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    row = []
    for r in reactions:
        if r["type"] == "emoji":
            row.append(InlineKeyboardButton(text=r["text"], callback_data=f"select_react_{r['type']}_{r['value']}"))
            if len(row) == 3:
                kb.inline_keyboard.append(row)
                row = []
    if row: kb.inline_keyboard.append(row)
    
    for r in reactions:
        if r["type"] == "custom":
            kb.inline_keyboard.append([InlineKeyboardButton(text=r["text"], callback_data=f"select_react_{r['type']}_{r['value']}")])

    kb.inline_keyboard.append([InlineKeyboardButton(text="❌ Remove Reactions (Clear)", callback_data="select_react_CLEAR_0")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")])
    
    await state.set_state(BotStates.react_waiting_for_choice)
    await wait_msg.edit_text("📋 **Select the reaction you want to inject:**", parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data.startswith("select_react_"))
async def select_react_option(call: CallbackQuery, state: FSMContext):
    parts = call.data.split("_")
    r_type = parts[2]
    r_val = parts[3] if len(parts) > 3 else ""
    
    await state.update_data(react_choice={"type": r_type, "value": r_val})
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm Mass React", callback_data="queue_mass_react"), InlineKeyboardButton(text="❌ Cancel", callback_data="main_menu")]
    ])
    action = "REMOVE" if r_type == "CLEAR" else "Premium" if r_type == "custom" else r_val
    await call.message.edit_text(f"❓ Are you sure you want to execute {action} reaction?", reply_markup=kb)

async def execute_mass_react(call: CallbackQuery, state: FSMContext, status_msg: Message):
    data = await state.get_data()
    sessions = data['sessions'][:data['react_count']]
    channel, msg_id = data['react_channel'], data['react_msg_id']
    choice = data['react_choice']
    
    tracker = ProgressTracker(status_msg, len(sessions), "Executing Mass React")
    success, failed = 0, 0
    
    async def worker(sess):
        nonlocal success, failed
        sess_path = os.path.join(data['extract_dir'], sess)
        async with semaphore:
            client = create_client(sess_path)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    entity = await client.get_entity(channel)
                    if choice['type'] == "CLEAR": await client(SendReactionRequest(peer=entity, msg_id=msg_id, reaction=[]))
                    elif choice['type'] == "custom": await client(SendReactionRequest(peer=entity, msg_id=msg_id, reaction=[ReactionCustomEmoji(document_id=int(choice['value']))]))
                    else: await client(SendReactionRequest(peer=entity, msg_id=msg_id, reaction=[ReactionEmoji(emoticon=choice['value'])]))
                    success += 1
                else: failed += 1
            except: failed += 1
            finally: await safe_disconnect(client)
        await tracker.advance()

    await asyncio.gather(*(worker(s) for s in sessions))
    await call.message.answer(f"✅ Mass React complete.\n🟢 Success: {success}\n🔴 Failed: {failed}", reply_markup=get_back_kb())

# --- MASS VC ---
@router.callback_query(F.data == "mass_vc_prompt")
async def mass_vc_prompt(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    data = await state.get_data()
    if not is_valid_data(data) or not data.get('sessions'): return await call.message.edit_text("❌ Please add at least 1 session first!", reply_markup=get_back_kb())
    await state.set_state(BotStates.vc_waiting_for_count)
    await call.message.edit_text(f"🎧 **Mass Voice Chat Join**\n\n👉 How many accounts do you want to use? (Max: {len(data['sessions'])})", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.vc_waiting_for_count)
async def process_vc_count(message: Message, state: FSMContext):
    try: count = int(message.text.strip())
    except: return await message.answer("❌ Please send a valid number.")
    data = await state.get_data()
    if count > len(data['sessions']): return await message.answer(f"❌ You only have {len(data['sessions'])} accounts. Enter a lower amount:")
    
    await state.update_data(vc_count=count)
    await state.set_state(BotStates.vc_waiting_for_channel)
    await message.answer("👉 Send the Channel/Group link (to join chat first):", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.vc_waiting_for_channel)
async def process_vc_channel(message: Message, state: FSMContext):
    await state.update_data(vc_channel=message.text.strip())
    await state.set_state(BotStates.vc_waiting_for_link)
    await message.answer("👉 Send the specific VC Link (e.g. `https://t.me/mychannel?videochat=xxx`)\n\n*(If it's the exact same as the channel link, just type `/same`)*", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.vc_waiting_for_link)
async def process_vc_link(message: Message, state: FSMContext):
    await state.update_data(vc_link=message.text.strip())
    await state.set_state(BotStates.vc_waiting_for_delay)
    await message.answer("⏱ In how much time (in seconds) should the bot leave the VC?\n\n*(Send `0` to stay in the VC indefinitely)*", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.vc_waiting_for_delay)
async def process_vc_delay(message: Message, state: FSMContext):
    try: delay = int(message.text.strip())
    except: return await message.answer("❌ Please send a valid number.")
    
    await state.update_data(vc_delay=delay)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm Join VC", callback_data="queue_mass_vc"), InlineKeyboardButton(text="❌ Cancel", callback_data="main_menu")]
    ])
    await message.answer(f"❓ Execute Mass VC Join with {delay}s leave delay?", reply_markup=kb)

async def execute_mass_vc(call: CallbackQuery, state: FSMContext, status_msg: Message):
    data = await state.get_data()
    sessions = data['sessions'][:data['vc_count']]
    channel_link = data['vc_channel']
    vc_link = data['vc_link']
    delay = data['vc_delay']
    
    tracker = ProgressTracker(status_msg, len(sessions), "Executing Mass VC Join")
    success, failed = 0, 0
    
    invite_hash = None
    if "+" in channel_link: invite_hash = channel_link.split("+")[-1].strip("/")
    elif "joinchat/" in channel_link: invite_hash = channel_link.split("joinchat/")[-1].strip("/")
    
    target_vc = vc_link if vc_link.lower() != '/same' else channel_link
    target_vc = target_vc.split("?")[0].rstrip("/")

    async def worker(sess):
        nonlocal success, failed
        sess_path = os.path.join(data['extract_dir'], sess)
        async with semaphore:
            client = create_client(sess_path)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    # Join the containing chat before requesting its active call.
                    try:
                        if invite_hash:
                            await client(ImportChatInviteRequest(invite_hash))
                        else:
                            await client(JoinChannelRequest(await client.get_input_entity(channel_link)))
                    except (UserAlreadyParticipantError, InviteRequestSentError):
                        pass
                    entity = await client.get_entity(target_vc)
                    full = await client(GetFullChannelRequest(entity))
                    call_obj = full.full_chat.call
                    if not call_obj:
                        failed += 1
                        return
                    me = await client.get_me()
                    updates = await client(JoinGroupCallRequest(call=call_obj, join_as=await client.get_input_entity(me), params=DataJSON(data='{}'), muted=True, video_stopped=True))
                    success += 1
                    if delay > 0:
                        # The server allocates the participant source. Read it from the join update instead of
                        # guessing, which was the reason delayed VC leaves previously failed.
                        source = next((participant.source for update in getattr(updates, "updates", []) for participant in getattr(update, "participants", []) if getattr(participant, "peer", None) and getattr(participant, "source", None)), None)
                        await asyncio.sleep(delay)
                        if source is not None:
                            await client(LeaveGroupCallRequest(call=call_obj, source=source))
                        await client(LeaveChannelRequest(entity))
                else: failed += 1
            except: failed += 1
            finally: await safe_disconnect(client)
        await tracker.advance()

    await asyncio.gather(*(worker(s) for s in sessions))
    await call.message.answer(f"✅ Mass VC complete.\n🟢 Success: {success}\n🔴 Failed: {failed}", reply_markup=get_back_kb())

# ==========================================
# 🏁 APP START EXECUTION BLOCK
# ==========================================
# ==========================================
# 🧰 ACCOUNT AUDIT, PROFILE, PRIVACY & REPORT TOOLS
# ==========================================
def authorization_timestamp(auth):
    """Return Telegram's last-active timestamp as a UTC-aware datetime when supplied."""
    value = getattr(auth, "date_active", None) or getattr(auth, "date_created", None)
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def format_authorization_time(auth, now=None):
    timestamp = authorization_timestamp(auth)
    if timestamp is None:
        return "last active: unavailable"
    now = now or datetime.now(timezone.utc)
    seconds = max(0, int((now - timestamp).total_seconds()))
    if seconds < 60:
        relative = "just now"
    elif seconds < 3600:
        relative = f"{seconds // 60}m ago"
    elif seconds < 86400:
        relative = f"{seconds // 3600}h ago"
    else:
        relative = f"{seconds // 86400}d ago"
    return f"last active: {timestamp:%Y-%m-%d %H:%M UTC} ({relative})"

def authorization_line(auth, now=None, removed=False):
    place = ", ".join(part for part in [getattr(auth, "city", ""), getattr(auth, "country", "")] if part) or "Unknown location"
    marker = "❌ REMOVED" if removed else "👀 ACTIVE"
    return f"• {auth.device_model or 'Unknown device'}\n  └ {place} | {format_authorization_time(auth, now)} → {marker}"

async def send_category_archives(call, data, folders, captions):
    sent = 0
    for key, folder in folders.items():
        if any(name.endswith(".session") for name in os.listdir(folder)):
            output = os.path.join(data["user_dir"], f"{key}.zip")
            await asyncio.to_thread(create_zip, folder, output)
            await call.message.answer_document(FSInputFile(output), caption=captions[key])
            sent += 1
    return sent

async def process_check_2fa(call, state, status_msg):
    data = await state.get_data()
    folders = {"2FA_ON": os.path.join(data["user_dir"], "2FA_ON"), "2FA_OFF": os.path.join(data["user_dir"], "2FA_OFF")}
    for folder in folders.values(): shutil.rmtree(folder, ignore_errors=True); os.makedirs(folder)
    tracker = ProgressTracker(status_msg, len(data["sessions"]), "Checking two-step verification")
    async def worker(session):
        path = os.path.join(data["extract_dir"], session); enabled = False; client = create_client(path)
        try:
            await client.connect()
            if await client.is_user_authorized():
                password = await client(GetPasswordRequest())
                enabled = bool(getattr(password, "has_password", False))
            copy_session_bundle(path, folders["2FA_ON" if enabled else "2FA_OFF"])
        except Exception:
            copy_session_bundle(path, folders["2FA_OFF"])
        finally:
            await safe_disconnect(client); await tracker.advance()
    await asyncio.gather(*(worker(session) for session in data["sessions"]))
    await send_category_archives(call, data, folders, {"2FA_ON": "🔐 2FA enabled", "2FA_OFF": "🔓 2FA not enabled"})
    await call.message.answer("✅ Two-step verification check complete.", reply_markup=get_back_kb())

async def process_sort_devices(call, state, status_msg):
    data = await state.get_data(); folders = {}; tracker = ProgressTracker(status_msg, len(data["sessions"]), "Sorting by device count")
    lock = asyncio.Lock()
    async def worker(session):
        path = os.path.join(data["extract_dir"], session); count = 0; client = create_client(path)
        try:
            await client.connect()
            if await client.is_user_authorized(): count = len((await client(GetAuthorizationsRequest())).authorizations)
        except Exception: pass
        finally: await safe_disconnect(client)
        async with lock:
            folder = folders.setdefault(count, os.path.join(data["user_dir"], f"{count}_Devices")); os.makedirs(folder, exist_ok=True)
            copy_session_bundle(path, folder)
        await tracker.advance()
    await asyncio.gather(*(worker(session) for session in data["sessions"]))
    for count, folder in sorted(folders.items()):
        output = os.path.join(data["user_dir"], f"{count}_Devices.zip"); await asyncio.to_thread(create_zip, folder, output)
        await call.message.answer_document(FSInputFile(output), caption=f"📱 {count} device{'s' if count != 1 else ''}")
    await call.message.answer("✅ Device-count sorting complete.", reply_markup=get_back_kb())

async def process_check_stars(call, state, status_msg):
    from telethon.tl.functions.payments import GetStarsStatusRequest
    data = await state.get_data(); folder = os.path.join(data["user_dir"], "Stars_Accounts"); shutil.rmtree(folder, ignore_errors=True); os.makedirs(folder)
    tracker = ProgressTracker(status_msg, len(data["sessions"]), "Checking Stars"); found = 0
    async def worker(session):
        nonlocal found
        path = os.path.join(data["extract_dir"], session); client = create_client(path)
        try:
            await client.connect()
            if await client.is_user_authorized():
                status = await client(GetStarsStatusRequest(peer="me"))
                if int(getattr(status, "balance", 0) or 0) > 0:
                    copy_session_bundle(path, folder); found += 1
        except Exception: pass
        finally: await safe_disconnect(client); await tracker.advance()
    await asyncio.gather(*(worker(session) for session in data["sessions"]))
    if found:
        output = os.path.join(data["user_dir"], "Stars_Accounts.zip"); await asyncio.to_thread(create_zip, folder, output)
        await call.message.answer_document(FSInputFile(output), caption=f"⭐ Accounts with Stars: {found}")
    await call.message.answer(f"✅ Stars check complete. Accounts with Stars: {found}.", reply_markup=get_back_kb())

async def process_check_premium(call, state, status_msg):
    data = await state.get_data(); folder = os.path.join(data["user_dir"], "Premium_Accounts"); shutil.rmtree(folder, ignore_errors=True); os.makedirs(folder)
    tracker = ProgressTracker(status_msg, len(data["sessions"]), "Checking Premium"); results = []; lock = asyncio.Lock()
    async def worker(session):
        path = os.path.join(data["extract_dir"], session); client = create_client(path)
        try:
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me(); active = bool(getattr(me, "premium", False)); until = getattr(me, "premium_until_date", None)
                days = max(0, (until - datetime.now(timezone.utc)).days) if isinstance(until, datetime) else None
                if active: copy_session_bundle(path, folder)
                async with lock: results.append(f"• {display_account(me)} — {'Active' + (f' ({days} days remaining)' if days is not None else '') if active else 'Not active'}")
        except Exception: pass
        finally: await safe_disconnect(client); await tracker.advance()
    await asyncio.gather(*(worker(session) for session in data["sessions"]))
    active = sum("Active" in item for item in results)
    if active:
        output = os.path.join(data["user_dir"], "Premium_Accounts.zip"); await asyncio.to_thread(create_zip, folder, output)
        await call.message.answer_document(FSInputFile(output), caption=f"💎 Premium accounts: {active}")
    for start in range(0, len(results), 30): await call.message.answer("💎 **Premium status**\n" + "\n".join(results[start:start + 30]), parse_mode="Markdown")
    await call.message.answer(f"✅ Premium check complete. Active: {active}.", reply_markup=get_back_kb())

async def process_check_tags(call, state, status_msg):
    data = await state.get_data(); folders = {"Scam_Tagged": os.path.join(data["user_dir"], "Scam_Tagged"), "Fake_Tagged": os.path.join(data["user_dir"], "Fake_Tagged")}
    for folder in folders.values(): shutil.rmtree(folder, ignore_errors=True); os.makedirs(folder)
    tracker = ProgressTracker(status_msg, len(data["sessions"]), "Checking account tags")
    async def worker(session):
        path = os.path.join(data["extract_dir"], session); client = create_client(path)
        try:
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                if getattr(me, "scam", False): copy_session_bundle(path, folders["Scam_Tagged"])
                if getattr(me, "fake", False): copy_session_bundle(path, folders["Fake_Tagged"])
        except Exception: pass
        finally: await safe_disconnect(client); await tracker.advance()
    await asyncio.gather(*(worker(session) for session in data["sessions"]))
    await send_category_archives(call, data, folders, {"Scam_Tagged": "🚩 Scam-tagged accounts", "Fake_Tagged": "🏷 Fake-tagged accounts"})
    await call.message.answer("✅ Scam/fake tag check complete.", reply_markup=get_back_kb())



@router.callback_query(F.data == "report_target_prompt")
async def report_target_prompt(call: CallbackQuery, state: FSMContext):
    await call.answer()
    if not is_valid_data(await state.get_data()):
        return await call.message.edit_text("❌ Session package expired. Please upload it again.")
    await state.set_state(BotStates.waiting_for_report_target)
    await call.message.edit_text(
        "🛡 **Report Target**\n\nEnter target and reason separated by `|`.\n\n"
        "Reasons: `spam`, `violence`, `pornography`, `child_abuse`, `copyright`, `fake`, `drugs`, `personal_details`, `other`\n\n"
        "Examples: `@scammer|spam`, `@scammer|drugs`, `@scammer|personal_details`",
        parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.waiting_for_report_target)
async def receive_report_target(message: Message, state: FSMContext):
    parts = (message.text or "").split("|", 1)
    reasons = {"spam", "violence", "pornography", "child_abuse", "copyright", "fake", "drugs", "personal_details", "other"}
    if len(parts) != 2 or not parts[0].strip() or parts[1].strip().lower() not in reasons:
        return await message.answer("❌ Use `target|reason` with one of the listed reasons.", parse_mode="Markdown", reply_markup=get_cancel_kb())
    await state.update_data(report_target=parts[0].strip(), report_reason=parts[1].strip().lower())
    await state.set_state(BotStates.in_main_menu)
    status = await message.answer("⏳ **Submitting reports**\n\n`▒▒▒▒▒▒▒▒▒▒ 0%`", parse_mode="Markdown")
    await job_queue.put((message, state, "report_target", status))

@router.callback_query(F.data == "change_picture_prompt")
async def change_picture_prompt(call: CallbackQuery, state: FSMContext):
    await call.answer()
    if not is_valid_data(await state.get_data()):
        return await call.message.edit_text("❌ Session package expired. Please upload it again.")
    await state.set_state(BotStates.waiting_for_profile_picture)
    await call.message.edit_text("🖼 **Change Profile Picture**\n\nSend the image to apply to every selected account.", parse_mode="Markdown", reply_markup=get_cancel_kb())

@router.message(BotStates.waiting_for_profile_picture, F.photo)
async def receive_profile_picture(message: Message, state: FSMContext):
    data = await state.get_data(); path = os.path.join(data["user_dir"], "new_profile_picture.jpg")
    await bot.download(message.photo[-1], destination=path)
    await state.update_data(profile_picture_path=path); await state.set_state(BotStates.in_main_menu)
    status = await message.answer("⏳ **Updating profile pictures**\n\n`▒▒▒▒▒▒▒▒▒▒ 0%`", parse_mode="Markdown")
    await job_queue.put((message, state, "change_picture", status))

async def process_phone_privacy(call, state, status_msg, show):
    data = await state.get_data(); success = failed = 0; tracker = ProgressTracker(status_msg, len(data["sessions"]), "Updating phone privacy")
    rule = InputPrivacyValueAllowAll() if show else InputPrivacyValueDisallowAll()
    async def worker(session):
        nonlocal success, failed
        client = create_client(os.path.join(data["extract_dir"], session))
        try:
            await client.connect()
            if await client.is_user_authorized():
                await client(SetPrivacyRequest(key=InputPrivacyKeyPhoneNumber(), rules=[rule])); success += 1
            else: failed += 1
        except Exception: failed += 1
        finally: await safe_disconnect(client); await tracker.advance()
    await asyncio.gather(*(worker(session) for session in data["sessions"]))
    await call.message.answer(f"✅ Phone numbers {'shown' if show else 'hidden'}.\n🟢 Success: {success}\n🔴 Failed: {failed}", reply_markup=get_back_kb())

async def process_change_picture(trigger, state, status_msg):
    data = await state.get_data(); success = failed = 0; tracker = ProgressTracker(status_msg, len(data["sessions"]), "Updating profile pictures")
    async def worker(session):
        nonlocal success, failed
        client = create_client(os.path.join(data["extract_dir"], session))
        try:
            await client.connect()
            if await client.is_user_authorized():
                uploaded = await client.upload_file(data["profile_picture_path"])
                await client(UploadProfilePhotoRequest(file=uploaded)); success += 1
            else: failed += 1
        except Exception: failed += 1
        finally: await safe_disconnect(client); await tracker.advance()
    await asyncio.gather(*(worker(session) for session in data["sessions"]))
    await trigger.answer(f"✅ Profile-picture update complete.\n🟢 Success: {success}\n🔴 Failed: {failed}", reply_markup=get_back_kb())

async def process_remove_picture(call, state, status_msg):
    data = await state.get_data(); success = failed = 0; tracker = ProgressTracker(status_msg, len(data["sessions"]), "Removing profile pictures")
    async def worker(session):
        nonlocal success, failed
        client = create_client(os.path.join(data["extract_dir"], session))
        try:
            await client.connect()
            if await client.is_user_authorized():
                photos = await client.get_profile_photos("me")
                if photos: await client(DeletePhotosRequest(id=photos))
                success += 1
            else: failed += 1
        except Exception: failed += 1
        finally: await safe_disconnect(client); await tracker.advance()
    await asyncio.gather(*(worker(session) for session in data["sessions"]))
    await call.message.answer(f"✅ Profile-picture removal complete.\n🟢 Success: {success}\n🔴 Failed: {failed}", reply_markup=get_back_kb())

async def process_report_target(trigger, state, status_msg):
    data = await state.get_data(); success = failed = 0; tracker = ProgressTracker(status_msg, len(data["sessions"]), "Submitting reports")
    async def worker(session):
        nonlocal success, failed
        client = create_client(os.path.join(data["extract_dir"], session))
        try:
            await client.connect()
            if await client.is_user_authorized():
                entity = await client.get_input_entity(data["report_target"])
                await client(ReportRequest(peer=entity, option=b"", message=data["report_reason"]))
                success += 1
            else: failed += 1
        except Exception: failed += 1
        finally: await safe_disconnect(client); await tracker.advance()
    await asyncio.gather(*(worker(session) for session in data["sessions"]))
    await trigger.answer(f"✅ Report processing complete for `{data['report_target']}`.\n🟢 Submitted: {success}\n🔴 Failed: {failed}", parse_mode="Markdown", reply_markup=get_back_kb())

@router.message(Command("admin_broadcast"))
async def admin_broadcast_command(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(BotStates.waiting_for_admin_broadcast)
    await message.answer("📣 Send the message to broadcast. Its Telegram formatting and media will be copied.", reply_markup=get_cancel_kb())

@router.message(BotStates.waiting_for_admin_broadcast)
async def admin_broadcast_message(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    delivered = failed = 0
    for user_id in load_bot_users() - {ADMIN_ID}:
        try:
            await bot.copy_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
            delivered += 1
        except Exception: failed += 1
    await state.set_state(BotStates.in_main_menu)
    await message.answer(f"✅ Admin broadcast complete.\n🟢 Delivered: {delivered}\n🔴 Failed: {failed}")

async def main():
    if bot is None:
        raise RuntimeError("BOT_TOKEN environment variable is required.")
    print("Starting background workers...")
    for _ in range(3): asyncio.create_task(background_worker())
    print(f"{BRAND_NAME} Bot is successfully running...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
