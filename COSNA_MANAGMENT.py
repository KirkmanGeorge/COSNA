import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
from datetime import datetime, date
from io import BytesIO
import bcrypt
import os
import random
import string
import difflib
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# =========================
# APP CONFIG
# =========================

APP_TITLE = "COSNA School Management System"
SCHOOL_NAME = "Cosna Daycare, Nursery, Day and Boarding Primary School Kiyinda-Mityana"
SCHOOL_ADDRESS = "P.O.BOX 000, Kiyinda-Mityana"
SCHOOL_EMAIL = "info@cosnaschool.com Or: admin@cosnaschool.com"
REGISTRATION_FEE = 50000.0
SIMILARITY_THRESHOLD = 0.82
LOGO_FILENAME = "school_badge.png"

st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)
st.markdown("Students • Uniforms • Finances • Reports")

# =========================
# DATABASE CONNECTION
# Supabase Pooler Safe
# =========================

def get_db_connection():
    return psycopg2.connect(
        host=st.secrets["DB_HOST"],
        port=st.secrets["DB_PORT"],
        dbname=st.secrets["DB_NAME"],
        user=st.secrets["DB_USER"],
        password=st.secrets["DB_PASSWORD"],
        sslmode="require",
        cursor_factory=RealDictCursor
    )

# =========================
# PASSWORD SECURITY (bcrypt)
# =========================

def hash_password(password: str):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(stored: str, provided: str):
    return bcrypt.checkpw(provided.encode(), stored.encode())

# =========================
# UTILITIES
# =========================

def normalize_text(s: str):
    if not s:
        return ""
    return " ".join(s.strip().lower().split())

def similar(a: str, b: str):
    return difflib.SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()

def generate_code(prefix="RCPT"):
    day = datetime.now().strftime("%d")
    rand = ''.join(random.choices(string.ascii_uppercase + string.digits, k=2))
    return f"{prefix}-{day}{rand}"

def generate_receipt_number():
    return generate_code("RCPT")

def generate_invoice_number():
    return generate_code("INV")

def generate_voucher_number():
    return generate_code("VCH")

# =========================
# DATABASE INITIALIZATION
# =========================

def initialize_database():
    conn = get_db_connection()
    cur = conn.cursor()

    # USERS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE,
            password_hash TEXT,
            role TEXT DEFAULT 'Clerk',
            full_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # CLASSES
    cur.execute("""
        CREATE TABLE IF NOT EXISTS classes (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE
        )
    """)

    # STUDENTS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            name TEXT,
            normalized_name TEXT,
            age INTEGER,
            enrollment_date DATE,
            class_id INTEGER REFERENCES classes(id),
            student_type TEXT,
            registration_fee_paid BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # EXPENSE CATEGORIES
    cur.execute("""
        CREATE TABLE IF NOT EXISTS expense_categories (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE,
            category_type TEXT CHECK(category_type IN ('Expense','Income'))
        )
    """)

    # INCOMES
    cur.execute("""
        CREATE TABLE IF NOT EXISTS incomes (
            id SERIAL PRIMARY KEY,
            date DATE,
            receipt_number TEXT UNIQUE,
            amount NUMERIC,
            source TEXT,
            category_id INTEGER REFERENCES expense_categories(id),
            description TEXT,
            payment_method TEXT,
            payer TEXT,
            received_by TEXT,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # EXPENSES
    cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            date DATE,
            voucher_number TEXT UNIQUE,
            amount NUMERIC,
            category_id INTEGER REFERENCES expense_categories(id),
            description TEXT,
            payment_method TEXT,
            payee TEXT,
            approved_by TEXT,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # AUDIT LOG
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id SERIAL PRIMARY KEY,
            action TEXT,
            details TEXT,
            performed_by TEXT,
            performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()

    # SEED ADMIN IF EMPTY
    cur.execute("SELECT COUNT(*) as count FROM users")
    count = cur.fetchone()["count"]

    if count == 0:
        cur.execute("""
            INSERT INTO users (username, password_hash, role, full_name)
            VALUES (%s, %s, %s, %s)
        """, (
            "admin",
            hash_password("costa2026"),
            "Admin",
            "Administrator"
        ))
        conn.commit()

    # SEED EXPENSE CATEGORIES
    default_categories = [
        ('Medical','Expense'),
        ('Salaries','Expense'),
        ('Utilities','Expense'),
        ('Maintenance','Expense'),
        ('Supplies','Expense'),
        ('Transport','Expense'),
        ('Events','Expense'),
        ('Tuition Fees','Income'),
        ('Registration Fees','Income'),
        ('Uniform Sales','Income'),
        ('Donations','Income')
    ]

    for name, ctype in default_categories:
        cur.execute("""
            INSERT INTO expense_categories (name, category_type)
            VALUES (%s,%s)
            ON CONFLICT (name) DO NOTHING
        """, (name,ctype))

    conn.commit()
    cur.close()
    conn.close()

initialize_database()

# =========================
# AUDIT LOGGING
# =========================

def log_action(action, details="", user="system"):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO audit_log (action, details, performed_by)
        VALUES (%s,%s,%s)
    """,(action,details,user))
    conn.commit()
    cur.close()
    conn.close()

