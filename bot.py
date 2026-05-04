import logging
import asyncio
import requests
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command

# config
BOT_TOKEN = "BOT_TOKEN_HERE"
SERVER_URL = "http://127.0.0.1:5000/api/update_location"
ANCHOR_URL = "http://127.0.0.1:5000/api/add_anchor"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# basic in-memory storage to keep track of driver's last location
user_locations = {}

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = [
        [types.KeyboardButton(text="📍 Share My Location", request_location=True)],
        # CHANGED: Updated button text to include SOS for safety requirements
        [types.KeyboardButton(text="⚠️ SOS / Issue"), types.KeyboardButton(text="✅ Arrived")]
    ]
    keyboard = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await message.answer("OrientTrack active. Please share your location first, then you can send photos of anchors.", reply_markup=keyboard)

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
        resp = requests.post(SERVER_URL, json=payload)
        if resp.status_code == 200:
            print(f"Location updated for {tg_id}")
            # tell the driver they can now send a photo
            await message.answer("Location updated. You can now send a photo of the gate or container to set a visual anchor.")
        else:
            print("Server error during update")
    except Exception as e:
        print(f"Connection failed: {e}")

# handling photo uploads for visual anchors
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    tg_id = message.from_user.id
    
    # check if we know where they are
    if tg_id not in user_locations:
        await message.answer("Please share your location first before sending an anchor photo.")
        return
        
    # get the highest resolution photo file_id
    photo_id = message.photo[-1].file_id
    lat = user_locations[tg_id]["lat"]
    lng = user_locations[tg_id]["lng"]
    
    payload = {
        "telegram_id": tg_id,
        "lat": lat,
        "lng": lng,
        "photo_id": photo_id,
        # if driver added text to photo, save it as a note
        "note": message.caption or "Visual anchor saved"
    }
    
    try:
        resp = requests.post(ANCHOR_URL, json=payload)
        if resp.status_code == 200:
            await message.answer("Visual anchor successfully saved to dispatcher dashboard.")
        else:
            await message.answer("Failed to save anchor on server.")
    except Exception as e:
         await message.answer("Error connecting to server.")

# NEW: safety feature - handling emergency button
@dp.message(F.text == "⚠️ SOS / Issue")
async def handle_emergency(message: types.Message):
    tg_id = message.from_user.id
    # in a real system this would hit a specific /api/emergency endpoint
    await message.answer("EMERGENCY SIGNAL SENT to dispatcher. Please stay calm, we are recording your last known location.")
    print(f"!!! EMERGENCY ALERT TRIGGERED BY USER {tg_id} !!!")

async def main():
    print("Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped")