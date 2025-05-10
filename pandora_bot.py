import random, asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

players = {}
answers = {}
random_answer = None
current_question = ""
host_id = None
collecting = False
guessed_this_round = set()

# 👋 Старт + меню
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    players[user.id] = {"name": user.username or user.first_name, "score": 0}
    await update.message.reply_text("👋 Вітаю у *Скриньці Пандори*! Обери дію:",
        parse_mode="Markdown",
        reply_markup=main_menu())

# 📋 Головне меню
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Новий раунд", callback_data="begin_round")],
        [InlineKeyboardButton("⏹ Завершити раунд", callback_data="end_round")],
        [InlineKeyboardButton("👑 Призначити ведучого", callback_data="set_host")],
        [InlineKeyboardButton("📊 Рахунок", callback_data="score")]
    ])

# 🔘 Кнопки меню
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if query.data == "begin_round":
        await begin_round(update, context, button=True)
    elif query.data == "end_round":
        await end_round(update, context, button=True)
    elif query.data == "set_host":
        host_id = user.id
        await query.edit_message_text(f"👑 @{user.username or user.first_name} тепер ведучий.")
    elif query.data == "score":
        await score(update, context)
    elif query.data == "submit_answer":
        await context.bot.send_message(chat_id=user.id, text="✍️ Напиши свою відповідь сюди:")
    elif query.data == "show_random" and user.id == host_id:
        await show_random(update, context)
    elif query.data.startswith("guess_"):
        await process_guess(update, context, int(query.data.split("_")[1]))

# 🔁 Початок раунду
async def begin_round(update: Update, context: ContextTypes.DEFAULT_TYPE, button=False):
    global current_question, answers, random_answer, host_id, collecting, guessed_this_round
    host_id = update.effective_user.id
    current_question = "(Питання зачитується вживу)"
    answers = {}
    random_answer = None
    collecting = True
    guessed_this_round.clear()

    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("✍️ Надіслати відповідь", callback_data="submit_answer")]])
    msg_func = update.callback_query.edit_message_text if button else update.message.reply_text

    await msg_func("🧠 *Новий раунд розпочато!*
⏳ У вас є *60 секунд*, щоб надіслати відповідь.",
        parse_mode="Markdown", reply_markup=reply_markup)

    await asyncio.sleep(60)
    collecting = False
    await context.bot.send_message(chat_id=update.effective_chat.id,
        text="⏰ Час завершено. Ведучий натискає кнопку нижче 👇",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔍 Показати відповідь", callback_data="show_random")]]
        ))

# ⏹ Завершення раунду вручну
async def end_round(update: Update, context: ContextTypes.DEFAULT_TYPE, button=False):
    global collecting
    if update.effective_user.id != host_id:
        await (update.callback_query if button else update.message).reply_text("❌ Тільки ведучий може завершити раунд.")
        return
    collecting = False
    await context.bot.send_message(chat_id=update.effective_chat.id,
        text="🔔 Раунд завершено вручну. Ведучий натискає кнопку нижче 👇",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔍 Показати відповідь", callback_data="show_random")]]
        ))

# ✉️ Збір відповідей
async def collect_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    if user.id not in players or not collecting:
        return
    if not text or user.id in answers or text in answers.values():
        await update.message.reply_text("⚠️ Некоректна або повторна відповідь.")
        return
    answers[user.id] = text
    await update.message.reply_text("✅ Ваша відповідь збережена анонімно.")

# 🔍 Показ випадкової відповіді
async def show_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global random_answer
    if not answers:
        await update.callback_query.edit_message_text("❌ Немає відповідей.")
        return
    random_id = random.choice(list(answers.keys()))
    random_answer = (random_id, answers[random_id])

    keyboard = [[InlineKeyboardButton(f"🤔 {data['name']}", callback_data=f"guess_{uid}")]
                for uid, data in players.items() if uid != host_id]
    markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=update.effective_chat.id,
        text=f"📜 Випадкова відповідь:
«*{random_answer[1]}*»

🕵️ Хто це написав?",
        parse_mode="Markdown", reply_markup=markup)

# 🎯 Обробка вгадування
async def process_guess(update: Update, context: ContextTypes.DEFAULT_TYPE, guessed_id: int):
    global guessed_this_round
    user = update.callback_query.from_user
    if user.id in guessed_this_round:
        await update.callback_query.answer("⚠️ Ви вже пробували.")
        return
    guessed_this_round.add(user.id)
    if guessed_id == random_answer[0]:
        players[user.id]["score"] += 1
        await update.callback_query.edit_message_text(f"🎉 {user.first_name} вгадав(ла) правильно!")
    else:
        await update.callback_query.edit_message_text(f"❌ {user.first_name} помилився(лась).")

# 📊 Рахунок
async def score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🏆 Рахунок:
" + "\n".join([f"{v['name']}: {v['score']} балів" for v in players.values()])
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)

# 🚀 Запуск
def main():
    app = ApplicationBuilder().token("7491368320:AAEnRYGYWj_UuDx62RuHAytDmZjAJJ0J1Ps").build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect_answers))
    app.run_polling()

if __name__ == "__main__":
    main()