# =========================
# AUTHENTICATION
# =========================

def get_user(username):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=%s",(username,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user

if "user" not in st.session_state:
    st.session_state.user = None

def show_login():
    st.subheader("Login")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")

        if submit:
            user = get_user(username)
            if user and verify_password(user["password_hash"], password):
                st.session_state.user = user
                log_action("login",f"{username} logged in",username)
                st.rerun()
            else:
                st.error("Invalid credentials")

if not st.session_state.user:
    show_login()
    st.stop()
# =========================
# SECTION 2 — STUDENTS & FEES
# =========================

st.sidebar.markdown("### Navigation")
menu = st.sidebar.radio(
    "Go To",
    [
        "Dashboard",
        "Students",
        "Record Payment",
        "Student Ledger",
        "Reports"
    ]
)

current_user = st.session_state.user["username"]

# =========================
# DASHBOARD
# =========================

if menu == "Dashboard":
    st.subheader("Dashboard Overview")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) as count FROM students")
    total_students = cur.fetchone()["count"]

    cur.execute("SELECT COALESCE(SUM(amount),0) as total FROM incomes")
    total_income = cur.fetchone()["total"]

    cur.execute("SELECT COALESCE(SUM(amount),0) as total FROM expenses")
    total_expense = cur.fetchone()["total"]

    balance = float(total_income) - float(total_expense)

    cur.close()
    conn.close()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Students", total_students)
    col2.metric("Total Income", f"{total_income}")
    col3.metric("Total Expenses", f"{total_expense}")
    col4.metric("Balance", f"{balance}")

# =========================
# STUDENT MANAGEMENT
# =========================

if menu == "Students":
    st.subheader("Student Registration")

    conn = get_db_connection()
    cur = conn.cursor()

    # Load classes
    cur.execute("SELECT * FROM classes ORDER BY name")
    classes = cur.fetchall()

    class_dict = {c["name"]: c["id"] for c in classes}

    if not classes:
        st.warning("No classes found. Add one below.")

    with st.form("add_class_form"):
        new_class = st.text_input("Add New Class")
        if st.form_submit_button("Add Class"):
            if new_class:
                cur.execute("""
                    INSERT INTO classes (name)
                    VALUES (%s)
                    ON CONFLICT (name) DO NOTHING
                """,(new_class,))
                conn.commit()
                st.success("Class added.")
                st.rerun()

    st.divider()

    with st.form("student_form"):
        name = st.text_input("Student Full Name")
        age = st.number_input("Age", 3, 25)
        selected_class = st.selectbox("Class", list(class_dict.keys()) if class_dict else [])
        student_type = st.selectbox("Student Type", ["Day","Boarding"])
        enrollment_date = st.date_input("Enrollment Date", date.today())

        submitted = st.form_submit_button("Register Student")

        if submitted and name and selected_class:
            normalized = normalize_text(name)

            # Duplicate detection
            cur.execute("SELECT name FROM students")
            existing = cur.fetchall()

            for student in existing:
                if similar(student["name"], name) > SIMILARITY_THRESHOLD:
                    st.error(f"Possible duplicate found: {student['name']}")
                    conn.close()
                    st.stop()

            cur.execute("""
                INSERT INTO students
                (name, normalized_name, age, enrollment_date, class_id, student_type)
                VALUES (%s,%s,%s,%s,%s,%s)
            """,(
                name,
                normalized,
                age,
                enrollment_date,
                class_dict[selected_class],
                student_type
            ))

            conn.commit()
            log_action("student_registered",name,current_user)
            st.success("Student registered successfully.")
            st.rerun()

    st.divider()

    st.subheader("All Students")

    cur.execute("""
        SELECT s.id, s.name, s.age, c.name as class_name,
               s.student_type, s.registration_fee_paid
        FROM students s
        LEFT JOIN classes c ON s.class_id = c.id
        ORDER BY s.name
    """)
    data = cur.fetchall()

    st.dataframe(pd.DataFrame(data))

    cur.close()
    conn.close()

