import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardRemove
from aiogram.filters import Command

# 🔑 BOT TOKEN
TOKEN = "YOUR_BOT_TOKEN"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# 🚀 START COMMAND → auto clear
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer(
        "👋 Welcome!\n\n🧹 UI cleaned successfully.",
        reply_markup=ReplyKeyboardRemove()
    )

# 🧹 CLEAR COMMAND
@dp.message(Command("clear"))
async def clear_cmd(message: types.Message):
    await message.answer(
        "✅ All buttons removed!",
        reply_markup=ReplyKeyboardRemove()
    )

# 🧨 AUTO REMOVE ANY MESSAGE KEYBOARD
@dp.message()
async def auto_clear(message: types.Message):
    await message.answer(
        "🧹 Clean mode active",
        reply_markup=ReplyKeyboardRemove()
    )

# ❌ REMOVE INLINE BUTTON (callback)
@dp.callback_query()
async def remove_inline(call: types.CallbackQuery):
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    await call.answer("❌ Buttons removed")

# ▶️ RUN BOT
async def main():
    print("🤖 Bot Running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())