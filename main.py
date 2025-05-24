import json
import logging
import os
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

DATA_FILE = "data.json"
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g., https://yourapp.onrender.com/

# Conversation states
(
    ADD_PERSON,
    REMOVE_PERSON,
    LIST_PERSON,
    ADD_ACCOUNT,
    REMOVE_ACCOUNT,
    ADD_SUB_PERSON,
    ADD_SUB_ACCOUNT,
    ADD_SUB_SLOT,
    ADD_SUB_SERVICE,
    ADD_SUB_DURATION,
    SET_PRICE_SERVICE,
    SET_PRICE_DURATION,
    SET_PRICE_AMOUNT,
) = range(13)

# Load or initialize data structure
def load_data():
    if not os.path.isfile(DATA_FILE):
        data = {
            "people": {},  # person_name -> {"subscriptions": [], "last_active": str}
            "accounts": {},  # account_name -> {"service": str, "slots": {slot_num: person_name or None}}
            "services": {},  # service_name -> {"emoji": str, "durations": {days: price}}
        }
        save_data(data)
    else:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
    return data


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def cleanup_expired_subs():
    """Remove subscriptions expired > 60 days ago and free slots"""
    data = load_data()
    now = datetime.utcnow()
    changed = False

    for person_name in list(data["people"].keys()):
        person = data["people"][person_name]
        new_subs = []
        for sub in person.get("subscriptions", []):
            end_date = datetime.strptime(sub["end_date"], "%Y-%m-%d")
            if (now - end_date).days <= 60:
                new_subs.append(sub)
            else:
                # Free the slot if exists
                account = data["accounts"].get(sub["account"])
                if account:
                    slot_num = sub.get("slot")
                    if slot_num and account["slots"].get(str(slot_num)) == person_name:
                        account["slots"][str(slot_num)] = None
                        changed = True
                changed = True
        person["subscriptions"] = new_subs

        # Remove person if no subscriptions for more than 10 days (inactive)
        if (
            len(person["subscriptions"]) == 0
            and "last_active" in person
            and (now - datetime.strptime(person["last_active"], "%Y-%m-%d")).days > 10
        ):
            del data["people"][person_name]
            changed = True

    if changed:
        save_data(data)


# Helper to build inline keyboard from a list of tuples [(text, callback_data), ...]
def build_menu(items, n_cols):
    menu = []
    for i in range(0, len(items), n_cols):
        menu.append(
            [InlineKeyboardButton(text, callback_data=cb) for text, cb in items[i : i + n_cols]]
        )
    return menu


# ======= BOT COMMANDS =======

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cleanup_expired_subs()
    keyboard = [
        [InlineKeyboardButton("Add Person", callback_data="add_person")],
        [InlineKeyboardButton("Remove Person", callback_data="remove_person")],
        [InlineKeyboardButton("List People", callback_data="list_people")],
        [InlineKeyboardButton("Add Account", callback_data="add_account")],
        [InlineKeyboardButton("Remove Account", callback_data="remove_account")],
        [InlineKeyboardButton("Add Subscription", callback_data="add_subscription")],
        [InlineKeyboardButton("Set Prices", callback_data="set_prices")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Welcome! Choose an action from the menu:", reply_markup=reply_markup
    )


# ------- Add Person -------
async def add_person_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Please send the name of the person to add:")
    return ADD_PERSON


async def add_person_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    person_name = update.message.text.strip()
    data = load_data()

    if person_name in data["people"]:
        await update.message.reply_text("Person already exists.")
    else:
        data["people"][person_name] = {"subscriptions": [], "last_active": datetime.utcnow().strftime("%Y-%m-%d")}
        save_data(data)
        await update.message.reply_text(f"Person '{person_name}' added.")

    return ConversationHandler.END


# ------- Remove Person -------
async def remove_person_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    await update.callback_query.answer()
    if not data["people"]:
        await update.callback_query.edit_message_text("No people found.")
        return ConversationHandler.END

    buttons = [
        (name, f"remove_person_{name}") for name in data["people"].keys()
    ]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 2))
    await update.callback_query.edit_message_text(
        "Select a person to remove:", reply_markup=keyboard
    )
    return REMOVE_PERSON


