import logging
import asyncio
import requests # needed for sending data to flask
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# config
BOT_TOKEN = "BOT_TOKEN_HERE"
SERVER_URL = "http://127.0.0.1:5000/api/update_location"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # keyboard with location request button
    kb = [
        [types.KeyboardButton(text="📍 Share My Location", request_location=True)],
        [types.KeyboardButton(text="⚠️ Report Issue"), types.KeyboardButton(text="✅ Arrived")]
    ]
    keyboard = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await message.answer("OrientTrack active. Please share your location for monitoring.", reply_markup=keyboard)

@dp.message(lambda message: message.location is not None)
async def handle_location(message: types.Message):
    # data to send to our backend
    payload = {
        "telegram_id": message.from_user.id,
        "lat": message.location.latitude,
        "lng": message.location.longitude
    }
    
    try:
        # push location data to the server
        resp = requests.post(SERVER_URL, json=payload)
        if resp.status_code == 200:
            print(f"Location updated for {message.from_user.id}")
        else:
            print("Server error during update")
    except Exception as e:
        print(f"Connection failed: {e}")

async def main():
    print("Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped")