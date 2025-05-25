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
    SET_PRICE_SAVE_AMOUNT,
) = range(14)


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
                    if slot_num is not None and account["slots"].get(str(slot_num)) == person_name:
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


def build_menu(items, n_cols):
    menu = []
    for i in range(0, len(items), n_cols):
        menu.append(
            [InlineKeyboardButton(text, callback_data=cb) for text, cb in items[i : i + n_cols]]
        )
    return menu


# ======= BOT COMMANDS =======

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = """
🌟 *Welcome to Subscription Manager Bot!* 🌟

I'll help you track shared subscriptions, accounts, and payments. Let's make managing shared accounts *easy peasy*!

What would you like to do today?
"""
    if update.message:
        await update.message.reply_text(
            welcome_msg,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("👤 Add Person", callback_data="add_person")],
                    [InlineKeyboardButton("🗑️ Remove Person", callback_data="remove_person")],
                    [InlineKeyboardButton("📜 List People", callback_data="list_people")],
                    [InlineKeyboardButton("🔑 Add Account", callback_data="add_account")],
                    [InlineKeyboardButton("🚮 Remove Account", callback_data="remove_account")],
                    [InlineKeyboardButton("💳 Add Subscription", callback_data="add_subscription")],
                    [InlineKeyboardButton("💰 Set Prices", callback_data="set_prices")],
                ]
            ),
        )
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            welcome_msg,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("👤 Add Person", callback_data="add_person")],
                    [InlineKeyboardButton("🗑️ Remove Person", callback_data="remove_person")],
                    [InlineKeyboardButton("📜 List People", callback_data="list_people")],
                    [InlineKeyboardButton("🔑 Add Account", callback_data="add_account")],
                    [InlineKeyboardButton("🚮 Remove Account", callback_data="remove_account")],
                    [InlineKeyboardButton("💳 Add Subscription", callback_data="add_subscription")],
                    [InlineKeyboardButton("💰 Set Prices", callback_data="set_prices")],
                ]
            ),
        )


# Add Person handlers
async def add_person_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("👋 Who's joining the subscription party? Send me their name:")
    return ADD_PERSON


async def add_person_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    person_name = update.message.text.strip()
    data = load_data()

    if person_name in data["people"]:
        await update.message.reply_text(f"🤔 Hmm, {person_name} is already in our system! Maybe they want another subscription?")
    else:
        data["people"][person_name] = {"subscriptions": [], "last_active": datetime.utcnow().strftime("%Y-%m-%d")}
        save_data(data)
        await update.message.reply_text(f"🎉 Welcome aboard, {person_name}! I've added you to our family.")

    return ConversationHandler.END


# Remove Person handlers
async def remove_person_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    await update.callback_query.answer()
    if not data["people"]:
        await update.callback_query.edit_message_text("😶 It's empty here... No people to remove!")
        return ConversationHandler.END

    buttons = [(f"👤 {name}", f"remove_person_{name}") for name in data["people"].keys()]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 2))
    await update.callback_query.edit_message_text("Who's leaving us? 😢 Pick someone:", reply_markup=keyboard)
    return REMOVE_PERSON


async def remove_person_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    person_name = query.data.replace("remove_person_", "")
    data = load_data()
    if person_name in data["people"]:
        del data["people"][person_name]
        save_data(data)
        await query.edit_message_text(f"👋 Farewell, {person_name}! I've removed them from our system.")
    else:
        await query.edit_message_text("🤨 Hmm, I can't find that person. Maybe they already left?")
    return ConversationHandler.END


