import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# ─── Page config ───────────────────────────────────────────────────────
st.set_page_config(page_title="COSNA School Management", layout="wide", initial_sidebar_state="expanded")
st.title("COSNA School Management System")
st.markdown("Students • Uniforms • Finances • Reports")

# ─── Simple login ──────────────────────────────────────────────────────
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.subheader("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if username == "admin" and password == "costa2026":
            st.session_state.logged_in = True
            st.success("Logged in!")
            st.rerun()
        else:
            st.error("Invalid credentials")
    st.stop()

with st.sidebar:
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.rerun()

# ─── Database ──────────────────────────────────────────────────────────
@st.cache_resource
def get_db_connection():
    conn = sqlite3.connect('cosna_school.db', check_same_thread=False)
    return conn

conn = get_db_connection()
cursor = conn.cursor()

# Create tables
cursor.execute('''CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, age INTEGER, enrollment_date DATE, class_id INTEGER, FOREIGN KEY(class_id) REFERENCES classes(id))''')
cursor.execute('''CREATE TABLE IF NOT EXISTS uniform_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT UNIQUE, gender TEXT, is_shared INTEGER DEFAULT 0)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS uniforms (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER UNIQUE, stock INTEGER DEFAULT 0, unit_price REAL DEFAULT 0.0, FOREIGN KEY(category_id) REFERENCES uniform_categories(id))''')
cursor.execute('''CREATE TABLE IF NOT EXISTS expense_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE, amount REAL, category_id INTEGER, FOREIGN KEY(category_id) REFERENCES expense_categories(id))''')
cursor.execute('''CREATE TABLE IF NOT EXISTS incomes (id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE, amount REAL, source TEXT)''')
conn.commit()

# ─── One-time initialization (cached) ──────────────────────────────────
@st.cache_resource
def initialize_database():
    # Uniform categories
    uniform_seeds = [
        ('Boys Main Shorts', 'boys', 0),
        ('Button Shirts Main', 'shared', 1),
        ('Boys Stockings', 'boys', 0),
        ('Boys Sports Shorts', 'boys', 0),
        ('Shared Sports T-Shirts', 'shared', 1),
        ('Girls Main Dresses', 'girls', 0)
    ]

    for cat_name, gender, is_shared in uniform_seeds:
        cursor.execute("SELECT id FROM uniform_categories WHERE category = ?", (cat_name,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO uniform_categories (category, gender, is_shared) VALUES (?, ?, ?)",
                (cat_name, gender, is_shared)
            )
            conn.commit()
            cat_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO uniforms (category_id, stock, unit_price) VALUES (?, 0, 0.0)",
                (cat_id,)
            )
            conn.commit()

    # Expense categories
    expense_seeds = ['Medical', 'Salaries', 'Utilities', 'Maintenance', 'Supplies', 'Transport', 'Events']
    for cat in expense_seeds:
        cursor.execute("SELECT id FROM expense_categories WHERE name = ?", (cat,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO expense_categories (name) VALUES (?)", (cat,))
            conn.commit()

    return "Initialization complete"

# Run initialization once (cached)
initialize_database()

# ─── Navigation ────────────────────────────────────────────────────────
page = st.sidebar.radio("Menu", ["Dashboard", "Students", "Uniforms", "Finances", "Financial Report"])

# ─── Dashboard ─────────────────────────────────────────────────────────
if page == "Dashboard":
    st.header("Overview")
    col1, col2 = st.columns(2)
    col1.metric("Total Students", conn.execute("SELECT COUNT(*) FROM students").fetchone()[0])
    col2.metric("Net Balance", f"USh {(conn.execute('SELECT SUM(amount) FROM incomes').fetchone()[0] or 0) - (conn.execute('SELECT SUM(amount) FROM expenses').fetchone()[0] or 0):,.0f}")

    st.subheader("Recent Incomes (last 5)")
    st.dataframe(pd.read_sql("SELECT date, amount, source FROM incomes ORDER BY date DESC LIMIT 5", conn), use_container_width=True)

# ─── Students ──────────────────────────────────────────────────────────
elif page == "Students":
    st.header("Students")

    tab_view, tab_add = st.tabs(["View & Export", "Add Student"])

    with tab_view:
        classes = ["All"] + pd.read_sql("SELECT name FROM classes ORDER BY name", conn)['name'].tolist()
        selected = st.selectbox("Class", classes)

        query = "SELECT s.id, s.name, s.age, s.enrollment_date, c.name AS class_name FROM students s LEFT JOIN classes c ON s.class_id = c.id"
        params = ()
        if selected != "All":
            query += " WHERE c.name = ?"
            params = (selected,)
        df = pd.read_sql_query(query, conn, params=params)
        st.dataframe(df, use_container_width=True)

        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Students', index=False)
        buf.seek(0)
        st.download_button("Download", buf, "students.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_add:
        with st.form("add_student", clear_on_submit=True):
            name = st.text_input("Full Name")
            age = st.number_input("Age", 5, 30, 10)
            enroll_date = st.date_input("Enrollment Date", datetime.today())
            cls_df = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
            cls_name = st.selectbox("Class", cls_df["name"] if not cls_df.empty else ["No classes"])
            cls_id = cls_df[cls_df["name"] == cls_name]["id"].iloc[0] if not cls_df.empty and cls_name != "No classes" else None

            if st.form_submit_button("Add") and name and cls_id is not None:
                cursor.execute("INSERT INTO students (name, age, enrollment_date, class_id) VALUES (?, ?, ?, ?)",
                               (name, age, enroll_date, int(cls_id)))
                conn.commit()
                st.success("Added")

    with st.expander("Add Class"):
        with st.form("add_class", clear_on_submit=True):
            new_cls = st.text_input("Name")
            if st.form_submit_button("Create") and new_cls:
                try:
                    cursor.execute("INSERT INTO classes (name) VALUES (?)", (new_cls,))
                    conn.commit()
                    st.success("Created")
                except sqlite3.IntegrityError:
                    st.error("Exists")

# ─── Uniforms ──────────────────────────────────────────────────────────
elif page == "Uniforms":
    st.header("Uniforms")

    tab_view, tab_update, tab_sale = st.tabs(["Inventory", "Update", "Sell"])

    with tab_view:
        df = pd.read_sql_query("""
            SELECT uc.category, uc.gender, uc.is_shared, u.stock, u.unit_price
            FROM uniforms u JOIN uniform_categories uc ON u.category_id = uc.id
        """, conn)
        st.dataframe(df, use_container_width=True)

        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Inventory', index=False)
        buf.seek(0)
        st.download_button("Download", buf, "uniforms.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_update:
        df_cats = pd.read_sql("SELECT category FROM uniform_categories ORDER BY category", conn)
        selected = st.selectbox("Category", df_cats["category"])
        cat_id = conn.execute("SELECT id FROM uniform_categories WHERE category = ?", (selected,)).fetchone()[0]

        row = conn.execute("SELECT stock, unit_price FROM uniforms WHERE category_id = ?", (cat_id,)).fetchone()
        stock, price = row if row else (0, 0.0)

        st.write(f"Stock: {stock}")
        st.write(f"Price: USh {price:,.0f}")

        with st.form("update", clear_on_submit=True):
            new_stock = st.number_input("Stock", value=stock)
            new_price = st.number_input("Price", value=price)
            if st.form_submit_button("Update"):
                cursor.execute("UPDATE uniforms SET stock = ?, unit_price = ? WHERE category_id = ?", (new_stock, new_price, cat_id))
                conn.commit()
                st.success("Updated")

    with tab_sale:
        df_cats = pd.read_sql("SELECT category FROM uniform_categories ORDER BY category", conn)
        selected = st.selectbox("Sell Category", df_cats["category"])
        cat_id = conn.execute("SELECT id FROM uniform_categories WHERE category = ?", (selected,)).fetchone()[0]

        row = conn.execute("SELECT stock, unit_price FROM uniforms WHERE category_id = ?", (cat_id,)).fetchone()
        stock, price = row if row else (0, 0.0)

        st.write(f"Available: {stock}")
        st.write(f"Price: USh {price:,.0f}")

        with st.form("sell", clear_on_submit=True):
            qty = st.number_input("Quantity", 1, stock or 1, 1)
            date = st.date_input("Date", datetime.today())
            if st.form_submit_button("Sell"):
                if qty > stock:
                    st.error("Not enough")
                else:
                    total = qty * price
                    cursor.execute("UPDATE uniforms SET stock = stock - ? WHERE category_id = ?", (qty, cat_id))
                    cursor.execute("INSERT INTO incomes (date, amount, source) VALUES (?, ?, ?)", (date, total, f"Uniform - {selected}"))
                    conn.commit()
                    st.success(f"Sold for USh {total:,.0f}")

# ─── Finances ──────────────────────────────────────────────────────────
elif page == "Finances":
    st.header("Finances")
    tab_exp, tab_inc, tab_cat = st.tabs(["Expenses", "Incomes", "Categories"])

    with tab_exp:
        df_cats = pd.read_sql("SELECT name FROM expense_categories ORDER BY name", conn)
        selected = st.selectbox("Category", df_cats["name"])
        cat_id = conn.execute("SELECT id FROM expense_categories WHERE name = ?", (selected,)).fetchone()[0]

        with st.form("exp", clear_on_submit=True):
            d = st.date_input("Date")
            a = st.number_input("Amount", 0.0, step=1000.0)
            if st.form_submit_button("Save") and cat_id:
                cursor.execute("INSERT INTO expenses (date, amount, category_id) VALUES (?, ?, ?)", (d, a, cat_id))
                conn.commit()
                st.success("Saved")

    with tab_inc:
        df = pd.read_sql("SELECT date, amount, source FROM incomes ORDER BY date DESC LIMIT 10", conn)
        st.dataframe(df)

    with tab_cat:
        df = pd.read_sql("SELECT name FROM expense_categories", conn)
        st.dataframe(df)

        with st.form("cat", clear_on_submit=True):
            name = st.text_input("New Category")
            if st.form_submit_button("Add") and name:
                try:
                    cursor.execute("INSERT INTO expense_categories (name) VALUES (?)", (name,))
                    conn.commit()
                    st.success("Added")
                except:
                    st.error("Exists")

# ─── Report ────────────────────────────────────────────────────────────
elif page == "Financial Report":
    st.header("Report")

    col1, col2 = st.columns(2)
    start = col1.date_input("Start", datetime(datetime.today().year, 1, 1))
    end = col2.date_input("End", datetime.today())

    if st.button("Generate"):
        exp = pd.read_sql_query("SELECT e.date, e.amount, ec.name FROM expenses e JOIN expense_categories ec ON e.category_id = ec.id WHERE e.date BETWEEN ? AND ?", conn, params=(start, end))
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

        pdf_buf = BytesIO()
        pdf = canvas.Canvas(pdf_buf, pagesize=letter)
        pdf.drawString(100, 750, "COSNA Report")
        pdf.drawString(100, 730, f"{start} – {end}")
        y = 680
        pdf.drawString(100, y, f"Income: {tinc:,.0f}"); y -= 40
        pdf.drawString(100, y, f"Expenses: {texp:,.0f}"); y -= 40
        pdf.drawString(100, y, f"Balance: {bal:,.0f}")
        pdf.save()
        pdf_buf.seek(0)
        st.download_button("PDF", pdf_buf, "report.pdf", "application/pdf")

st.sidebar.info("Logged in as admin")
