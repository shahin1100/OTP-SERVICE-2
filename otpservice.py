import telebot
from telebot.types import ReplyKeyboardRemove

# 🔐 NEW TOKEN (old revoke kore nibe)
TOKEN = "8343363851:AAETAyJXJJTyCm5cWuMI5S5l3Ll70Yv_EAM"

bot = telebot.TeleBot(TOKEN)

# 🚀 START → auto clean
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "👋 Welcome!\n\n🧹 UI cleaned successfully.",
        reply_markup=ReplyKeyboardRemove()
    )

# 🧹 CLEAR COMMAND
@bot.message_handler(commands=['clear'])
def clear(message):
    bot.send_message(
        message.chat.id,
        "✅ All buttons removed!",
        reply_markup=ReplyKeyboardRemove()
    )

# 🧨 AUTO CLEAR (any message)
@bot.message_handler(func=lambda m: True)
def auto_clear(message):
    bot.send_message(
        message.chat.id,
        "🧹 Clean mode active",
        reply_markup=ReplyKeyboardRemove()
    )

# ❌ INLINE BUTTON REMOVE
@bot.callback_query_handler(func=lambda call: True)
def remove_inline(call):
    try:
        bot.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=None
        )
    except:
        pass
    bot.answer_callback_query(call.id, "❌ Buttons removed")

# ▶️ RUN
print("🤖 Bot Running...")
bot.infinity_polling()