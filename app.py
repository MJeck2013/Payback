import json
import os
import streamlit as st

SYSTEM_ACCOUNT = "j.member"
DATA_FILE = "payback.json"
GIFT_FILE = "gift.json"

# --- Data Management Functions ---

def load_data():
    if os.path.exists(DATA_FILE) and os.path.getsize(DATA_FILE) > 0:
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def load_gifts():
    if os.path.exists(GIFT_FILE) and os.path.getsize(GIFT_FILE) > 0:
        try:
            with open(GIFT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_gifts(gifts_data):
    with open(GIFT_FILE, "w", encoding="utf-8") as f:
        json.dump(gifts_data, f, indent=4)

def get_balance(account_data):
    try:
        if isinstance(account_data, dict):
            raw_bal = account_data.get("balance", 0)
        else:
            raw_bal = account_data
        return int(raw_bal)
    except (ValueError, TypeError):
        return 0

def set_balance(account_data, new_balance):
    new_balance = int(new_balance)
    if isinstance(account_data, dict):
        account_data["balance"] = new_balance
        return account_data
    return new_balance

def get_coin_prices(payback_db):
    j_balance = get_balance(payback_db.get(SYSTEM_ACCOUNT, 0))
    sell_price = j_balance * 0.00001
    buy_price = sell_price * 1.10
    return buy_price, sell_price, j_balance

# --- App UI Configuration ---

st.set_page_config(page_title="Payback Coin System", page_icon="🚽", layout="centered")

st.title("Payback Coin Management System")
st.markdown("Welcome to the web version of your coin tracking system! Made by Mjeck Studios")

# Load database
payback = load_data()

# Sidebar Navigation
st.sidebar.header("Menu Options")
choice = st.sidebar.radio(
    "Choose an Action:",
    [
        "Check Balance/Login",
        "Create Account",
        "View Coin Prices",
        "Transfer Coins",
        "Redeem Gift Card",
        "Admin Controls",
        "More"
    ]
)

st.sidebar.markdown("---")
st.sidebar.info("Tip: Make sure the system account exists before creating regular accounts!")

# --- Option 1: Check Balance / Login ---
if choice == "Check Balance / Login":
    st.subheader("🔍 Balance Lookup")
    
    with st.form("login_form"):
        username = st.text_input("Username").strip().lower()
        password = st.text_input("Password", type="password")
        submit_login = st.form_submit_button("Check Balance")
        
        if submit_login:
            if not username:
                st.warning("⚠️ Please enter a username.")
            elif username in payback:
                user_data = payback[username]
                if isinstance(user_data, dict) and user_data.get("password") != password:
                    st.error("❌ Incorrect password!")
                else:
                    bal = get_balance(user_data)
                    st.success(f"✅ Success! You currently have **{bal:,.2f}** payback coins.")
            else:
                st.error(f"❌ Found no matches for username: '{username}'")

# --- Option 2: Create Account ---
elif choice == "Create Account":
    st.subheader("📝 Account Maker")
    
    if SYSTEM_ACCOUNT not in payback:
        st.error(f"❌ System error: Primary account '{SYSTEM_ACCOUNT}' must be created first!")
    else:
        j_bal = get_balance(payback[SYSTEM_ACCOUNT])
        st.info(f"🏦 System Reserve Balance: **{j_bal:,.2f}** coins available.")
        
        if j_bal < 10:
            st.error(f"❌ Cannot create accounts! '{SYSTEM_ACCOUNT}' has less than 10 Payback coins.")
        else:
            with st.form("create_account_form"):
                new_user = st.text_input("Choose a Future Username").strip().lower()
                new_pass = st.text_input("Choose a Password", type="password")
                submit_create = st.form_submit_button("Create Account")
                
                if submit_create:
                    if not new_user or not new_pass:
                        st.warning("⚠️ Please fill out both fields.")
                    elif new_user in payback:
                        st.error(f"❌ '{new_user}' already exists! Choose a different username.")
                    else:
                        payback[SYSTEM_ACCOUNT] = set_balance(payback[SYSTEM_ACCOUNT], j_bal - 10)
                        payback[new_user] = {"password": new_pass, "balance": 10}
                        save_data(payback)
                        st.success(f"🎉 Success! Account created for '{new_user}' with 10 starter coins.")

# --- Option 3: View Coin Prices ---
elif choice == "View Coin Prices":
    st.subheader("📈 Payback Coin Market Value")
    
    buy_price, sell_price, j_bal = get_coin_prices(payback)
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Reserve Left", f"{j_bal:,.2f}")
    col2.metric("Sell Value / Coin", f"${sell_price:,.4f}")
    col3.metric("Buy Value / Coin", f"${buy_price:,.4f}")

# --- Option 4: Transfer Coins ---
elif choice == "Transfer Coins":
    st.subheader("💸 Transfer Coins")
    
    with st.form("transfer_form"):
        sender = st.text_input("Your Username").strip().lower()
        pwd = st.text_input("Your Password", type="password")
        recipient = st.text_input("Recipient's Username").strip().lower()
        amount = st.number_input("Amount to Transfer", min_value=1, step=1)
        submit_transfer = st.form_submit_button("Send Coins")
        
        if submit_transfer:
            if sender not in payback:
                st.error("❌ Sender username not found.")
            else:
                user_info = payback[sender]
                if isinstance(user_info, dict) and user_info.get("password") != pwd:
                    st.error("❌ Incorrect password!")
                elif recipient not in payback:
                    st.error(f"❌ Recipient '{recipient}' does not exist!")
                elif recipient == sender:
                    st.error("❌ You cannot send coins to yourself!")
                else:
                    sender_balance = get_balance(user_info)
                    if sender_balance < amount:
                        st.error(f"❌ Insufficient funds! You only have {sender_balance} coins.")
                    else:
                        recipient_balance = get_balance(payback[recipient])
                        
                        new_sender_bal = sender_balance - amount
                        new_recipient_bal = recipient_balance + amount
                        
                        payback[sender] = set_balance(payback[sender], new_sender_bal)
                        payback[recipient] = set_balance(payback[recipient], new_recipient_bal)
                        save_data(payback)
                        
                        st.success(f"🎉 Success! Transferred {amount} coins to '{recipient}'.")
                        st.info(f"💰 Your new balance: **{new_sender_bal}** coins.")

# --- Option 5: Redeem Gift Card ---
elif choice == "Redeem Gift Card":
    st.subheader("🎁 Redeem Gift Card")
    
    gifts = load_gifts()
    
    with st.form("gift_form"):
        user = st.text_input("Your Username").strip().lower()
        pwd = st.text_input("Your Password", type="password")
        code = st.text_input("Gift Card Code").strip()
        submit_gift = st.form_submit_button("Redeem Code")
        
        if submit_gift:
            if user not in payback:
                st.error("❌ Username not found.")
            else:
                user_info = payback[user]
                if isinstance(user_info, dict) and user_info.get("password") != pwd:
                    st.error("❌ Incorrect password!")
                elif code not in gifts:
                    st.error("❌ Invalid or expired gift card code!")
                else:
                    try:
                        coin_amount = int(gifts[code])
                    except (ValueError, TypeError):
                        st.error("❌ Gift card error: Invalid coin value stored in file.")
                        coin_amount = 0
                    
                    if coin_amount > 0:
                        j_bal = get_balance(payback.get(SYSTEM_ACCOUNT, 0))
                        if j_bal < coin_amount:
                            st.error(f"❌ System Error: Reserve '{SYSTEM_ACCOUNT}' does not have enough coins!")
                        else:
                            user_bal = get_balance(payback[user])
                            
                            payback[SYSTEM_ACCOUNT] = set_balance(payback[SYSTEM_ACCOUNT], j_bal - coin_amount)
                            payback[user] = set_balance(payback[user], user_bal + coin_amount)
                            save_data(payback)
                            
                            del gifts[code]
                            save_gifts(gifts)
                            
                            st.success(f"🎉 Success! Redeemed {coin_amount} Payback coins from code '{code}'.")
                            st.info(f"💰 Your new balance: **{user_bal + coin_amount}** coins.")
elif choice == "Admin Controls":
    st.info("Note: This Page is for Admins only")
    with st.form("admin_form"):
        input_code = st.text_input("Admin Code", type="password")
        submit = st.form_submit_button("Submit Admin Code")

        if submit:
            code1 = st.secrets.get("admin", {}).get("code1")
            code2 = st.secrets.get("admin", {}).get("code2")
            if input_code == code1:
                exit()
            elif input_code == code2:
                st.message("Hello")
            else:
                st.error("❌ Incorrect Admin Code!")
elif choice == "More":
    st.subheader("Click on One of these links to see more by Mjeck Studios")
    st.markdown("[Click here to visit NoSchool](https://mywebbrowser-noschool.streamlit.app)")
