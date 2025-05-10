import asyncio
import random
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Load environment variables (for your bot token)
BOT_TOKEN = "7491368320:AAEnRYGYWj_UuDx62RuHAytDmZjAJJ0J1Ps" # Make sure you have TELEGRAM_BOT_TOKEN in your .env file

# Global game state variables
players = {}  # Stores player data {user_id: {"name": "username", "score": 0}}
answers = {}  # Stores answers from players {user_id: "answer_text"}
joined_players = set()  # Set of user_ids of players who joined the current game
random_answer_data = None  # Stores the (user_id, answer_text) of the randomly selected answer
host_id = None  # user_id of the person who started the game
group_chat_id = None # chat_id of the group where the game is running
collecting_answers_active = False  # Flag to indicate if the bot is currently collecting answers
guessing_active = False  # Flag to indicate if the bot is currently in the guessing phase
player_guesses = {} # Stores guesses from players {guesser_user_id: guessed_user_id}
answer_collection_task = None # To store the asyncio task for answer collection timeout

# 1. /start - Welcomes the user
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message when the /start command is issued."""
    await update.message.reply_text("👋 Вітаю! Я бот для гри 'Скринька Пандори'.\n"
                                     "Напиши /startgame у груповому чаті, щоб почати нову гру.\n"
                                     "Використой /help для перегляду правил.")

# 2. /help - Explains the game rules
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends game rules when /help is issued."""
    await update.message.reply_text(
        "📖 *Правила гри Скринька Пандори:*\n\n"
        "1. Ведучий (той, хто почав гру) запускає гру командою `/startgame` у груповому чаті.\n"
        "2. Інші учасники натискають кнопку «🙋‍♀️ Долучитись до гри», щоб приєднатися.\n"
        "3. Коли ведучий натискає «✅ Почати раунд», бот надсилає всім гравцям (окрім ведучого) повідомлення у приватні чати з проханням надіслати відповідь на уявне запитання.\n"
        "4. Гравці мають 60 секунд, щоб надіслати свою відповідь боту у приватний чат. Ведучий також може завершити збір відповідей достроково кнопкою в груповому чаті.\n"
        "5. Після збору відповідей, бот випадковим чином обирає одну з відповідей і показує її всім гравцям (окрім автора відповіді та ведучого) у приватних чатах.\n"
        "6. Гравці мають 60 секунд, щоб вгадати, хто є автором цієї відповіді, натиснувши на кнопку з ім'ям іншого гравця.\n"
        "7. Після завершення часу на вгадування, бот оголошує в груповому чаті, хто автор обраної відповіді, хто за кого голосував, і хто вгадав правильно.\n"
        "8. Гравці, які правильно вгадали автора, отримують 1 бал. Автор відповіді, яку не вгадали, також може отримувати бали (це можна додати як розширення гри).\n"
        "9. Гра може тривати декілька раундів. Ведучий може почати новий раунд кнопкою «🔄 Новий раунд».\n"
        "10. Перемагає найкмітливіший гравець з найбільшою кількістю балів!\n\n"
        "Використовуйте /score, щоб переглянути поточний рахунок.",
        parse_mode="Markdown"
    )

# 3. /startgame — Initiates the game in a group chat
async def startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiates a new game. Only works in group chats."""
    global joined_players, host_id, players, answers, group_chat_id, player_guesses, random_answer_data
    global collecting_answers_active, guessing_active

    chat_type = update.effective_chat.type
    if chat_type == "private":
        await update.message.reply_text("Цю команду можна використовувати лише в групових чатах.")
        return

    # Reset game state for a new game
    joined_players.clear()
    players.clear()
    answers.clear()
    player_guesses.clear()
    random_answer_data = None
    collecting_answers_active = False
    guessing_active = False

    host_id = update.effective_user.id
    group_chat_id = update.effective_chat.id # Store the group chat ID

    players[host_id] = {"name": update.effective_user.username or update.effective_user.first_name, "score": 0}
    joined_players.add(host_id) # Host is also a player (can be changed if host shouldn't play)

    await update.message.reply_text(
        f"🎲 Нова гра 'Скринька Пандори' розпочинається! Ведучий: {players[host_id]['name']}.\n"
        "Гравці, натисніть кнопку, щоб долучитись.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🙋‍♀️ Долучитись до гри", callback_data="join_game")],
            [InlineKeyboardButton("✅ Почати раунд", callback_data="begin_round")]
        ])
    )
    await context.bot.send_message(chat_id=group_chat_id, text=f"{players[host_id]['name']} долучився до гри як ведучий 🎉")


# 4. Button Handler — Handles all inline button presses
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles callbacks from inline buttons."""
    global joined_players, host_id, players, collecting_answers_active, guessing_active, group_chat_id, answer_collection_task
    query = update.callback_query
    user = query.from_user
    await query.answer() # Acknowledge the button press

    # --- Join Game Button ---
    if query.data == "join_game":
        if user.id in joined_players:
            await context.bot.send_message(
                chat_id=query.message.chat_id, # Send to group chat
                text=f"{user.first_name}, ти вже у грі! 😊"
            )
        else:
            joined_players.add(user.id)
            players[user.id] = {"name": user.username or user.first_name, "score": 0}
            await context.bot.send_message(
                chat_id=query.message.chat_id, # Send to group chat
                text=f"{players[user.id]['name']} долучився до гри 🎉"
            )

    # --- Begin Round Button (Host Only) ---
    elif query.data == "begin_round":
        if user.id != host_id:
            await query.answer("Тільки ведучий може почати раунд.", show_alert=True)
            return
        if len(joined_players) < 2: # Need at least 2 players (e.g., host + 1 other, or 2 non-hosts)
                                    # If host doesn't submit an answer, need at least 1 other player.
                                    # If host also submits an answer, need at least 2 players for guessing.
            await context.bot.send_message(chat_id=group_chat_id, text="Для початку раунду потрібно хоча б 2 гравці (включаючи ведучого, якщо він грає).")
            return
        await begin_round(context) # Pass context directly

    # --- End Answer Collection Early (Host Only) ---
    elif query.data == "end_collection_early":
        if user.id != host_id:
            await query.answer("Тільки ведучий може завершити збір відповідей.", show_alert=True)
            return
        if collecting_answers_active:
            if answer_collection_task:
                answer_collection_task.cancel() # Cancel the timeout task
            await end_answer_collection(context) # Proceed to end collection
        else:
            await query.answer("Збір відповідей ще не розпочато або вже завершено.", show_alert=True)

    # --- Guessing Buttons (Player Action) ---
    elif query.data.startswith("guess_") and guessing_active:
        if query.message.chat.type != "private":
            await query.answer("❗ Вгадування відбувається лише у приватних повідомленнях з ботом.", show_alert=True)
            return
        guessed_player_id = int(query.data.split("_")[1])
        await process_player_guess(update, context, guessed_player_id)

    # --- New Round Button (Host Only, appears after a round) ---
    elif query.data == "new_round":
        if user.id != host_id:
            await query.answer("Тільки ведучий може почати новий раунд.", show_alert=True)
            return
        await begin_round(context)


# 5. Begin Round — Starts the answer collection phase
async def begin_round(context: ContextTypes.DEFAULT_TYPE):
    """Starts a new round: resets answers, notifies players to submit answers."""
    global answers, collecting_answers_active, guessing_active, player_guesses, random_answer_data, group_chat_id, answer_collection_task

    if not group_chat_id:
        print("Error: group_chat_id not set before begin_round")
        # Potentially send a message to host if possible, or log error
        return

    answers.clear()
    player_guesses.clear()
    random_answer_data = None
    collecting_answers_active = True
    guessing_active = False

    # Message to the group chat
    host_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Завершити збір відповідей", callback_data="end_collection_early")]
    ])
    await context.bot.send_message(
        chat_id=group_chat_id,
        text="📝 Розпочато новий раунд! Учасники, перевірте приватні повідомлення від бота.\n"
             "У вас є 60 секунд, щоб надіслати свою відповідь.\n"
             "Ведучий може завершити збір достроково.",
        reply_markup=host_markup
    )

    # DM players to submit answers
    players_to_dm = [pid for pid in joined_players if pid != host_id] # Host doesn't submit an answer in this version
                                                                     # If host should also answer, remove `if pid != host_id`

    if not players_to_dm:
        await context.bot.send_message(
            chat_id=group_chat_id,
            text="🤷 Немає гравців для надсилання запиту на відповідь (окрім ведучого). Раунд не може бути проведений."
        )
        collecting_answers_active = False # Stop collection if no one to ask
        # Optionally, allow host to restart or add players
        await context.bot.send_message(
            chat_id=group_chat_id,
            text="Ведучий, ви можете спробувати почати новий раунд, коли гравці долучаться.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Новий раунд", callback_data="new_round")]])
        )
        return

    for user_id in players_to_dm:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="✍️ Будь ласка, напиши свою відповідь на (уявне) запитання ведучого та надішли її мені у відповідь на це повідомлення."
            )
        except Exception as e:
            print(f"Error sending DM to user {user_id}: {e}")
            await context.bot.send_message(
                chat_id=group_chat_id,
                text=f"⚠️ Не вдалося надіслати повідомлення гравцю {players.get(user_id, {}).get('name', user_id)}. Можливо, він не починав чат з ботом."
            )

    # Schedule the end of answer collection
    answer_collection_task = asyncio.create_task(schedule_end_collection(context, 60))


async def schedule_end_collection(context: ContextTypes.DEFAULT_TYPE, delay: int):
    """Waits for a 'delay' and then ends answer collection if still active."""
    await asyncio.sleep(delay)
    if collecting_answers_active: # Check if collection wasn't ended early by host
        await context.bot.send_message(
            chat_id=group_chat_id,
            text="⏰ Час на відповіді вийшов!"
        )
        await end_answer_collection(context)

