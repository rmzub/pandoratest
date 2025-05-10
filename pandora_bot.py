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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    players[user.id] = {"name": user.username or user.first_name, "score": 0}
    await update.message.reply_text("👋 Вас додано до гри! Ведучий може почати раунд командою /begin_round.")

async def begin_round(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_question, answers, random_answer, host_id, collecting, guessed_this_round
    if not context.args:
        await update.message.reply_text("❗ Формат: /begin_round [питання]")
        return
    host_id = update.effective_user.id
    current_question = " ".join(context.args)
    answers = {}
    random_answer = None
    collecting = True
    guessed_this_round.clear()

    keyboard = [[InlineKeyboardButton("✍️ Надіслати відповідь", callback_data="submit_answer")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=update.effective_chat.id,
        text=f"🧠 Питання:\n*{current_question}*\n\n⏳ У вас є *60 секунд* на відповідь!",
        parse_mode="Markdown", reply_markup=reply_markup)

    await asyncio.sleep(60)
    collecting = False
    await context.bot.send_message(chat_id=update.effective_chat.id,
        text="⏰ Час вийшов! Ведучий натискає 👇",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔍 Показати відповідь", callback_data="show_random")]]
        ))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if query.data == "submit_answer":
        await context.bot.send_message(chat_id=user.id, text="✍️ Напиши свою відповідь сюди:")
    elif query.data == "show_random" and user.id == host_id:
        await show_random(update, context)
    elif query.data.startswith("guess_"):
        await process_guess(update, context, int(query.data.split("_")[1]))

async def collect_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    if user.id not in players or not collecting:
        return
    if not text or user.id in answers:
        await update.message.reply_text("⚠️ Ви вже надіслали відповідь або вона некоректна.")
        return
    if text in answers.values():
        await update.message.reply_text("⚠️ Така відповідь уже є. Спробуйте щось інше.")
        return

    answers[user.id] = text
    await update.message.reply_text("✅ Ваша відповідь збережена анонімно.")

async def show_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global random_answer
    if not answers:
        await update.effective_message.reply_text("❌ Немає відповідей.")
        return

    random_id = random.choice(list(answers.keys()))
    random_answer = (random_id, answers[random_id])

    keyboard = []
    for uid, data in players.items():
        if uid != host_id:
            keyboard.append([InlineKeyboardButton(f"🤔 {data['name']}", callback_data=f"guess_{uid}")])
    markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=update.effective_chat.id,
        text=f"📜 Випадкова відповідь:\n«*{random_answer[1]}*»\n\n🕵️ Хто це написав?",
        parse_mode="Markdown", reply_markup=markup)

async def process_guess(update: Update, context: ContextTypes.DEFAULT_TYPE, guessed_id: int):
    global guessed_this_round
    user = update.callback_query.from_user

    if user.id in guessed_this_round:
        await update.callback_query.answer("⚠️ Ви вже вгадували.")
        return

    guessed_this_round.add(user.id)
    real_id = random_answer[0]

    if guessed_id == real_id:
        players[user.id]["score"] += 1
        await update.callback_query.edit_message_text(f"🎉 {user.first_name} вгадав(ла) правильно й отримує 1 бал!")
    else:
        await update.callback_query.edit_message_text(f"❌ {user.first_name} помилився(лась).")

async def score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🏆 Рахунок:\n" + "\n".join([f"{v['name']}: {v['score']} балів" for v in players.values()])
    await update.message.reply_text(text)

def main():
    app = ApplicationBuilder().token("YOUR_BOT_TOKEN_HERE").build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("begin_round", begin_round))
    app.add_handler(CommandHandler("score", score))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect_answers))
    app.run_polling()

if __name__ == "__main__":
    main()
