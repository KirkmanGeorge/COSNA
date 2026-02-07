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
    st.stop()

# Logout in sidebar
with st.sidebar:
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.rerun()

# ─── SQLite connection ─────────────────────────────────────────────────
@st.cache_resource
def get_db_connection():
    conn = sqlite3.connect('cosna_school.db', check_same_thread=False)
    return conn

conn = get_db_connection()
cursor = conn.cursor()

# ─── Create tables ─────────────────────────────────────────────────────
cursor.execute('''CREATE TABLE IF NOT EXISTS classes
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS students
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   name TEXT, age INTEGER, enrollment_date DATE,
                   class_id INTEGER, FOREIGN KEY(class_id) REFERENCES classes(id))''')

cursor.execute('''CREATE TABLE IF NOT EXISTS uniform_categories
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   category TEXT UNIQUE, gender TEXT, is_shared INTEGER DEFAULT 0)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS uniforms
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   category_id INTEGER UNIQUE, stock INTEGER DEFAULT 0, unit_price REAL DEFAULT 0.0,
                   FOREIGN KEY(category_id) REFERENCES uniform_categories(id))''')

cursor.execute('''CREATE TABLE IF NOT EXISTS expense_categories
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS expenses
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   date DATE, amount REAL, category_id INTEGER,
                   FOREIGN KEY(category_id) REFERENCES expense_categories(id))''')

cursor.execute('''CREATE TABLE IF NOT EXISTS incomes
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   date DATE, amount REAL, source TEXT)''')

conn.commit()

# ─── Pre-populate uniform categories (only if missing) ─────────────────
uniform_seeds = [
    ('Boys Main Shorts', 'boys', 0),
    ('Button Shirts Main', 'shared', 1),
    ('Boys Stockings', 'boys', 0),
    ('Boys Sports Shorts', 'boys', 0),
    ('Shared Sports T-Shirts', 'shared', 1),
    ('Girls Main Dresses', 'girls', 0)
]

for cat_name, gender, shared in uniform_seeds:
    cursor.execute("SELECT id FROM uniform_categories WHERE category = ?", (cat_name,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO uniform_categories (category, gender, is_shared) VALUES (?, ?, ?)",
            (cat_name, gender, shared)
        )
        conn.commit()
        cat_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO uniforms (category_id, stock, unit_price) VALUES (?, 0, 0.0)",
            (cat_id,)
        )
        conn.commit()

