import logging
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import config # Importing our centralized configuration

# URLs are now built dynamically from config
SERVER_URL = f"{config.SERVER_URL}/api/update_location"
ANCHOR_URL = f"{config.SERVER_URL}/api/add_anchor"
STATUS_URL = f"{config.SERVER_URL}/api/check_status"
EMERGENCY_URL = f"{config.SERVER_URL}/api/emergency"
SETNAME_URL = f"{config.SERVER_URL}/api/update_name"
RESET_URL = f"{config.SERVER_URL}/api/reset_route"
ISSUE_URL = f"{config.SERVER_URL}/api/issue"
VOICE_URL = f"{config.SERVER_URL}/api/voice"
CHAT_RECEIVE_URL = f"{config.SERVER_URL}/api/chat_receive"
SAFETY_URL = f"{config.SERVER_URL}/api/safety"

logging.basicConfig(level=logging.INFO)

# Token is now securely loaded from config
bot = Bot(token=config.TELEGRAM_TOKEN)
dp = Dispatcher()

# basic in-memory storage to keep track of driver's last location
user_locations = {}

# defining finite state machines for strict data flow
class AppState(StatesGroup):
    waiting_for_live_location = State()
    waiting_for_issue_text = State()

class AnchorState(StatesGroup):
    waiting_for_photo = State()
    waiting_for_description = State()

class SafetyState(StatesGroup):
    waiting_for_custom_time = State()

# menu buttons to filter out from issue and free text handlers
menu_buttons = [
    "🔄 Update Status", "⛰️ Safety Timer", "📸 Add Visual Anchor", 
    "⚠️ SOS / Issue", "🏁 Reset Shift", "❌ Cancel", 
    "1 hour", "2 hours", "🛑 Disable Timer", "⏱️ Custom time (mins)"
]