async def remove_person_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    person_name = query.data.replace("remove_person_", "")
    data = load_data()
    if person_name in data["people"]:
        del data["people"][person_name]
        save_data(data)
        await query.edit_message_text(f"Person '{person_name}' removed.")
    else:
        await query.edit_message_text("Person not found.")
    return ConversationHandler.END


# ------- List People -------
async def list_people(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data["people"]:
        await update.message.reply_text("No people found.")
        return

    text = "People and their subscriptions:\n"
    for person, info in data["people"].items():
        text += f"\n👤 {person}:\n"
        if not info["subscriptions"]:
            text += "  - No active subscriptions\n"
        else:
            for sub in info["subscriptions"]:
                text += (
                    f"  - {sub['service']} on account {sub['account']} (Slot {sub.get('slot', '-')}) "
                    f"until {sub['end_date']} ({sub['duration']} days)\n"
                )
    await update.message.reply_text(text)


# ------- Add Account -------
async def add_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Send new account name (e.g. Netflix user@gmail.com):")
    return ADD_ACCOUNT


async def add_account_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    account_name = update.message.text.strip()
    data = load_data()
    if account_name in data["accounts"]:
        await update.message.reply_text("Account already exists.")
    else:
        # Ask for service for the account
        data["accounts"][account_name] = {"service": None, "slots": {"1": None, "2": None, "3": None, "4": None}}
        save_data(data)
        context.user_data["new_account"] = account_name
        await update.message.reply_text(
            "Account added. Now please send the service name this account belongs to (e.g., Netflix, Spotify)."
        )
        return ADD_ACCOUNT + 100  # special state for setting service


async def add_account_service_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    service_name = update.message.text.strip()
    data = load_data()
    account_name = context.user_data.get("new_account")
    if account_name and account_name in data["accounts"]:
        data["accounts"][account_name]["service"] = service_name
        save_data(data)
        await update.message.reply_text(
            f"Service '{service_name}' set for account '{account_name}'."
        )
    else:
        await update.message.reply_text("Error setting service for account.")
    return ConversationHandler.END


# ------- Remove Account -------
async def remove_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    await update.callback_query.answer()
    if not data["accounts"]:
        await update.callback_query.edit_message_text("No accounts found.")
        return ConversationHandler.END

    buttons = [
        (acc, f"remove_account_{acc}") for acc in data["accounts"].keys()
    ]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 2))
    await update.callback_query.edit_message_text(
        "Select an account to remove:", reply_markup=keyboard
    )
    return REMOVE_ACCOUNT


async def remove_account_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_name = query.data.replace("remove_account_", "")
    data = load_data()
    if account_name in data["accounts"]:
        del data["accounts"][account_name]
        save_data(data)
        await query.edit_message_text(f"Account '{account_name}' removed.")
    else:
        await query.edit_message_text("Account not found.")
    return ConversationHandler.END


# ------- Add Subscription -------

# Step 1: Ask person name
async def add_sub_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Send the person's name to add subscription for:")
    return ADD_SUB_PERSON


async def add_sub_person_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    person_name = update.message.text.strip()
    data = load_data()
    if person_name not in data["people"]:
        await update.message.reply_text("Person not found. Please add the person first using Add Person.")
        return ConversationHandler.END
    context.user_data["sub_person"] = person_name

    # Show accounts as buttons to pick from
    data = load_data()
    if not data["accounts"]:
        await update.message.reply_text("No accounts found. Please add accounts first.")
        return ConversationHandler.END

    buttons = [
        (acc, f"add_sub_account_{acc}") for acc in data["accounts"].keys()
    ]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 2))
    await update.message.reply_text("Choose an account:", reply_markup=keyboard)
    return ADD_SUB_ACCOUNT


async def add_sub_account_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_name = query.data.replace("add_sub_account_", "")
    context.user_data["sub_account"] = account_name

    # Show free slots in the account (1-4)
    data = load_data()
    account = data["accounts"].get(account_name)
    if not account:
        await query.edit_message_text("Account not found. Aborting.")
        return ConversationHandler.END

    slots = account["slots"]
    buttons = []
    for slot_num in sorted(slots.keys()):
        val = slots[slot_num]
        emoji = "✅" if val is None else "❌"
        buttons.append((f"Slot {slot_num} {emoji}", f"add_sub_slot_{slot_num}"))

    keyboard = InlineKeyboardMarkup(build_menu(buttons, 2))
    await query.edit_message_text("Choose a free slot:", reply_markup=keyboard)
    return ADD_SUB_SLOT


async def add_sub_slot_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    slot_num = query.data.replace("add_sub_slot_", "")
    context.user_data["sub_slot"] = slot_num

    # Show services to pick
    data = load_data()
    services = data["services"]
    if not services:
        await query.edit_message_text("No services found. Please add services and prices first.")
        return ConversationHandler.END

    buttons = []
    for svc, info in services.items():
        text = f"{info.get('emoji', '')} {svc}"
        buttons.append((text, f"add_sub_service_{svc}"))
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 2))
    await query.edit_message_text("Choose a service:", reply_markup=keyboard)
    return ADD_SUB_SERVICE


async def add_sub_service_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    service_name = query.data.replace("add_sub_service_", "")
    context.user_data["sub_service"] = service_name

    # Show durations for this service
    data = load_data()
    service = data["services"].get(service_name)
    if not service:
        await query.edit_message_text("Service not found. Aborting.")
        return ConversationHandler.END

    durations = service.get("durations", {})
    if not durations:
        await query.edit_message_text("No durations found for this service.")
        return ConversationHandler.END

    buttons = []
    for dur in durations.keys():
        buttons.append((f"{dur} days", f"add_sub_duration_{dur}"))
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 2))
    await query.edit_message_text("Choose a subscription duration:", reply_markup=keyboard)
    return ADD_SUB_DURATION


async def add_sub_duration_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    duration_days = int(query.data.replace("add_sub_duration_", ""))
    context.user_data["sub_duration"] = duration_days

    # Calculate end date and add subscription
    person_name = context.user_data["sub_person"]
    account_name = context.user_data["sub_account"]
    slot_num = context.user_data["sub_slot"]
    service_name = context.user_data["sub_service"]
    duration = duration_days

    end_date = (datetime.utcnow() + timedelta(days=duration)).strftime("%Y-%m-%d")

    data = load_data()

    # Check slot availability again (race condition prevention)
    if data["accounts"][account_name]["slots"].get(str(slot_num)) is not None:
        await query.edit_message_text("Selected slot is already occupied. Try again.")
        return ConversationHandler.END

    # Assign slot
    data["accounts"][account_name]["slots"][str(slot_num)] = person_name

    # Add subscription to person
    sub = {
        "account": account_name,
        "slot": int(slot_num),
        "service": service_name,
        "duration": duration,
        "end_date": end_date,
    }

    if person_name not in data["people"]:
        data["people"][person_name] = {"subscriptions": [], "last_active": datetime.utcnow().strftime("%Y-%m-%d")}

    data["people"][person_name]["subscriptions"].append(sub)
    data["people"][person_name]["last_active"] = datetime.utcnow().strftime("%Y-%m-%d")
    save_data(data)

    await query.edit_message_text(
        f"Subscription added for {person_name}: {service_name} on {account_name}, slot {slot_num}, until {end_date}."
    )
    return ConversationHandler.END


# ------- Set Prices -------
async def set_prices_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    keyboard = [
        [InlineKeyboardButton("Add/Modify Service", callback_data="set_price_add_service")],
        [InlineKeyboardButton("Back to Main Menu", callback_data="start")],
    ]
    await update.callback_query.edit_message_text(
        "Price settings menu:", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SET_PRICE_SERVICE


async def set_price_add_service_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "Send the name of the service to add or modify (e.g., Netflix):"
    )
    return SET_PRICE_SERVICE


async def set_price_service_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    service_name = update.message.text.strip()
    context.user_data["price_service"] = service_name
    data = load_data()

    if service_name not in data["services"]:
        # Add new service with empty emoji and durations
        data["services"][service_name] = {"emoji": "", "durations": {}}
        save_data(data)
        await update.message.reply_text(f"Added new service '{service_name}'. Now send the emoji for it:")
        return SET_PRICE_DURATION
    else:
        await update.message.reply_text(
            f"Service '{service_name}' found. Send the emoji to update it or type '-' to skip:"
        )
        return SET_PRICE_DURATION


async def set_price_duration_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    emoji = update.message.text.strip()
    data = load_data()
    service_name = context.user_data["price_service"]

    if emoji != "-":
        data["services"][service_name]["emoji"] = emoji
        save_data(data)
        await update.message.reply_text(
            f"Emoji set to '{emoji}' for service '{service_name}'. Now send the duration in days (e.g., 30):"
        )
    else:
        await update.message.reply_text("Emoji skipped. Now send the duration in days (e.g., 30):")
    return SET_PRICE_AMOUNT


async def set_price_amount_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        duration = int(update.message.text.strip())
        context.user_data["price_duration"] = duration
        await update.message.reply_text(f"Duration set to {duration} days. Now send the price (number):")
        return SET_PRICE_AMOUNT + 1
    except ValueError:
        await update.message.reply_text("Please send a valid integer for duration (days).")
        return SET_PRICE_AMOUNT


async def set_price_save_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.strip())
        data = load_data()
        service_name = context.user_data["price_service"]
        duration = context.user_data["price_duration"]
        data["services"][service_name]["durations"][duration] = price
        save_data(data)
        await update.message.reply_text(
            f"Price for {service_name} ({duration} days) set to {price}."
        )
    except ValueError:
        await update.message.reply_text("Please send a valid number for price.")
        return SET_PRICE_AMOUNT + 1
    return ConversationHandler.END


# ------- Unknown command -------
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sorry, I didn't understand that command.")


# ======= MAIN FUNCTION =======
def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("list", list_people))

    # Conversation handlers for multi-step commands
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start, pattern="^start$")],
        states={
            ADD_PERSON: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_person_receive)],
            REMOVE_PERSON: [CallbackQueryHandler(remove_person_confirm, pattern="^remove_person_")],
            ADD_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_receive)],
            ADD_ACCOUNT + 100: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_service_receive)],
            REMOVE_ACCOUNT: [CallbackQueryHandler(remove_account_confirm, pattern="^remove_account_")],
            ADD_SUB_PERSON: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_sub_person_receive)],
            ADD_SUB_ACCOUNT: [CallbackQueryHandler(add_sub_account_choose, pattern="^add_sub_account_")],
            ADD_SUB_SLOT: [CallbackQueryHandler(add_sub_slot_choose, pattern="^add_sub_slot_")],
            ADD_SUB_SERVICE: [CallbackQueryHandler(add_sub_service_choose, pattern="^add_sub_service_")],
            ADD_SUB_DURATION: [CallbackQueryHandler(add_sub_duration_choose, pattern="^add_sub_duration_")],
            SET_PRICE_SERVICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_price_service_receive)],
            SET_PRICE_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_price_duration_receive)],
            SET_PRICE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_price_amount_receive)],
            SET_PRICE_AMOUNT + 1: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_price_save_amount)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    # CallbackQueryHandlers for main menu buttons
    application.add_handler(CallbackQueryHandler(add_person_start, pattern="^add_person$"))
    application.add_handler(CallbackQueryHandler(remove_person_start, pattern="^remove_person$"))
    application.add_handler(CallbackQueryHandler(remove_account_start, pattern="^remove_account$"))
    application.add_handler(CallbackQueryHandler(add_account_start, pattern="^add_account$"))
    application.add_handler(CallbackQueryHandler(add_sub_start, pattern="^add_subscription$"))
    application.add_handler(CallbackQueryHandler(set_prices_start, pattern="^set_prices$"))

    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Set webhook
    async def on_startup(application):
        await application.bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook set to {WEBHOOK_URL}")

    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        webhook_url=WEBHOOK_URL,
        on_startup=on_startup,
    )


if __name__ == "__main__":
    main()
