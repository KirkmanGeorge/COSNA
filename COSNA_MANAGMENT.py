import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# ─── Page config ───────────────────────────────────────────────────────
st.set_page_config(page_title="Costa School Management", layout="wide")
st.title("Costa School Management System")
st.markdown("Students • Uniforms • Finances • Reports")

# ─── Simple login (session state) ──────────────────────────────────────
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.subheader("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if username == "admin" and password == "costa2026":
            st.session_state.logged_in = True
            st.success("Logged in successfully!")
            st.rerun()
        else:
            st.error("Invalid username or password")
    st.stop()  # Stop here if not logged in

# Logout button in sidebar
with st.sidebar:
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.rerun()

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

# ─── Navigation ────────────────────────────────────────────────────────
page = st.sidebar.radio("Menu", ["Dashboard", "Students", "Uniforms", "Finances", "Financial Report"])

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
            age = st.number_input("Age", min_value=5, max_value=30, value=10)
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
        utype = st.text_input("Type (e.g. Shirt)")
        size = st.text_input("Size (e.g. M)")
        stock = st.number_input("Stock", min_value=0, step=1)
        cost = st.number_input("Unit cost (UGX)", min_value=0.0, step=500.0)
        if st.form_submit_button("Add item"):
            cursor.execute(
                "INSERT INTO uniforms (type, size, stock, unit_cost) VALUES (?, ?, ?, ?)",
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
            a = st.number_input("Amount", min_value=0.0, step=1000.0)
            cat = st.text_input("Category (e.g. Salaries)")
            if st.form_submit_button("Save"):
                cursor.execute("INSERT INTO expenses (date, amount, category) VALUES (?, ?, ?)", (d, a, cat))
                conn.commit()
                st.success("Expense saved")

    with col2:
        st.subheader("Income")
        with st.form("inc"):
            d = st.date_input("Date")
            a = st.number_input("Amount", min_value=0.0, step=1000.0)
            src = st.text_input("Source (e.g. Fees)")
            if st.form_submit_button("Save"):
                cursor.execute("INSERT INTO incomes (date, amount, source) VALUES (?, ?, ?)", (d, a, src))
                conn.commit()
                st.success("Income saved")

# ─── Financial Report ──────────────────────────────────────────────────
elif page == "Financial Report":
    st.header("Financial Report")

    col1, col2 = st.columns(2)
    start = col1.date_input("Start Date", datetime(datetime.today().year, 1, 1))
    end = col2.date_input("End Date", datetime.today())

    if st.button("Generate Report"):
        exp = pd.read_sql_query("SELECT * FROM expenses WHERE date BETWEEN ? AND ?", conn, params=(start, end))
        inc = pd.read_sql_query("SELECT * FROM incomes WHERE date BETWEEN ? AND ?", conn, params=(start, end))

        total_exp = exp["amount"].sum()
        total_inc = inc["amount"].sum()
        balance = total_inc - total_exp

        st.metric("Total Income", f"USh {total_inc:,.0f}")
        st.metric("Total Expenses", f"USh {total_exp:,.0f}")
        st.metric("Balance", f"USh {balance:,.0f}")

        tab1, tab2 = st.tabs(["Incomes", "Expenses"])
        tab1.dataframe(inc)
        tab2.dataframe(exp)

        # PDF Export
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

        # Excel Export
        excel_buf = BytesIO()
        with pd.ExcelWriter(excel_buf, engine='xlsxwriter') as writer:
            inc.to_excel(writer, sheet_name="Incomes", index=False)
            exp.to_excel(writer, sheet_name="Expenses", index=False)
            pd.DataFrame({
                "Metric": ["Total Income", "Total Expenses", "Balance"],
                "Value (USh)": [total_inc, total_exp, balance]
            }).to_excel(writer, sheet_name="Summary", index=False)
        excel_buf.seek(0)
        st.download_button("Download Excel Report", excel_buf, f"financial_{start}_to_{end}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.sidebar.info("Logged in as admin – data saved in SQLite (persistent on Streamlit Cloud)")
