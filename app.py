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
from telethon.tl.functions.account import GetAuthorizationsRequest, UpdateProfileRequest, ResetAuthorizationRequest
from telethon.tl.functions.auth import ResetAuthorizationsRequest
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest, GetFullChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, SendVoteRequest, GetMessagesViewsRequest, SendReactionRequest, GetBotCallbackAnswerRequest
from telethon.tl.functions.phone import JoinGroupCallRequest, LeaveGroupCallRequest
from telethon.tl.types import ReactionEmoji, ReactionCustomEmoji, DataJSON

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
BOT_TOKEN = "7962465718:AAHQ31pkxtfLwEkRk9fbOdxG50M6yebU50U"

API_CREDENTIALS = [
    {"api_id": 30283245, "api_hash": "4ff403953f3c0d1911cf1b380ac77b90"},
]

BRAND_NAME = "Oggy"
MAX_DM_AMOUNT = 50
AUTO_UPDATE_BIO = f"Purchased From @DeamonOTPBot"

CONCURRENT_CHECKS = 50
semaphore = asyncio.Semaphore(CONCURRENT_CHECKS)
job_queue = asyncio.Queue()

WORK_DIR = "work_dir"
os.makedirs(WORK_DIR, exist_ok=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

active_logins = {}

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
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Check Sessions", callback_data="queue_check_session"), 
         InlineKeyboardButton(text="🛡 Check Spam", callback_data="queue_check_spam")],
        [InlineKeyboardButton(text="📅 Check Age", callback_data="queue_check_age"),
         InlineKeyboardButton(text="🔐 Read OTP", callback_data="read_otp_start")],
        [InlineKeyboardButton(text="💥 Destroy Sessions", callback_data="destroy_prompt"),
         InlineKeyboardButton(text="🧹 Clear Chats", callback_data="clear_chats_prompt")],
        [InlineKeyboardButton(text="🆕 Create New Sessions", callback_data="create_new_prompt"),
         InlineKeyboardButton(text="🔑 2FA Management", callback_data="2fa_manage_menu")],
        [InlineKeyboardButton(text="🛡 Device & Security", callback_data="device_sec_menu")],
        [InlineKeyboardButton(text="✏️ Rename Zip", callback_data="rename_zip"), 
         InlineKeyboardButton(text="🧩 Split Zip", callback_data="split_zip")],
        [InlineKeyboardButton(text="🧷 Merge Zip", callback_data="merge_zip")],
        [InlineKeyboardButton(text="✉️ Mass DM", callback_data="mass_dm_prompt"),
         InlineKeyboardButton(text="📢 Mass Join", callback_data="mass_join_prompt")],
        [InlineKeyboardButton(text="🗳 Mass Vote/Click", callback_data="mass_vote_prompt"),
         InlineKeyboardButton(text="👁 Mass View", callback_data="mass_view_prompt")],
        [InlineKeyboardButton(text="❤️ Mass React", callback_data="mass_react_prompt"),
         InlineKeyboardButton(text="🎧 Mass VC", callback_data="mass_vc_prompt")]
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
    with zipfile.ZipFile(zip_path, 'r') as zip_ref: zip_ref.extractall(extract_to)

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

async def auto_update_bio_task(sessions, extract_dir):
    for sess in sessions:
        sess_path = os.path.join(extract_dir, sess)
        async with semaphore:
            client = create_client(sess_path)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    await client(UpdateProfileRequest(about=AUTO_UPDATE_BIO))
            except Exception: pass
            finally: await safe_disconnect(client)

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
        except Exception as e:
            print(f"Job Error: {e}")
        finally:
            job_queue.task_done()