# List People handler
async def list_people(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data["people"]:
        await update.message.reply_text("🦗 Cricket sounds... No people found. Wanna invite someone?")
        return

    text = "📋 *Current Members & Their Subscriptions:*\n"
    for person, info in data["people"].items():
        text += f"\n🌟 *{person}*:\n"
        if not info["subscriptions"]:
            text += "  - Just chilling with no subscriptions\n"
        else:
            for sub in info["subscriptions"]:
                text += (
                    f"  - {sub['service']} on {sub['account']} (Slot {sub.get('slot', '-')}) "
                    f"until {sub['end_date']} ({sub['duration']} days)\n"
                )
    await update.message.reply_text(text, parse_mode="Markdown")


# Add Account handlers
async def add_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("🔐 Let's add a new account! What's the account details? (e.g. 'Netflix user@gmail.com')")
    return ADD_ACCOUNT


async def add_account_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    account_name = update.message.text.strip()
    data = load_data()
    if account_name in data["accounts"]:
        await update.message.reply_text("🤷‍♂️ Oops, we already have that account! Maybe try a different one?")
        return ConversationHandler.END
    else:
        data["accounts"][account_name] = {"service": None, "slots": {}}
        save_data(data)
        context.user_data["new_account"] = account_name
        await update.message.reply_text(
            "👍 Account saved! Now, what service is this for? (e.g., Netflix, Spotify)"
        )
        return SET_PRICE_SERVICE


async def add_account_service_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    service_name = update.message.text.strip()
    data = load_data()
    account_name = context.user_data.get("new_account")
    if account_name and account_name in data["accounts"]:
        data["accounts"][account_name]["service"] = service_name
        save_data(data)
        await update.message.reply_text(f"✨ Perfect! {account_name} is now linked to {service_name}.")
    else:
        await update.message.reply_text("😕 Oops, something went wrong. Let's try that again from the start.")
    return ConversationHandler.END


# Remove Account handlers
async def remove_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    await update.callback_query.answer()
    if not data["accounts"]:
        await update.callback_query.edit_message_text("🤷‍♀️ No accounts to remove! Everything's clean.")
        return ConversationHandler.END

    buttons = [(f"🔑 {name}", f"remove_account_{name}") for name in data["accounts"].keys()]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 1))
    await update.callback_query.edit_message_text("Which account should we say goodbye to? 👋", reply_markup=keyboard)
    return REMOVE_ACCOUNT


async def remove_account_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_name = query.data.replace("remove_account_", "")
    data = load_data()
    if account_name in data["accounts"]:
        del data["accounts"][account_name]
        save_data(data)
        await query.edit_message_text(f"🗑️ Poof! {account_name} is gone. Hope we didn't need that!")
    else:
        await query.edit_message_text("🤨 That account doesn't exist. Magic?")
    return ConversationHandler.END


# Add Subscription handlers (multi-step)
async def add_subscription_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    await update.callback_query.answer()
    if not data["people"]:
        await update.callback_query.edit_message_text("😅 Oops, no people yet! Add someone first so they can enjoy subscriptions.")
        return ConversationHandler.END
    buttons = [(f"👤 {name}", f"addsub_person_{name}") for name in data["people"].keys()]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 2))
    await update.callback_query.edit_message_text("Who's getting a new subscription? 🎁", reply_markup=keyboard)
    return ADD_SUB_PERSON


async def add_subscription_person_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    person_name = query.data.replace("addsub_person_", "")
    context.user_data["addsub_person"] = person_name

    data = load_data()
    if not data["accounts"]:
        await query.edit_message_text("😲 No accounts available! Add an account first.")
        return ConversationHandler.END

    buttons = [(f"🔑 {name}", f"addsub_account_{name}") for name in data["accounts"].keys()]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 1))
    await query.edit_message_text("Which account should we use? 🤔", reply_markup=keyboard)
    return ADD_SUB_ACCOUNT


async def add_subscription_account_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_name = query.data.replace("addsub_account_", "")
    context.user_data["addsub_account"] = account_name

    data = load_data()
    account = data["accounts"].get(account_name)
    if not account:
        await query.edit_message_text("🤯 Account vanished! Maybe it was removed?")
        return ConversationHandler.END

    # Show free slots
    free_slots = [num for num, holder in account["slots"].items() if holder is None]
    if not free_slots:
        await query.edit_message_text("😫 No free slots left! This account is packed.")
        return ConversationHandler.END

    buttons = [(f"🎟️ Slot {slot}", f"addsub_slot_{slot}") for slot in free_slots]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 2))
    await query.edit_message_text("Pick a slot for this subscription:", reply_markup=keyboard)
    return ADD_SUB_SLOT


async def add_subscription_slot_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    slot_num = query.data.replace("addsub_slot_", "")
    context.user_data["addsub_slot"] = slot_num

    data = load_data()
    services = list(data["services"].keys())
    if not services:
        await query.edit_message_text("😅 No services set up yet! Use /setprices to add some.")
        return ConversationHandler.END

    buttons = [(f"{data['services'][s]['emoji']} {s}", f"addsub_service_{s}") for s in services]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 2))
    await query.edit_message_text("What service is this for? 🎬🎵", reply_markup=keyboard)
    return ADD_SUB_SERVICE


async def add_subscription_service_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    service_name = query.data.replace("addsub_service_", "")
    context.user_data["addsub_service"] = service_name

    data = load_data()
    durations = data["services"].get(service_name, {}).get("durations", {})
    if not durations:
        await query.edit_message_text("🤷 No durations set for this service. Set prices first!")
        return ConversationHandler.END

    buttons = [(f"⏳ {days} days", f"addsub_duration_{days}") for days in durations.keys()]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 2))
    await query.edit_message_text("How long should this subscription last? ⏰", reply_markup=keyboard)
    return ADD_SUB_DURATION


async def add_subscription_duration_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    duration_days = int(query.data.replace("addsub_duration_", ""))
    context.user_data["addsub_duration"] = duration_days

    # Finalize the subscription
    person_name = context.user_data.get("addsub_person")
    account_name = context.user_data.get("addsub_account")
    slot_num = context.user_data.get("addsub_slot")
    service_name = context.user_data.get("addsub_service")
    duration = duration_days

    data = load_data()
    price = data["services"].get(service_name, {}).get("durations", {}).get(str(duration), "N/A")

    end_date = (datetime.utcnow() + timedelta(days=duration)).strftime("%Y-%m-%d")

    subscription = {
        "service": service_name,
        "account": account_name,
        "slot": int(slot_num),
        "duration": duration,
        "end_date": end_date,
        "price": price,
    }

    # Assign slot
    data["accounts"][account_name]["slots"][str(slot_num)] = person_name

    # Add to person's subscriptions
    person = data["people"].setdefault(person_name, {"subscriptions": [], "last_active": datetime.utcnow().strftime("%Y-%m-%d")})
    person["subscriptions"].append(subscription)
    person["last_active"] = datetime.utcnow().strftime("%Y-%m-%d")

    save_data(data)

    await query.edit_message_text(
        f"""🎉 *Subscription Activated!* 🎉

• 👤 Person: {person_name}
• 🔑 Account: {account_name}
• 🎟️ Slot: {slot_num}
• 🎬 Service: {service_name}
• ⏳ Duration: {duration} days
• 💰 Price: {price}
• 📅 Expires: {end_date}

Enjoy! 🍿🎶"""
    )
    return ConversationHandler.END


# Set Prices handlers
async def set_prices_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    await update.callback_query.answer()

    buttons = [
        ("✨ Add/Edit Service", "setprice_service"),
        ("📜 View Services", "view_services"),
        ("🔙 Back to Menu", "back_to_menu"),
    ]
    keyboard = InlineKeyboardMarkup(build_menu(buttons, 1))
    await update.callback_query.edit_message_text("💰 *Price Management* 💰\nWhat would you like to do?", reply_markup=keyboard, parse_mode="Markdown")
    return SET_PRICE_SERVICE


async def set_price_service_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "view_services":
        data = load_data()
        if not data["services"]:
            await query.edit_message_text("🛍️ No services in our catalog yet!")
        else:
            text = "🌟 *Available Services* 🌟\n"
            for svc, info in data["services"].items():
                text += f"\n{info['emoji']} *{svc}*\n"
                for dur, price in info.get("durations", {}).items():
                    text += f"  - {dur} days: ${price}\n"
            await query.edit_message_text(text, parse_mode="Markdown")
        return ConversationHandler.END

    if query.data == "back_to_menu":
        return await start(update, context)

    if query.data == "setprice_service":
        await query.edit_message_text("What service are we pricing? (e.g., Netflix, Spotify)")
        return SET_PRICE_SERVICE


async def set_price_service_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    service_name = update.message.text.strip()
    context.user_data["service_name"] = service_name
    data = load_data()

    if service_name not in data["services"]:
        data["services"][service_name] = {"emoji": "❓", "durations": {}}
        save_data(data)

    current_emoji = data["services"][service_name]["emoji"]
    await update.message.reply_text(
        f"Got it! {service_name} it is. What emoji represents this service?\n"
        f"(Current: {current_emoji}, or type /skip to keep it)"
    )
    return SET_PRICE_DURATION


async def set_price_emoji_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    emoji = update.message.text.strip()
    service_name = context.user_data.get("service_name")
    data = load_data()
    if service_name in data["services"]:
        data["services"][service_name]["emoji"] = emoji
        save_data(data)
    await update.message.reply_text(f"👌 {emoji} saved! Now, how many days for this pricing option? (e.g., 30)")
    return SET_PRICE_AMOUNT


async def skip_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Keeping the current emoji. Now, how many days for this pricing option? (e.g., 30)")
    return SET_PRICE_AMOUNT


async def set_price_duration_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    duration = update.message.text.strip()
    if not duration.isdigit():
        await update.message.reply_text("🙅‍♂️ Oops! Duration must be a number. Try again:")
        return SET_PRICE_AMOUNT

    context.user_data["duration"] = duration
    await update.message.reply_text("💰 What's the price for this duration? (e.g., 9.99)")
    return SET_PRICE_SAVE_AMOUNT


async def set_price_amount_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price = update.message.text.strip()
    try:
        price_val = float(price)
    except ValueError:
        await update.message.reply_text("💸 That doesn't look like a valid price. Try again:")
        return SET_PRICE_SAVE_AMOUNT

    service_name = context.user_data.get("service_name")
    duration = context.user_data.get("duration")

    data = load_data()
    if service_name in data["services"]:
        data["services"][service_name]["durations"][duration] = price_val
        save_data(data)
        await update.message.reply_text(
            f"""✅ *Price Set!* ✅

{data['services'][service_name]['emoji']} *{service_name}*
{duration} days: ${price_val}

Use /setprices to add more options."""
        )
    else:
        await update.message.reply_text("🤯 Whoops! Service disappeared. Let's start over.")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("🚫 Operation cancelled. No changes made.")
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("🚫 Operation cancelled. No changes made.")
    return ConversationHandler.END


# ===== NEW FEATURES =====

async def list_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = load_data()
        if not data.get("people"):
            await update.message.reply_text("🌌 It's quiet... Too quiet. No subscriptions found!")
            return
        
        message = "📦 *Active Subscriptions* 📦\n"
        for person, info in data["people"].items():
            subs = info.get("subscriptions", [])
            if not subs:
                continue
            message += f"\n🌟 *{person}*:\n"
            for sub in subs:
                message += (
                    f"  ├ {sub.get('service', '?')} \n"
                    f"  ├ Account: {sub.get('account', '?')}\n"
                    f"  ├ Slot: {sub.get('slot', '?')}\n"
                    f"  └ Until: {sub.get('end_date', '?')}\n"
                )
        
        await update.message.reply_text(message or "🌫️ No active subscriptions.", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in list_subscriptions: {e}")
        await update.message.reply_text("🤖 *Bzzt!* Something went wrong. Try again later!", parse_mode="Markdown")


async def calculate_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    total = 0
    for person in data["people"].values():
        for sub in person.get("subscriptions", []):
            service = sub["service"]
            duration = sub["duration"]
            price_data = data["services"].get(service, {}).get("durations", {})
            price = price_data.get(str(duration), 0)
            total += float(price)
    
    await update.message.reply_text(
        f"""💰 *Income Report* 💰

Total estimated income: *${total:.2f}*

Breakdown:
- Per month: *${total/30:.2f}/day*
- Per year: *${total*12:.2f}*

Nice work! 🎉""",
        parse_mode="Markdown"
    )


async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists(DATA_FILE):
        await update.message.reply_document(
            document=open(DATA_FILE, "rb"),
            caption="📤 Here's your data backup! Handle with care."
        )
    else:
        await update.message.reply_text("🤷‍♂️ Oops! Data file went on vacation. It's missing!")


async def set_default_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /set_default_slots <service> <count>\nExample: /set_default_slots Netflix 4")
        return
    
    service, count = context.args[0], context.args[1]
    data = load_data()
    try:
        count = int(count)
        data.setdefault("default_slots", {})[service] = count
        save_data(data)
        await update.message.reply_text(f"✅ Default slots for *{service}* set to *{count}*. New accounts will start with this.", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("🔢 Slot count must be a number. Try again!")


async def add_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /add_slot <account> <slot>\nExample: /add_slot Netflix_user@gmail.com 5")
        return
    
    account, slot = context.args[0], context.args[1]
    data = load_data()
    if account not in data["accounts"]:
        await update.message.reply_text("🔍 Account not found. Check your spelling!")
        return
    
    if slot in data["accounts"][account]["slots"]:
        await update.message.reply_text("🤔 That slot already exists!")
        return
    
    data["accounts"][account]["slots"][slot] = None
    save_data(data)
    await update.message.reply_text(f"🎟️ Added slot *{slot}* to *{account}*! Now there's room for one more.", parse_mode="Markdown")


async def remove_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /remove_slot <account> <slot>\nExample: /remove_slot Netflix_user@gmail.com 3")
        return
    
    account, slot = context.args[0], context.args[1]
    data = load_data()
    if account not in data["accounts"]:
        await update.message.reply_text("🔍 Account not found. Did it get removed already?")
        return
    
    if slot not in data["accounts"][account]["slots"]:
        await update.message.reply_text("🤷‍♂️ That slot doesn't exist!")
        return
    
    if data["accounts"][account]["slots"][slot] is not None:
        await update.message.reply_text("⚠️ Can't remove! Someone is using this slot. Remove their subscription first.")
        return
    
    del data["accounts"][account]["slots"][slot]
    save_data(data)
    await update.message.reply_text(f"🗑️ Slot *{slot}* removed from *{account}*. One less to manage!", parse_mode="Markdown")


# Remove Subscription flow
async def remove_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data["people"]:
        await update.message.reply_text("🌌 It's empty here... No people to remove subscriptions from!")
        return
    
    keyboard = [[InlineKeyboardButton(f"👤 {name}", callback_data=f"removesub_{name}")]
                for name in data["people"]]
    await update.message.reply_text("Who's subscription should we remove?",
                                  reply_markup=InlineKeyboardMarkup(keyboard))


async def remove_subscription_step2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    person = query.data.replace("removesub_", "")
    context.user_data["remove_sub_person"] = person
    data = load_data()
    subs = data["people"][person]["subscriptions"]
    
    if not subs:
        await query.edit_message_text(f"🤷‍♀️ {person} has no subscriptions to remove!")
        return
    
    keyboard = [[InlineKeyboardButton(
        f"{s['service']} ({s['account']})", callback_data=f"removeconf_{i}"
    )] for i, s in enumerate(subs)]
    
    await query.edit_message_text(f"Which of {person}'s subscriptions should we remove?",
                               reply_markup=InlineKeyboardMarkup(keyboard))


async def remove_subscription_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_index = int(query.data.replace("removeconf_", ""))
    person = context.user_data["remove_sub_person"]
    data = load_data()
    
    sub = data["people"][person]["subscriptions"].pop(sub_index)
    account = sub["account"]
    slot = str(sub["slot"])
    
    if account in data["accounts"]:
        data["accounts"][account]["slots"][slot] = None
    
    save_data(data)
    await query.edit_message_text(
        f"""✅ *Subscription Removed!* ✅

• Person: {person}
• Service: {sub['service']}
• Account: {account}
• Slot: {slot}

The slot is now free! 🎉"""
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set.")
    if not WEBHOOK_URL:
        raise RuntimeError("WEBHOOK_URL environment variable is not set.")
    cleanup_expired_subs()  # Clean expired on startup

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Main menu
    application.add_handler(CommandHandler("start", start))

    # Conversation for adding a person
    add_person_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_person_start, pattern="add_person")],
        states={ADD_PERSON: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_person_receive)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(add_person_conv)

    # Conversation for removing a person
    remove_person_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(remove_person_start, pattern="remove_person")],
        states={REMOVE_PERSON: [CallbackQueryHandler(remove_person_confirm, pattern="remove_person_.*")]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(remove_person_conv)

    # List people (simple command)
    application.add_handler(CommandHandler("listpeople", list_people))

    # Add account conversation
    add_account_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_account_start, pattern="add_account")],
        states={
            ADD_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_receive)],
            SET_PRICE_SERVICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_service_receive)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(add_account_conv)

    # Remove account conversation
    remove_account_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(remove_account_start, pattern="remove_account")],
        states={REMOVE_ACCOUNT: [CallbackQueryHandler(remove_account_confirm, pattern="remove_account_.*")]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(remove_account_conv)

    # Add subscription conversation (multi-step)
    add_sub_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_subscription_start, pattern="add_subscription")],
        states={
            ADD_SUB_PERSON: [CallbackQueryHandler(add_subscription_person_chosen, pattern="addsub_person_.*")],
            ADD_SUB_ACCOUNT: [CallbackQueryHandler(add_subscription_account_chosen, pattern="addsub_account_.*")],
            ADD_SUB_SLOT: [CallbackQueryHandler(add_subscription_slot_chosen, pattern="addsub_slot_.*")],
            ADD_SUB_SERVICE: [CallbackQueryHandler(add_subscription_service_chosen, pattern="addsub_service_.*")],
            ADD_SUB_DURATION: [CallbackQueryHandler(add_subscription_duration_chosen, pattern="addsub_duration_.*")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(add_sub_conv)

    # Set prices conversation
    set_price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_prices_start, pattern="set_prices")],
        states={
            SET_PRICE_SERVICE: [
                CallbackQueryHandler(set_price_service_choose),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_price_service_receive),
            ],
            SET_PRICE_DURATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_price_emoji_receive),
                CommandHandler("skip", skip_emoji),
            ],
            SET_PRICE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_price_duration_receive)],
            SET_PRICE_SAVE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_price_amount_receive)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(set_price_conv)

    # New command handlers
    application.add_handler(CommandHandler("listsubs", list_subscriptions))
    application.add_handler(CommandHandler("income", calculate_income))
    application.add_handler(CommandHandler("export", export_data))
    application.add_handler(CommandHandler("set_default_slots", set_default_slots))
    application.add_handler(CommandHandler("add_slot", add_slot))
    application.add_handler(CommandHandler("remove_slot", remove_slot))

    # Remove subscription conversation
    remove_sub_conv = ConversationHandler(
        entry_points=[CommandHandler("removesub", remove_subscription)],
        states={
            0: [CallbackQueryHandler(remove_subscription_step2, pattern="removesub_.*")],
            1: [CallbackQueryHandler(remove_subscription_confirm, pattern="removeconf_.*")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(remove_sub_conv)

    # Start the bot with webhook if configured
    if WEBHOOK_URL:
        application.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ["PORT"]),
            url_path="webhook",
            webhook_url=WEBHOOK_URL + "webhook",
        )
    else:
        application.run_polling()


if __name__ == "__main__":
    main()