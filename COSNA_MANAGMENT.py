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
    st.stop()  # Stop here if not logged in

# Logout button in sidebar
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

# Create tables if they don't exist
cursor.execute('''CREATE TABLE IF NOT EXISTS classes
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS students
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   name TEXT, age INTEGER, enrollment_date DATE,
                   class_id INTEGER, FOREIGN KEY(class_id) REFERENCES classes(id))''')

cursor.execute('''CREATE TABLE IF NOT EXISTS uniform_categories
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   category TEXT UNIQUE, gender TEXT, is_shared INTEGER DEFAULT 0)''')  # gender: 'boys', 'girls', 'shared'

cursor.execute('''CREATE TABLE IF NOT EXISTS uniforms
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   category_id INTEGER, stock INTEGER DEFAULT 0, unit_price REAL DEFAULT 0.0,
                   FOREIGN KEY(category_id) REFERENCES uniform_categories(id))''')

cursor.execute('''CREATE TABLE IF NOT EXISTS expense_categories
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS expenses
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   date DATE, amount REAL, category_id INTEGER,
                   FOREIGN KEY(category_id) REFERENCES expense_categories(id))''')

cursor.execute('''CREATE TABLE IF NOT EXISTS incomes
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   date DATE, amount REAL, source TEXT)''')  # source e.g. 'Uniform Sale', 'Fees', 'Donations'

conn.commit()

# Pre-populate uniform categories if not exist (your specified logic)
uniform_data = [
    ('shorts_main', 'boys', 0),
    ('button_shirts_main', 'shared', 1),
    ('stockings', 'boys', 0),
    ('shorts_sports', 'boys', 0),
    ('t_shirts_sports', 'shared', 1),
    ('dresses_main', 'girls', 0)
]

for cat, gender, is_shared in uniform_data:
    cursor.execute("SELECT id FROM uniform_categories WHERE category = ?", (cat,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO uniform_categories (category, gender, is_shared) VALUES (?, ?, ?)", (cat, gender, is_shared))
        conn.commit()
        # Initialize stock and price for each category
        cursor.execute("INSERT INTO uniforms (category_id, stock, unit_price) VALUES ((SELECT MAX(id) FROM uniform_categories), 0, 0.0)")
        conn.commit()

# Pre-populate some expense categories if not exist (example logic: common school expenses)
expense_cats = ['Medical', 'Salaries', 'Utilities', 'Maintenance', 'Supplies', 'Transportation', 'Events']
for cat in expense_cats:
    cursor.execute("SELECT id FROM expense_categories WHERE name = ?", (cat,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO expense_categories (name) VALUES (?)", (cat,))
        conn.commit()

# ─── Navigation ────────────────────────────────────────────────────────
page = st.sidebar.radio("Menu", ["Dashboard", "Students", "Uniforms", "Finances", "Financial Report"])

# ─── Dashboard ─────────────────────────────────────────────────────────
if page == "Dashboard":
    st.header("Overview")

    col1, col3 = st.columns(2)  # Removed uniform from dashboard
    col1.metric("Total Students", conn.execute("SELECT COUNT(*) FROM students").fetchone()[0])

    inc_sum = conn.execute("SELECT SUM(amount) FROM incomes").fetchone()[0] or 0
    exp_sum = conn.execute("SELECT SUM(amount) FROM expenses").fetchone()[0] or 0
    col3.metric("Net Balance (All Time)", f"USh {inc_sum - exp_sum:,.0f}")

    # Other income sources suggestion: View recent incomes
    st.subheader("Recent Incomes")
    df_inc = pd.read_sql("SELECT date, amount, source FROM incomes ORDER BY date DESC LIMIT 5", conn)
    st.dataframe(df_inc, use_container_width=True)

# ─── Students ──────────────────────────────────────────────────────────
elif page == "Students":
    st.header("Students")

    tab1, tab2 = st.tabs(["View & Export", "Add Student"])

    with tab1:
        # Filter by class
        classes = pd.read_sql("SELECT name FROM classes", conn)['name'].tolist()
        selected_class = st.selectbox("Select Class to View", ["All Classes"] + classes)
        if selected_class == "All Classes":
            df = pd.read_sql_query("""
                SELECT s.id, s.name, s.age, s.enrollment_date, c.name AS class_name
                FROM students s LEFT JOIN classes c ON s.class_id = c.id
            """, conn)
        else:
            df = pd.read_sql_query("""
                SELECT s.id, s.name, s.age, s.enrollment_date, c.name AS class_name
                FROM students s LEFT JOIN classes c ON s.class_id = c.id
                WHERE c.name = ?
            """, conn, params=(selected_class,))
        st.dataframe(df, use_container_width=True)

        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Students', index=False)
        buf.seek(0)
        st.download_button(
            label="Download Students Excel",
            data=buf,
            file_name="cosna_students.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    with tab2:
        with st.form("add_student", clear_on_submit=True):  # Clear form after submit
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
    st.header("Uniforms (Inventory & Sales)")

    tab1, tab2, tab3 = st.tabs(["View & Export Inventory", "Update Stock & Price", "Record Sale"])

    with tab1:
        df = pd.read_sql_query("""
            SELECT u.id, uc.category, uc.gender, uc.is_shared, u.stock, u.unit_price
            FROM uniforms u LEFT JOIN uniform_categories uc ON u.category_id = uc.id
        """, conn)
        st.dataframe(df, use_container_width=True)

        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Uniforms', index=False)
        buf.seek(0)
        st.download_button(
            label="Download Uniforms Inventory Excel",
            data=buf,
            file_name="cosna_uniforms.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    with tab2:
        st.subheader("Update Stock & Price")
        df_cats = pd.read_sql("SELECT id, category FROM uniform_categories", conn)
        selected_cat_id = st.selectbox("Select Category", df_cats["category"], format_func=lambda x: x)
        cat_id = df_cats[df_cats["category"] == selected_cat_id]["id"].iloc[0] if selected_cat_id else None

        current_stock = conn.execute("SELECT stock FROM uniforms WHERE category_id = ?", (cat_id,)).fetchone()[0] or 0
        current_price = conn.execute("SELECT unit_price FROM uniforms WHERE category_id = ?", (cat_id,)).fetchone()[0] or 0.0

        st.write(f"Current stock: {current_stock}")
        st.write(f"Current unit price: USh {current_price:,.0f}")

        with st.form("update_uniform", clear_on_submit=True):
            new_stock = st.number_input("New Stock (overrides current)", min_value=0, value=current_stock)
            new_price = st.number_input("New Unit Price (USh)", min_value=0.0, value=current_price)

            if st.form_submit_button("Update"):
                cursor.execute("UPDATE uniforms SET stock = ?, unit_price = ? WHERE category_id = ?", (new_stock, new_price, cat_id))
                conn.commit()
                st.success("Updated successfully")

    with tab3:
        st.subheader("Record Uniform Sale")
        df_cats = pd.read_sql("SELECT id, category FROM uniform_categories", conn)
        selected_cat_id = st.selectbox("Select Category to Sell", df_cats["category"], format_func=lambda x: x)
        cat_id = df_cats[df_cats["category"] == selected_cat_id]["id"].iloc[0] if selected_cat_id else None

        if cat_id:
            current_stock = conn.execute("SELECT stock FROM uniforms WHERE category_id = ?", (cat_id,)).fetchone()[0] or 0
            unit_price = conn.execute("SELECT unit_price FROM uniforms WHERE category_id = ?", (cat_id,)).fetchone()[0] or 0.0
            st.write(f"Current stock: {current_stock}")
            st.write(f"Unit price: USh {unit_price:,.0f}")

            with st.form("sell_uniform", clear_on_submit=True):
                quantity = st.number_input("Quantity to Sell", min_value=1, max_value=current_stock, value=1)
                sale_date = st.date_input("Sale Date", datetime.today())

                if st.form_submit_button("Record Sale"):
                    if quantity > current_stock:
                        st.error("Not enough stock")
                    else:
                        total_amount = quantity * unit_price
                        # Update stock
                        cursor.execute("UPDATE uniforms SET stock = stock - ? WHERE category_id = ?", (quantity, cat_id))
                        # Add to incomes
                        cursor.execute("INSERT INTO incomes (date, amount, source) VALUES (?, ?, ?)", (sale_date, total_amount, 'Uniform Sale'))
                        conn.commit()
                        st.success(f"Sold {quantity} items for USh {total_amount:,.0f}. Income recorded.")

# ─── Finances ──────────────────────────────────────────────────────────
elif page == "Finances":
    st.header("Finances")

    tab_exp, tab_inc, tab_cat = st.tabs(["Expenses", "Incomes", "Expense Categories"])

    with tab_exp:
        st.subheader("Add Expense")
        df_cats = pd.read_sql("SELECT id, name FROM expense_categories", conn)
        selected_cat = st.selectbox("Select Category", df_cats["name"], format_func=lambda x: x)
        cat_id = df_cats[df_cats["name"] == selected_cat]["id"].iloc[0] if selected_cat else None

        with st.form("add_expense", clear_on_submit=True):
            date = st.date_input("Date", datetime.today())
            amount = st.number_input("Amount (USh)", min_value=0.0, step=1000.0)
            if st.form_submit_button("Save Expense") and cat_id:
                cursor.execute("INSERT INTO expenses (date, amount, category_id) VALUES (?, ?, ?)", (date, amount, int(cat_id)))
                conn.commit()
                st.success("Expense saved")

        st.subheader("Recent Expenses")
        df_exp = pd.read_sql_query("""
            SELECT e.date, e.amount, ec.name AS category
            FROM expenses e LEFT JOIN expense_categories ec ON e.category_id = ec.id
            ORDER BY e.date DESC LIMIT 10
        """, conn)
        st.dataframe(df_exp, use_container_width=True)

    with tab_inc:
        st.subheader("Recent Incomes")
        df_inc = pd.read_sql("SELECT date, amount, source FROM incomes ORDER BY date DESC LIMIT 10", conn)
        st.dataframe(df_inc, use_container_width=True)

        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
            df_inc.to_excel(writer, sheet_name='Incomes', index=False)
        buf.seek(0)
        st.download_button("Download Recent Incomes Excel", buf, "incomes.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_cat:
        st.subheader("Expense Categories")
        df_cats = pd.read_sql("SELECT name FROM expense_categories", conn)
        st.dataframe(df_cats, use_container_width=True)

        with st.form("add_category", clear_on_submit=True):
            new_cat = st.text_input("New Category Name (e.g. Library)")
            if st.form_submit_button("Add Category") and new_cat:
                try:
                    cursor.execute("INSERT INTO expense_categories (name) VALUES (?)", (new_cat,))
                    conn.commit()
                    st.success(f"Category {new_cat} added")
                except sqlite3.IntegrityError:
                    st.error("Category already exists")

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
        pdf.drawString(100, 750, "COSNA School Financial Report")
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
