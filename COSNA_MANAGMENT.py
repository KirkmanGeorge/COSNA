import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import time

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
conn = sqlite3.connect('cosna_school.db', check_same_thread=False)
cursor = conn.cursor()

# ─── Initialize database ───────────────────────────────────────────────
def initialize_database():
    cursor.execute('''CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, age INTEGER, enrollment_date DATE, class_id INTEGER, FOREIGN KEY(class_id) REFERENCES classes(id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS uniform_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT UNIQUE, gender TEXT, is_shared INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS uniforms (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER UNIQUE, stock INTEGER DEFAULT 0, unit_price REAL DEFAULT 0.0, FOREIGN KEY(category_id) REFERENCES uniform_categories(id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS expense_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE, amount REAL, category_id INTEGER, FOREIGN KEY(category_id) REFERENCES expense_categories(id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS incomes (id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE, amount REAL, source TEXT)''')
    conn.commit()

    # Seed uniforms
    uniform_seeds = [
        ('Boys Main Shorts', 'boys', 0),
        ('Button Shirts Main', 'shared', 1),
        ('Boys Stockings', 'boys', 0),
        ('Boys Sports Shorts', 'boys', 0),
        ('Shared Sports T-Shirts', 'shared', 1),
        ('Girls Main Dresses', 'girls', 0)
    ]
    for name, gender, shared in uniform_seeds:
        cursor.execute("SELECT id FROM uniform_categories WHERE category = ?", (name,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO uniform_categories (category, gender, is_shared) VALUES (?, ?, ?)", (name, gender, shared))
            conn.commit()
            cat_id = cursor.lastrowid
            cursor.execute("INSERT INTO uniforms (category_id, stock, unit_price) VALUES (?, 0, 0.0)", (cat_id,))
            conn.commit()

    # Seed expenses
    expense_seeds = ['Medical', 'Salaries', 'Utilities', 'Maintenance', 'Supplies', 'Transport', 'Events']
    for cat in expense_seeds:
        cursor.execute("SELECT id FROM expense_categories WHERE name = ?", (cat,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO expense_categories (name) VALUES (?)", (cat,))
            conn.commit()

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
    df_inc = pd.read_sql("SELECT date, amount, source FROM incomes ORDER BY date DESC LIMIT 5", conn)
    st.dataframe(df_inc, use_container_width=True)

# ─── Students ──────────────────────────────────────────────────────────
elif page == "Students":
    st.header("Students")

    tab_view, tab_add = st.tabs(["View & Export", "Add Student"])

    with tab_view:
        classes = ["All Classes"] + pd.read_sql("SELECT name FROM classes ORDER BY name", conn)['name'].tolist()
        selected_class = st.selectbox("Filter by Class", classes)

        query = "SELECT s.id, s.name, s.age, s.enrollment_date, c.name AS class_name FROM students s LEFT JOIN classes c ON s.class_id = c.id"
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
            st.download_button("Download Filtered Students Excel", buf, "cosna_students.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_add:
        with st.form("add_student"):
            name = st.text_input("Full Name")
            age = st.number_input("Age", 5, 30, 10)
            enroll_date = st.date_input("Enrollment Date", datetime.today())
            cls_df = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
            cls_name = st.selectbox("Class", cls_df["name"] if not cls_df.empty else ["No classes yet"])
            cls_id = cls_df[cls_df["name"] == cls_name]["id"].iloc[0] if not cls_df.empty and cls_name != "No classes yet" else None

            if st.form_submit_button("Add Student") and name and cls_id is not None:
                cursor.execute("INSERT INTO students (name, age, enrollment_date, class_id) VALUES (?, ?, ?, ?)",
                               (name, age, enroll_date, int(cls_id)))
                conn.commit()
                st.success("Student added")
                st.rerun()

    with st.expander("Add New Class"):
        with st.form("add_class"):
            new_cls = st.text_input("Class Name")
            if st.form_submit_button("Create Class") and new_cls:
                try:
                    cursor.execute("INSERT INTO classes (name) VALUES (?)", (new_cls,))
                    conn.commit()
                    st.success(f"Class '{new_cls}' created")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Class already exists")

# ─── Uniforms ──────────────────────────────────────────────────────────
elif page == "Uniforms":
    st.header("Uniforms – Inventory & Sales")
    
    # Add a session state key to force refresh
    if 'uniform_refresh' not in st.session_state:
        st.session_state.uniform_refresh = 0

    tab_view, tab_update, tab_sale = st.tabs(["View Inventory", "Update Stock/Price", "Record Sale"])

    with tab_view:
        st.subheader("Current Inventory")
        # Use st.session_state.uniform_refresh to force re-query
        df = pd.read_sql_query("""
            SELECT uc.category, uc.gender, uc.is_shared, u.stock, u.unit_price
            FROM uniforms u JOIN uniform_categories uc ON u.category_id = uc.id
            ORDER BY uc.gender, uc.category
        """, conn)
        st.dataframe(df, use_container_width=True)

        # Refresh button with enhanced functionality
        if st.button("Refresh Inventory"):
            st.session_state.uniform_refresh += 1
            st.rerun()

        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Uniform Inventory', index=False)
        buf.seek(0)
        st.download_button("Download Inventory Excel", buf, "cosna_uniforms.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_update:
        df_cats = pd.read_sql("SELECT id, category FROM uniform_categories ORDER BY category", conn)
        selected_cat = st.selectbox("Select Category", df_cats["category"])
        cat_id = df_cats[df_cats["category"] == selected_cat]["id"].iloc[0] if selected_cat else None

        if cat_id:
            # Fetch fresh data directly from database
            current = conn.execute("SELECT stock, unit_price FROM uniforms WHERE category_id = ?", (cat_id,)).fetchone()
            curr_stock, curr_price = current if current else (0, 0.0)

            st.write(f"**Current stock:** {curr_stock}")
            st.write(f"**Current unit price:** USh {curr_price:,.0f}")

            with st.form("update_uniform"):
                new_stock = st.number_input("New Stock Level", min_value=0, value=curr_stock)
                new_price = st.number_input("New Unit Price (USh)", min_value=0.0, value=curr_price, step=500.0)

                if st.form_submit_button("Update Stock & Price"):
                    cursor.execute("UPDATE uniforms SET stock = ?, unit_price = ? WHERE category_id = ?",
                                   (new_stock, new_price, cat_id))
                    conn.commit()
                    # Commit changes properly
                    conn.commit()
                    st.success(f"**Updated!** Now {new_stock} items at USh {new_price:,.0f}")
                    # Clear cache and force refresh
                    if 'uniform_refresh' in st.session_state:
                        st.session_state.uniform_refresh += 1
                    time.sleep(0.5)  # Brief pause for DB sync
                    st.rerun()

    with tab_sale:
        df_cats = pd.read_sql("SELECT id, category FROM uniform_categories ORDER BY category", conn)
        selected_cat = st.selectbox("Select Category to Sell", df_cats["category"])
        cat_id = df_cats[df_cats["category"] == selected_cat]["id"].iloc[0] if selected_cat else None

        if cat_id:
            # Fetch fresh data directly
            current = conn.execute("SELECT stock, unit_price FROM uniforms WHERE category_id = ?", (cat_id,)).fetchone()
            curr_stock, unit_price = current if current else (0, 0.0)

            st.write(f"**Available stock:** {curr_stock}")
            st.write(f"**Unit price:** USh {unit_price:,.0f}")

            with st.form("sell_uniform"):
                quantity = st.number_input("Quantity to Sell", min_value=1, max_value=curr_stock or 1, value=1)
                sale_date = st.date_input("Sale Date", datetime.today())

                if st.form_submit_button("Record Sale"):
                    if quantity > curr_stock:
                        st.error(f"Not enough stock (only {curr_stock} available)")
                    else:
                        total_amount = quantity * unit_price
                        cursor.execute("UPDATE uniforms SET stock = stock - ? WHERE category_id = ?", (quantity, cat_id))
                        cursor.execute("INSERT INTO incomes (date, amount, source) VALUES (?, ?, ?)",
                                       (sale_date, total_amount, f"Uniform Sale - {selected_cat}"))
                        conn.commit()
                        # Force refresh
                        if 'uniform_refresh' in st.session_state:
                            st.session_state.uniform_refresh += 1
                        st.success(f"Sold {quantity} items for USh {total_amount:,.0f}. Income recorded.")
                        time.sleep(0.5)
                        st.rerun()

# ─── Finances ──────────────────────────────────────────────────────────
elif page == "Finances":
    st.header("Finances")

    tab_exp, tab_inc, tab_cat = st.tabs(["Expenses", "Incomes", "Expense Categories"])

    with tab_exp:
        df_cats = pd.read_sql("SELECT id, name FROM expense_categories ORDER BY name", conn)
        selected_cat = st.selectbox("Select Category", df_cats["name"])
        cat_id = df_cats[df_cats["name"] == selected_cat]["id"].iloc[0] if not df_cats.empty else None

        with st.form("add_expense"):
            date = st.date_input("Date", datetime.today())
            amount = st.number_input("Amount (USh)", min_value=0.0, step=1000.0)
            if st.form_submit_button("Save Expense") and cat_id:
                cursor.execute("INSERT INTO expenses (date, amount, category_id) VALUES (?, ?, ?)", (date, amount, int(cat_id)))
                conn.commit()
                st.success("Expense recorded")
                st.rerun()

        st.subheader("Recent Expenses")
        df_exp = pd.read_sql_query("""
            SELECT e.date, e.amount, ec.name AS category
            FROM expenses e LEFT JOIN expense_categories ec ON e.category_id = ec.id
            ORDER BY e.date DESC LIMIT 10
        """, conn)
        st.dataframe(df_exp, use_container_width=True)

    with tab_inc:
        st.subheader("Add Income (Fees, Donations, etc.)")
        with st.form("add_income"):
            date = st.date_input("Date", datetime.today())
            amount = st.number_input("Amount (USh)", min_value=0.0, step=1000.0)
            source = st.text_input("Source (e.g. Fees, Donations)")
            if st.form_submit_button("Save Income") and source:
                cursor.execute("INSERT INTO incomes (date, amount, source) VALUES (?, ?, ?)", (date, amount, source))
                conn.commit()
                st.success("Income recorded")
                st.rerun()

        st.subheader("Recent Incomes")
        df_inc = pd.read_sql("SELECT date, amount, source FROM incomes ORDER BY date DESC LIMIT 10", conn)
        st.dataframe(df_inc, use_container_width=True)

    with tab_cat:
        st.subheader("Expense Categories")
        df_cats = pd.read_sql("SELECT name FROM expense_categories ORDER BY name", conn)
        st.dataframe(df_cats, use_container_width=True)

        with st.form("add_category"):
            new_cat = st.text_input("New Category Name")
            if st.form_submit_button("Add Category") and new_cat:
                try:
                    cursor.execute("INSERT INTO expense_categories (name) VALUES (?)", (new_cat,))
                    conn.commit()
                    st.success(f"Category '{new_cat}' added")
                    st.rerun()
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

        pdf_buf = BytesIO()
        pdf = canvas.Canvas(pdf_buf, pagesize=letter)
        pdf.drawString(100, 750, "COSNA School Financial Report")
        pdf.drawString(100, 730, f"Period: {start} to {end}")
        y = 680
        pdf.drawString(100, y, f"Total Income: USh {total_inc:,.0f}"); y -= 40
        pdf.drawString(100, y, f"Total Expenses: USh {total_exp:,.0f}"); y -= 40
        pdf.drawString(100, y, f"Balance: USh {balance:,.0f}")
        pdf.save()
        pdf_buf.seek(0)
        st.download_button("Download PDF", pdf_buf, f"report_{start}_to_{end}.pdf", "application/pdf")

st.sidebar.info("Logged in as admin – data saved in SQLite (persistent on Streamlit Cloud)")