# ==========================================
# 📱 1. START COMMAND & GLOBAL CANCEL
# ==========================================
@router.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext):
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
            f"*⚡ Tasks:*\n"
            f"└ ♻️ Update: `Running...`\n\n"
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
    if not message.document.file_name.endswith('.zip'): 
        return await message.answer("❌ Please send a valid .zip file.")

    current_state = await state.get_state()
    if current_state == BotStates.waiting_for_merge.state:
        return await process_merge(message, state)

    msg = await message.answer("📥 Downloading and extracting zip...")
    user_dir = os.path.join(WORK_DIR, str(message.from_user.id))
    if os.path.exists(user_dir): shutil.rmtree(user_dir)
    os.makedirs(user_dir, exist_ok=True)

    zip_path = os.path.join(user_dir, "sessions.zip")
    await bot.download(message.document, destination=zip_path)
    
    extract_dir = os.path.join(user_dir, "extracted")
    try: await asyncio.to_thread(extract_zip, zip_path, extract_dir)
    except Exception as e: return await msg.edit_text(f"❌ Failed to extract zip. Corrupted?\nError: {e}")

    # 1. Grab native .sessions
    sessions = [f for f in os.listdir(extract_dir) if f.endswith('.session')]
    
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

    asyncio.create_task(auto_update_bio_task(sessions, extract_dir))

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
        f"*⚡ Background Tasks:*\n"
        f"└ Update: `Running...`\n\n"
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
        "terminate_others": "Terminating Other Devices"
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
        await call.message.answer_document(FSInputFile(zip_path))
    if os.listdir(out_dead):
        zip_path = os.path.join(user_dir, "Dead_Sessions.zip")
        await asyncio.to_thread(create_zip, out_dead, zip_path)
        await call.message.answer_document(FSInputFile(zip_path))
        
    await call.message.answer("✅ Checking complete.", reply_markup=get_back_kb())

async def process_check_spam(call: CallbackQuery, state: FSMContext, status_msg: Message):
    data = await state.get_data()
    extract_dir, user_dir = data['extract_dir'], data['user_dir']
    dirs = {k: os.path.join(user_dir, k) for k in ['Spamfree', 'Spam', 'Failed']}
    for d in dirs.values(): os.makedirs(d, exist_ok=True)

    sessions = data['sessions']
    tracker = ProgressTracker(status_msg, len(sessions), "Checking Spam")

    async def worker(sess):
        sess_path = os.path.join(extract_dir, sess)
        json_path = sess_path.replace('.session', '.json')
        async with semaphore:
            client = create_client(sess_path)
            status = "Failed"
            try:
                await client.connect()
                if await client.is_user_authorized():
                    await client.send_message('@spambot', '/start')
                    for _ in range(8):
                        await asyncio.sleep(0.5)
                        async for msg in client.iter_messages('@spambot', limit=2):
                            if not msg.out and msg.text:
                                if "Good news" in msg.text or "no limits" in msg.text.lower(): status = "Spamfree"
                                else: status = "Spam"
                                break
                        if status != "Failed": break
                shutil.copy(sess_path, os.path.join(dirs[status], sess))
                if os.path.exists(json_path): shutil.copy(json_path, os.path.join(dirs[status], os.path.basename(json_path)))
            except: 
                shutil.copy(sess_path, os.path.join(dirs['Failed'], sess))
                if os.path.exists(json_path): shutil.copy(json_path, os.path.join(dirs['Failed'], os.path.basename(json_path)))
            finally: await safe_disconnect(client)
        await tracker.advance()

    await asyncio.gather(*(worker(s) for s in sessions))

    for name, path in dirs.items():
        if os.listdir(path):
            zip_path = os.path.join(user_dir, f"{name}_Sessions.zip")
            await asyncio.to_thread(create_zip, path, zip_path)
            await call.message.answer_document(FSInputFile(zip_path))
    await call.message.answer("✅ Spam check complete.", reply_markup=get_back_kb())

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
    try: await call.answer()
    except: pass
    data = await state.get_data()
    if not is_valid_data(data): return await call.message.edit_text("❌ Session expired. Upload zip again.")
    await state.update_data(device_idx=0)
    await show_device_page(call.message, state, edit=True)

async def show_device_page(message: Message, state: FSMContext, edit=True):
    data = await state.get_data()
    sessions = data['sessions']
    idx = data.get('device_idx', 0)
    limit = 5 
    
    if idx >= len(sessions): return await message.edit_text("✅ End of device list.", reply_markup=get_back_kb())

    page_sessions = sessions[idx:idx+limit]
    result_text = ""
    if edit: 
        try: await message.edit_text("⏳ Compiling device data for next page...")
        except: pass
    
    for i, sess in enumerate(page_sessions):
        actual_acc_num = idx + i + 1
        sess_path = os.path.join(data['extract_dir'], sess)
        client = create_client(sess_path)
        acc_info = f"📱 **Account {actual_acc_num} / {len(sessions)}**\n────────────────\n"
        try:
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                auths = await client(GetAuthorizationsRequest())
                acc_info += f"👤 {me.first_name} (+`{me.phone}`)\n\n"
                now = datetime.now(timezone.utc)
                for auth in auths.authorizations:
                    diff_hours = (now - auth.date_active).total_seconds() / 3600
                    if auth.current: 
                        acc_info += f"📍 Current Device: {auth.device_model} | Hash: `{auth.hash}`\n────────────────\n"
                    else: 
                        acc_info += f"• {auth.device_model}\n  └ {auth.country} | Hash: `{auth.hash}` | {diff_hours:.1f}h -> 👀 DETECTED\n"
            else: acc_info += "❌ Session is dead.\n"
        except: acc_info += f"❌ Error\n"
        finally: await safe_disconnect(client)
        result_text += acc_info + "\n"

    btns = []
    if idx + limit < len(sessions): btns.append([InlineKeyboardButton(text="⏭ Next Page", callback_data="device_next_page")])
    btns.append([InlineKeyboardButton(text="🔙 Back", callback_data="device_sec_menu")])
    
    try:
        if edit: await message.edit_text(result_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns), parse_mode="Markdown")
        else: await message.answer(result_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns), parse_mode="Markdown")
    except: pass