# 6. Collect Answers — Handles messages from players in private chat
async def collect_player_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collects answers sent by players in private chat."""
    global collecting_answers_active, answers

    user = update.effective_user
    if update.message.chat.type != "private": # Only accept answers in DMs
        return

    if collecting_answers_active and user.id in joined_players and user.id != host_id: # Host doesn't answer
        if user.id not in answers:
            answers[user.id] = update.message.text
            await update.message.reply_text("✅ Ваша відповідь прийнята та збережена!")
            # Optional: Notify host or group that a player has answered
            # await context.bot.send_message(chat_id=group_chat_id, text=f"👍 {players[user.id]['name']} надіслав свою відповідь.")
        else:
            await update.message.reply_text("❗ Ви вже надіслали свою відповідь у цьому раунді.")
    elif not collecting_answers_active and user.id in joined_players:
        await update.message.reply_text("⚠️ На жаль, час для збору відповідей вже вийшов.")
    # Ignore messages if not collecting or user not in game

# 7. End Answer Collection — Transitions to the guessing phase
async def end_answer_collection(context: ContextTypes.DEFAULT_TYPE):
    """Ends the answer collection phase and starts the guessing phase if answers exist."""
    global collecting_answers_active, random_answer_data, guessing_active, group_chat_id

    collecting_answers_active = False # Stop collecting new answers

    if not answers:
        await context.bot.send_message(
            chat_id=group_chat_id,
            text="🙁 На жаль, жоден гравець не надіслав відповідь. Раунд завершено.\n"
                 "Ведучий, можете почати новий раунд.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Новий раунд", callback_data="new_round")]])
        )
        return

    # Select a random answer
    author_id, answer_text = random.choice(list(answers.items()))
    random_answer_data = {"author_id": author_id, "text": answer_text}
    guessing_active = True

    await context.bot.send_message(
        chat_id=group_chat_id,
        text=f"🤫 Збір відповідей завершено! Всього отримано: {len(answers)}.\n"
             f"Зараз я надішлю випадкову відповідь гравцям для вгадування. У вас буде 60 секунд."
    )

    # Prepare list of players for guessing (excluding the author of the random answer and the host)
    potential_authors_for_buttons = {
        pid: pdata["name"] for pid, pdata in players.items()
        if pid in answers and pid != host_id # Only those who submitted answers and are not the host
    }

    # Send the random answer to players (excluding author and host) for guessing
    for player_id in joined_players:
        if player_id == host_id or player_id == random_answer_data["author_id"]:
            continue # Host and author don't guess their own answer

        # Create buttons for guessing - show names of other players who submitted answers
        guess_buttons = []
        for p_id, p_name in potential_authors_for_buttons.items():
            if p_id != player_id: # A player cannot guess themselves
                 guess_buttons.append([InlineKeyboardButton(p_name, callback_data=f"guess_{p_id}")])

        if not guess_buttons:
            try:
                await context.bot.send_message(
                    chat_id=player_id,
                    text=f"📜 *Ось випадкова відповідь:*\n«{random_answer_data['text']}»\n\n"
                         f"🤔 На жаль, немає інших гравців, чию відповідь можна було б вгадати."
                         f"Очікуємо на результати.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"Error sending guess prompt (no buttons) to {player_id}: {e}")
            continue


        markup = InlineKeyboardMarkup(guess_buttons)
        try:
            await context.bot.send_message(
                chat_id=player_id,
                text=f"📜 *Ось випадкова відповідь:*\n«{random_answer_data['text']}»\n\n"
                     f"🕵️ Як ти думаєш, хто це написав? Обери зі списку нижче:",
                parse_mode="Markdown",
                reply_markup=markup
            )
        except Exception as e:
            print(f"Error sending guess prompt to user {player_id}: {e}")
            await context.bot.send_message(
                chat_id=group_chat_id,
                text=f"⚠️ Не вдалося надіслати запит на вгадування гравцю {players.get(player_id,{}).get('name', player_id)}."
            )

    # Schedule the end of guessing
    asyncio.create_task(schedule_end_guessing(context, 60))


async def schedule_end_guessing(context: ContextTypes.DEFAULT_TYPE, delay: int):
    """Waits for 'delay' and then ends guessing phase if still active."""
    await asyncio.sleep(delay)
    if guessing_active: # Check if results weren't processed earlier for some reason
        await context.bot.send_message(
            chat_id=group_chat_id,
            text="⏰ Час на вгадування вийшов!"
        )
        await end_guessing_phase(context)


# 8. Process Player Guess — Handles a player's guess from a private chat button
async def process_player_guess(update: Update, context: ContextTypes.DEFAULT_TYPE, guessed_player_id: int):
    """Processes a player's guess."""
    global player_guesses, guessing_active

    user = update.effective_user

    if not guessing_active:
        await update.callback_query.answer("⏳ Час для вгадування вже вийшов!", show_alert=True)
        return

    if user.id not in joined_players or user.id == host_id or user.id == random_answer_data["author_id"]:
        await update.callback_query.answer("🚫 Ти не можеш брати участь у вгадуванні цього разу.", show_alert=True)
        return

    if user.id in player_guesses:
        await update.callback_query.answer("❗ Ти вже зробив свій вибір у цьому раунді.", show_alert=True)
        return

    player_guesses[user.id] = guessed_player_id
    guessed_player_name = players.get(guessed_player_id, {}).get("name", "Невідомий гравець")
    await update.callback_query.edit_message_text(text=f"✅ Твій варіант ({guessed_player_name}) прийнято!")
    # await context.bot.send_message(chat_id=user.id, text=f"🕵️ Твій варіант ({guessed_player_name}) прийнято!")


# 9. End Guessing Phase — Calculates scores and announces results
async def end_guessing_phase(context: ContextTypes.DEFAULT_TYPE):
    """Ends the guessing phase, calculates scores, and announces results."""
    global guessing_active, players, player_guesses, random_answer_data, group_chat_id

    if not guessing_active: # Avoid double processing
        return
    guessing_active = False

    if not random_answer_data:
        await context.bot.send_message(chat_id=group_chat_id, text="Сталася помилка: не знайдено випадкову відповідь для перевірки.")
        return

    author_id = random_answer_data["author_id"]
    author_name = players.get(author_id, {}).get("name", "Невідомий автор")
    random_answer_text = random_answer_data["text"]

    results_message = f"🧐 *Результати раунду!*\n\nОбрана відповідь: «{random_answer_text}»\n"
    results_message += f"✍️ Автор цієї відповіді: *{author_name}*\n\n"

    # --- Requirement 5: Show who voted for whom ---
    if player_guesses:
        results_message += "🗳 *Хто за кого голосував:*\n"
        for guesser_id, guessed_id in player_guesses.items():
            guesser_name = players.get(guesser_id, {}).get("name", f"Гравець {guesser_id}")
            choice_name = players.get(guessed_id, {}).get("name", f"Гравець {guessed_id}")
            results_message += f"  - {guesser_name} подумав(ла) на: *{choice_name}*\n"
    else:
        results_message += "💨 Ніхто не намагався вгадати.\n"
    results_message += "\n"

    winners = []
    for guesser_user_id, guessed_author_id in player_guesses.items():
        if guessed_author_id == author_id:
            winners.append(guesser_user_id)
            players[guesser_user_id]["score"] += 1

    if winners:
        winner_names = ", ".join([players[uid]["name"] for uid in winners])
        results_message += f"🎉 *Правильно вгадали: {winner_names}!* Вони отримують по 1 балу.\n"
    else:
        results_message += f"💔 *На жаль, цього разу ніхто не вгадав правильно.*\n"

    await context.bot.send_message(chat_id=group_chat_id, text=results_message, parse_mode="Markdown")
    await show_current_scores(context, group_chat_id) # Show scores after results

    # Offer host to start a new round
    host_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Новий раунд", callback_data="new_round")],
        [InlineKeyboardButton("📊 Рахунок", callback_data="show_score_button")] # Can be handled by /score too
    ])
    await context.bot.send_message(
        chat_id=group_chat_id,
        text="Ведучий, бажаєте почати новий раунд?",
        reply_markup=host_markup
    )

# 10. /score or button "Show Score" — Displays current scores
async def show_current_scores_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /score command to show scores."""
    chat_id_to_send = update.effective_chat.id
    await show_current_scores(context, chat_id_to_send)

async def show_current_scores_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'show_score_button' callback to show scores."""
    query = update.callback_query
    await query.answer()
    chat_id_to_send = query.message.chat_id
    await show_current_scores(context, chat_id_to_send, message_to_edit=query.message)


async def show_current_scores(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_to_edit=None):
    """Helper function to format and send the current scores."""
    if not players:
        score_text = "🏆 Рахунок:\nЩе ніхто не грав або рахунки порожні."
    else:
        score_text = "🏆 *Поточний Рахунок:*\n"
        sorted_players = sorted(players.items(), key=lambda item: item[1]["score"], reverse=True)
        for user_id, data in sorted_players:
            score_text += f"  - {data['name']}: {data['score']} бал(ів)\n"

    if message_to_edit:
        try:
            await message_to_edit.edit_text(text=score_text, parse_mode="Markdown")
        except Exception: # If message is identical or other error, send new
            await context.bot.send_message(chat_id=chat_id, text=score_text, parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id=chat_id, text=score_text, parse_mode="Markdown")


# Main function to set up and run the bot
def main():
    """Sets up the bot handlers and starts polling."""
    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env file or environment variables.")
        return

    print("Bot is starting...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Command Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("startgame", startgame))
    app.add_handler(CommandHandler("score", show_current_scores_command))

    # Callback Query Handler (for all inline buttons)
    app.add_handler(CallbackQueryHandler(button_handler))

    # Message Handler (for collecting answers in private chat)
    # Filters for text messages, in private chat, and not commands
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, collect_player_answers))

    print("Bot is polling for updates...")
    app.run_polling()

if __name__ == "__main__":
    main()
