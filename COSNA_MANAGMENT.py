import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import streamlit_authenticator as stauth
from streamlit_authenticator.utilities.hasher import Hasher
import yaml
from yaml.loader import SafeLoader
import secrets

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

# ─── streamlit-authenticator setup ─────────────────────────────────────
# Initial credentials (hashed passwords)
if 'credentials' not in st.session_state:
    credentials = {
        'usernames': {
            'admin': {
                'name': 'Administrator',
                'password': Hasher(['costa2026']).generate()[0],  # hashed version of "costa2026"
                'email': 'admin@costa.school'
            }
            # You can add more users here later
        }
    }
    st.session_state.credentials = credentials

authenticator = stauth.Authenticate(
    st.session_state.credentials,
    cookie_name='costa_school_cookie',
    key='costa_school_secret_key_2026_change_this',  # change this to a strong random string
    cookie_expiry_days=30
)

# ─── Login UI ──────────────────────────────────────────────────────────
name, authentication_status, username = authenticator.login('Login', 'main')

if authentication_status:
    st.session_state.logged_in = True
    st.session_state.username = username

    # Logout & password change in sidebar
    with st.sidebar:
        st.write(f"Welcome, **{name}**")
        authenticator.logout('Logout', 'sidebar', key='unique_key_logout')

        # Allow user to change their own password
        with st.expander("Change my password"):
            try:
                if authenticator.reset_password(username, location='sidebar'):
                    st.success('Password updated successfully')
                    # Update the in-memory credentials (important!)
                    st.session_state.credentials['usernames'][username]['password'] = \
                        authenticator.credentials['usernames'][username]['password']
            except Exception as e:
                st.error(e)

elif authentication_status is False:
    st.error('Username / password is incorrect')
elif authentication_status is None:
    st.warning('Please enter your username and password')

# Forgot Password (shows new random password on screen)
try:
    username_of_forgot_pw, email_of_forgot_pw, random_password = authenticator.forgot_password('main')
    if username_of_forgot_pw:
        st.success(f"**New temporary password for {username_of_forgot_pw}:**  {random_password}")
        st.info("Copy this password now — it will NOT be shown again.")
        st.warning("After login, go to sidebar → Change my password to set a new one.")
        # Update credentials in session state
        st.session_state.credentials['usernames'][username_of_forgot_pw]['password'] = \
            Hasher([random_password]).generate()[0]
except Exception as e:
    if "No username provided" not in str(e):
        st.error(f"Forgot password error: {e}")

if not authentication_status:
    st.stop()

# ─── Main navigation ───────────────────────────────────────────────────
page = st.sidebar.radio("Go to", ["Dashboard", "Students", "Uniforms", "Finances", "Financial Report"])

# ─── Dashboard ─────────────────────────────────────────────────────────
if page == "Dashboard":
    st.header("Overview")

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Students", conn.execute("SELECT COUNT(*) FROM students").fetchone()[0])
    col2.metric("Total Uniform Items", conn.execute("SELECT SUM(stock) FROM uniforms").fetchone()[0] or 0)

    total_inc = conn.execute("SELECT SUM(amount) FROM incomes").fetchone()[0] or 0
    total_exp = conn.execute("SELECT SUM(amount) FROM expenses").fetchone()[0] or 0
    col3.metric("Net Balance (All Time)", f"USh {total_inc - total_exp:,.0f}")

# ─── Students ──────────────────────────────────────────────────────────
elif page == "Students":
    st.header("Students")

    tab1, tab2 = st.tabs(["View & Export", "Add Student"])

    with tab1:
        df = pd.read_sql_query("""
            SELECT s.id, s.name, s.age, s.enrollment_date, c.name as class_name
            FROM students s
            LEFT JOIN classes c ON s.class_id = c.id
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
            name = st.text_input("Full Name")
            age = st.number_input("Age", 5, 30, 10)
            enroll_date = st.date_input("Enrollment Date", datetime.today())
            classes_df = pd.read_sql("SELECT id, name FROM classes", conn)
            class_name = st.selectbox("Class", classes_df["name"] if not classes_df.empty else ["No classes yet"])
            class_id = classes_df[classes_df["name"] == class_name]["id"].iloc[0] if not classes_df.empty and class_name != "No classes yet" else None

            if st.form_submit_button("Add Student") and name and class_id:
                cursor.execute(
                    "INSERT INTO students (name, age, enrollment_date, class_id) VALUES (?, ?, ?, ?)",
                    (name, age, enroll_date, int(class_id))
                )
                conn.commit()
                st.success("Student added")
                st.rerun()

    with st.expander("Add New Class"):
        new_class = st.text_input("Class name (e.g. P.1, S.1)")
        if st.button("Add Class") and new_class:
            try:
                cursor.execute("INSERT INTO classes (name) VALUES (?)", (new_class,))
                conn.commit()
                st.success(f"Class '{new_class}' added")
            except sqlite3.IntegrityError:
                st.error("Class already exists")

# ─── Uniforms ──────────────────────────────────────────────────────────
elif page == "Uniforms":
    st.header("Uniforms Inventory")

    df = pd.read_sql("SELECT * FROM uniforms", conn)
    st.dataframe(df, use_container_width=True)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Uniforms', index=False)
    output.seek(0)
    st.download_button("Download Uniforms Excel", output, "uniforms.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with st.form("add_uniform"):
        utype = st.text_input("Type (Shirt, Skirt, Trouser, etc.)")
        size = st.text_input("Size (S, M, L, XL, etc.)")
        stock = st.number_input("Current Stock", 0, step=1)
        cost = st.number_input("Unit Cost (UGX)", 0.0, step=500.0)

        if st.form_submit_button("Add Uniform Item"):
            cursor.execute(
                "INSERT INTO uniforms (type, size, stock, unit_cost) VALUES (?, ?, ?, ?)",
                (utype, size, stock, cost)
            )
            conn.commit()
            st.success("Uniform added")
            st.rerun()

# ─── Finances ──────────────────────────────────────────────────────────
elif page == "Finances":
    st.header("Income & Expenses")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Record Expense")
        with st.form("expense"):
            date = st.date_input("Date")
            amount = st.number_input("Amount (UGX)", 0.0, step=1000.0)
            category = st.text_input("Category (Salaries, Rent, Supplies, etc.)")
            if st.form_submit_button("Save Expense"):
                cursor.execute("INSERT INTO expenses (date, amount, category) VALUES (?,?,?)",
                               (date, amount, category))
                conn.commit()
                st.success("Expense recorded")

    with col2:
        st.subheader("Record Income")
        with st.form("income"):
            date = st.date_input("Date")
            amount = st.number_input("Amount (UGX)", 0.0, step=1000.0)
            source = st.text_input("Source (Fees, Donation, Uniform sales, etc.)")
            if st.form_submit_button("Save Income"):
                cursor.execute("INSERT INTO incomes (date, amount, source) VALUES (?,?,?)",
                               (date, amount, source))
                conn.commit()
                st.success("Income recorded")

    # Recent records
    st.subheader("Recent Transactions")
    tab_exp, tab_inc = st.tabs(["Expenses", "Incomes"])
    with tab_exp:
        df_exp = pd.read_sql("SELECT * FROM expenses ORDER BY date DESC LIMIT 15", conn)
        st.dataframe(df_exp)
    with tab_inc:
        df_inc = pd.read_sql("SELECT * FROM incomes ORDER BY date DESC LIMIT 15", conn)
        st.dataframe(df_inc)

# ─── Financial Report ──────────────────────────────────────────────────
elif page == "Financial Report":
    st.header("Financial Report")

    col1, col2 = st.columns(2)
    start = col1.date_input("Start date", datetime(datetime.today().year, 1, 1))
    end   = col2.date_input("End date", datetime.today())

    if st.button("Generate Report"):
        df_exp = pd.read_sql_query("SELECT * FROM expenses WHERE date BETWEEN ? AND ?", conn, params=(start, end))
        df_inc = pd.read_sql_query("SELECT * FROM incomes  WHERE date BETWEEN ? AND ?", conn, params=(start, end))

        total_exp = df_exp["amount"].sum()
        total_inc = df_inc["amount"].sum()
        balance   = total_inc - total_exp

        st.metric("Total Income",   f"USh {total_inc:,.0f}")
        st.metric("Total Expenses", f"USh {total_exp:,.0f}")
        st.metric("Balance",        f"USh {balance:,.0f}", delta_color="normal")

        tab1, tab2 = st.tabs(["Incomes", "Expenses"])
        with tab1: st.dataframe(df_inc)
        with tab2: st.dataframe(df_exp)

        # PDF
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=letter)
        pdf.drawString(100, 750, "Costa School Financial Report")
        pdf.drawString(100, 730, f"Period: {start} to {end}")
        y = 680
        pdf.drawString(100, y, f"Total Income:   USh {total_inc:,.0f}"); y -= 40
        pdf.drawString(100, y, f"Total Expenses: USh {total_exp:,.0f}"); y -= 40
        pdf.drawString(100, y, f"Balance:        USh {balance:,.0f}")
        pdf.save()
        buffer.seek(0)
        st.download_button("Download PDF", buffer, f"report_{start}_to_{end}.pdf", "application/pdf")

        # Excel
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
            df_inc.to_excel(writer, sheet_name="Incomes", index=False)
            df_exp.to_excel(writer, sheet_name="Expenses", index=False)
            pd.DataFrame({
                "Metric": ["Total Income", "Total Expenses", "Balance"],
                "Value (UGX)": [total_inc, total_exp, balance]
            }).to_excel(writer, sheet_name="Summary", index=False)
        excel_buffer.seek(0)
        st.download_button("Download Excel Report", excel_buffer, f"financial_report_{start}_to_{end}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.sidebar.info("SQLite database is persistent on Streamlit Cloud")
