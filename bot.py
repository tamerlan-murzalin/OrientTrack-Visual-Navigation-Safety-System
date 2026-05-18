import logging
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
import config # Importing our centralized configuration

# URLs are now built dynamically from config
SERVER_URL = f"{config.SERVER_URL}/api/update_location"
ANCHOR_URL = f"{config.SERVER_URL}/api/add_anchor"
STATUS_URL = f"{config.SERVER_URL}/api/check_status"
EMERGENCY_URL = f"{config.SERVER_URL}/api/emergency"
SETNAME_URL = f"{config.SERVER_URL}/api/update_name"
RESET_URL = f"{config.SERVER_URL}/api/reset_route"

logging.basicConfig(level=logging.INFO)

# Token is now securely loaded from config
bot = Bot(token=config.TELEGRAM_TOKEN)
dp = Dispatcher()

# basic in-memory storage to keep track of driver's last location
user_locations = {}

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = [
        [types.KeyboardButton(text="📍 Share My Location", request_location=True)],
        [types.KeyboardButton(text="⚠️ SOS / Issue"), types.KeyboardButton(text="✅ Arrived")],
        [types.KeyboardButton(text="🏁 Reset Shift")]
    ]
    keyboard = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await message.answer("OrientTrack active. Use /status to check connection, or the buttons below for location and shift management.", reply_markup=keyboard)

# handling /status command to check server connection asynchronously
@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    tg_id = message.from_user.id
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{STATUS_URL}/{tg_id}", timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    await message.answer(f"✅ Connection OK.\nStatus: {data['status']}\nLast update: {data['last_update']}")
                else:
                    await message.answer("❌ Server reached but you are not registered yet. Please share location first.")
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
    payload = {"telegram_id": tg_id, "name": new_name}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(SETNAME_URL, json=payload) as resp:
                if resp.status == 200:
                    await message.answer(f"✅ Name successfully updated to: {new_name}")
                else:
                    await message.answer("❌ Please share your location first to register in the system.")
    except Exception as e:
        await message.answer("⚠️ Connection to server failed.")

# handling shift reset request asynchronously
@dp.message(F.text == "🏁 Reset Shift")
async def handle_reset(message: types.Message):
    tg_id = message.from_user.id
    payload = {"telegram_id": tg_id}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(RESET_URL, json=payload) as resp:
                if resp.status == 200:
                    await message.answer("✅ Shift history reset. Your route on the map has been cleared for a new trip.")
                else:
                    await message.answer("❌ Failed to reset shift. Are you registered?")
    except Exception as e:
        await message.answer("⚠️ Error connecting to server.")

# handling location updates
@dp.message(F.location)
async def handle_location(message: types.Message):
    lat = message.location.latitude
    lng = message.location.longitude
    tg_id = message.from_user.id
    
    # save locally so we can attach it to photos later
    user_locations[tg_id] = {"lat": lat, "lng": lng}
    
    payload = {
        "telegram_id": tg_id,
        "lat": lat,
        "lng": lng
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(SERVER_URL, json=payload) as resp:
                if resp.status == 200:
                    logging.info(f"Location updated for {tg_id}")
                    await message.answer("Location updated. You can now send a photo of the gate or container to set a visual anchor.")
                else:
                    logging.error("Server error during update")
    except Exception as e:
        logging.error(f"Connection failed: {e}")

# handling photo uploads for visual anchors
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    tg_id = message.from_user.id
    
    if tg_id not in user_locations:
        await message.answer("Please share your location first before sending an anchor photo.")
        return
        
    photo_id = message.photo[-1].file_id
    lat = user_locations[tg_id]["lat"]
    lng = user_locations[tg_id]["lng"]
    
    payload = {
        "telegram_id": tg_id,
        "lat": lat,
        "lng": lng,
        "photo_id": photo_id,
        "note": message.caption or "Visual anchor saved"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(ANCHOR_URL, json=payload) as resp:
                if resp.status == 200:
                    await message.answer("Visual anchor successfully saved to dispatcher dashboard.")
                else:
                    await message.answer("Failed to save anchor on server.")
    except Exception as e:
         await message.answer("Error connecting to server.")

# safety feature - handling emergency button
@dp.message(F.text == "⚠️ SOS / Issue")
async def handle_emergency(message: types.Message):
    tg_id = message.from_user.id
    payload = {"telegram_id": tg_id}
    
    # Fire and forget request for SOS
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(EMERGENCY_URL, json=payload)
    except Exception as e:
        logging.error(f"Failed to alert server: {e}")
        
    await message.answer("EMERGENCY SIGNAL SENT to dispatcher. Please stay calm, we are recording your last known location.")
    logging.warning(f"!!! EMERGENCY ALERT TRIGGERED BY USER {tg_id} !!!")

# fallback handler for any unrecognized text or media
@dp.message()
async def handle_unrecognized(message: types.Message):
    await message.answer("Command not recognized. Please share your location, send a photo, or use the menu buttons.")

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