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

# ─── Authenticator setup (only once per session) ───────────────────────
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

    st.session_state.authenticator = stauth.Authenticate(
        credentials,
        cookie_name='costa_school_cookie',
        cookie_key='costa_school_secret_key_2026_change_me_please',  # ← FIXED: cookie_key, not key
        cookie_expiry_days=30
    )

    st.session_state.credentials = credentials

authenticator = st.session_state.authenticator

# ─── Login screen ──────────────────────────────────────────────────────
name, authentication_status, username = authenticator.login('Login', 'main')

if authentication_status:
    st.session_state.logged_in = True
    st.session_state.username = username

    # Sidebar – welcome + logout + change password
    with st.sidebar:
        st.write(f"**Welcome, {name}**")
        authenticator.logout('Logout', 'sidebar', key='unique_logout_key')

        # Change own password
        with st.expander("Change my password"):
            try:
                if authenticator.reset_password(username, location='main'):
                    st.success('Password changed successfully!')
                    st.session_state.credentials['usernames'][username]['password'] = \
                        authenticator.credentials['usernames'][username]['password']
            except Exception as e:
                st.error(str(e))

elif authentication_status is False:
    st.error('Username or password is incorrect')
elif authentication_status is None:
    st.warning('Please enter username and password')

# Forgot password – shows new random password on screen
try:
    username_forgot, email_forgot, random_pw = authenticator.forgot_password('main')
    if username_forgot:
        st.success(f"**New temporary password for {username_forgot}:**  {random_pw}")
        st.info("Copy this immediately — it disappears after refresh.")
        st.warning("Log in now, then change it via sidebar → Change my password")
        st.session_state.credentials['usernames'][username_forgot]['password'] = \
            Hasher([random_pw]).generate()[0]
except Exception as e:
    if "No username provided" not in str(e):
        st.error(f"Forgot password error: {str(e)}")

if not authentication_status:
    st.stop()

# ─── Navigation ────────────────────────────────────────────────────────
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

# ─── Students ──────────────────────────────────────────────────────────
elif page == "Students":
    st.header("Students")

    tab1, tab2 = st.tabs(["View & Export", "Add Student"])

    with tab1:
        df = pd.read_sql_query("""
            SELECT s.id, s.name, s.age, s.enrollment_date, c.name AS class_name
            FROM students s LEFT JOIN classes c ON s.class_id = c.id
        """, conn)
        st.dataframe(df, use_container_width=True)

        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Students', index=False)
        buf.seek(0)
        st.download_button(
            label="Download Students Excel",
            data=buf,
            file_name="costa_students.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    with tab2:
        with st.form("add_student"):
            name = st.text_input("Full name")
            age = st.number_input("Age", 5, 30, 10)
            enroll_date = st.date_input("Enrollment date", datetime.today())
            cls_df = pd.read_sql("SELECT id, name FROM classes", conn)
            cls_name = st.selectbox("Class", cls_df["name"] if not cls_df.empty else ["No classes yet"])
            cls_id = cls_df[cls_df["name"] == cls_name]["id"].iloc[0] if not cls_df.empty and cls_name != "No classes yet" else None

            if st.form_submit_button("Add Student") and name and cls_id is not None:
                cursor.execute(
                    "INSERT INTO students (name, age, enrollment_date, class_id) VALUES (?, ?, ?, ?)",
                    (name, age, enroll_date, int(cls_id))
                )
                conn.commit()
                st.success("Student added")
                st.rerun()

    with st.expander("Add new class"):
        new_cls = st.text_input("Class name (e.g. P.1, S.2)")
        if st.button("Create class") and new_cls:
            try:
                cursor.execute("INSERT INTO classes (name) VALUES (?)", (new_cls,))
                conn.commit()
                st.success(f"Class {new_cls} created")
            except sqlite3.IntegrityError:
                st.error("Class name already exists")

# ─── Uniforms ──────────────────────────────────────────────────────────
elif page == "Uniforms":
    st.header("Uniforms")

    df = pd.read_sql("SELECT * FROM uniforms", conn)
    st.dataframe(df, use_container_width=True)

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Uniforms', index=False)
    buf.seek(0)
    st.download_button("Download Uniforms Excel", buf, "uniforms.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with st.form("add_uniform"):
        utype = st.text_input("Type")
        size  = st.text_input("Size")
        stock = st.number_input("Stock", 0, step=1)
        cost  = st.number_input("Unit cost (UGX)", 0.0, step=500.0)

        if st.form_submit_button("Add item"):
            cursor.execute(
                "INSERT INTO uniforms (type, size, stock, unit_cost) VALUES (?,?,?,?)",
                (utype, size, stock, cost)
            )
            conn.commit()
            st.success("Item added")
            st.rerun()

# ─── Finances ──────────────────────────────────────────────────────────
elif page == "Finances":
    st.header("Income & Expenses")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Expense")
        with st.form("exp"):
            d = st.date_input("Date")
            a = st.number_input("Amount", 0.0, step=1000.0)
            cat = st.text_input("Category")
            if st.form_submit_button("Save"):
                cursor.execute("INSERT INTO expenses (date, amount, category) VALUES (?,?,?)", (d, a, cat))
                conn.commit()
                st.success("Saved")

    with col2:
        st.subheader("Income")
        with st.form("inc"):
            d = st.date_input("Date")
            a = st.number_input("Amount", 0.0, step=1000.0)
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
    end   = col2.date_input("To", datetime.today())

    if st.button("Generate"):
        exp_df = pd.read_sql_query("SELECT * FROM expenses WHERE date BETWEEN ? AND ?", conn, params=(start, end))
        inc_df = pd.read_sql_query("SELECT * FROM incomes WHERE date BETWEEN ? AND ?", conn, params=(start, end))

        total_exp = exp_df["amount"].sum()
        total_inc = inc_df["amount"].sum()
        balance = total_inc - total_exp

        st.metric("Income", f"USh {total_inc:,.0f}")
        st.metric("Expenses", f"USh {total_exp:,.0f}")
        st.metric("Balance", f"USh {balance:,.0f}")

        tab1, tab2 = st.tabs(["Incomes", "Expenses"])
        tab1.dataframe(inc_df)
        tab2.dataframe(exp_df)

        # PDF export
        pdf_buf = BytesIO()
        pdf = canvas.Canvas(pdf_buf, pagesize=letter)
        pdf.drawString(100, 750, "Costa School Financial Report")
        pdf.drawString(100, 730, f"Period: {start} to {end}")
        y = 680
        pdf.drawString(100, y, f"Total Income: USh {total_inc:,.0f}"); y -= 40
        pdf.drawString(100, y, f"Total Expenses: USh {total_exp:,.0f}"); y -= 40
        pdf.drawString(100, y, f"Balance: USh {balance:,.0f}")
        pdf.save()
        pdf_buf.seek(0)
        st.download_button("Download PDF", pdf_buf, f"report_{start}_to_{end}.pdf", "application/pdf")

        # Excel export
        excel_buf = BytesIO()
        with pd.ExcelWriter(excel_buf, engine='xlsxwriter') as writer:
            inc_df.to_excel(writer, sheet_name="Incomes", index=False)
            exp_df.to_excel(writer, sheet_name="Expenses", index=False)
            pd.DataFrame({
                "Metric": ["Total Income", "Total Expenses", "Balance"],
                "Value (USh)": [total_inc, total_exp, balance]
            }).to_excel(writer, sheet_name="Summary", index=False)
        excel_buf.seek(0)
        st.download_button("Download Excel", excel_buf, f"financial_{start}_to_{end}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.sidebar.info("Data stored in SQLite – persistent on Streamlit Cloud")