# ─── Pre-populate common expense categories ────────────────────────────
expense_seeds = ['Medical', 'Salaries', 'Utilities', 'Maintenance', 'Supplies', 'Transport', 'Events']
for cat in expense_seeds:
    cursor.execute("SELECT id FROM expense_categories WHERE name = ?", (cat,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO expense_categories (name) VALUES (?)", (cat,))
        conn.commit()

# ─── Navigation ────────────────────────────────────────────────────────
page = st.sidebar.radio("Menu", ["Dashboard", "Students", "Uniforms", "Finances", "Financial Report"])

# ─── Dashboard ─────────────────────────────────────────────────────────
if page == "Dashboard":
    st.header("Overview")

    col1, col2 = st.columns(2)
    col1.metric("Total Students", conn.execute("SELECT COUNT(*) FROM students").fetchone()[0])
    col2.metric("Net Balance (All Time)", f"USh {(conn.execute('SELECT SUM(amount) FROM incomes').fetchone()[0] or 0) - (conn.execute('SELECT SUM(amount) FROM expenses').fetchone()[0] or 0):,.0f}")

    st.subheader("Recent Incomes (last 5)")
    df_recent_inc = pd.read_sql("SELECT date, amount, source FROM incomes ORDER BY date DESC LIMIT 5", conn)
    st.dataframe(df_recent_inc, use_container_width=True)

# ─── Students ──────────────────────────────────────────────────────────
elif page == "Students":
    st.header("Students Management")

    tab_view, tab_add = st.tabs(["View Students", "Add New Student"])

    with tab_view:
        classes = pd.read_sql("SELECT name FROM classes ORDER BY name", conn)['name'].tolist()
        selected_class = st.selectbox("Filter by Class", ["All Classes"] + classes)

        query = """
            SELECT s.id, s.name, s.age, s.enrollment_date, c.name AS class_name
            FROM students s LEFT JOIN classes c ON s.class_id = c.id
        """
        params = ()
        if selected_class != "All Classes":
            query += " WHERE c.name = ?"
            params = (selected_class,)

        df = pd.read_sql_query(query, conn, params=params)
        st.dataframe(df, use_container_width=True)

        if not df.empty:
            buf = BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                df.to_excel(writer, sheet_name='Students', index=False)
            buf.seek(0)
            st.download_button("Download Filtered Students Excel", buf, "cosna_students.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_add:
        with st.form("add_student", clear_on_submit=True):
            name = st.text_input("Full Name")
            age = st.number_input("Age", min_value=5, max_value=30, value=10)
            enroll_date = st.date_input("Enrollment Date", datetime.today())
            cls_df = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
            cls_name = st.selectbox("Class", cls_df["name"] if not cls_df.empty else ["No classes yet"])
            cls_id = cls_df[cls_df["name"] == cls_name]["id"].iloc[0] if not cls_df.empty and cls_name != "No classes yet" else None

            if st.form_submit_button("Add Student") and name and cls_id is not None:
                cursor.execute(
                    "INSERT INTO students (name, age, enrollment_date, class_id) VALUES (?, ?, ?, ?)",
                    (name, age, enroll_date, int(cls_id))
                )
                conn.commit()
                st.success(f"Student '{name}' added to {cls_name}")

    with st.expander("Add New Class"):
        with st.form("add_class", clear_on_submit=True):
            new_cls = st.text_input("Class Name (e.g. P.1, S.1)")
            if st.form_submit_button("Create Class") and new_cls:
                try:
                    cursor.execute("INSERT INTO classes (name) VALUES (?)", (new_cls,))
                    conn.commit()
                    st.success(f"Class '{new_cls}' created")
                except sqlite3.IntegrityError:
                    st.error("Class already exists")

# ─── Uniforms ──────────────────────────────────────────────────────────
elif page == "Uniforms":
    st.header("Uniform Inventory & Sales")

    tab_view, tab_update, tab_sale = st.tabs(["View Inventory", "Update Stock/Price", "Record Sale"])

    with tab_view:
        df = pd.read_sql_query("""
            SELECT uc.category, uc.gender, uc.is_shared, u.stock, u.unit_price
            FROM uniforms u
            JOIN uniform_categories uc ON u.category_id = uc.id
            ORDER BY uc.gender, uc.category
        """, conn)
        st.dataframe(df, use_container_width=True)

        if not df.empty:
            buf = BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                df.to_excel(writer, sheet_name='Uniform Inventory', index=False)
            buf.seek(0)
            st.download_button("Download Inventory Excel", buf, "cosna_uniform_inventory.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_update:
        st.subheader("Update Stock & Unit Price")
        df_cats = pd.read_sql("SELECT id, category FROM uniform_categories ORDER BY category", conn)
        selected_cat = st.selectbox("Select Uniform Category", df_cats["category"])
        cat_id = df_cats[df_cats["category"] == selected_cat]["id"].iloc[0]

        current = conn.execute("SELECT stock, unit_price FROM uniforms WHERE category_id = ?", (cat_id,)).fetchone()
        curr_stock, curr_price = current if current else (0, 0.0)

        st.write(f"**Current stock:** {curr_stock}")
        st.write(f"**Current price:** USh {curr_price:,.0f}")

        with st.form("update_uniform", clear_on_submit=True):
            new_stock = st.number_input("New Stock Level", min_value=0, value=curr_stock)
            new_price = st.number_input("New Unit Price (USh)", min_value=0.0, value=curr_price, step=500.0)

            if st.form_submit_button("Update"):
                cursor.execute("UPDATE uniforms SET stock = ?, unit_price = ? WHERE category_id = ?",
                               (new_stock, new_price, cat_id))
                conn.commit()
                st.success("Inventory updated")

    with tab_sale:
        st.subheader("Sell Uniforms (Auto-reduces stock & adds income)")
        df_cats = pd.read_sql("SELECT id, category FROM uniform_categories ORDER BY category", conn)
        selected_cat = st.selectbox("Select Category to Sell", df_cats["category"])
        cat_id = df_cats[df_cats["category"] == selected_cat]["id"].iloc[0]

        current = conn.execute("SELECT stock, unit_price FROM uniforms WHERE category_id = ?", (cat_id,)).fetchone()
        curr_stock, unit_price = current if current else (0, 0.0)

        st.write(f"**Available stock:** {curr_stock}")
        st.write(f"**Unit price:** USh {unit_price:,.0f}")

        with st.form("sell_uniform", clear_on_submit=True):
            quantity = st.number_input("Quantity to Sell", min_value=1, max_value=curr_stock or 1, value=1)
            sale_date = st.date_input("Sale Date", datetime.today())

            if st.form_submit_button("Record Sale"):
                if quantity > curr_stock:
                    st.error("Not enough stock available")
                else:
                    total = quantity * unit_price
                    cursor.execute("UPDATE uniforms SET stock = stock - ? WHERE category_id = ?", (quantity, cat_id))
                    cursor.execute("INSERT INTO incomes (date, amount, source) VALUES (?, ?, ?)",
                                   (sale_date, total, f"Uniform Sale - {selected_cat}"))
                    conn.commit()
                    st.success(f"Sold {quantity} × {selected_cat} for USh {total:,.0f}. Income recorded.")

# ─── Finances ──────────────────────────────────────────────────────────
elif page == "Finances":
    st.header("Finances")

    tab_exp, tab_inc, tab_cats = st.tabs(["Add Expense", "View Incomes", "Expense Categories"])

    with tab_exp:
        df_cats = pd.read_sql("SELECT id, name FROM expense_categories ORDER BY name", conn)
        selected_cat = st.selectbox("Expense Category", df_cats["name"])
        cat_id = df_cats[df_cats["name"] == selected_cat]["id"].iloc[0] if not df_cats.empty else None

        with st.form("add_expense", clear_on_submit=True):
            date = st.date_input("Date", datetime.today())
            amount = st.number_input("Amount (USh)", min_value=0.0, step=1000.0)
            if st.form_submit_button("Save Expense") and cat_id:
                cursor.execute("INSERT INTO expenses (date, amount, category_id) VALUES (?, ?, ?)",
                               (date, amount, int(cat_id)))
                conn.commit()
                st.success("Expense recorded")

    with tab_inc:
        df_inc = pd.read_sql("SELECT date, amount, source FROM incomes ORDER BY date DESC LIMIT 15", conn)
        st.dataframe(df_inc, use_container_width=True)

        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
            df_inc.to_excel(writer, sheet_name='Incomes', index=False)
        buf.seek(0)
        st.download_button("Download Incomes Excel", buf, "cosna_incomes.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_cats:
        st.subheader("Expense Categories")
        df_cats = pd.read_sql("SELECT name FROM expense_categories ORDER BY name", conn)
        st.dataframe(df_cats, use_container_width=True)

        with st.form("add_exp_cat", clear_on_submit=True):
            new_cat = st.text_input("New Category Name")
            if st.form_submit_button("Add Category") and new_cat:
                try:
                    cursor.execute("INSERT INTO expense_categories (name) VALUES (?)", (new_cat,))
                    conn.commit()
                    st.success(f"Category '{new_cat}' added")
                except sqlite3.IntegrityError:
                    st.error("Category already exists")

# ─── Financial Report ──────────────────────────────────────────────────
elif page == "Financial Report":
    st.header("Financial Report")

    col1, col2 = st.columns(2)
    start = col1.date_input("Start Date", datetime(datetime.today().year, 1, 1))
    end = col2.date_input("End Date", datetime.today())

    if st.button("Generate Report"):
        exp = pd.read_sql_query("SELECT e.date, e.amount, ec.name AS category FROM expenses e JOIN expense_categories ec ON e.category_id = ec.id WHERE e.date BETWEEN ? AND ?", conn, params=(start, end))
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

        # PDF
        pdf_buf = BytesIO()
        pdf = canvas.Canvas(pdf_buf, pagesize=letter)
        pdf.drawString(100, 750, "COSNA School Financial Report")
        pdf.drawString(100, 730, f"Period: {start} to {end}")
        y = 680
        pdf.drawString(100, y, f"Income: USh {total_inc:,.0f}"); y -= 40
        pdf.drawString(100, y, f"Expenses: USh {total_exp:,.0f}"); y -= 40
        pdf.drawString(100, y, f"Balance: USh {balance:,.0f}")
        pdf.save()
        pdf_buf.seek(0)
        st.download_button("Download PDF", pdf_buf, f"cosna_report_{start}_to_{end}.pdf", "application/pdf")

        # Excel
        excel_buf = BytesIO()
        with pd.ExcelWriter(excel_buf, engine='xlsxwriter') as writer:
            inc.to_excel(writer, sheet_name="Incomes", index=False)
            exp.to_excel(writer, sheet_name="Expenses", index=False)
            pd.DataFrame({
                "Metric": ["Total Income", "Total Expenses", "Balance"],
                "Value (USh)": [total_inc, total_exp, balance]
            }).to_excel(writer, sheet_name="Summary", index=False)
        excel_buf.seek(0)
        st.download_button("Download Excel Report", excel_buf, f"cosna_financial_{start}_to_{end}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.sidebar.info("Logged in as admin – data saved in SQLite (persistent)")