@router.callback_query(F.data == "device_next_page")
async def device_next_page(call: CallbackQuery, state: FSMContext):
    try: await call.answer()
    except: pass
    data = await state.get_data()
    await state.update_data(device_idx=data.get('device_idx', 0) + 5)
    await show_device_page(call.message, state, edit=True)

async def process_terminate_others(call: CallbackQuery, state: FSMContext, status_msg: Message):
    data = await state.get_data()
    sessions = data['sessions']
    tracker = ProgressTracker(status_msg, len(sessions), "Terminating Other Devices")
    success, failed, locked_24h = 0, 0, 0
    errors = set()
    
    async def worker(sess):
        nonlocal success, failed, locked_24h
        sess_path = os.path.join(data['extract_dir'], sess)
        async with semaphore:
            client = create_client(sess_path)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    await client(ResetAuthorizationsRequest())
                    success += 1
                else: 
                    failed += 1
                    errors.add("Account is Dead")
            except FreshResetAuthorisationForbiddenError:
                locked_24h += 1
            except Exception as e:
                failed += 1
                errors.add(type(e).__name__ + ": " + str(e))
            finally: await safe_disconnect(client)
        await tracker.advance()

    await asyncio.gather(*(worker(s) for s in sessions))
    
    error_log = "\n".join(list(errors)[:3]) if errors else "None"
    if locked_24h > 0:
        await call.message.answer(f"✅ Bulk Termination Attempted.\n🟢 Success: {success}\n⏳ **Locked (24h Rule): {locked_24h}**\n🔴 Failed: {failed}\n\n⚠️ *Telegram blocked {locked_24h} account(s) because they are too new. You must wait 24 hours from login to terminate others.*", parse_mode="Markdown", reply_markup=get_back_kb())
    else:
        await call.message.answer(f"✅ Bulk Termination Complete.\n🟢 Success: {success}\n🔴 Failed: {failed}\n\n⚠️ **Errors:**\n`{error_log}`", parse_mode="Markdown", reply_markup=get_back_kb())

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
    target_vc = target_vc.split("?")[0]

    async def worker(sess):
        nonlocal success, failed
        sess_path = os.path.join(data['extract_dir'], sess)
        async with semaphore:
            client = create_client(sess_path)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    # 1. Join Chat first
                    try:
                        if invite_hash: await client(ImportChatInviteRequest(invite_hash))
                        else: await client(JoinChannelRequest(channel_link))
                    except UserAlreadyParticipantError: pass
                    
                    # 2. Get Call Object
                    entity = await client.get_entity(target_vc)
                    full = await client(GetFullChannelRequest(entity))
                    call_obj = full.full_chat.call
                    
                    if call_obj:
                        me = await client.get_me()
                        await client(JoinGroupCallRequest(call=call_obj, join_as=await client.get_input_entity(me), params=DataJSON(data='{}'), muted=True, video_stopped=True))
                        success += 1
                        
                        if delay > 0:
                            await asyncio.sleep(delay)
                            await client(LeaveGroupCallRequest(call=call_obj, source=0))
                            await client(LeaveChannelRequest(entity))
                    else: failed += 1
                else: failed += 1
            except: failed += 1
            finally: await safe_disconnect(client)
        await tracker.advance()

    await asyncio.gather(*(worker(s) for s in sessions))
    await call.message.answer(f"✅ Mass VC complete.\n🟢 Success: {success}\n🔴 Failed: {failed}", reply_markup=get_back_kb())

# ==========================================
# 🏁 APP START EXECUTION BLOCK
# ==========================================
async def main():
    print("Starting background workers...")
    for _ in range(3): asyncio.create_task(background_worker())
    print(f"{BRAND_NAME} Bot is successfully running...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
