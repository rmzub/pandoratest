import asyncio
import random
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

load_dotenv()
players = {}
answers = {}
joined_players = set()
random_answer = None
host_id = None
collecting = False
guessing = False
guessed = {}

# /startgame — ініціює гру
async def startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global joined_players, host_id
    joined_players.clear()
    host_id = update.effective_user.id
    await update.message.reply_text(
        "🎲 Гра розпочинається! Натисни кнопку, щоб долучитись.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🙋‍♀️ Долучитись до гри", callback_data="join_game")],
            [InlineKeyboardButton("✅ Почати гру", callback_data="begin_round")]
        ])
    )

# Кнопки
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if query.data == "join_game":
        joined_players.add(user.id)
        players[user.id] = {"name": user.username or user.first_name, "score": 0}
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"{user.first_name} долучився до гри 🎉"
        )

    elif query.data == "begin_round" and user.id == host_id:
        await begin_round(update, context)

    elif query.data == "show_random" and user.id == host_id:
        await show_random(update, context)

    elif query.data.startswith("guess_") and guessing:
        await process_guess(update, context, int(query.data.split("_")[1]))

# Початок раунду
async def begin_round(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global answers, collecting, guessed, guessing
    answers.clear()
    guessed.clear()
    collecting = True
    guessing = False
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🧠 Почали! У вас є 90 секунд на відповідь. Пишіть прямо в чат."
    )
    await asyncio.sleep(90)
    if collecting:
        await end_collection(context)

# Збір відповідей
async def collect_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global collecting
    user = update.effective_user
    if collecting and user.id in joined_players and user.id not in answers:
        answers[user.id] = update.message.text
        await update.message.reply_text("✅ Ваша відповідь записана!")

# Завершення збору
async def end_collection(context: ContextTypes.DEFAULT_TYPE):
    global collecting, random_answer, guessing
    collecting = False
    if not answers:
        await context.bot.send_message(chat_id=list(joined_players)[0], text="❌ Немає відповідей.")
        return

    random_id = random.choice(list(answers.keys()))
    random_answer = (random_id, answers[random_id])
    guessing = True

    keyboard = [
        [InlineKeyboardButton(players[uid]["name"], callback_data=f"guess_{uid}")]
        for uid in joined_players if uid != host_id
    ]
    markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
    chat_id=update.effective_chat.id,
    text=f"📜 *Випадкова відповідь:*\n«⭑{random_answer[1]}⭑»\n\n🕵️ Хто це написав?",
    parse_mode="Markdown",
    reply_markup=markup)
    await asyncio.sleep(60)
    await end_guessing(context)

# Вгадування
async def process_guess(update: Update, context: ContextTypes.DEFAULT_TYPE, guessed_id: int):
    global guessed
    user = update.effective_user
    if user.id in guessed:
        await update.callback_query.answer("❗ Ви вже проголосували.")
        return
    guessed[user.id] = guessed_id
    await update.callback_query.answer("✅ Ваш варіант збережено!")

# Підбиття результатів
async def end_guessing(context: ContextTypes.DEFAULT_TYPE):
    global guessing
    guessing = False
    if not random_answer:
        return

    correct_id = random_answer[0]
    winners = [uid for uid, gid in guessed.items() if gid == correct_id]

    if winners:
        for uid in winners:
            players[uid]["score"] += 1
        names = ", ".join([players[uid]["name"] for uid in winners])
        result = f"🎯 Правильно вгадали: {names}!"
    else:
        result = "❌ Ніхто не вгадав."

    await context.bot.send_message(chat_id=list(joined_players)[0], text=result)
    await show_score(context)

# Рахунок
async def score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🏆 Рахунок:\n" + "\n".join([f"{v['name']}: {v['score']} балів" for v in players.values()])
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Вітаю! Напиши /startgame щоб почати нову гру.")

# main
def main():
    app = ApplicationBuilder().token("7491368320:AAEnRYGYWj_UuDx62RuHAytDmZjAJJ0J1Ps").build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("startgame", startgame))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect_answers))
    app.run_polling()

if __name__ == "__main__":
    main()