# building dynamic keyboards for the workflow
def get_start_keyboard():
    buttons = [[InlineKeyboardButton(text="🚀 Start Shift", callback_data="init_start")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_main_keyboard():
    kb = [
        [KeyboardButton(text="🔄 Update Status"), KeyboardButton(text="⛰️ Safety Timer")],
        [KeyboardButton(text="📸 Add Visual Anchor"), KeyboardButton(text="⚠️ SOS / Issue")],
        [KeyboardButton(text="🏁 Reset Shift")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_status_keyboard():
    buttons = [
        [InlineKeyboardButton(text="📦 Cargo Loaded", callback_data="status_Loaded")],
        [InlineKeyboardButton(text="✅ Delivered", callback_data="status_Delivered")],
        [InlineKeyboardButton(text="🚨 Report Issue", callback_data="status_Issue")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    welcome_text = (
        f"Welcome to OrientTrack, {message.from_user.first_name}!\n\n"
        "To begin your shift, please tap 'Start Shift' below. "
        "The system requires an active Live Location stream to ensure safety and accurate tracking."
    )
    await message.answer(welcome_text, reply_markup=types.ReplyKeyboardRemove())
    await message.answer("Ready to begin?", reply_markup=get_start_keyboard())
    await state.clear()

@dp.message(F.text == "❌ Cancel")
async def cancel_action(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Action canceled.", reply_markup=get_main_keyboard())

# handling shift initialization and strict tracking requirement
@dp.callback_query(F.data == "init_start")
async def process_init_start(callback: types.CallbackQuery, state: FSMContext):
    instruction = (
        "📍 <b>Action Required:</b>\n"
        "Please broadcast your live location to continue:\n\n"
        "1. Tap the 📎 Paperclip icon\n"
        "2. Select 'Location'\n"
        "3. Choose <b>'Share My Live Location for...'</b> and select <b>'Until turned off'</b>.\n\n"
        "Controls will unlock once the background stream is detected."
    )
    await callback.message.edit_text(instruction, parse_mode="HTML")
    await state.set_state(AppState.waiting_for_live_location)
    await callback.answer()

@dp.message(Command("setname"))
async def cmd_setname(message: types.Message):
    tg_id = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Please provide a name or vehicle number. Example: /setname Truck 55")
        return
    new_name = parts[1]
    payload = {"telegram_id": str(tg_id), "name": new_name}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(SETNAME_URL, json=payload) as resp:
                if resp.status == 200:
                    await message.answer(f"✅ Name successfully updated to: {new_name}")
                else:
                    await message.answer("❌ Please share your location first to register.")
    except Exception:
        await message.answer("⚠️ Connection to server failed.")

# handling dynamic status updates
@dp.message(F.text == "🔄 Update Status")
async def update_status_menu(message: types.Message):
    await message.answer("Select your current operational status:", reply_markup=get_status_keyboard())

@dp.callback_query(F.data.startswith("status_"))
async def process_status_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "status_Issue":
        await callback.message.edit_text("🚨 Please describe the issue briefly (or send a voice message):")
        await state.set_state(AppState.waiting_for_issue_text)
        await callback.answer()
        return

    new_status = callback.data.split("_")[1]
    payload = {"telegram_id": str(callback.from_user.id), "status": new_status}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(SERVER_URL, json=payload) as resp:
                if resp.status == 200:
                    await callback.message.edit_text(f"✅ Status updated to: <b>{new_status}</b>", parse_mode="HTML")
                else:
                    await callback.answer("❌ Server error during update.", show_alert=True)
    except Exception:
        await callback.answer("❌ Server connection failed", show_alert=True)

@dp.message(AppState.waiting_for_issue_text, F.text, ~F.text.in_(menu_buttons))
async def process_issue_text(message: types.Message, state: FSMContext):
    payload = {"telegram_id": str(message.from_user.id), "issue_text": message.text}
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(ISSUE_URL, json=payload)
        await message.answer("🚨 Issue reported. Awaiting dispatcher response.", reply_markup=get_main_keyboard())
    except Exception:
        await message.answer("❌ Failed to send issue report.")
    await state.clear()

# handling shift reset request asynchronously
@dp.message(F.text == "🏁 Reset Shift")
async def handle_reset(message: types.Message, state: FSMContext):
    payload = {"telegram_id": str(message.from_user.id)}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(RESET_URL, json=payload) as resp:
                if resp.status == 200:
                    await message.answer("✅ Shift history reset and archived. Please stop Live Location sharing in Telegram.", reply_markup=types.ReplyKeyboardRemove())
                    await message.answer("Ready for a new delivery?", reply_markup=get_start_keyboard())
                    await state.clear()
                else:
                    await message.answer("❌ Failed to reset shift.")
    except Exception:
        await message.answer("⚠️ Error connecting to server.")

# handling initial location stream attachment
@dp.message(F.location)
async def handle_location(message: types.Message, state: FSMContext):
    is_live = bool(message.location.live_period)
    lat, lng = message.location.latitude, message.location.longitude
    tg_id = message.from_user.id
    current_state = await state.get_state()
    
    user_locations[tg_id] = {"lat": lat, "lng": lng}
    
    # Passing the name so the server doesn't create "User 1234"
    payload = {
        "telegram_id": str(tg_id), 
        "name": message.from_user.first_name, 
        "lat": lat, 
        "lng": lng, 
        "is_tracking": is_live
    }
    
    if current_state == AppState.waiting_for_live_location.state:
        if not is_live:
            await message.answer("⚠️ You sent a STATIC point. The system requires 'Live Location' to initialize the shift.")
            return
        
        payload["status"] = "Active"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(SERVER_URL, json=payload) as resp:
                    if resp.status == 200:
                        logging.info(f"Shift initialized for {tg_id}")
                        await message.answer("✅ <b>Live tracking locked!</b> Shift controls are now available.", parse_mode="HTML", reply_markup=get_main_keyboard())
                        await state.clear()
                    else:
                        await message.answer("❌ The server rejected the request.")
        except Exception as e:
            logging.error(f"Connection failed during init: {e}")
            await message.answer("⚠️ Could not connect to the server.")
    else:
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(SERVER_URL, json=payload)
        except Exception:
            pass

# handling background live location updates quietly
@dp.edited_message(F.location)
async def handle_live_updates(message: types.Message):
    is_live = bool(message.location.live_period)
    tg_id = message.from_user.id
    user_locations[tg_id] = {"lat": message.location.latitude, "lng": message.location.longitude}
    payload = {"telegram_id": str(tg_id), "lat": message.location.latitude, "lng": message.location.longitude, "is_tracking": is_live}
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(SERVER_URL, json=payload)
    except Exception:
        pass
    if not is_live:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{STATUS_URL}/{tg_id}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == "Offline":
                            return
        except Exception:
            pass
        await message.answer("🛑 <b>Live tracking stopped.</b> The dispatcher has been notified.", parse_mode="HTML")

# handling FSM for visual anchors (step 1)
@dp.message(F.text == "📸 Add Visual Anchor")
async def start_anchor(message: types.Message, state: FSMContext):
    if message.from_user.id not in user_locations:
        await message.answer("❌ Please start Live Tracking first to record the anchor coordinates.")
        return
    await message.answer("📸 Step 1: Send a photo of the area (gate, container, or issue).", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Cancel")]], resize_keyboard=True))
    await state.set_state(AnchorState.waiting_for_photo)

# handling photo uploads for visual anchors (step 2)
@dp.message(AnchorState.waiting_for_photo, F.photo)
async def process_anchor_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("📝 Step 2: Add a brief description or note for the dispatcher:")
    await state.set_state(AnchorState.waiting_for_description)

# handling description for visual anchors (step 3)
@dp.message(AnchorState.waiting_for_description, F.text, ~F.text.in_(menu_buttons))
async def process_anchor_desc(message: types.Message, state: FSMContext):
    tg_id = message.from_user.id
    d = await state.get_data()
    payload = {"telegram_id": str(tg_id), "lat": user_locations[tg_id]["lat"], "lng": user_locations[tg_id]["lng"], "photo_id": d.get("photo_id"), "note": message.text}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(ANCHOR_URL, json=payload) as resp:
                if resp.status == 200:
                    await message.answer("✅ Visual anchor successfully saved to dispatcher dashboard.", reply_markup=get_main_keyboard())
                else:
                    await message.answer("❌ Failed to save anchor on server.", reply_markup=get_main_keyboard())
    except Exception:
        await message.answer("⚠️ Error connecting to server.", reply_markup=get_main_keyboard())
    finally:
        await state.clear()

# handling safety timer logic for blind zones
@dp.message(F.text == "⛰️ Safety Timer")
async def start_safety_timer(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="1 hour"), KeyboardButton(text="2 hours")], 
        [KeyboardButton(text="⏱️ Custom time (mins)")],
        [KeyboardButton(text="🛑 Disable Timer"), KeyboardButton(text="❌ Cancel")]
    ], resize_keyboard=True)
    await message.answer("⚠️ Entering a blind zone?\nSelect a safety timeout duration:", reply_markup=kb)

@dp.message(F.text == "⏱️ Custom time (mins)")
async def ask_custom_time(message: types.Message, state: FSMContext):
    await message.answer("Enter duration in minutes (e.g., 45):", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Cancel")]], resize_keyboard=True))
    await state.set_state(SafetyState.waiting_for_custom_time)

@dp.message(SafetyState.waiting_for_custom_time, F.text, ~F.text.in_(menu_buttons))
async def process_custom_time(message: types.Message, state: FSMContext):
    try:
        minutes = int(message.text.strip())
        async with aiohttp.ClientSession() as session:
            await session.post(SAFETY_URL, json={"telegram_id": str(message.from_user.id), "action": "start", "minutes": minutes})
        await message.answer(f"⏳ Safety timer set for {minutes} minutes!", reply_markup=get_main_keyboard())
        await state.clear()
    except ValueError:
        await message.answer("❌ Invalid format.")

@dp.message(F.text.in_(["1 hour", "2 hours", "🛑 Disable Timer"]))
async def process_standard_timer(message: types.Message):
    action = "stop" if message.text == "🛑 Disable Timer" else "start"
    hours = 0 if action == "stop" else int(message.text.split()[0])
    async with aiohttp.ClientSession() as session:
        await session.post(SAFETY_URL, json={"telegram_id": str(message.from_user.id), "action": action, "hours": hours})
    await message.answer("✅ Timer updated.", reply_markup=get_main_keyboard())

# safety feature - handling voice reports
@dp.message(F.voice)
async def handle_voice_chat(message: types.Message, state: FSMContext):
    async with aiohttp.ClientSession() as session:
        await session.post(CHAT_RECEIVE_URL, json={"telegram_id": str(message.from_user.id), "voice_id": message.voice.file_id})
    await message.answer("🎙️ Voice delivered.")
    await state.clear()

# handling driver free-text chat to dispatcher
@dp.message(F.text, ~F.text.in_(menu_buttons))
async def handle_free_text_chat(message: types.Message):
    async with aiohttp.ClientSession() as session:
        await session.post(CHAT_RECEIVE_URL, json={"telegram_id": str(message.from_user.id), "text": message.text})
    await message.answer("💬 Message sent to dispatcher.")

@dp.message(F.text == "⚠️ SOS / Issue")
async def handle_emergency(message: types.Message):
    async with aiohttp.ClientSession() as session:
        await session.post(EMERGENCY_URL, json={"telegram_id": str(message.from_user.id)})
    await message.answer("🚨 EMERGENCY SIGNAL SENT.")

# fallback handler for any unrecognized text or media
@dp.message()
async def handle_unrecognized(message: types.Message):
    await message.answer("Command not recognized. Please use the menu buttons to manage your shift.")

async def main():
    logging.info("Starting bot...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped")