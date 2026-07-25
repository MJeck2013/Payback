import json
import os
import sqlite3
import base64
import hashlib
import streamlit as st
from typing import Optional, Tuple

# Constants
SYSTEM_ACCOUNT = "j.member"
DB_FILE = "payback.db"
JSON_DATA_FILE = "payback.json"
JSON_GIFT_FILE = "gift.json"

# --- Database Utilities ---

def init_db(db_path: str = DB_FILE) -> sqlite3.Connection:
    need_create = not os.path.exists(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    if need_create:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE users (
                username TEXT PRIMARY KEY,
                password_hash TEXT,
                balance INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE gifts (
                code TEXT PRIMARY KEY,
                amount INTEGER NOT NULL
            )
            """
        )
        conn.commit()
    return conn


# Password hashing (PBKDF2 using stdlib)
def hash_password(password: str, iterations: int = 100_000) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{base64.b64encode(salt).decode()}${iterations}${base64.b64encode(dk).decode()}"


def verify_password(stored: str, provided: str) -> bool:
    try:
        salt_b64, iter_s, hash_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
        iterations = int(iter_s)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", provided.encode("utf-8"), salt, iterations)
        return hashlib.compare_digest(dk, expected)
    except Exception:
        return False


# Migration helpers: import existing JSON files into SQLite if present
def migrate_json_to_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    # migrate users
    if os.path.exists(JSON_DATA_FILE) and os.path.getsize(JSON_DATA_FILE) > 0:
        try:
            with open(JSON_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

        for username, val in (data.items() if isinstance(data, dict) else []):
            username = username.strip().lower()
            # skip if user exists already
            cur.execute("SELECT 1 FROM users WHERE username = ?", (username,))
            if cur.fetchone():
                continue

            if isinstance(val, dict):
                pwd = val.get("password")
                bal = val.get("balance", 0)
            else:
                pwd = None
                bal = val
            try:
                bal = int(bal)
            except Exception:
                bal = 0

            pwd_hash = hash_password(pwd) if pwd else ""
            cur.execute(
                "INSERT INTO users(username, password_hash, balance) VALUES (?, ?, ?)",
                (username, pwd_hash, bal),
            )
        conn.commit()

    # migrate gifts
    if os.path.exists(JSON_GIFT_FILE) and os.path.getsize(JSON_GIFT_FILE) > 0:
        try:
            with open(JSON_GIFT_FILE, "r", encoding="utf-8") as f:
                gifts = json.load(f)
        except Exception:
            gifts = {}

        for code, amt in (gifts.items() if isinstance(gifts, dict) else []):
            try:
                amt_i = int(amt)
            except Exception:
                continue
            cur.execute("SELECT 1 FROM gifts WHERE code = ?", (code,))
            if cur.fetchone():
                continue
            cur.execute("INSERT INTO gifts(code, amount) VALUES (?, ?)", (code, amt_i))
        conn.commit()


# Basic DB operations

def get_user(conn: sqlite3.Connection, username: str) -> Optional[dict]:
    cur = conn.cursor()
    cur.execute("SELECT username, password_hash, balance FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    if not row:
        return None
    return {"username": row[0], "password_hash": row[1], "balance": int(row[2])}


def create_user(conn: sqlite3.Connection, username: str, password: Optional[str], balance: int = 0) -> Tuple[bool, str]:
    username = username.strip().lower()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE username = ?", (username,))
    if cur.fetchone():
        return False, "username exists"
    pwd_hash = hash_password(password) if password else ""
    try:
        cur.execute("INSERT INTO users(username, password_hash, balance) VALUES (?, ?, ?)", (username, pwd_hash, int(balance)))
        conn.commit()
        return True, "ok"
    except Exception as e:
        return False, str(e)


def update_balance(conn: sqlite3.Connection, username: str, new_balance: int):
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = ? WHERE username = ?", (int(new_balance), username))
    conn.commit()


def transfer(conn: sqlite3.Connection, sender: str, recipient: str, amount: int) -> Tuple[bool, str]:
    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute("SELECT balance FROM users WHERE username = ?", (sender,))
        s = cur.fetchone()
        cur.execute("SELECT balance FROM users WHERE username = ?", (recipient,))
        r = cur.fetchone()
        if not s:
            conn.rollback()
            return False, "sender not found"
        if not r:
            conn.rollback()
            return False, "recipient not found"
        s_bal = int(s[0])
        if s_bal < amount:
            conn.rollback()
            return False, "insufficient funds"
        cur.execute("UPDATE users SET balance = balance - ? WHERE username = ?", (amount, sender))
        cur.execute("UPDATE users SET balance = balance + ? WHERE username = ?", (amount, recipient))
        conn.commit()
        return True, "ok"
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, str(e)


def redeem_gift(conn: sqlite3.Connection, username: str, code: str) -> Tuple[bool, str, int]:
    code = code.strip()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute("SELECT amount FROM gifts WHERE code = ?", (code,))
        g = cur.fetchone()
        if not g:
            conn.rollback()
            return False, "invalid code", 0
        amount = int(g[0])
        # check reserve
        cur.execute("SELECT balance FROM users WHERE username = ?", (SYSTEM_ACCOUNT,))
        j = cur.fetchone()
        if not j or int(j[0]) < amount:
            conn.rollback()
            return False, "system reserve insufficient", 0
        # update balances
        cur.execute("UPDATE users SET balance = balance - ? WHERE username = ?", (amount, SYSTEM_ACCOUNT))
        cur.execute("UPDATE users SET balance = balance + ? WHERE username = ?", (amount, username))
        cur.execute("DELETE FROM gifts WHERE code = ?", (code,))
        conn.commit()
        return True, "ok", amount
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, str(e), 0


def get_coin_prices(conn: sqlite3.Connection) -> Tuple[float, float, int]:
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE username = ?", (SYSTEM_ACCOUNT,))
    row = cur.fetchone()
    j_balance = int(row[0]) if row else 0
    sell_price = j_balance * 0.00001
    buy_price = sell_price * 1.10
    return buy_price, sell_price, j_balance


# --- App UI Configuration ---

st.set_page_config(page_title="Payback Coin System", page_icon="𝐌𝐉𝐞𝐜𝐤", layout="centered")
st.title("Payback Coin Management System")
st.markdown("Welcome to the web version of your coin tracking system! Made by Mjeck Studios")

# Initialize DB and migrate data if needed
conn = init_db()
migrate_json_to_db(conn)

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
        "More",
    ],
)

st.sidebar.markdown("---")
st.sidebar.info("Tip: Make sure the system account exists before creating regular accounts!")

# --- Option 1: Check Balance / Login ---
if choice == "Check Balance/Login":
    st.subheader("🔍 Balance Lookup")

    with st.form("login_form"):
        username = st.text_input("Username").strip().lower()
        password = st.text_input("Password", type="password")
        submit_login = st.form_submit_button("Check Balance")

        if submit_login:
            if not username:
                st.warning("⚠️ Please enter a username.")
            else:
                user = get_user(conn, username)
                if not user:
                    st.error(f"❌ Found no matches for username: '{username}'")
                else:
                    stored = user.get("password_hash", "")
                    if stored and not verify_password(stored, password):
                        st.error("❌ Incorrect password!")
                    else:
                        bal = int(user.get("balance", 0))
                        st.success(f"✅ Success! You currently have **{bal:,.2f}** payback coins.")

# --- Option 2: Create Account ---
elif choice == "Create Account":
    st.subheader("📝 Account Maker")

    sys_user = get_user(conn, SYSTEM_ACCOUNT)
    if not sys_user:
        st.error(f"❌ System error: Primary account '{SYSTEM_ACCOUNT}' must be created first!")
    else:
        j_bal = int(sys_user.get("balance", 0))
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
                    elif get_user(conn, new_user):
                        st.error(f"❌ '{new_user}' already exists! Choose a different username.")
                    else:
                        # perform transfer of 10 coins from system to new user atomically
                        ok, msg = create_user(conn, new_user, new_pass, balance=0)
                        if not ok:
                            st.error(f"❌ Could not create user: {msg}")
                        else:
                            ok2, msg2 = transfer(conn, SYSTEM_ACCOUNT, new_user, 10)
                            if not ok2:
                                st.error(f"❌ Could not fund new account: {msg2}")
                            else:
                                st.success(f"🎉 Success! Account created for '{new_user}' with 10 starter coins.")

# --- Option 3: View Coin Prices ---
elif choice == "View Coin Prices":
    st.subheader("📈 Payback Coin Market Value")

    buy_price, sell_price, j_bal = get_coin_prices(conn)

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
            s_user = get_user(conn, sender)
            if not s_user:
                st.error("❌ Sender username not found.")
            else:
                stored = s_user.get("password_hash", "")
                if stored and not verify_password(stored, pwd):
                    st.error("❌ Incorrect password!")
                elif recipient == sender:
                    st.error("❌ You cannot send coins to yourself!")
                elif not get_user(conn, recipient):
                    st.error(f"❌ Recipient '{recipient}' does not exist!")
                else:
                    sender_balance = int(s_user.get("balance", 0))
                    if sender_balance < int(amount):
                        st.error(f"❌ Insufficient funds! You only have {sender_balance} coins.")
                    else:
                        ok, msg = transfer(conn, sender, recipient, int(amount))
                        if not ok:
                            st.error(f"❌ Transfer failed: {msg}")
                        else:
                            new_sender = get_user(conn, sender)
                            st.success(f"🎉 Success! Transferred {int(amount)} coins to '{recipient}'.")
                            st.info(f"💰 Your new balance: **{new_sender.get('balance', 0)}** coins.")

# --- Option 5: Redeem Gift Card ---
elif choice == "Redeem Gift Card":
    st.subheader("🎁 Redeem Gift Card")

    with st.form("gift_form"):
        user = st.text_input("Your Username").strip().lower()
        pwd = st.text_input("Your Password", type="password")
        code = st.text_input("Gift Card Code").strip()
        submit_gift = st.form_submit_button("Redeem Code")

        if submit_gift:
            u = get_user(conn, user)
            if not u:
                st.error("❌ Username not found.")
            else:
                stored = u.get("password_hash", "")
                if stored and not verify_password(stored, pwd):
                    st.error("❌ Incorrect password!")
                else:
                    ok, msg, amt = redeem_gift(conn, user, code)
                    if not ok:
                        st.error(f"❌ {msg}")
                    else:
                        st.success(f"🎉 Success! Redeemed {amt} Payback coins from code '{code}'.")
                        new_bal = get_user(conn, user).get("balance", 0)
                        st.info(f"💰 Your new balance: **{new_bal}** coins.")

# --- Admin Controls ---
elif choice == "Admin Controls":
    st.info("Note: This Page is for Admins only")
    with st.form("admin_form"):
        input_code = st.text_input("Admin Code", type="password")
        submit = st.form_submit_button("Submit Admin Code")

        if submit:
            code1 = st.secrets.get("admin", {}).get("code1")
            code2 = st.secrets.get("admin", {}).get("code2")
            if input_code and (input_code == code1 or input_code == code2):
                st.success("Admin authenticated.")
                st.markdown("---")
                st.subheader("Admin Actions")
                # Bootstrap system account if missing
                if not get_user(conn, SYSTEM_ACCOUNT):
                    if st.button("Create SYSTEM_ACCOUNT with 1000 coins"):
                        ok, msg = create_user(conn, SYSTEM_ACCOUNT, None, balance=1000)
                        if ok:
                            st.success(f"Created {SYSTEM_ACCOUNT} with 1000 coins.")
                        else:
                            st.error(f"Failed: {msg}")
                else:
                    s = get_user(conn, SYSTEM_ACCOUNT)
                    st.info(f"{SYSTEM_ACCOUNT} balance: {s.get('balance', 0)}")

                # Option: view all users (dangerous on public deploy)
                if st.checkbox("Show all users (usernames and balances)"):
                    cur = conn.cursor()
                    cur.execute("SELECT username, balance FROM users ORDER BY username")
                    rows = cur.fetchall()
                    for r in rows:
                        st.write(f"- {r[0]}: {int(r[1])}")

                # Option: import JSON again
                if st.button("Re-run JSON -> DB migration"):
                    migrate_json_to_db(conn)
                    st.success("Migration attempted. Check logs/messages above for errors.")

            else:
                st.error("❌ Incorrect Admin Code!")

elif choice == "More":
    st.subheader("Click on One of these links to see more by Mjeck Studios")
    st.markdown("[Click here to visit NoSchool](https://mywebbrowser-noschool.streamlit.app)")


# End of app
