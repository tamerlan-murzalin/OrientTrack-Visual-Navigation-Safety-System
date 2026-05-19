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

logging.basicConfig(level=logging.INFO)

# Token is now securely loaded from config
bot = Bot(token=config.TELEGRAM_TOKEN)
dp = Dispatcher()

# basic in-memory storage to keep track of driver's last location
user_locations = {}

# defining finite state machines for strict data flow
class AppState(StatesGroup):
    waiting_for_live_location = State()

class AnchorState(StatesGroup):
    waiting_for_photo = State()
    waiting_for_description = State()

# building dynamic keyboards for the workflow
def get_start_keyboard():
    buttons = [[InlineKeyboardButton(text="🚀 Start Shift", callback_data="init_start")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_main_keyboard():
    kb = [
        [KeyboardButton(text="🔄 Update Status"), KeyboardButton(text="📍 Live Tracking Guide")],
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

# handling shift initialization and strict tracking requirement
@dp.callback_query(F.data == "init_start")
async def process_init_start(callback: types.CallbackQuery, state: FSMContext):
    instruction = (
        "📍 <b>Action Required:</b>\n"
        "Please broadcast your live location to continue:\n\n"
        "1. Tap the 📎 Paperclip icon\n"
        "2. Select 'Location'\n"
        "3. Choose <b>'Share My Live Location for...'</b>\n\n"
        "Controls will unlock once the background stream is detected."
    )
    await callback.message.edit_text(instruction, parse_mode="HTML")
    await state.set_state(AppState.waiting_for_live_location)
    await callback.answer()

@dp.message(F.text == "📍 Live Tracking Guide")
async def guide_location(message: types.Message):
    await message.answer("Remember: Always use 'Share My Live Location' for constant background tracking. Static points do not update on the dispatcher map.")

# handling /status command to check server connection asynchronously
@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    tg_id = message.from_user.id
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{STATUS_URL}/{tg_id}", timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tracking = "🟢 Active" if data.get('is_tracking') else "🔴 Inactive"
                    await message.answer(f"✅ Connection OK.\nStatus: {data['status']}\nTracking: {tracking}\nLast update: {data['last_update']}")
                else:
                    await message.answer("❌ Server reached but you are not registered yet. Please start your shift first.")
    except Exception as e:
        await message.answer("⚠️ Connection to server failed. You might be in a dead zone.")

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
                    await message.answer("❌ Please share your location first to register in the system.")
    except Exception as e:
        await message.answer("⚠️ Connection to server failed.")

# handling dynamic status updates
@dp.message(F.text == "🔄 Update Status")
async def update_status_menu(message: types.Message):
    await message.answer("Select your current operational status:", reply_markup=get_status_keyboard())

@dp.callback_query(F.data.startswith("status_"))
async def process_status_callback(callback: types.CallbackQuery):
    new_status = callback.data.split("_")[1]
    payload = {"telegram_id": str(callback.from_user.id), "status": new_status}
    
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(SERVER_URL, json=payload)
        await callback.message.edit_text(f"✅ Status updated to: <b>{new_status}</b>", parse_mode="HTML")
    except Exception:
        await callback.answer("❌ Server error", show_alert=True)

# handling shift reset request asynchronously
@dp.message(F.text == "🏁 Reset Shift")
async def handle_reset(message: types.Message, state: FSMContext):
    tg_id = message.from_user.id
    payload = {"telegram_id": str(tg_id)}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(RESET_URL, json=payload) as resp:
                if resp.status == 200:
                    await message.answer("✅ Shift history reset and archived. Please stop Live Location sharing in Telegram.", reply_markup=types.ReplyKeyboardRemove())
                    await message.answer("Ready for a new delivery?", reply_markup=get_start_keyboard())
                    await state.clear()
                else:
                    await message.answer("❌ Failed to reset shift.")
    except Exception as e:
        await message.answer("⚠️ Error connecting to server.")

# handling initial location stream attachment
@dp.message(F.location)
async def handle_location(message: types.Message, state: FSMContext):
    is_live = bool(message.location.live_period)
    lat = message.location.latitude
    lng = message.location.longitude
    tg_id = message.from_user.id
    current_state = await state.get_state()
    
    # save locally so we can attach it to photos later
    user_locations[tg_id] = {"lat": lat, "lng": lng}
    
    payload = {
        "telegram_id": str(tg_id),
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
                        logging.info(f"Shift initialized and location updated for {tg_id}")
                        await message.answer("✅ <b>Live tracking locked!</b> Shift controls are now available.", parse_mode="HTML", reply_markup=get_main_keyboard())
                        await state.clear()
        except Exception as e:
            logging.error(f"Connection failed: {e}")
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
    
    payload = {
        "telegram_id": str(tg_id),
        "lat": message.location.latitude,
        "lng": message.location.longitude,
        "is_tracking": is_live
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(SERVER_URL, json=payload)
    except Exception:
        pass
        
    if not is_live:
        await message.answer("🛑 <b>Live tracking stopped.</b> The dispatcher has been notified.", parse_mode="HTML")

# handling FSM for visual anchors (step 1)
@dp.message(F.text == "📸 Add Visual Anchor")
async def start_anchor(message: types.Message, state: FSMContext):
    tg_id = message.from_user.id
    if tg_id not in user_locations:
        await message.answer("❌ Please start Live Tracking first to record the anchor coordinates.")
        return
        
    await message.answer("📸 Step 1: Send a photo of the area (gate, container, or issue).")
    await state.set_state(AnchorState.waiting_for_photo)

# handling photo uploads for visual anchors (step 2)
@dp.message(AnchorState.waiting_for_photo, F.photo)
async def process_anchor_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("📝 Step 2: Add a brief description or note for the dispatcher:")
    await state.set_state(AnchorState.waiting_for_description)

# handling description for visual anchors (step 3)
@dp.message(AnchorState.waiting_for_description, F.text)
async def process_anchor_desc(message: types.Message, state: FSMContext):
    tg_id = message.from_user.id
    d = await state.get_data()
    
    payload = {
        "telegram_id": str(tg_id),
        "lat": user_locations[tg_id]["lat"],
        "lng": user_locations[tg_id]["lng"],
        "photo_id": d.get("photo_id"),
        "note": message.text
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(ANCHOR_URL, json=payload) as resp:
                if resp.status == 200:
                    await message.answer("✅ Visual anchor successfully saved to dispatcher dashboard.")
                else:
                    await message.answer("❌ Failed to save anchor on server.")
    except Exception as e:
        await message.answer("⚠️ Error connecting to server.")
    finally:
        await state.clear()

# safety feature - handling emergency button
@dp.message(F.text == "⚠️ SOS / Issue")
async def handle_emergency(message: types.Message):
    tg_id = message.from_user.id
    payload = {"telegram_id": str(tg_id)}
    
    # Fire and forget request for SOS
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(EMERGENCY_URL, json=payload)
    except Exception as e:
        logging.error(f"Failed to alert server: {e}")
        
    await message.answer("🚨 EMERGENCY SIGNAL SENT to dispatcher. Please stay calm, we are recording your last known location.")
    logging.warning(f"!!! EMERGENCY ALERT TRIGGERED BY USER {tg_id} !!!")

# fallback handler for any unrecognized text or media
@dp.message()
async def handle_unrecognized(message: types.Message):
    await message.answer("Command not recognized. Please use the menu buttons to manage your shift.")

async def main():
    logging.info("Starting bot...")
    # Drop pending updates to avoid processing old locations if bot was offline
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped")