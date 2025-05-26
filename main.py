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
WEBHOOK_URL = os.getenv("WEBHOOK_URL") # e.g., https://yourapp.onrender.com/

# Conversation states
(
    # Basic operations
    CHOOSE_PERSON_TO_ADD,
    CHOOSE_PERSON_TO_REMOVE,

    # ADD_ACCOUNT flow
    GET_ACCOUNT_DETAILS,
    GET_ACCOUNT_SERVICE,

    # REMOVE_ACCOUNT flow
    CHOOSE_ACCOUNT_TO_REMOVE,

    # ADD_SUBSCRIPTION flow (New Order: Person -> Service -> Account -> Slot -> Duration)
    SUB_CHOOSE_PERSON,
    SUB_CHOOSE_SERVICE,
    SUB_CHOOSE_ACCOUNT,
    SUB_CHOOSE_SLOT,
    SUB_CHOOSE_DURATION,

    # SET_PRICES flow
    PRICE_MAIN_MENU,
    PRICE_GET_SERVICE_NAME,
    PRICE_GET_EMOJI,
    PRICE_GET_DURATION_DAYS,
    PRICE_GET_PRICE_AMOUNT,

    # REMOVE_PRICE_OPTION flow (New sub-flow for set_prices)
    PRICE_REMOVE_SELECT_SERVICE,
    PRICE_REMOVE_SELECT_DURATION,

    # REMOVE_SUBSCRIPTION flow (/removesub command)
    REMSUB_CHOOSE_PERSON,
    REMSUB_CHOOSE_SUBSCRIPTION,
    REMSUB_CONFIRM_DELETION
) = range(20)


def load_data():
    if not os.path.isfile(DATA_FILE):
        data = {
            "people": {},
            "accounts": {},
            "services": {},
            "default_slots": {}
        }
        save_data(data)
    else: 
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
    if "default_slots" not in data:
        data["default_slots"] = {}
    return data


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def cleanup_expired_subs():
    data = load_data()
    now = datetime.utcnow()
    changed = False

    for person_name in list(data["people"].keys()):
        person = data["people"][person_name]
        new_subs = []
        for sub in person.get("subscriptions", []):
            try:
                end_date = datetime.strptime(sub["end_date"], "%Y-%m-%d")
                if (now - end_date).days <= 60:
                    new_subs.append(sub)
                else: 
                    logger.info(f"Subscription for {person_name} ({sub.get('service')}) expired on {sub['end_date']}, removing.")
                    account = data["accounts"].get(sub["account"])
                    if account:
                        slot_num = sub.get("slot")
                        if slot_num is not None and account["slots"].get(str(slot_num)) == person_name: 
                            account["slots"][str(slot_num)] = None
                            logger.info(f"Freed slot {slot_num} in account {sub['account']} from {person_name}.")
                            changed = True 
                    changed = True 
            except ValueError:
                logger.error(f"Could not parse end_date for subscription: {sub}")
                new_subs.append(sub) 

        if len(person["subscriptions"]) != len(new_subs):
            person["subscriptions"] = new_subs
            changed = True

        if (
            len(person["subscriptions"]) == 0
            and "last_active" in person
        ): 
            try:
                last_active_date = datetime.strptime(person["last_active"], "%Y-%m-%d")
                if (now - last_active_date).days > 10:
                    logger.info(f"Removing inactive person {person_name} (no subs, last active {person['last_active']}).")
                    del data["people"][person_name] 
                    changed = True
            except ValueError:
                logger.error(f"Could not parse last_active_date for person: {person_name}")

    if changed:
        save_data(data)


def build_menu(items, n_cols):
    menu = []
    for i in range(0, len(items), n_cols):
        menu.append( 
            [InlineKeyboardButton(text, callback_data=cb) for text, cb in items[i : i + n_cols]]
        )
    return menu

# --- Helper function for main menu components ---
def _get_main_menu_components():
    welcome_msg = """
🌟 *Welcome to Subscription Manager Bot!* 🌟

I'll help you track shared subscriptions, accounts, and payments.
Let's make managing shared accounts *easy peasy*!
What would you like to do today?
"""
    keyboard_buttons = [
        [InlineKeyboardButton("👤 Add Person", callback_data="add_person_start")],
        [InlineKeyboardButton("🗑️ Remove Person", callback_data="remove_person_start")],
        [InlineKeyboardButton("📜 List People", callback_data="list_people_cmd")],
        [InlineKeyboardButton("🔑 Add Account", callback_data="add_account_start")],
        [InlineKeyboardButton("🚮 Remove Account", callback_data="remove_account_start")],
        [InlineKeyboardButton("💳 Add Subscription", callback_data="add_sub_start")],
        [InlineKeyboardButton("💰 Set Prices", callback_data="set_prices_start")],
        [InlineKeyboardButton("📊 List Subscriptions", callback_data="list_subs_cmd")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard_buttons)
    return welcome_msg, reply_markup

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the main menu. Edits if from a callback query, replies if from a command."""
    welcome_msg, reply_markup = _get_main_menu_components()
    
    if update.message: # User typed /start
        await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=reply_markup)
    elif update.callback_query: # Menu was reached from a button press that directly led to 'start' (e.g. "Back to Menu" type buttons on the main menu itself)
        try:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(welcome_msg, parse_mode="Markdown", reply_markup=reply_markup)
        except Exception as e: 
            logger.warning(f"Failed to edit message in start() for callback_query: {e}. Sending new message.")
            await context.bot.send_message(chat_id=update.effective_chat.id, text=welcome_msg, parse_mode="Markdown", reply_markup=reply_markup)
    
    return ConversationHandler.END

async def send_main_menu_new_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Always sends the main menu as a new message."""
    welcome_msg, reply_markup = _get_main_menu_components()
    await context.bot.send_message(chat_id=update.effective_chat.id, text=welcome_msg, parse_mode="Markdown", reply_markup=reply_markup)


# ======= BOT COMMANDS =======

async def handle_list_people_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # list_people will now edit the message to show the list
    await list_people(update, context, from_callback=True) 
    # Then send a new message with the main menu
    await send_main_menu_new_message(update, context)

async def handle_list_subs_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # list_subscriptions will now edit the message to show the list
    await list_subscriptions(update, context, from_callback=True) 
    # Then send a new message with the main menu
    await send_main_menu_new_message(update, context)


# Add Person handlers
async def add_person_start_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("👋 Who's joining the subscription party? Send me their name:") 
    return CHOOSE_PERSON_TO_ADD


async def add_person_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    person_name = update.message.text.strip()
    data = load_data()

    if person_name in data["people"]:
        await update.message.reply_text(f"🤔 Hmm, {person_name} is already in our system! Maybe they want another subscription?")
    else:
        data["people"][person_name] = {"subscriptions": [], "last_active": datetime.utcnow().strftime("%Y-%m-%d")}
        save_data(data)
        await update.message.reply_text(f"🎉 Welcome aboard, {person_name}! I've added you to our family.")
    # For MessageHandlers, start() already sends a new message, which is fine.
    await start(update, context) 
    return ConversationHandler.END


# Remove Person handlers
async def remove_person_start_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    await update.callback_query.answer()
    if not data["people"]:
        await update.callback_query.edit_message_text("😶 It's empty here... No people to remove!")
        # No further action, let user click a main menu button if presented, or /start
        # Or send new menu: await send_main_menu_new_message(update, context)
        return ConversationHandler.END # Keep it simple, let them re-initiate

    buttons = [(f"👤 {name}", f"remove_person_{name}") for name in data["people"].keys()]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 2))
    await update.callback_query.edit_message_text("Who's leaving us? 😢 Pick someone:", reply_markup=keyboard) 
    return CHOOSE_PERSON_TO_REMOVE


async def remove_person_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    person_name = query.data.replace("remove_person_", "")
    data = load_data()
    feedback_message = ""
    if person_name in data["people"]:
        for acc_name, acc_details in data["accounts"].items():
            for slot_num, occupant in list(acc_details["slots"].items()):
                if occupant == person_name: 
                    acc_details["slots"][slot_num] = None
                    logger.info(f"Freed slot {slot_num} in account {acc_name} as {person_name} is being removed.")
        del data["people"][person_name] 
        save_data(data)
        feedback_message = f"👋 Farewell, {person_name}! I've removed them and freed up their slots."
    else:
        feedback_message = "🤨 Hmm, I can't find that person. Maybe they already left?"
    
    await query.edit_message_text(feedback_message)
    await send_main_menu_new_message(update, context) 
    return ConversationHandler.END


# List People handler
async def list_people(update: Update, context: ContextTypes.DEFAULT_TYPE, from_callback=False):
    data = load_data()
    # reply_fn will be edit_message_text if from_callback is True
    reply_fn = update.callback_query.edit_message_text if from_callback and update.callback_query else context.bot.send_message 
    chat_id_to_use = update.effective_chat.id if not (from_callback and update.callback_query) else None


    if not data["people"]:
        msg_text = "🦗 Cricket sounds... No people found. Wanna invite someone?"
        if chat_id_to_use:
            await reply_fn(chat_id=chat_id_to_use, text=msg_text)
        elif update.callback_query:
            await update.callback_query.edit_message_text(msg_text)
        # No automatic return to menu here, handled by the calling button handler
        return

    text = "📋 *Current Members & Their Subscriptions:*\n"
    for person, info in data["people"].items(): 
        text += f"\n🌟 *{person}* (Last active: {info.get('last_active', 'N/A')}):\n"
        if not info["subscriptions"]:
            text += "  - Just chilling with no subscriptions\n"
        else:
            for sub in info["subscriptions"]:
                text += (
                    f"  - {sub['service']} on {sub['account']} (Slot {sub.get('slot', '-')}) " 
                    f"until {sub['end_date']} ({sub['duration']} days) - Price: ${sub.get('price', 'N/A')}\n"
                )
    
    if chat_id_to_use:
        await reply_fn(chat_id=chat_id_to_use, text=text, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown")
    # No automatic return to menu here, handled by the calling button handler


# Add Account handlers
async def add_account_start_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer() 
    await update.callback_query.edit_message_text("🔐 Let's add a new account! What's the account identifier? (e.g. 'Netflix Main' or 'spotify_user@example.com')") 
    return GET_ACCOUNT_DETAILS


async def add_account_get_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    account_name = update.message.text.strip()
    data = load_data()
    if account_name in data["accounts"]:
        await update.message.reply_text("🤷‍♂️ Oops, we already have an account with that identifier! Try a different one.")
        return GET_ACCOUNT_DETAILS

    context.user_data["new_account_name"] = account_name
    
    services = list(data["services"].keys())
    if not services: 
        await update.message.reply_text("👍 Account name noted! However, no services (like Netflix, Spotify) are defined yet. Please use 'Set Prices' from the main menu to add a service first. Then you can link this account.")
        data["accounts"][account_name] = {"service": None, "slots": {}}
        save_data(data)
        await update.message.reply_text(f"Account '{account_name}' added, but no service linked. You might need to manage this manually or add services first.") 
        await start(update, context) # This will send a new message
        return ConversationHandler.END

    buttons = [(f"{data['services'][s]['emoji']} {s}", f"addacc_service_{s}") for s in services]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 2))
    await update.message.reply_text(
        f"👍 Account '{account_name}' will be added. Now, which service is this account for?",
        reply_markup=keyboard
    )
    return GET_ACCOUNT_SERVICE


async def add_account_set_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    service_name = query.data.replace("addacc_service_", "")
    
    account_name = context.user_data.get("new_account_name")
    if not account_name:
        await query.edit_message_text("😕 Oops, something went wrong (couldn't find account name). Let's try that again from the start.")
        await send_main_menu_new_message(update, context)
        return ConversationHandler.END

    data = load_data()
    data["accounts"][account_name] = {"service": service_name, "slots": {}}
    
    default_slots_count = data.get("default_slots", {}).get(service_name, 0)
    if default_slots_count > 0:
        for i in range(1, int(default_slots_count) + 1):
            data["accounts"][account_name]["slots"][str(i)] = None
        logger.info(f"Added {default_slots_count} default slots to new account {account_name} for service {service_name}.")

    save_data(data)
    await query.edit_message_text(f"✨ Perfect! Account '{account_name}' is now linked to {service_name} and default slots (if any) have been added.") 
    await send_main_menu_new_message(update, context)
    return ConversationHandler.END


# Remove Account handlers
async def remove_account_start_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    await update.callback_query.answer()
    if not data["accounts"]:
        await update.callback_query.edit_message_text("🤷‍♀️ No accounts to remove! Everything's clean.")
        # await send_main_menu_new_message(update, context)
        return ConversationHandler.END

    buttons = [(f"🔑 {name} ({data['accounts'][name].get('service', 'N/A')})", f"remove_account_{name}") for name in data["accounts"].keys()] 
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 1))
    await update.callback_query.edit_message_text("Which account should we say goodbye to? 👋", reply_markup=keyboard)
    return CHOOSE_ACCOUNT_TO_REMOVE


async def remove_account_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_name = query.data.replace("remove_account_", "")
    data = load_data()
    feedback_message = ""
    if account_name in data["accounts"]:
        active_subs_on_account = False
        for person_info in data["people"].values(): 
            for sub in person_info.get("subscriptions", []):
                if sub.get("account") == account_name:
                    active_subs_on_account = True
                    break
            if active_subs_on_account:
                break 
        
        if active_subs_on_account:
            feedback_message = f"⚠️ Account '{account_name}' still has active subscriptions! Please remove those subscriptions first before deleting the account."
        else:
            del data["accounts"][account_name]
            save_data(data)
            feedback_message = f"🗑️ Poof! Account '{account_name}' is gone."
    else:
        feedback_message = "🤨 That account doesn't exist. Magic?"
    
    await query.edit_message_text(feedback_message)
    await send_main_menu_new_message(update, context)
    return ConversationHandler.END


# Add Subscription handlers
async def add_sub_start_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    await update.callback_query.answer()
    if not data["people"]:
        await update.callback_query.edit_message_text("😅 Oops, no people yet! Add someone first so they can enjoy subscriptions.")
        # await send_main_menu_new_message(update, context)
        return ConversationHandler.END
    buttons = [(f"👤 {name}", f"addsub_person_{name}") for name in data["people"].keys()]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 2))
    await update.callback_query.edit_message_text("Who's getting a new subscription? 🎁", reply_markup=keyboard) 
    return SUB_CHOOSE_PERSON


async def add_sub_person_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    person_name = query.data.replace("addsub_person_", "")
    context.user_data["addsub_person"] = person_name
    data = load_data()

    if not data["services"]:
        await query.edit_message_text("😲 No services (like Netflix, Spotify) defined yet! Please use 'Set Prices' from the main menu to add services and their pricing first.")
        await send_main_menu_new_message(update, context)
        return ConversationHandler.END

    buttons = [(f"{data['services'][s]['emoji']} {s}", f"addsub_service_{s}") for s in data["services"].keys()] 
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 2))
    await query.edit_message_text(f"Great! Which service is this subscription for {person_name}?", reply_markup=keyboard)
    return SUB_CHOOSE_SERVICE


async def add_sub_service_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    service_name = query.data.replace("addsub_service_", "")
    context.user_data["addsub_service"] = service_name
    data = load_data()

    filtered_accounts = {name: acc_info for name, acc_info in data["accounts"].items() if acc_info.get("service") == service_name}

    if not filtered_accounts: 
        await query.edit_message_text(f"😲 No accounts found for the service '{service_name}'. Add an account for this service first.") 
        await send_main_menu_new_message(update, context) 
        return ConversationHandler.END

    buttons = [(f"🔑 {name}", f"addsub_account_{name}") for name in filtered_accounts.keys()]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 1)) 
    await query.edit_message_text(f"Got it, service is {service_name}. Now, which account (for {service_name}) should we use? 🤔", reply_markup=keyboard)
    return SUB_CHOOSE_ACCOUNT


async def add_sub_account_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_name = query.data.replace("addsub_account_", "") 
    context.user_data["addsub_account"] = account_name
    data = load_data()
    account = data["accounts"].get(account_name)

    if not account:
        await query.edit_message_text("🤯 Account vanished! Maybe it was removed? Please try again.")
        await send_main_menu_new_message(update, context)
        return ConversationHandler.END

    free_slots = {num: holder for num, holder in account.get("slots", {}).items() if holder is None}
    
    if not account.get("slots"): 
         await query.edit_message_text(f"😫 Account '{account_name}' has no slots defined. You can add slots using /add_slot {account_name} <slot_number>.") 
         await send_main_menu_new_message(update, context)
         return ConversationHandler.END
    elif not free_slots: 
        await query.edit_message_text(f"😫 No free slots left in account '{account_name}'! This account is packed.")
        await send_main_menu_new_message(update, context)
        return ConversationHandler.END

    buttons = [(f"🎟️ Slot {slot_num}", f"addsub_slot_{slot_num}") for slot_num in free_slots.keys()]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 3)) 
    await query.edit_message_text("Pick an available slot for this subscription:", reply_markup=keyboard)
    return SUB_CHOOSE_SLOT


async def add_sub_slot_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    slot_num_str = query.data.replace("addsub_slot_", "")
    context.user_data["addsub_slot"] = slot_num_str 

    service_name = context.user_data.get("addsub_service")
    data = load_data()
    durations = data["services"].get(service_name, {}).get("durations", {})

    if not durations:
        await query.edit_message_text(f"🤷 No durations (and prices) set for the service '{service_name}'. Please use 'Set Prices' from the main menu to set them up first!") 
        await send_main_menu_new_message(update, context)
        return ConversationHandler.END

    buttons = [(f"⏳ {days} days (${price})", f"addsub_duration_{days}") for days, price in durations.items()]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 2))
    await query.edit_message_text("How long should this subscription last? ⏰", reply_markup=keyboard)
    return SUB_CHOOSE_DURATION


async def add_sub_duration_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    duration_days_str = query.data.replace("addsub_duration_", "") 
    
    try:
        duration_days = int(duration_days_str)
    except ValueError:
        await query.edit_message_text("Invalid duration selected. Please try again.")
        await send_main_menu_new_message(update, context)
        return ConversationHandler.END

    context.user_data["addsub_duration"] = duration_days

    person_name = context.user_data.get("addsub_person")
    account_name = context.user_data.get("addsub_account")
    slot_num_str = context.user_data.get("addsub_slot") 
    service_name = context.user_data.get("addsub_service")
    
    data = load_data()
    price = data["services"].get(service_name, {}).get("durations", {}).get(str(duration_days), "N/A")

    end_date = (datetime.utcnow() + timedelta(days=duration_days)).strftime("%Y-%m-%d")

    subscription = {
        "service": service_name,
        "account": account_name,
        "slot": slot_num_str,
        "duration": duration_days,
        "end_date": end_date, 
        "price": price,
    }

    if account_name in data["accounts"] and slot_num_str in data["accounts"][account_name]["slots"]:
        data["accounts"][account_name]["slots"][slot_num_str] = person_name
    else:
        await query.edit_message_text("Error: Account or slot not found during finalization. Please check data integrity.") 
        await send_main_menu_new_message(update, context)
        return ConversationHandler.END

    person = data["people"].setdefault(person_name, {"subscriptions": [], "last_active": datetime.utcnow().strftime("%Y-%m-%d")})
    person["subscriptions"].append(subscription)
    person["last_active"] = datetime.utcnow().strftime("%Y-%m-%d")

    save_data(data)

    await query.edit_message_text(
        f"""🎉 *Subscription Activated!* 🎉

• 👤 Person: {person_name}
• 🎬 Service: {service_name}
• 🔑 Account: {account_name}
• 🎟️ Slot: {slot_num_str}
• ⏳ Duration: {duration_days} days
• 💰 Price: ${price}
• 📅 Expires: {end_date}

Enjoy! 🍿🎶""", parse_mode="Markdown"
    )
    await send_main_menu_new_message(update, context) 
    return ConversationHandler.END


# Set Prices handlers
async def set_prices_start_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    buttons = [
        ("✨ Add/Edit Service Price", "setprice_add_edit_service"),
        ("📜 View Services & Prices", "setprice_view_services"),
        ("🗑️ Remove Price Option", "setprice_remove_option_start"), 
        ("🔙 Back to Menu", "main_menu_from_prices"),
    ]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 1))
    await update.callback_query.edit_message_text("💰 *Price Management* 💰\nWhat would you like to do?", reply_markup=keyboard, parse_mode="Markdown") 
    return PRICE_MAIN_MENU


async def price_main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data

    if action == "setprice_view_services":
        data = load_data()
        if not data["services"]:
            await query.edit_message_text("🛍️ No services in our catalog yet!")
        else:
            text = "🌟 *Available Services & Prices* 🌟\n" 
            for svc, info in data["services"].items():
                text += f"\n{info.get('emoji', '❓')} *{svc}*\n"
                if info.get("durations"):
                    for dur, price in info.get("durations", {}).items():
                        text += f"  - {dur} days: ${price}\n" 
                else:
                    text += "  - No pricing options set yet.\n"
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Price Menu", callback_data="set_prices_start_dummy")]]))
        return PRICE_MAIN_MENU 

    elif action == "main_menu_from_prices":
        # This button intends to go back to the main menu, replacing the current price menu
        await start(update, context) 
        return ConversationHandler.END
    
    elif action == "setprice_add_edit_service":
        await query.edit_message_text("What service are we adding or editing prices for? (e.g., Netflix, Spotify)\nType the name:") 
        return PRICE_GET_SERVICE_NAME
        
    elif action == "setprice_remove_option_start":
        data = load_data()
        services_with_prices = {s: i for s, i in data["services"].items() if i.get("durations")}
        if not services_with_prices:
            await query.edit_message_text("🤷 No services with pricing options found to remove from.")
            return PRICE_MAIN_MENU 
        
        buttons = [(f"{data['services'][s]['emoji']} {s}", f"remprice_svc_{s}") for s in services_with_prices.keys()]
        keyboard = InlineKeyboardMarkup(build_menu(buttons, 1))
        await query.edit_message_text("From which service do you want to remove a pricing option?", reply_markup=keyboard)
        return PRICE_REMOVE_SELECT_SERVICE
    
    elif action == "set_prices_start_dummy": # This button is on the "View Services" message, to go back to Price Menu
        return await set_prices_start_cb(update, context) 

    return PRICE_MAIN_MENU 


async def price_get_service_name_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    service_name = update.message.text.strip()
    context.user_data["price_service_name"] = service_name
    data = load_data()

    current_emoji = "❓"
    if service_name not in data["services"]:
        data["services"][service_name] = {"emoji": current_emoji, "durations": {}}
    else: 
        current_emoji = data["services"][service_name].get("emoji", "❓")

    await update.message.reply_text(
        f"Got it! Service: {service_name}. What emoji represents this service?\n"
        f"(Current: {current_emoji}, or type a new emoji, or type /skip to keep/use default '❓')"
    )
    return PRICE_GET_EMOJI


async def price_get_emoji_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    emoji = update.message.text.strip()
    service_name = context.user_data.get("price_service_name")
    data = load_data()

    if service_name: 
        if service_name not in data["services"]:
            data["services"][service_name] = {"emoji": emoji, "durations": {}}
        else:
            data["services"][service_name]["emoji"] = emoji
        save_data(data)
        await update.message.reply_text(f"👌 Emoji {emoji} saved for {service_name}! Now, for how many days is this pricing option? (e.g., 30)") 
    else:
        await update.message.reply_text("Error: Service name not found. Please start over.")
        await start(update, context) # start() will send a new message
        return ConversationHandler.END
    return PRICE_GET_DURATION_DAYS


async def price_skip_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    service_name = context.user_data.get("price_service_name")
    data = load_data()
    if service_name:
        if service_name not in data["services"]:
             data["services"][service_name] = {"emoji": "❓", "durations": {}} 
             save_data(data)
    await update.message.reply_text("Keeping current/default emoji. Now, for how many days is this pricing option? (e.g., 30)")
    return PRICE_GET_DURATION_DAYS


async def price_get_duration_days_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    duration_str = update.message.text.strip()
    if not duration_str.isdigit() or int(duration_str) <= 0:
        await update.message.reply_text("🙅‍♂️ Oops! Duration must be a positive number. Try again:")
        return PRICE_GET_DURATION_DAYS 

    context.user_data["price_duration_days"] = int(duration_str)
    await update.message.reply_text(f"💰 Duration set to {duration_str} days. What's the price for this duration? (e.g., 9.99)")
    return PRICE_GET_PRICE_AMOUNT


async def price_get_amount_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price_str = update.message.text.strip()
    try:
        price_val = round(float(price_str), 2)
        if price_val < 0: raise ValueError("Price cannot be negative")
    except ValueError:
        await update.message.reply_text("💸 That doesn't look like a valid positive price. Try again (e.g., 9.99):") 
        return PRICE_GET_PRICE_AMOUNT

    service_name = context.user_data.get("price_service_name")
    duration_days = context.user_data.get("price_duration_days")

    if not service_name or duration_days is None:
        await update.message.reply_text("🤯 Whoops! Something went wrong (missing service or duration). Let's start setting prices over.") 
        await start(update, context) # start() will send a new message
        return ConversationHandler.END
        
    data = load_data()
    if service_name not in data["services"]:
        data["services"][service_name] = {"emoji": "❓", "durations": {}}
    if "durations" not in data["services"][service_name]: 
         data["services"][service_name]["durations"] = {}

    data["services"][service_name]["durations"][str(duration_days)] = price_val
    save_data(data)
    
    emoji = data["services"][service_name].get('emoji', '❓')
    # Send feedback as a new message
    await update.message.reply_text(
        f"""✅ *Price Set!* ✅

{emoji} *{service_name}*
{duration_days} days: ${price_val:.2f}

Use 'Set Prices' menu to add more options or go back to main menu.""", parse_mode="Markdown"
    )
    # Then offer buttons to go back to Price Menu (which edits) or Main Menu (which should send new)
    keyboard = [[InlineKeyboardButton("🔙 Price Menu", callback_data="set_prices_start_dummy_end")],[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu_from_price_set_end")]] 
    await update.message.reply_text("What next?", reply_markup=InlineKeyboardMarkup(keyboard))
    # This return keeps them in the set_price_conv, PRICE_MAIN_MENU allows interaction with new buttons
    return PRICE_MAIN_MENU


# Handlers for removing a price option
async def price_remove_select_service_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    service_name = query.data.replace("remprice_svc_", "")
    context.user_data["removeprice_service"] = service_name
    data = load_data()

    durations = data["services"].get(service_name, {}).get("durations", {})
    if not durations:
        await query.edit_message_text(f"🤷 No pricing options found for {service_name} to remove.")
        return PRICE_MAIN_MENU 

    buttons = [(f"⏳ {days} days (${price})", f"remprice_dur_{days}") for days, price in durations.items()]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 1))
    await query.edit_message_text(f"Which pricing option for {service_name} do you want to remove?", reply_markup=keyboard)
    return PRICE_REMOVE_SELECT_DURATION


async def price_remove_select_duration_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    duration_to_remove = query.data.replace("remprice_dur_", "") 
    service_name = context.user_data.get("removeprice_service")
    data = load_data()
    feedback_message = ""

    if service_name and service_name in data["services"] and \
       "durations" in data["services"][service_name] and \
       duration_to_remove in data["services"][service_name]["durations"]: 
        
        price = data["services"][service_name]["durations"][duration_to_remove]
        del data["services"][service_name]["durations"][duration_to_remove]
        save_data(data)
        feedback_message = f"🗑️ Price for {service_name} ({duration_to_remove} days at ${price}) has been removed."
    else:
        feedback_message = "🤯 Oops! Could not find that price option to remove. It might have already been deleted." 
    
    context.user_data.pop("removeprice_service", None)
    context.user_data.pop("removeprice_duration", None) 

    await query.edit_message_text(feedback_message) # Edit to show completion
    # Then offer buttons in a new message or send menu directly
    # Option 1: Buttons for next steps
    # keyboard = [[InlineKeyboardButton("💰 Set Prices", callback_data="set_prices_start")],[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu_generic")]]
    # await query.message.reply_text("What would you like to do next?", reply_markup=InlineKeyboardMarkup(keyboard))
    # Option 2: Directly send main menu
    await send_main_menu_new_message(update, context)
    return ConversationHandler.END 

async def main_menu_generic_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles 'main_menu_generic' callback, always sending a new main menu."""
    query = update.callback_query
    if query: 
        await query.answer()
    await send_main_menu_new_message(update, context) 
    return ConversationHandler.END


# Cancel handler
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name if update.effective_user else "User"
    logger.info(f"User {user_name} cancelled a conversation.")
    cancel_message = "🚫 Operation cancelled. No changes made." # Simplified
    
    if update.message:
        await update.message.reply_text(cancel_message)
    elif update.callback_query:
        await update.callback_query.answer("Operation Cancelled")
        try:
            # Edit the message where the cancel button was pressed
            await update.callback_query.edit_message_text(cancel_message)
        except Exception as e: 
            logger.warning(f"Could not edit message on cancel: {e}")
            # If edit fails, send a new message
            if update.effective_chat: 
                 await context.bot.send_message(chat_id=update.effective_chat.id, text=cancel_message + " Returning to main menu.")
    
    # Clear context data
    keys_to_clear = ["new_account_name", "addsub_person", "addsub_service", "addsub_account", 
                     "addsub_slot", "addsub_duration", "price_service_name", "price_duration_days",
                     "removeprice_service", "remove_sub_person"] 
    for key in keys_to_clear:
        if key in context.user_data:
            del context.user_data[key]
            
    # Always send a new main menu after cancel
    await send_main_menu_new_message(update, context) 
    return ConversationHandler.END


# ===== OTHER COMMANDS =====

async def list_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE, from_callback=False):
    data = load_data() 
    # reply_fn will be edit_message_text if from_callback is True
    reply_fn = update.callback_query.edit_message_text if from_callback and update.callback_query else context.bot.send_message
    chat_id_to_use = update.effective_chat.id if not (from_callback and update.callback_query) else None
    
    if not data.get("people"):
        msg_text = "🌌 It's quiet... Too quiet. No people with subscriptions found!"
        if chat_id_to_use:
            await reply_fn(chat_id=chat_id_to_use, text=msg_text)
        elif update.callback_query:
             await update.callback_query.edit_message_text(msg_text)
        # No automatic return to menu here, handled by the calling button handler
        return
    
    message = "📦 *Active Subscriptions Overview* 📦\n"
    found_any_subs = False
    for person, info in data["people"].items():
        subs = info.get("subscriptions", [])
        if not subs:
            continue
        
        person_has_subs = False 
        temp_person_message = f"\n🌟 *{person}*:\n"
        for sub in subs:
            found_any_subs = True
            person_has_subs = True
            temp_person_message += (
                f"  ├ {sub.get('service', '?')} on {sub.get('account', '?')} (Slot: {sub.get('slot', '?')})\n"
                f"  └ Expires: {sub.get('end_date', '?')} (Price: ${sub.get('price', 'N/A')})\n" 
            )
        if person_has_subs:
            message += temp_person_message
            
    if not found_any_subs:
        message = "🌫️ No active subscriptions found for anyone."

    if chat_id_to_use:
        await reply_fn(chat_id=chat_id_to_use, text=message, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.edit_message_text(message, parse_mode="Markdown")
    # No automatic return to menu here, handled by the calling button handler


async def calculate_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    total_income_from_active_subs = 0
    active_subs_details = [] 

    for person_name, person_data in data["people"].items():
        for sub in person_data.get("subscriptions", []):
            try:
                price = float(sub.get("price", 0))
                total_income_from_active_subs += price
                active_subs_details.append(f"- {person_name}: {sub.get('service')} for ${price:.2f}")
            except ValueError:
                logger.warning(f"Invalid price format for a subscription of {person_name}: {sub.get('price')}")

    breakdown_text = "\n".join(active_subs_details) if active_subs_details else "No specific subscriptions to list." 
    feedback_text = ( 
        f"""💰 *Income Summary (from active subscriptions)* 💰

Total value of active subscriptions: *${total_income_from_active_subs:.2f}*

This sum represents the total price of all subscriptions currently recorded as active.
It does not predict future recurring income directly without more payment tracking logic.

Breakdown of included subscriptions:
{breakdown_text}

Keep up the good work! 🎉"""
    )
    await update.message.reply_text(feedback_text, parse_mode="Markdown")
    await send_main_menu_new_message(update, context)


async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists(DATA_FILE):
        try:
            await update.message.reply_document(
                document=open(DATA_FILE, "rb"), 
                filename="subscription_data_backup.json",
                caption="📤 Here's your data backup! Handle with care."
            )
        except Exception as e:
            logger.error(f"Error sending data file: {e}")
            await update.message.reply_text("🤖 Oops! Something went wrong while trying to send the data file.") 
    else:
        await update.message.reply_text("🤷‍♂️ Oops! Data file went on vacation. It's missing!")
    await send_main_menu_new_message(update, context)


async def set_default_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) != 2:
        await update.message.reply_text("Usage: /set_default_slots <ServiceName> <Count>\nExample: /set_default_slots Netflix 4\n(ServiceName must match one from 'Set Prices')")
        # No menu here, let user re-issue command or /start
        return
    
    service_name_arg, count_str = context.args[0], context.args[1]
    data = load_data()

    if service_name_arg not in data["services"]:
        await update.message.reply_text(f"⚠️ Service '{service_name_arg}' not found. Please add this service via 'Set Prices' menu first, then set its default slots.")
        await send_main_menu_new_message(update, context)
        return

    try:
        count = int(count_str)
        if count < 0:
            await update.message.reply_text("🔢 Slot count must be a non-negative number. Try again!") 
            # No menu here, error in command usage
            return
            
        data.setdefault("default_slots", {})[service_name_arg] = count
        save_data(data)
        if count == 0:
            await update.message.reply_text(f"✅ Default slots for *{service_name_arg}* removed. New accounts for this service won't get auto-slots.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"✅ Default slots for *{service_name_arg}* set to *{count}*. New accounts for this service will start with this many slots.", parse_mode="Markdown") 
    except ValueError:
        await update.message.reply_text("🔢 Slot count must be a valid number. Try again!")
    await send_main_menu_new_message(update, context)


async def add_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /add_slot <FullAccountName> <SlotNumber1> [SlotNumber2 ...]\nExample: /add_slot \"Netflix Main\" 5 6\n(Account name might need quotes if it contains spaces)")
        return 
    
    account_name_arg = context.args[0]
    slot_numbers_to_add = context.args[1:]
    data = load_data()

    if account_name_arg not in data["accounts"]:
        await update.message.reply_text(f"🔍 Account '{account_name_arg}' not found. Check your spelling or use 'Add Account' first!") 
        await send_main_menu_new_message(update, context)
        return
    
    added_slots = []
    already_exist_slots = []
    invalid_slots = []

    for slot_str in slot_numbers_to_add:
        if not slot_str.isalnum():
            invalid_slots.append(slot_str)
            continue
        if slot_str in data["accounts"][account_name_arg]["slots"]: 
            already_exist_slots.append(slot_str)
        else:
            data["accounts"][account_name_arg]["slots"][slot_str] = None
            added_slots.append(slot_str)
    
    if added_slots:
        save_data(data)
        await update.message.reply_text(f"🎟️ Added slot(s) *{', '.join(added_slots)}* to *{account_name_arg}*!", parse_mode="Markdown")
    
    if already_exist_slots:
        await update.message.reply_text(f"🤔 Slot(s) *{', '.join(already_exist_slots)}* already exist for *{account_name_arg}*.", parse_mode="Markdown") 
    if invalid_slots:
        await update.message.reply_text(f"⚠️ Slot name(s) *{', '.join(invalid_slots)}* seem invalid. Please use alphanumeric names.", parse_mode="Markdown") 
    if not added_slots and not already_exist_slots and not invalid_slots:
         await update.message.reply_text(f"No slots specified to add to *{account_name_arg}*.", parse_mode="Markdown")
    await send_main_menu_new_message(update, context)


async def remove_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /remove_slot <FullAccountName> <SlotNumber1> [SlotNumber2 ...]\nExample: /remove_slot \"Netflix Main\" 3\n(Account name might need quotes if it contains spaces)")
        return
    
    account_name_arg = context.args[0]
    slot_numbers_to_remove = context.args[1:]
    data = load_data() 

    if account_name_arg not in data["accounts"]:
        await update.message.reply_text(f"🔍 Account '{account_name_arg}' not found. Did it get removed already?")
        await send_main_menu_new_message(update, context)
        return
    
    removed_slots = []
    not_found_slots = []
    occupied_slots = []

    for slot_str in slot_numbers_to_remove:
        if slot_str not in data["accounts"][account_name_arg]["slots"]:
            not_found_slots.append(slot_str)
        elif data["accounts"][account_name_arg]["slots"][slot_str] is not None: 
            occupant = data["accounts"][account_name_arg]["slots"][slot_str]
            occupied_slots.append(f"{slot_str} (used by {occupant})")
        else:
            del data["accounts"][account_name_arg]["slots"][slot_str]
            removed_slots.append(slot_str)
            
    if removed_slots:
        save_data(data)
        await update.message.reply_text(f"🗑️ Slot(s) *{', '.join(removed_slots)}* removed from *{account_name_arg}*.", parse_mode="Markdown") 

    if not_found_slots:
        await update.message.reply_text(f"🤷‍♂️ Slot(s) *{', '.join(not_found_slots)}* don't exist in *{account_name_arg}*.", parse_mode="Markdown")
    if occupied_slots:
        await update.message.reply_text(f"⚠️ Can't remove occupied slot(s): *{', '.join(occupied_slots)}*. Remove their subscriptions first.", parse_mode="Markdown") 
    if not removed_slots and not not_found_slots and not occupied_slots:
        await update.message.reply_text(f"No valid, empty slots specified to remove from *{account_name_arg}*.", parse_mode="Markdown")
    await send_main_menu_new_message(update, context)


# Remove Subscription flow (/removesub command)
async def remove_sub_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    active_people_with_subs = {
        name: info for name, info in data["people"].items() if info.get("subscriptions")
    }

    if not active_people_with_subs:
        await update.message.reply_text("🌌 It's empty here... No people with active subscriptions to remove from!") 
        return ConversationHandler.END
    
    buttons = [[InlineKeyboardButton(f"👤 {name}", callback_data=f"remsub_person_{name}")]
               for name in active_people_with_subs.keys()]
    await update.message.reply_text("Whose subscription should we remove? Pick a person:", 
                                  reply_markup=InlineKeyboardMarkup(buttons))
    return REMSUB_CHOOSE_PERSON


async def remove_sub_person_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    person_name = query.data.replace("remsub_person_", "")
    context.user_data["remove_sub_person"] = person_name
    data = load_data()
    
    if person_name not in data["people"] or not data["people"][person_name].get("subscriptions"):
         await query.edit_message_text(f"🤷‍♀️ {person_name} has no subscriptions to remove or person not found!") 
        context.user_data.pop("remove_sub_person", None) 
        await send_main_menu_new_message(update, context)
        return ConversationHandler.END 
    
    subs = data["people"][person_name]["subscriptions"]
    
    buttons = []
    for i, s in enumerate(subs):
        buttons.append([InlineKeyboardButton(
            f"{s.get('service','Unknown Service')} on {s.get('account','Unknown Acc')} (Slot {s.get('slot','N/A')}), ends {s.get('end_date','N/A')}",  
            callback_data=f"remsub_confirm_{i}" 
        )])
    
    if not buttons: 
        await query.edit_message_text(f"🤷‍♀️ No subscriptions found for {person_name} after all.")
        await send_main_menu_new_message(update, context)
        return ConversationHandler.END

    await query.edit_message_text(f"Which of {person_name}'s subscriptions should we remove?",
                                   reply_markup=InlineKeyboardMarkup(buttons)) 
    return REMSUB_CHOOSE_SUBSCRIPTION


async def remove_sub_confirm_and_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    feedback_message = ""
    
    try:
        sub_index = int(query.data.replace("remsub_confirm_", ""))
    except ValueError:
        await query.edit_message_text("Error: Invalid subscription selection. Please try again.") 
        return REMSUB_CHOOSE_SUBSCRIPTION 

    person_name = context.user_data.get("remove_sub_person")
    if not person_name:
        await query.edit_message_text("Error: User context lost. Please start removing subscription again.")
        await send_main_menu_new_message(update, context)
        return ConversationHandler.END
        
    data = load_data()
    
    if person_name not in data["people"] or not data["people"][person_name].get("subscriptions") or sub_index >= len(data["people"][person_name]["subscriptions"]):
        await query.edit_message_text("Error: Subscription or person not found. It might have been removed already. Please try again.") 
        context.user_data.pop("remove_sub_person", None)
        await send_main_menu_new_message(update, context)
        return ConversationHandler.END

    try:
        removed_sub_info = data["people"][person_name]["subscriptions"].pop(sub_index)
        account_name = removed_sub_info.get("account")
        slot_num_str = str(removed_sub_info.get("slot"))

        if account_name and account_name in data["accounts"] and \
           slot_num_str and slot_num_str in data["accounts"][account_name]["slots"]: 
            if data["accounts"][account_name]["slots"][slot_num_str] == person_name:
                data["accounts"][account_name]["slots"][slot_num_str] = None
                slot_freed_msg = f"Slot {slot_num_str} on account {account_name} is now free! 🎉" 
            else:
                slot_freed_msg = f"Slot {slot_num_str} on account {account_name} was not held by {person_name}, no change to slot occupancy by this action."
                logger.warning(f"Slot {slot_num_str} on {account_name} was expected to be held by {person_name} but found {data['accounts'][account_name]['slots'][slot_num_str]}") 
        else:
            slot_freed_msg = "Could not verify/free slot (account/slot info missing from sub or account)."
            logger.warning(f"Could not free slot for sub: {removed_sub_info}")

        data["people"][person_name]["last_active"] = datetime.utcnow().strftime("%Y-%m-%d")
        save_data(data)
        
        feedback_message = ( 
            f"""✅ *Subscription Removed!* ✅

• Person: {person_name}
• Service: {removed_sub_info.get('service', 'N/A')}
• Account: {account_name or 'N/A'}
• Slot: {slot_num_str or 'N/A'}

{slot_freed_msg}"""
        )
    except IndexError:
        feedback_message = "Error: Could not find that specific subscription to remove. It might have been removed already." 
    except Exception as e:
        logger.error(f"Error during subscription removal: {e}")
        feedback_message = "An unexpected error occurred while removing the subscription."

    await query.edit_message_text(feedback_message, parse_mode="Markdown")
    context.user_data.pop("remove_sub_person", None)
    await send_main_menu_new_message(update, context) 
    return ConversationHandler.END


def main():
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN environment variable is not set.")
        raise RuntimeError("BOT_TOKEN environment variable is not set.")

    cleanup_expired_subs()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CallbackQueryHandler(handle_list_people_button, pattern="list_people_cmd"))
    application.add_handler(CallbackQueryHandler(handle_list_subs_button, pattern="list_subs_cmd"))
    application.add_handler(CallbackQueryHandler(main_menu_generic_handler, pattern="main_menu_generic")) # Used by some buttons to go to main menu

    add_person_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_person_start_cb, pattern="add_person_start")],
        states={CHOOSE_PERSON_TO_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_person_receive)]},
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern="cancel"), CommandHandler("start", start)],
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )
    application.add_handler(add_person_conv)

    remove_person_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(remove_person_start_cb, pattern="remove_person_start")],
        states={CHOOSE_PERSON_TO_REMOVE: [CallbackQueryHandler(remove_person_confirm, pattern="^remove_person_.*")]}, 
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern="cancel"), CommandHandler("start", start)],
    )
    application.add_handler(remove_person_conv)

    add_account_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_account_start_cb, pattern="add_account_start")],
        states={
            GET_ACCOUNT_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_get_details)],
            GET_ACCOUNT_SERVICE: [CallbackQueryHandler(add_account_set_service, pattern="^addacc_service_.*")],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern="cancel"), CommandHandler("start", start)], 
    )
    application.add_handler(add_account_conv)

    remove_account_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(remove_account_start_cb, pattern="remove_account_start")],
        states={CHOOSE_ACCOUNT_TO_REMOVE: [CallbackQueryHandler(remove_account_confirm, pattern="^remove_account_.*")]},
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern="cancel"), CommandHandler("start", start)],
    )
    application.add_handler(remove_account_conv)

    add_sub_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_sub_start_cb, pattern="add_sub_start")],
        states={ 
            SUB_CHOOSE_PERSON: [CallbackQueryHandler(add_sub_person_chosen, pattern="^addsub_person_.*")],
            SUB_CHOOSE_SERVICE: [CallbackQueryHandler(add_sub_service_chosen, pattern="^addsub_service_.*")],
            SUB_CHOOSE_ACCOUNT: [CallbackQueryHandler(add_sub_account_chosen, pattern="^addsub_account_.*")],
            SUB_CHOOSE_SLOT: [CallbackQueryHandler(add_sub_slot_chosen, pattern="^addsub_slot_.*")],
            SUB_CHOOSE_DURATION: [CallbackQueryHandler(add_sub_duration_chosen, pattern="^addsub_duration_.*")],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern="cancel"), CommandHandler("start", start)],
    )
    application.add_handler(add_sub_conv) 

    set_price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_prices_start_cb, pattern="set_prices_start")],
        states={
            PRICE_MAIN_MENU: [
                CallbackQueryHandler(price_main_menu_handler), 
            ], 
            PRICE_GET_SERVICE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, price_get_service_name_receive)],
            PRICE_GET_EMOJI: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, price_get_emoji_receive),
                CommandHandler("skip", price_skip_emoji),
            ],
            PRICE_GET_DURATION_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, price_get_duration_days_receive)], 
            PRICE_GET_PRICE_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, price_get_amount_receive),
                CallbackQueryHandler(set_prices_start_cb, pattern="set_prices_start_dummy_end"), # This leads back to price menu
                CallbackQueryHandler(main_menu_generic_handler, pattern="main_menu_from_price_set_end") # This leads to new main menu
            ], 
            PRICE_REMOVE_SELECT_SERVICE: [CallbackQueryHandler(price_remove_select_service_handler, pattern="^remprice_svc_.*")],
            PRICE_REMOVE_SELECT_DURATION: [CallbackQueryHandler(price_remove_select_duration_handler, pattern="^remprice_dur_.*")],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern="cancel"), CommandHandler("start", start)],
    )
    application.add_handler(set_price_conv)

    remove_sub_conv = ConversationHandler(
        entry_points=[CommandHandler("removesub", remove_sub_start_command)], 
        states={
            REMSUB_CHOOSE_PERSON: [CallbackQueryHandler(remove_sub_person_selected, pattern="^remsub_person_.*")],
            REMSUB_CHOOSE_SUBSCRIPTION: [CallbackQueryHandler(remove_sub_confirm_and_delete, pattern="^remsub_confirm_.*")],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern="cancel"), CommandHandler("start", start)],
    )
    application.add_handler(remove_sub_conv)

    application.add_handler(CommandHandler("start", start)) 

    application.add_handler(CommandHandler("listpeople", list_people)) 
    application.add_handler(CommandHandler("listsubs", list_subscriptions)) 
    application.add_handler(CommandHandler("income", calculate_income))
    application.add_handler(CommandHandler("export", export_data))
    application.add_handler(CommandHandler("setdefaultslots", set_default_slots)) 
    application.add_handler(CommandHandler("addslot", add_slot)) 
    application.add_handler(CommandHandler("removeslot", remove_slot)) 

    # --- Corrected Webhook Section ---
    if WEBHOOK_URL and "PORT" in os.environ:
        static_webhook_path = "telegramwebhook" 
        full_webhook_url = f"{WEBHOOK_URL.rstrip('/')}/{static_webhook_path}"
        
        logger.info(f"Starting webhook on {full_webhook_url}")
        application.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 8443)),
            url_path=static_webhook_path, 
            webhook_url=full_webhook_url
        )
    # --- End of Corrected Webhook Section ---
    else:
        logger.info("Starting polling")
        application.run_polling() 


if __name__ == "__main__":
    main()