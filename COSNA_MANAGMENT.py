import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import streamlit_authenticator as stauth
from streamlit_authenticator.utilities.hasher import Hasher

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

# Create tables if they don't exist
cursor.execute('''CREATE TABLE IF NOT EXISTS classes
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS students
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   name TEXT, age INTEGER, enrollment_date DATE,
                   class_id INTEGER, FOREIGN KEY(class_id) REFERENCES classes(id))''')

cursor.execute('''CREATE TABLE IF NOT EXISTS uniforms
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   type TEXT, size TEXT, stock INTEGER, unit_cost REAL)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS expenses
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   date DATE, amount REAL, category TEXT)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS incomes
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   date DATE, amount REAL, source TEXT)''')

conn.commit()

# ─── Authenticator setup ───────────────────────────────────────────────
# Only run once per session (avoids recreating on every rerun)
if 'authenticator' not in st.session_state:
    credentials = {
        'usernames': {
            'admin': {
                'name': 'Administrator',
                'password': Hasher(['costa2026']).generate()[0],
                'email': 'admin@costa.school'
            }
        }
    }

    # CRITICAL: All arguments after credentials MUST be keywords (not positional!)
    st.session_state.authenticator = stauth.Authenticate(
        credentials,
        cookie_name='costa_school_cookie',
        key='costa_school_secret_key_2026_change_me_please',
        cookie_expiry_days=30
    )

    # Keep credentials reference for updates during forgot/reset
    st.session_state.credentials = credentials

authenticator = st.session_state.authenticator

# ─── Login screen ──────────────────────────────────────────────────────
name, authentication_status, username = authenticator.login('Login', 'main')

if authentication_status:
    st.session_state.logged_in = True
    st.session_state.username = username

    # Sidebar content
    with st.sidebar:
        st.write(f"**Welcome, {name}**")
        authenticator.logout('Logout', 'sidebar', key='unique_logout_key')

        # Change password (for logged-in user)
        with st.expander("Change my password"):
            try:
                if authenticator.reset_password(username, location='main'):
                    st.success('Password changed successfully!')
                    # Sync in-memory credentials
                    st.session_state.credentials['usernames'][username]['password'] = \
                        authenticator.credentials['usernames'][username]['password']
            except Exception as e:
                st.error(str(e))

elif authentication_status is False:
    st.error('Username or password is incorrect')
elif authentication_status is None:
    st.warning('Please enter your username and password')

# Forgot password – displays new random password on screen
try:
    username_forgot, email_forgot, random_pw = authenticator.forgot_password('main')
    if username_forgot:
        st.success(f"**New temporary password for {username_forgot}:**  {random_pw}")
        st.info("Copy this immediately — it disappears after refresh.")
        st.warning("Log in now, then change it via sidebar → Change my password")
        # Update in-memory hash
        st.session_state.credentials['usernames'][username_forgot]['password'] = \
            Hasher([random_pw]).generate()[0]
except Exception as e:
    if "No username provided" not in str(e):
        st.error(f"Forgot password error: {str(e)}")

# Stop execution if not authenticated
if not authentication_status:
    st.stop()

# ─── Main navigation ───────────────────────────────────────────────────
page = st.sidebar.radio("Menu", [
    "Dashboard",
    "Students",
    "Uniforms",
    "Finances",
    "Financial Report"
])

# ─── Dashboard ─────────────────────────────────────────────────────────
if page == "Dashboard":
    st.header("Overview")

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Students", conn.execute("SELECT COUNT(*) FROM students").fetchone()[0])
    col2.metric("Total Uniform Stock", conn.execute("SELECT SUM(stock) FROM uniforms").fetchone()[0] or 0)

    inc_sum = conn.execute("SELECT SUM(amount) FROM incomes").fetchone()[0] or 0
    exp_sum = conn.execute("SELECT SUM(amount) FROM expenses").fetchone()[0] or 0
    col3.metric("Net Balance (All Time)", f"USh {inc_sum - exp_sum:,.0f}")

# ─── Students page ─────────────────────────────────────────────────────
elif page == "Students":
    st.header("Students")

    tab1, tab2 = st.tabs(["View & Export", "Add Student"])

    with tab1:
        df = pd.read_sql_query("""
            SELECT s.id, s.name, s.age, s.enrollment_date, c.name AS class_name
            FROM students s LEFT JOIN classes c ON s.class_id = c.id
        """, conn)
        st.dataframe(df, use_container_width=True)

        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Students', index=False)
        output.seek(0)
        st.download_button(
            "Download Students Excel",
            output,
            file_name="costa_students.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    with tab2:
        with st.form("add_student"):
            name = st.text_input("Name")
            age = st.number_input("Age", min_value=5, max_value=30)
            enroll_date = st.date_input("Enrollment Date")
            classes = pd.read_sql("SELECT id, name FROM classes", conn)
            class_name = st.selectbox("Class", classes['name'] if not classes.empty else ["No classes"])
            class_id = classes[classes['name'] == class_name]['id'].iloc[0] if not classes.empty and class_name != "No classes" else None

            submitted = st.form_submit_button("Add")
            if submitted and name and class_id is not None:
                cursor.execute(
                    "INSERT INTO students (name, age, enrollment_date, class_id) VALUES (?, ?, ?, ?)",
                    (name, age, enroll_date, int(class_id))
                )
                conn.commit()
                st.success("Student added!")
                st.rerun()

    with st.expander("Add Class"):
        new_class = st.text_input("Class name")
        if st.button("Add") and new_class:
            try:
                cursor.execute("INSERT INTO classes (name) VALUES (?)", (new_class,))
                conn.commit()
                st.success("Class added")
            except:
                st.error("Class already exists")

# ─── Uniforms page ─────────────────────────────────────────────────────
elif page == "Uniforms":
    st.header("Uniforms")

    df = pd.read_sql("SELECT * FROM uniforms", conn)
    st.dataframe(df)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Uniforms', index=False)
    output.seek(0)
    st.download_button("Download Excel", output, "uniforms.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with st.form("uniform"):
        typ = st.text_input("Type")
        sz = st.text_input("Size")
        stk = st.number_input("Stock", 0)
        cst = st.number_input("Cost", 0.0)
        if st.form_submit_button("Add"):
            cursor.execute("INSERT INTO uniforms (type, size, stock, unit_cost) VALUES (?,?,?,?)", (typ, sz, stk, cst))
            conn.commit()
            st.success("Added")

# ─── Finances page ─────────────────────────────────────────────────────
elif page == "Finances":
    st.header("Finances")

    c1, c2 = st.columns(2)
    with c1:
        with st.form("expense"):
            dt = st.date_input("Date")
            amt = st.number_input("Amount")
            cat = st.text_input("Category")
            if st.form_submit_button("Save Expense"):
                cursor.execute("INSERT INTO expenses VALUES (NULL,?,?,?)", (dt, amt, cat))
                conn.commit()
                st.success("Saved")

    with c2:
        with st.form("income"):
            dt = st.date_input("Date")
            amt = st.number_input("Amount")
            src = st.text_input("Source")
            if st.form_submit_button("Save Income"):
                cursor.execute("INSERT INTO incomes VALUES (NULL,?,?,?)", (dt, amt, src))
                conn.commit()
                st.success("Saved")

# ─── Report page ───────────────────────────────────────────────────────
elif page == "Financial Report":
    st.header("Financial Report")

    c1, c2 = st.columns(2)
    sdate = c1.date_input("Start")
    edate = c2.date_input("End")

    if st.button("Generate"):
        exp = pd.read_sql_query("SELECT * FROM expenses WHERE date BETWEEN ? AND ?", conn, params=(sdate, edate))
        inc = pd.read_sql_query("SELECT * FROM incomes WHERE date BETWEEN ? AND ?", conn, params=(sdate, edate))

        texp = exp.amount.sum()
        tinc = inc.amount.sum()
        bal = tinc - texp

        st.metric("Income", f"USh {tinc:,.0f}")
        st.metric("Expenses", f"USh {texp:,.0f}")
        st.metric("Balance", f"USh {bal:,.0f}")

        t1, t2 = st.tabs(["Incomes", "Expenses"])
        t1.dataframe(inc)
        t2.dataframe(exp)

        # PDF
        buf = BytesIO()
        p = canvas.Canvas(buf, pagesize=letter)
        p.drawString(100, 750, "Costa School Report")
        p.drawString(100, 730, f"{sdate} to {edate}")
        y = 680
        p.drawString(100, y, f"Income: {tinc:,.0f}"); y -= 30
        p.drawString(100, y, f"Expenses: {texp:,.0f}"); y -= 30
        p.drawString(100, y, f"Balance: {bal:,.0f}")
        p.save()
        buf.seek(0)
        st.download_button("PDF", buf, "report.pdf", "application/pdf")

        # Excel
        ebuf = BytesIO()
        with pd.ExcelWriter(ebuf, engine='xlsxwriter') as w:
            inc.to_excel(w, "Incomes")
            exp.to_excel(w, "Expenses")
            pd.DataFrame({"Metric": ["Income","Expenses","Balance"], "Value":[tinc,texp,bal]}).to_excel(w, "Summary")
        ebuf.seek(0)
        st.download_button("Excel", ebuf, "report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.sidebar.info("Powered by SQLite on Streamlit Cloud")