# =========================
# RECORD PAYMENT
# =========================

if menu == "Record Payment":
    st.subheader("Record Student Payment")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT id,name FROM students ORDER BY name")
    students = cur.fetchall()

    student_dict = {s["name"]: s["id"] for s in students}

    cur.execute("""
        SELECT id,name FROM expense_categories
        WHERE category_type='Income'
    """)
    categories = cur.fetchall()

    category_dict = {c["name"]: c["id"] for c in categories}

    with st.form("payment_form"):
        student_name = st.selectbox("Student", list(student_dict.keys()))
        category_name = st.selectbox("Payment Category", list(category_dict.keys()))
        amount = st.number_input("Amount", min_value=0.0)
        payment_method = st.selectbox("Payment Method", ["Cash","Mobile Money","Bank"])
        description = st.text_area("Description")

        submit_payment = st.form_submit_button("Record Payment")

        if submit_payment and amount > 0:
            receipt = generate_receipt_number()

            try:
                cur.execute("""
                    INSERT INTO incomes
                    (date, receipt_number, amount, source,
                     category_id, description,
                     payment_method, payer, received_by, created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,(
                    date.today(),
                    receipt,
                    amount,
                    "Student Payment",
                    category_dict[category_name],
                    description,
                    payment_method,
                    student_name,
                    current_user,
                    current_user
                ))

                # Mark registration fee paid if applicable
                if category_name == "Registration Fees":
                    cur.execute("""
                        UPDATE students
                        SET registration_fee_paid=TRUE
                        WHERE id=%s
                    """,(student_dict[student_name],))

                conn.commit()
                log_action("payment_recorded",f"{student_name} paid {amount}",current_user)

                st.success(f"Payment recorded. Receipt: {receipt}")
                st.rerun()

            except Exception as e:
                conn.rollback()
                st.error(f"Error: {e}")

    cur.close()
    conn.close()

# =========================
# STUDENT LEDGER
# =========================

if menu == "Student Ledger":
    st.subheader("Student Ledger")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT id,name FROM students ORDER BY name")
    students = cur.fetchall()
    student_dict = {s["name"]: s["id"] for s in students}

    selected_student = st.selectbox("Select Student", list(student_dict.keys()))

    if selected_student:
        cur.execute("""
            SELECT date, receipt_number, amount,
                   payment_method, description
            FROM incomes
            WHERE payer=%s
            ORDER BY date
        """,(selected_student,))

        payments = cur.fetchall()

        df = pd.DataFrame(payments)
        total_paid = df["amount"].sum() if not df.empty else 0

        st.dataframe(df)
        st.metric("Total Paid", total_paid)

    cur.close()
    conn.close()

# =========================
# REPORTS
# =========================

if menu == "Reports":
    st.subheader("Financial Reports")

    conn = get_db_connection()
    cur = conn.cursor()

    start_date = st.date_input("Start Date", date(date.today().year,1,1))
    end_date = st.date_input("End Date", date.today())

    if st.button("Generate Report"):
        cur.execute("""
            SELECT date, receipt_number, amount, payer
            FROM incomes
            WHERE date BETWEEN %s AND %s
        """,(start_date,end_date))

        report = cur.fetchall()
        df = pd.DataFrame(report)

        st.dataframe(df)

        total = df["amount"].sum() if not df.empty else 0
        st.metric("Total Income", total)

    cur.close()
    conn.close()
# =========================
# SECTION 3 — STAFF & UNIFORMS
# =========================

if menu == "Dashboard":
    pass  # already handled above


# Add new sidebar options for this section
extra_menu = st.sidebar.radio(
    "Management",
    [
        "None",
        "Staff Management",
        "Uniform Inventory",
        "Sell Uniform"
    ]
)

# =========================
# STAFF MANAGEMENT
# =========================

if extra_menu == "Staff Management":

    st.subheader("Staff Management")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            id SERIAL PRIMARY KEY,
            name TEXT,
            role TEXT,
            salary NUMERIC,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    with st.form("add_staff"):
        name = st.text_input("Full Name")
        role = st.text_input("Role")
        salary = st.number_input("Salary", min_value=0.0)
        phone = st.text_input("Phone")

        if st.form_submit_button("Add Staff"):
            if name and role:
                cur.execute("""
                    INSERT INTO staff (name, role, salary, phone)
                    VALUES (%s,%s,%s,%s)
                """,(name,role,salary,phone))
                conn.commit()
                log_action("staff_added",name,current_user)
                st.success("Staff added.")
                st.rerun()

    st.divider()

    cur.execute("SELECT * FROM staff ORDER BY name")
    staff_data = cur.fetchall()
    st.dataframe(pd.DataFrame(staff_data))

    cur.close()
    conn.close()


# =========================
# UNIFORM INVENTORY
# =========================

if extra_menu == "Uniform Inventory":

    st.subheader("Uniform Inventory Management")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS uniforms (
            id SERIAL PRIMARY KEY,
            item_name TEXT UNIQUE,
            quantity INTEGER,
            price NUMERIC,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    with st.form("add_uniform"):
        item = st.text_input("Uniform Item Name")
        quantity = st.number_input("Quantity", min_value=0)
        price = st.number_input("Selling Price", min_value=0.0)

        if st.form_submit_button("Add / Update Item"):
            if item:
                cur.execute("""
                    INSERT INTO uniforms (item_name, quantity, price)
                    VALUES (%s,%s,%s)
                    ON CONFLICT (item_name)
                    DO UPDATE SET
                        quantity = uniforms.quantity + EXCLUDED.quantity,
                        price = EXCLUDED.price
                """,(item,quantity,price))
                conn.commit()
                log_action("uniform_stock_updated",item,current_user)
                st.success("Inventory updated.")
                st.rerun()

    st.divider()

    cur.execute("SELECT * FROM uniforms ORDER BY item_name")
    uniform_data = cur.fetchall()
    st.dataframe(pd.DataFrame(uniform_data))

    cur.close()
    conn.close()


# =========================
# SELL UNIFORM
# =========================

if extra_menu == "Sell Uniform":

    st.subheader("Sell Uniform")

    conn = get_db_connection()
    cur = conn.cursor()

    # Load uniforms
    cur.execute("SELECT * FROM uniforms ORDER BY item_name")
    uniforms = cur.fetchall()

    if not uniforms:
        st.warning("No uniforms in stock.")
        conn.close()
        st.stop()

    uniform_dict = {u["item_name"]: u for u in uniforms}

    # Load students
    cur.execute("SELECT name FROM students ORDER BY name")
    students = [s["name"] for s in cur.fetchall()]

    with st.form("sell_uniform"):
        selected_student = st.selectbox("Student", students)
        selected_item = st.selectbox("Uniform Item", list(uniform_dict.keys()))
        quantity = st.number_input("Quantity", min_value=1)

        submit_sale = st.form_submit_button("Complete Sale")

        if submit_sale:
            item_data = uniform_dict[selected_item]

            if item_data["quantity"] < quantity:
                st.error("Not enough stock available.")
            else:
                total_price = float(item_data["price"]) * quantity
                receipt = generate_receipt_number()

                try:
                    # Deduct stock
                    cur.execute("""
                        UPDATE uniforms
                        SET quantity = quantity - %s
                        WHERE id = %s
                    """,(quantity,item_data["id"]))

                    # Record income
                    cur.execute("""
                        INSERT INTO incomes
                        (date, receipt_number, amount, source,
                         category_id, description,
                         payment_method, payer, received_by, created_by)
                        VALUES (%s,%s,%s,%s,
                                (SELECT id FROM expense_categories WHERE name='Uniform Sales'),
                                %s,%s,%s,%s,%s)
                    """,(
                        date.today(),
                        receipt,
                        total_price,
                        "Uniform Sale",
                        f"{selected_item} x{quantity}",
                        "Cash",
                        selected_student,
                        current_user,
                        current_user
                    ))

                    conn.commit()
                    log_action("uniform_sold",
                               f"{selected_student} bought {selected_item} x{quantity}",
                               current_user)

                    st.success(f"Sale completed. Receipt: {receipt}")
                    st.rerun()

                except Exception as e:
                    conn.rollback()
                    st.error(f"Transaction failed: {e}")

    cur.close()
    conn.close()
# =========================
# SECTION 4 — FINANCE & ADMIN
# =========================

admin_menu = st.sidebar.radio(
    "Finance & Admin",
    [
        "None",
        "Record Expense",
        "Cashbook",
        "Export Data",
        "User Management",
        "Audit Log",
        "Logout"
    ]
)

# =========================
# RECORD EXPENSE
# =========================

if admin_menu == "Record Expense":

    st.subheader("Record Expense")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id,name FROM expense_categories
        WHERE category_type='Expense'
    """)
    categories = cur.fetchall()
    category_dict = {c["name"]: c["id"] for c in categories}

    with st.form("expense_form"):
        category_name = st.selectbox("Category", list(category_dict.keys()))
        amount = st.number_input("Amount", min_value=0.0)
        payment_method = st.selectbox("Payment Method", ["Cash","Mobile Money","Bank"])
        description = st.text_area("Description")
        payee = st.text_input("Paid To")

        submit_expense = st.form_submit_button("Record Expense")

        if submit_expense and amount > 0:
            voucher = generate_voucher_number()

            try:
                cur.execute("""
                    INSERT INTO expenses
                    (date, voucher_number, amount,
                     category_id, description,
                     payment_method, payee,
                     approved_by, created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,(
                    date.today(),
                    voucher,
                    amount,
                    category_dict[category_name],
                    description,
                    payment_method,
                    payee,
                    current_user,
                    current_user
                ))

                conn.commit()
                log_action("expense_recorded",
                           f"{category_name} - {amount}",
                           current_user)

                st.success(f"Expense recorded. Voucher: {voucher}")
                st.rerun()

            except Exception as e:
                conn.rollback()
                st.error(f"Error: {e}")

    cur.close()
    conn.close()

# =========================
# CASHBOOK
# =========================

if admin_menu == "Cashbook":

    st.subheader("Cashbook")

    conn = get_db_connection()
    cur = conn.cursor()

    start = st.date_input("Start Date", date(date.today().year,1,1))
    end = st.date_input("End Date", date.today())

    if st.button("Load Cashbook"):

        cur.execute("""
            SELECT date, receipt_number as ref, amount,
                   'Income' as type
            FROM incomes
            WHERE date BETWEEN %s AND %s
        """,(start,end))
        incomes_data = cur.fetchall()

        cur.execute("""
            SELECT date, voucher_number as ref, amount,
                   'Expense' as type
            FROM expenses
            WHERE date BETWEEN %s AND %s
        """,(start,end))
        expenses_data = cur.fetchall()

        df_income = pd.DataFrame(incomes_data)
        df_expense = pd.DataFrame(expenses_data)

        df = pd.concat([df_income, df_expense], ignore_index=True)
        df = df.sort_values("date")

        if not df.empty:
            df["balance"] = df.apply(
                lambda row: row["amount"]
                if row["type"]=="Income"
                else -row["amount"], axis=1
            ).cumsum()

        st.dataframe(df)

    cur.close()
    conn.close()

# =========================
# EXPORT DATA
# =========================

if admin_menu == "Export Data":

    st.subheader("Export Financial Data")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM incomes")
    incomes_data = pd.DataFrame(cur.fetchall())

    cur.execute("SELECT * FROM expenses")
    expenses_data = pd.DataFrame(cur.fetchall())

    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        incomes_data.to_excel(writer, sheet_name="Incomes", index=False)
        expenses_data.to_excel(writer, sheet_name="Expenses", index=False)

    st.download_button(
        label="Download Excel Report",
        data=output.getvalue(),
        file_name="financial_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    cur.close()
    conn.close()

# =========================
# USER MANAGEMENT (ADMIN ONLY)
# =========================

if admin_menu == "User Management":

    if st.session_state.user["role"] != "Admin":
        st.error("Access Denied")
        st.stop()

    st.subheader("User Management")

    conn = get_db_connection()
    cur = conn.cursor()

    with st.form("add_user"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        role = st.selectbox("Role", ["Admin","Clerk"])
        full_name = st.text_input("Full Name")

        if st.form_submit_button("Create User"):
            cur.execute("""
                INSERT INTO users
                (username,password_hash,role,full_name)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (username) DO NOTHING
            """,(username,hash_password(password),role,full_name))
            conn.commit()
            st.success("User created.")
            st.rerun()

    st.divider()

    cur.execute("SELECT id,username,role,full_name FROM users")
    users_data = cur.fetchall()
    st.dataframe(pd.DataFrame(users_data))

    cur.close()
    conn.close()

# =========================
# AUDIT LOG
# =========================

if admin_menu == "Audit Log":

    if st.session_state.user["role"] != "Admin":
        st.error("Access Denied")
        st.stop()

    st.subheader("System Audit Log")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT action, details, performed_by, performed_at
        FROM audit_log
        ORDER BY performed_at DESC
        LIMIT 200
    """)
    logs = cur.fetchall()

    st.dataframe(pd.DataFrame(logs))

    cur.close()
    conn.close()

# =========================
# LOGOUT
# =========================

if admin_menu == "Logout":
    log_action("logout","User logged out",current_user)
    st.session_state.user = None
    st.success("Logged out successfully.")
    st.rerun()
# ────────────────────────────────────────────────
# Footer
# ────────────────────────────────────────────────
st.markdown("---")
st.caption(f"© COSNA School Management System • {datetime.now().year}")
st.caption("Developed for Cosna Daycare, Nursery, Day and Boarding Primary School Kiyinda-Mityana")
