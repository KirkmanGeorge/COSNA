import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import streamlit_authenticator as stauth

# ─── Page config ───────────────────────────────────────────────────────
st.set_page_config(page_title="Costa School Management", layout="wide")
st.title("Costa School Management System")
st.markdown("Students • Uniforms • Finances • Reports")

# ─── SQLite connection ─────────────────────────────────────────────────
@st.cache_resource
def get_db_connection():
    conn = sqlite3.connect('costa_school.db', check_same_thread=False)
    return conn

conn = get_db_connection()
cursor = conn.cursor()

# Create tables
cursor.execute('''CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, age INTEGER, enrollment_date DATE, class_id INTEGER, FOREIGN KEY(class_id) REFERENCES classes(id))''')
cursor.execute('''CREATE TABLE IF NOT EXISTS uniforms (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, size TEXT, stock INTEGER, unit_cost REAL)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE, amount REAL, category TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS incomes (id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE, amount REAL, source TEXT)''')
conn.commit()

# ─── Authenticator setup ───────────────────────────────────────────────
if 'authenticator' not in st.session_state:
    credentials = {
        'usernames': {
            'admin': {
                'name': 'Administrator',
                'password': 'costa2026',  # plain text – library auto-hashes
                'email': 'admin@costa.school'
            }
        }
    }

    st.session_state.authenticator = stauth.Authenticate(
        credentials=credentials,
        cookie_name='costa_school_cookie',
        cookie_key='costa_school_secret_2026_change_this',
        cookie_expiry_days=30
    )

    st.session_state.credentials = credentials

authenticator = st.session_state.authenticator

# ─── Login – with required location keyword ────────────────────────────
name, authentication_status, username = authenticator.login(
    form_name='Login',
    location='main'  # ← this is required in your installed version
)

if authentication_status:
    st.session_state.logged_in = True
    st.session_state.username = username

    with st.sidebar:
        st.write(f"**Welcome, {name}**")
        authenticator.logout('Logout', 'sidebar', key='logout_key')

        with st.expander("Change my password"):
            try:
                if authenticator.reset_password(username):
                    st.success('Password changed successfully')
            except Exception as e:
                st.error(str(e))

elif authentication_status is False:
    st.error('Username or password is incorrect')
elif authentication_status is None:
    st.warning('Please enter username and password')

# Forgot password
try:
    username_forgot, email_forgot, random_pw = authenticator.forgot_password('Forgot password?')
    if username_forgot:
        st.success(f"**New temporary password for {username_forgot}:**  {random_pw}")
        st.info("Copy this immediately – it disappears after refresh.")
        st.warning("Log in now, then change it via sidebar → Change my password")
except Exception as e:
    if "No username provided" not in str(e):
        st.error(f"Forgot password error: {str(e)}")

if not authentication_status:
    st.stop()

# ─── Navigation ────────────────────────────────────────────────────────
page = st.sidebar.radio("Menu", ["Dashboard", "Students", "Uniforms", "Finances", "Financial Report"])

# ─── Dashboard ─────────────────────────────────────────────────────────
if page == "Dashboard":
    st.header("Overview")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Students", conn.execute("SELECT COUNT(*) FROM students").fetchone()[0])
    col2.metric("Total Uniform Stock", conn.execute("SELECT SUM(stock) FROM uniforms").fetchone()[0] or 0)
    inc = conn.execute("SELECT SUM(amount) FROM incomes").fetchone()[0] or 0
    exp = conn.execute("SELECT SUM(amount) FROM expenses").fetchone()[0] or 0
    col3.metric("Net Balance", f"USh {inc - exp:,.0f}")

# ─── Students (expand as needed) ───────────────────────────────────────
elif page == "Students":
    st.header("Students")
    # Add your view/add/export code here

# ─── Uniforms ──────────────────────────────────────────────────────────
elif page == "Uniforms":
    st.header("Uniforms")
    # Add your code

# ─── Finances ──────────────────────────────────────────────────────────
elif page == "Finances":
    st.header("Income & Expenses")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Expense")
        with st.form("exp"):
            d = st.date_input("Date")
            a = st.number_input("Amount", 0.0)
            cat = st.text_input("Category")
            if st.form_submit_button("Save"):
                cursor.execute("INSERT INTO expenses (date, amount, category) VALUES (?,?,?)", (d, a, cat))
                conn.commit()
                st.success("Saved")
    with col2:
        st.subheader("Income")
        with st.form("inc"):
            d = st.date_input("Date")
            a = st.number_input("Amount", 0.0)
            src = st.text_input("Source")
            if st.form_submit_button("Save"):
                cursor.execute("INSERT INTO incomes (date, amount, source) VALUES (?,?,?)", (d, a, src))
                conn.commit()
                st.success("Saved")

# ─── Financial Report ──────────────────────────────────────────────────
elif page == "Financial Report":
    st.header("Financial Report")
    col1, col2 = st.columns(2)
    start = col1.date_input("From", datetime(datetime.today().year, 1, 1))
    end = col2.date_input("To", datetime.today())
    if st.button("Generate"):
        exp = pd.read_sql_query("SELECT * FROM expenses WHERE date BETWEEN ? AND ?", conn, params=(start, end))
        inc = pd.read_sql_query("SELECT * FROM incomes WHERE date BETWEEN ? AND ?", conn, params=(start, end))
        texp = exp["amount"].sum()
        tinc = inc["amount"].sum()
        bal = tinc - texp
        st.metric("Income", f"USh {tinc:,.0f}")
        st.metric("Expenses", f"USh {texp:,.0f}")
        st.metric("Balance", f"USh {bal:,.0f}")
        tab1, tab2 = st.tabs(["Incomes", "Expenses"])
        tab1.dataframe(inc)
        tab2.dataframe(exp)
        # Add PDF/Excel if needed

st.sidebar.info("SQLite database – persistent on Streamlit Cloud")
