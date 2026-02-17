import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
from datetime import datetime, date
from io import BytesIO
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import random
import string
import difflib
import bcrypt
import os
import traceback

# ---------------------------
# Configuration
# ---------------------------
APP_TITLE = "COSNA School Management System"
SCHOOL_NAME = "Cosna Daycare, Nursery, Day and Boarding Primary School Kiyinda-Mityana"
SCHOOL_ADDRESS = "P.O.BOX 000, Kiyinda-Mityana"
SCHOOL_EMAIL = "info@cosnaschool.com Or: admin@cosnaschool.com"
REGISTRATION_FEE = 50000.0
SIMILARITY_THRESHOLD = 0.82
LOGO_FILENAME = "school_badge.png"
PAGE_LAYOUT = "wide"
st.set_page_config(page_title=APP_TITLE, layout=PAGE_LAYOUT, initial_sidebar_state="expanded")
st.title(APP_TITLE)
st.markdown("Students • Uniforms • Finances • Reports")

# ---------------------------
# Database Connection
# ---------------------------
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

# ---------------------------
# Utilities
# ---------------------------
def normalize_text(s: str):
    if s is None:
        return ""
    return " ".join(s.strip().lower().split())

def similar(a: str, b: str):
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()

def is_near_duplicate(candidate: str, existing_list, threshold=SIMILARITY_THRESHOLD):
    candidate_n = normalize_text(candidate)
    for ex in existing_list:
        if similar(candidate_n, ex) >= threshold:
            return True, ex
    return False, None

def hash_password(password: str):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(stored: str, provided: str):
    return bcrypt.checkpw(provided.encode(), stored.encode())

def generate_code(prefix="RCPT"):
    day = datetime.now().strftime("%d")
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=2))
    return f"{prefix}-{day}{random_chars}"

def generate_receipt_number(): return generate_code("RCPT")
def generate_invoice_number(): return generate_code("INV")
def generate_voucher_number(): return generate_code("VCH")

def safe_rerun():
    try:
        st.rerun()
    except:
        pass

# ---------------------------
# DB Migration Helpers
# ---------------------------
def table_has_column(conn, table_name, column_name):
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table_name, column_name))
    return cur.fetchone() is not None

def safe_alter_add_column(conn, table, column_def):
    col_name = column_def.split()[0]
    if not table_has_column(conn, table, col_name):
        cur = conn.cursor()
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
        conn.commit()
        return True
    return False

# ---------------------------
# Initialize Database
# ---------------------------
def initialize_database():
    conn = get_db_connection()
    cur = conn.cursor()
    # Users
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE,
            password_hash TEXT,
            role TEXT DEFAULT 'Clerk',
            full_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Expense Categories
    cur.execute('''
        CREATE TABLE IF NOT EXISTS expense_categories (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE,
            category_type TEXT DEFAULT 'Expense' CHECK(category_type IN ('Expense','Income'))
        )
    ''')
    # Classes
    cur.execute('CREATE TABLE IF NOT EXISTS classes (id SERIAL PRIMARY KEY, name TEXT UNIQUE)')
    # Students
    cur.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            name TEXT,
            normalized_name TEXT,
            age INTEGER,
            enrollment_date DATE,
            class_id INTEGER REFERENCES classes(id),
            student_type TEXT DEFAULT 'Returning',
            registration_fee_paid INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Uniform Categories
    cur.execute('''
        CREATE TABLE IF NOT EXISTS uniform_categories (
            id SERIAL PRIMARY KEY,
            category TEXT UNIQUE,
            normalized_category TEXT,
            gender TEXT,
            is_shared INTEGER DEFAULT 0
        )
    ''')
    # Uniforms
    cur.execute('''
        CREATE TABLE IF NOT EXISTS uniforms (
            id SERIAL PRIMARY KEY,
            category_id INTEGER REFERENCES uniform_categories(id),
            stock INTEGER DEFAULT 0,
            unit_price REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Expenses
    cur.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            date DATE,
            voucher_number TEXT UNIQUE,
            amount REAL,
            category_id INTEGER REFERENCES expense_categories(id),
            description TEXT,
            payment_method TEXT CHECK(payment_method IN ('Cash','Bank Transfer','Mobile Money','Cheque')),
            payee TEXT,
            attachment_path TEXT,
            approved_by TEXT,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Incomes
    cur.execute('''
        CREATE TABLE IF NOT EXISTS incomes (
            id SERIAL PRIMARY KEY,
            date DATE,
            receipt_number TEXT UNIQUE,
            amount REAL,
            source TEXT,
            category_id INTEGER REFERENCES expense_categories(id),
            description TEXT,
            payment_method TEXT CHECK(payment_method IN ('Cash','Bank Transfer','Mobile Money','Cheque')),
            payer TEXT,
            student_id INTEGER REFERENCES students(id),
            attachment_path TEXT,
            received_by TEXT,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Fee Structure
    cur.execute('''
        CREATE TABLE IF NOT EXISTS fee_structure (
            id SERIAL PRIMARY KEY,
            class_id INTEGER REFERENCES classes(id),
            term TEXT CHECK(term IN ('Term 1','Term 2','Term 3')),
            academic_year TEXT,
            tuition_fee REAL DEFAULT 0,
            uniform_fee REAL DEFAULT 0,
            activity_fee REAL DEFAULT 0,
            exam_fee REAL DEFAULT 0,
            library_fee REAL DEFAULT 0,
            other_fee REAL DEFAULT 0,
            total_fee REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Invoices
    cur.execute('''
        CREATE TABLE IF NOT EXISTS invoices (
            id SERIAL PRIMARY KEY,
            invoice_number TEXT UNIQUE,
            student_id INTEGER REFERENCES students(id),
            issue_date DATE,
            due_date DATE,
            academic_year TEXT,
            term TEXT,
            total_amount REAL,
            paid_amount REAL DEFAULT 0,
            balance_amount REAL,
            status TEXT CHECK(status IN ('Pending','Partially Paid','Fully Paid','Overdue')) DEFAULT 'Pending',
            notes TEXT,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Payments
    cur.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            invoice_id INTEGER REFERENCES invoices(id),
            receipt_number TEXT UNIQUE,
            payment_date DATE,
            amount REAL,
            payment_method TEXT CHECK(payment_method IN ('Cash','Bank Transfer','Mobile Money','Cheque')),
            reference_number TEXT,
            received_by TEXT,
            notes TEXT,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Audit Log
    cur.execute('''
        CREATE TABLE IF NOT EXISTS audit_log (
            id SERIAL PRIMARY KEY,
            action TEXT,
            details TEXT,
            performed_by TEXT,
            performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Terms
    cur.execute('''
        CREATE TABLE IF NOT EXISTS terms (
            id SERIAL PRIMARY KEY,
            academic_year TEXT,
            term TEXT CHECK(term IN ('Term 1','Term 2','Term 3')),
            start_date DATE,
            end_date DATE,
            UNIQUE(academic_year, term)
        )
    ''')
    # Staff
    cur.execute('''
        CREATE TABLE IF NOT EXISTS staff (
            id SERIAL PRIMARY KEY,
            name TEXT,
            normalized_name TEXT,
            staff_type TEXT CHECK(staff_type IN ('Teaching', 'Non-Teaching')),
            position TEXT,
            hire_date DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Staff Transactions
    cur.execute('''
        CREATE TABLE IF NOT EXISTS staff_transactions (
            id SERIAL PRIMARY KEY,
            staff_id INTEGER REFERENCES staff(id),
            date DATE,
            transaction_type TEXT CHECK(transaction_type IN ('Salary', 'Allowance', 'Advance', 'Other')),
            amount REAL,
            description TEXT,
            payment_method TEXT CHECK(payment_method IN ('Cash','Bank Transfer','Mobile Money','Cheque')),
            voucher_number TEXT UNIQUE,
            approved_by TEXT,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    # Migrations
    safe_alter_add_column(conn, "students", "normalized_name TEXT")
    safe_alter_add_column(conn, "uniform_categories", "normalized_category TEXT")
    safe_alter_add_column(conn, "staff", "normalized_name TEXT")
    # Seed Admin
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO users (username, password_hash, role, full_name)
            VALUES (%s, %s, %s, %s)
        """, ("admin", hash_password("costa2026"), "Admin", "Administrator"))
        conn.commit()
    # Seed Expense Categories
    default_categories = [
        ('Medical', 'Expense'),
        ('Salaries', 'Expense'),
        ('Utilities', 'Expense'),
        ('Maintenance', 'Expense'),
        ('Supplies', 'Expense'),
        ('Transport', 'Expense'),
        ('Events', 'Expense'),
        ('Tuition Fees', 'Income'),
        ('Registration Fees', 'Income'),
        ('Uniform Sales', 'Income'),
        ('Donations', 'Income')
    ]
    for name, ctype in default_categories:
        cur.execute("""
            INSERT INTO expense_categories (name, category_type)
            VALUES (%s, %s) ON CONFLICT (name) DO NOTHING
        """, (name, ctype))
    conn.commit()
    # Seed Uniform Categories if needed
    uniform_seeds = [
        ("Boys Main Shorts", "boys", 0),
        ("Button Shirts Main", "shared", 1),
        # Add more as per u1
    ]
    for category, gender, is_shared in uniform_seeds:
        normalized = normalize_text(category)
        cur.execute("""
            INSERT INTO uniform_categories (category, normalized_category, gender, is_shared)
            VALUES (%s, %s, %s, %s) ON CONFLICT (category) DO NOTHING
        """, (category, normalized, gender, is_shared))
        conn.commit()
        cur.execute("SELECT id FROM uniform_categories WHERE category = %s", (category,))
        cat_id = cur.fetchone()['id']
        cur.execute("""
            INSERT INTO uniforms (category_id, stock, unit_price)
            VALUES (%s, 0, 0.0) ON CONFLICT (category_id) DO NOTHING
        """, (cat_id,))
    conn.commit()
    cur.close()
    conn.close()

initialize_database()

# ---------------------------
# Audit Log
# ---------------------------
def log_action(action, details, user):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO audit_log (action, details, performed_by)
        VALUES (%s, %s, %s)
    """, (action, details, user))
    conn.commit()
    cur.close()
    conn.close()

# ---------------------------
# Authentication
# ---------------------------
if "user" not in st.session_state:
    st.session_state.user = None

if not st.session_state.user:
    if not os.path.exists(LOGO_FILENAME):
        uploaded = st.file_uploader("Upload School Badge (PNG)", type=["png"])
        if uploaded:
            with open(LOGO_FILENAME, "wb") as f:
                f.write(uploaded.getbuffer())
            safe_rerun()
    else:
        st.image(LOGO_FILENAME, width=150)
    st.subheader("Login")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")
    if submit:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        db_user = cur.fetchone()
        cur.close()
        conn.close()
        if db_user and verify_password(db_user['password_hash'], password):
            st.session_state.user = db_user
            log_action("login", f"{username} logged in", username)
            safe_rerun()
        else:
            st.error("Invalid credentials")
    st.stop()

user = st.session_state.user
role = user['role']

# Sidebar
if os.path.exists(LOGO_FILENAME):
    st.sidebar.image(LOGO_FILENAME, width=100)
st.sidebar.markdown(f"Welcome, {user.get('full_name', user['username'])} ({role})")

conn = get_db_connection()
cur = conn.cursor()
cur.execute("SELECT academic_year, term FROM terms ORDER BY academic_year DESC, term")
terms = cur.fetchall()
cur.close()
conn.close()
term_options = [f"{t['academic_year']} - {t['term']}" for t in terms]
if term_options:
    st.sidebar.selectbox("Current Term", term_options, key="current_term")
else:
    st.sidebar.info("No terms defined")

pages = ["Dashboard", "Students", "Uniforms", "Finances", "Staff", "Reports", "Audit Log"]
if role == "Admin":
    pages += ["User Management"]
pages += ["User Settings", "Logout"]
page = st.sidebar.selectbox("Navigation", pages)

def require_role(roles):
    if role not in roles:
        st.error("Access denied")
        st.stop()

# ---------------------------
# Dashboard
# ---------------------------
if page == "Dashboard":
    st.header("Dashboard")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM students")
    total_students = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(amount), 0) FROM incomes")
    total_income = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(amount), 0) FROM expenses")
    total_expenses = cur.fetchone()[0]
    balance = total_income - total_expenses
    cur.close()
    conn.close()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Students", total_students)
    col2.metric("Total Income", f"{total_income:,.0f}")
    col3.metric("Total Expenses", f"{total_expenses:,.0f}")
    col4.metric("Balance", f"{balance:,.0f}")

# ---------------------------
# Students
# ---------------------------
if page == "Students":
    st.header("Student Management")
    tab_add, tab_edit, tab_delete, tab_classes, tab_view = st.tabs(["Add Student", "Edit Student", "Delete Student", "Manage Classes", "View Students"])
    with tab_classes:
        st.subheader("Manage Classes")
        conn = get_db_connection()
        classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
        conn.close()
        if not classes.empty:
            st.dataframe(classes)
        with st.form("add_class_form"):
            class_name = st.text_input("Class Name")
            add_class = st.form_submit_button("Add Class")
        if add_class:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT name FROM classes")
            existing = [r['name'] for r in cur.fetchall()]
            is_dup, match = is_near_duplicate(class_name, existing)
            if is_dup:
                st.error(f"Similar class: {match}")
            else:
                cur.execute("INSERT INTO classes (name) VALUES (%s)", (class_name,))
                conn.commit()
                st.success("Class added")
                log_action("add_class", class_name, user['username'])
                safe_rerun()
            cur.close()
            conn.close()
    with tab_add:
        st.subheader("Add Student")
        conn = get_db_connection()
        classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
        conn.close()
        if classes.empty:
            st.info("Add classes first")
        else:
            with st.form("add_student_form"):
                name = st.text_input("Full Name")
                age = st.number_input("Age", min_value=0, value=5)
                enrollment_date = st.date_input("Enrollment Date", date.today())
                class_name = st.selectbox("Class", classes['name'].tolist())
                class_id = classes[classes['name'] == class_name]['id'].iloc[0]
                student_type = st.selectbox("Type", ["New", "Returning"])
                reg_paid = st.checkbox("Registration Fee Paid")
                submit = st.form_submit_button("Add Student")
            if submit:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT normalized_name FROM students")
                existing = [r['normalized_name'] for r in cur.fetchall()]
                is_dup, match = is_near_duplicate(name, existing)
                if is_dup:
                    st.error(f"Similar student: {match}")
                else:
                    normalized = normalize_text(name)
                    cur.execute("""
                        INSERT INTO students (name, normalized_name, age, enrollment_date, class_id, student_type, registration_fee_paid)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (name, normalized, age, enrollment_date, class_id, student_type, 1 if reg_paid else 0))
                    conn.commit()
                    st.success("Student added")
                    log_action("add_student", name, user['username'])
                    safe_rerun()
                cur.close()
                conn.close()
    with tab_edit:
        st.subheader("Edit Student")
        conn = get_db_connection()
        students = pd.read_sql("SELECT s.id, s.name, c.name as class_name FROM students s JOIN classes c ON s.class_id = c.id ORDER BY s.name", conn)
        classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
        conn.close()
        if students.empty:
            st.info("No students")
        else:
            selected = st.selectbox("Select Student", students.apply(lambda x: f"{x['name']} ({x['class_name']})", axis=1))
            student_id = students[students.apply(lambda x: f"{x['name']} ({x['class_name']})", axis=1) == selected]['id'].iloc[0]
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM students WHERE id = %s", (student_id,))
            student = cur.fetchone()
            cur.close()
            conn.close()
            with st.form("edit_student_form"):
                name = st.text_input("Full Name", student['name'])
                age = st.number_input("Age", student['age'])
                enrollment_date = st.date_input("Enrollment Date", student['enrollment_date'])
                class_name = st.selectbox("Class", classes['name'], index=classes[classes['id'] == student['class_id']].index[0])
                class_id = classes[classes['name'] == class_name]['id'].iloc[0]
                student_type = st.selectbox("Type", ["New", "Returning"], index=0 if student['student_type'] == "New" else 1)
                reg_paid = st.checkbox("Registration Fee Paid", value=bool(student['registration_fee_paid']))
                submit = st.form_submit_button("Update")
            if submit:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT normalized_name FROM students WHERE id != %s", (student_id,))
                existing = [r['normalized_name'] for r in cur.fetchall()]
                is_dup, match = is_near_duplicate(name, existing)
                if is_dup:
                    st.error(f"Similar student: {match}")
                else:
                    normalized = normalize_text(name)
                    cur.execute("""
                        UPDATE students SET name=%s, normalized_name=%s, age=%s, enrollment_date=%s, class_id=%s, student_type=%s, registration_fee_paid=%s WHERE id=%s
                    """, (name, normalized, age, enrollment_date, class_id, student_type, 1 if reg_paid else 0, student_id))
                    conn.commit()
                    st.success("Updated")
                    log_action("edit_student", name, user['username'])
                    safe_rerun()
                cur.close()
                conn.close()
    with tab_delete:
        require_role(["Admin"])
        st.subheader("Delete Student")
        conn = get_db_connection()
        students = pd.read_sql("SELECT id, name FROM students ORDER BY name", conn)
        conn.close()
        if students.empty:
            st.info("No students")
        else:
            selected = st.selectbox("Select Student", students['name'])
            student_id = students[students['name'] == selected]['id'].iloc[0]
            confirm = st.checkbox(f"Confirm delete {selected}")
            if confirm and st.button("Delete"):
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("DELETE FROM students WHERE id = %s", (student_id,))
                conn.commit()
                st.success("Deleted")
                log_action("delete_student", selected, user['username'])
                safe_rerun()
                cur.close()
                conn.close()
    with tab_view:
        st.subheader("View Students")
        conn = get_db_connection()
        students = pd.read_sql("""
            SELECT s.name, s.age, s.enrollment_date, c.name as class, s.student_type, CASE WHEN s.registration_fee_paid = 1 THEN 'Yes' ELSE 'No' END as reg_paid
            FROM students s JOIN classes c ON s.class_id = c.id ORDER BY s.name
        """, conn)
        conn.close()
        st.dataframe(students)
        buf = BytesIO()
        students.to_excel(buf, index=False)
        st.download_button("Download Excel", buf.getvalue(), "students.xlsx")
        pdf_buf = BytesIO()
        c = canvas.Canvas(pdf_buf, pagesize=landscape(letter))
        if os.path.exists(LOGO_FILENAME):
            img = ImageReader(LOGO_FILENAME)
            c.drawImage(img, 50, 500, width=100, height=100)
        c.drawString(160, 550, SCHOOL_NAME)
        c.drawString(160, 530, SCHOOL_ADDRESS)
        data = [students.columns.tolist()] + students.values.tolist()
        y = 450
        for row in data:
            x = 50
            for cell in row:
                c.drawString(x, y, str(cell))
                x += 100
            y -= 20
            if y < 50:
                c.showPage()
                y = 550
        c.save()
        pdf_buf.seek(0)
        st.download_button("Download PDF", pdf_buf, "students.pdf")

# ---------------------------
# Uniforms
# ---------------------------
if page == "Uniforms":
    st.header("Uniform Management")
    tab_categories, tab_inventory, tab_sales = st.tabs(["Categories", "Inventory", "Sales"])
    with tab_categories:
        st.subheader("Manage Categories")
        conn = get_db_connection()
        categories = pd.read_sql("SELECT id, category, gender, is_shared FROM uniform_categories ORDER BY category", conn)
        conn.close()
        st.dataframe(categories)
        with st.form("add_category_form"):
            category = st.text_input("Category")
            gender = st.selectbox("Gender", ["boys", "girls", "shared"])
            is_shared = 1 if gender == "shared" else 0
            submit = st.form_submit_button("Add")
        if submit:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT normalized_category FROM uniform_categories")
            existing = [r['normalized_category'] for r in cur.fetchall()]
            is_dup, match = is_near_duplicate(category, existing)
            if is_dup:
                st.error(f"Similar category: {match}")
            else:
                normalized = normalize_text(category)
                cur.execute("""
                    INSERT INTO uniform_categories (category, normalized_category, gender, is_shared)
                    VALUES (%s, %s, %s, %s)
                """, (category, normalized, gender, is_shared))
                conn.commit()
                cat_id = cur.execute("SELECT currval('uniform_categories_id_seq')").fetchone()[0]
                cur.execute("INSERT INTO uniforms (category_id) VALUES (%s)", (cat_id,))
                conn.commit()
                st.success("Added")
                log_action("add_category", category, user['username'])
                safe_rerun()
            cur.close()
            conn.close()
    with tab_inventory:
        st.subheader("Update Inventory")
        conn = get_db_connection()
        uniforms = pd.read_sql("""
            SELECT u.id, uc.category, u.stock, u.unit_price FROM uniforms u JOIN uniform_categories uc ON u.category_id = uc.id ORDER BY uc.category
        """, conn)
        conn.close()
        if uniforms.empty:
            st.info("No categories")
        else:
            selected_cat = st.selectbox("Category", uniforms['category'])
            row = uniforms[uniforms['category'] == selected_cat].iloc[0]
            with st.form("update_inv_form"):
                stock = st.number_input("Stock", value=int(row['stock']))
                price = st.number_input("Price", value=float(row['unit_price']))
                submit = st.form_submit_button("Update")
            if submit:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE uniforms SET stock=%s, unit_price=%s WHERE id=%s", (stock, price, row['id']))
                conn.commit()
                st.success("Updated")
                log_action("update_inventory", selected_cat, user['username'])
                safe_rerun()
                cur.close()
                conn.close()
            st.dataframe(uniforms)
    with tab_sales:
        st.subheader("Record Sale")
        conn = get_db_connection()
        students = pd.read_sql("SELECT id, name FROM students ORDER BY name", conn)
        uniforms = pd.read_sql("""
            SELECT u.id, uc.category, u.stock, u.unit_price FROM uniforms u JOIN uniform_categories uc ON u.category_id = uc.id WHERE u.stock > 0 ORDER BY uc.category
        """, conn)
        conn.close()
        if students.empty or uniforms.empty:
            st.info("No students or stock")
        else:
            with st.form("sale_form"):
                student_name = st.selectbox("Student", students['name'])
                student_id = students[students['name'] == student_name]['id'].iloc[0]
                category = st.selectbox("Category", uniforms['category'])
                row = uniforms[uniforms['category'] == category].iloc[0]
                quantity = st.number_input("Quantity", 1, int(row['stock']))
                amount = quantity * row['unit_price']
                method = st.selectbox("Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
                desc = st.text_area("Description")
                sale_date = st.date_input("Date", date.today())
                submit = st.form_submit_button("Record")
            if submit:
                if quantity > row['stock']:
                    st.error("Insufficient stock")
                else:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    receipt_no = generate_receipt_number()
                    cur.execute("""
                        INSERT INTO incomes (date, receipt_number, amount, source, category_id, description, payment_method, payer, student_id, received_by, created_by)
                        VALUES (%s, %s, %s, %s, (SELECT id FROM expense_categories WHERE name='Uniform Sales'), %s, %s, %s, %s, %s, %s)
                    """, (sale_date, receipt_no, amount, "Uniform Sale", f"Sold {quantity} {category}", method, student_name, student_id, user['username'], user['username']))
                    cur.execute("UPDATE uniforms SET stock = stock - %s WHERE id = %s", (quantity, row['id']))
                    conn.commit()
                    st.success(f"Recorded. Receipt {receipt_no}")
                    log_action("uniform_sale", f"{student_name} {category} x{quantity}", user['username'])
                    safe_rerun()
                    cur.close()
                    conn.close()

# ---------------------------
# Finances
# ---------------------------
if page == "Finances":
    st.header("Finance Management")
    tab_incomes, tab_expenses, tab_cashbook, tab_fees, tab_invoices, tab_edit_inv, tab_delete_inv = st.tabs(["Incomes", "Expenses", "Cashbook", "Fee Structures", "Generate Invoice", "Edit Invoice", "Delete Invoice"])
    with tab_incomes:
        st.subheader("Record Income")
        conn = get_db_connection()
        categories = pd.read_sql("SELECT id, name FROM expense_categories WHERE category_type='Income'", conn)
        students = pd.read_sql("SELECT id, name FROM students ORDER BY name", conn)
        conn.close()
        with st.form("income_form"):
            date_val = st.date_input("Date", date.today())
            amount = st.number_input("Amount", min_value=0.0)
            category_name = st.selectbox("Category", categories['name'])
            category_id = categories[categories['name'] == category_name]['id'].iloc[0]
            source = st.text_input("Source")
            payer = st.text_input("Payer")
            student_name = st.selectbox("Student (optional)", ["None"] + students['name'].tolist())
            student_id = None if student_name == "None" else students[students['name'] == student_name]['id'].iloc[0]
            method = st.selectbox("Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
            desc = st.text_area("Description")
            attach = st.file_uploader("Attachment", type=["pdf", "jpg", "png"])
            submit = st.form_submit_button("Record")
        if submit:
            path = None
            if attach:
                os.makedirs("attachments", exist_ok=True)
                path = f"attachments/{attach.name}"
                with open(path, "wb") as f:
                    f.write(attach.getbuffer())
            conn = get_db_connection()
            cur = conn.cursor()
            receipt_no = generate_receipt_number()
            cur.execute("""
                INSERT INTO incomes (date, receipt_number, amount, source, category_id, description, payment_method, payer, student_id, attachment_path, received_by, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (date_val, receipt_no, amount, source, category_id, desc, method, payer, student_id, path, user['username'], user['username']))
            conn.commit()
            st.success(f"Recorded. Receipt {receipt_no}")
            log_action("record_income", f"{amount} from {payer}", user['username'])
            safe_rerun()
            cur.close()
            conn.close()
    with tab_expenses:
        require_role(["Admin", "Accountant"])
        st.subheader("Record Expense")
        conn = get_db_connection()
        categories = pd.read_sql("SELECT id, name FROM expense_categories WHERE category_type='Expense'", conn)
        conn.close()
        with st.form("expense_form"):
            date_val = st.date_input("Date", date.today())
            amount = st.number_input("Amount", min_value=0.0)
            category_name = st.selectbox("Category", categories['name'])
            category_id = categories[categories['name'] == category_name]['id'].iloc[0]
            payee = st.text_input("Payee")
            method = st.selectbox("Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
            desc = st.text_area("Description")
            attach = st.file_uploader("Attachment", type=["pdf", "jpg", "png"])
            submit = st.form_submit_button("Record")
        if submit:
            path = None
            if attach:
                os.makedirs("attachments", exist_ok=True)
                path = f"attachments/{attach.name}"
                with open(path, "wb") as f:
                    f.write(attach.getbuffer())
            conn = get_db_connection()
            cur = conn.cursor()
            voucher_no = generate_voucher_number()
            cur.execute("""
                INSERT INTO expenses (date, voucher_number, amount, category_id, description, payment_method, payee, attachment_path, approved_by, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (date_val, voucher_no, amount, category_id, desc, method, payee, path, user['username'], user['username']))
            conn.commit()
            st.success(f"Recorded. Voucher {voucher_no}")
            log_action("record_expense", f"{amount} to {payee}", user['username'])
            safe_rerun()
            cur.close()
            conn.close()
    with tab_cashbook:
        st.subheader("Cashbook")
        start = st.date_input("Start Date", date.today().replace(month=1, day=1))
        end = st.date_input("End Date", date.today())
        if st.button("Load"):
            conn = get_db_connection()
            incomes = pd.read_sql("""
                SELECT date, receipt_number as ref, amount as income, 0 as expense FROM incomes WHERE date BETWEEN %s AND %s
            """, conn, params=(start, end))
            expenses = pd.read_sql("""
                SELECT date, voucher_number as ref, 0 as income, amount as expense FROM expenses WHERE date BETWEEN %s AND %s
            """, conn, params=(start, end))
            conn.close()
            df = pd.concat([incomes, expenses]).sort_values("date")
            df['balance'] = (df['income'] - df['expense']).cumsum()
            st.dataframe(df)
            buf = BytesIO()
            df.to_excel(buf, index=False)
            st.download_button("Download Excel", buf.getvalue(), "cashbook.xlsx")
            pdf_buf = BytesIO()
            c = canvas.Canvas(pdf_buf, pagesize=landscape(letter))
            if os.path.exists(LOGO_FILENAME):
                img = ImageReader(LOGO_FILENAME)
                c.drawImage(img, 50, 500, width=100, height=100)
            c.drawString(160, 550, SCHOOL_NAME)
            data = [df.columns.tolist()] + df.values.tolist()
            y = 450
            for row in data:
                x = 50
                for cell in row:
                    c.drawString(x, y, str(cell))
                    x += 100
                y -= 20
                if y < 50:
                    c.showPage()
                    y = 550
            c.save()
            pdf_buf.seek(0)
            st.download_button("Download PDF", pdf_buf, "cashbook.pdf")
    with tab_fees:
        st.subheader("Fee Structure")
        conn = get_db_connection()
        classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
        conn.close()
        if classes.empty:
            st.info("No classes")
        else:
            with st.form("fee_form"):
                class_name = st.selectbox("Class", classes['name'])
                class_id = classes[classes['name'] == class_name]['id'].iloc[0]
                term = st.selectbox("Term", ["Term 1", "Term 2", "Term 3"])
                year = st.text_input("Academic Year")
                tuition = st.number_input("Tuition", min_value=0.0)
                uniform = st.number_input("Uniform", min_value=0.0)
                activity = st.number_input("Activity", min_value=0.0)
                exam = st.number_input("Exam", min_value=0.0)
                library = st.number_input("Library", min_value=0.0)
                other = st.number_input("Other", min_value=0.0)
                submit = st.form_submit_button("Save")
            if submit:
                total = tuition + uniform + activity + exam + library + other
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT id FROM fee_structure WHERE class_id=%s AND term=%s AND academic_year=%s", (class_id, term, year))
                existing = cur.fetchone()
                if existing:
                    cur.execute("""
                        UPDATE fee_structure SET tuition_fee=%s, uniform_fee=%s, activity_fee=%s, exam_fee=%s, library_fee=%s, other_fee=%s, total_fee=%s WHERE id=%s
                    """, (tuition, uniform, activity, exam, library, other, total, existing['id']))
                else:
                    cur.execute("""
                        INSERT INTO fee_structure (class_id, term, academic_year, tuition_fee, uniform_fee, activity_fee, exam_fee, library_fee, other_fee, total_fee)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (class_id, term, year, tuition, uniform, activity, exam, library, other, total))
                conn.commit()
                st.success("Saved")
                log_action("fee_structure", f"{class_name} {term} {year}", user['username'])
                safe_rerun()
                cur.close()
                conn.close()
    with tab_invoices:
        st.subheader("Generate Invoice")
        conn = get_db_connection()
        students = pd.read_sql("SELECT s.id, s.name, c.name as class FROM students s JOIN classes c ON s.class_id = c.id ORDER BY s.name", conn)
        conn.close()
        if students.empty:
            st.info("No students")
        else:
            selected = st.selectbox("Student", students.apply(lambda x: f"{x['name']} ({x['class']})", axis=1))
            student_id = students[students.apply(lambda x: f"{x['name']} ({x['class']})", axis=1) == selected]['id'].iloc[0]
            conn = get_db_connection()
            fees = pd.read_sql("SELECT * FROM fee_structure WHERE class_id = (SELECT class_id FROM students WHERE id=%s) ORDER BY academic_year DESC", conn, params=(student_id,))
            conn.close()
            if fees.empty:
                st.info("No fee structure")
            else:
                chosen = st.selectbox("Fee", fees.apply(lambda x: f"{x['academic_year']} {x['term']} {x['total_fee']}", axis=1))
                fee_row = fees[fees.apply(lambda x: f"{x['academic_year']} {x['term']} {x['total_fee']}", axis=1) == chosen].iloc[0]
                issue_date = st.date_input("Issue Date", date.today())
                due_date = st.date_input("Due Date", date.today())
                notes = st.text_area("Notes")
                if st.button("Create"):
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM invoices WHERE student_id=%s AND term=%s AND academic_year=%s", (student_id, fee_row['term'], fee_row['academic_year']))
                    if cur.fetchone():
                        st.error("Invoice exists")
                    else:
                        inv_no = generate_invoice_number()
                        total = fee_row['total_fee']
                        cur.execute("""
                            INSERT INTO invoices (invoice_number, student_id, issue_date, due_date, academic_year, term, total_amount, balance_amount, notes, created_by)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (inv_no, student_id, issue_date, due_date, fee_row['academic_year'], fee_row['term'], total, total, notes, user['username']))
                        conn.commit()
                        st.success(f"Created {inv_no}")
                        log_action("create_invoice", inv_no, user['username'])
                        safe_rerun()
                    cur.close()
                    conn.close()
    with tab_edit_inv:
        st.subheader("Edit Invoice")
        conn = get_db_connection()
        invoices = pd.read_sql("SELECT i.id, i.invoice_number, s.name as student, i.total_amount, i.paid_amount, i.balance_amount FROM invoices i JOIN students s ON i.student_id = s.id ORDER BY i.issue_date DESC", conn)
        conn.close()
        if invoices.empty:
            st.info("No invoices")
        else:
            selected_inv = st.selectbox("Invoice", invoices['invoice_number'])
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM invoices WHERE invoice_number = %s", (selected_inv,))
            inv = cur.fetchone()
            cur.close()
            conn.close()
            with st.form("edit_inv_form"):
                issue_date = st.date_input("Issue Date", inv['issue_date'])
                due_date = st.date_input("Due Date", inv['due_date'])
                total = st.number_input("Total", value=float(inv['total_amount']))
                notes = st.text_area("Notes", inv['notes'])
                submit = st.form_submit_button("Update")
            if submit:
                new_balance = total - inv['paid_amount']
                status = 'Fully Paid' if new_balance <= 0 else 'Partially Paid' if inv['paid_amount'] > 0 else 'Pending'
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("""
                    UPDATE invoices SET issue_date=%s, due_date=%s, total_amount=%s, balance_amount=%s, status=%s, notes=%s WHERE id=%s
                """, (issue_date, due_date, total, new_balance, status, notes, inv['id']))
                conn.commit()
                st.success("Updated")
                log_action("edit_invoice", selected_inv, user['username'])
                safe_rerun()
                cur.close()
                conn.close()
    with tab_delete_inv:
        require_role(["Admin"])
        st.subheader("Delete Invoice")
        conn = get_db_connection()
        invoices = pd.read_sql("SELECT id, invoice_number FROM invoices ORDER BY issue_date DESC", conn)
        conn.close()
        if invoices.empty:
            st.info("No invoices")
        else:
            selected_inv = st.selectbox("Invoice", invoices['invoice_number'])
            inv_id = invoices[invoices['invoice_number'] == selected_inv]['id'].iloc[0]
            confirm = st.checkbox(f"Confirm delete {selected_inv}")
            if confirm and st.button("Delete"):
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("DELETE FROM invoices WHERE id = %s", (inv_id,))
                conn.commit()
                st.success("Deleted")
                log_action("delete_invoice", selected_inv, user['username'])
                safe_rerun()
                cur.close()
                conn.close()

# ---------------------------
# Staff
# ---------------------------
if page == "Staff":
    st.header("Staff Management")
    tab_add, tab_edit, tab_delete, tab_view = st.tabs(["Add Staff", "Edit Staff", "Delete Staff", "View Staff"])
    with tab_add:
        st.subheader("Add Staff")
        with st.form("add_staff_form"):
            name = st.text_input("Name")
            staff_type = st.selectbox("Type", ["Teaching", "Non-Teaching"])
            position = st.text_input("Position")
            hire_date = st.date_input("Hire Date", date.today())
            submit = st.form_submit_button("Add")
        if submit:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT normalized_name FROM staff")
            existing = [r['normalized_name'] for r in cur.fetchall()]
            is_dup, match = is_near_duplicate(name, existing)
            if is_dup:
                st.error(f"Similar staff: {match}")
            else:
                normalized = normalize_text(name)
                cur.execute("""
                    INSERT INTO staff (name, normalized_name, staff_type, position, hire_date)
                    VALUES (%s, %s, %s, %s, %s)
                """, (name, normalized, staff_type, position, hire_date))
                conn.commit()
                st.success("Added")
                log_action("add_staff", name, user['username'])
                safe_rerun()
            cur.close()
            conn.close()
    with tab_edit:
        st.subheader("Edit Staff")
        conn = get_db_connection()
        staff = pd.read_sql("SELECT id, name FROM staff ORDER BY name", conn)
        conn.close()
        if staff.empty:
            st.info("No staff")
        else:
            selected = st.selectbox("Staff", staff['name'])
            staff_id = staff[staff['name'] == selected]['id'].iloc[0]
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM staff WHERE id = %s", (staff_id,))
            s = cur.fetchone()
            cur.close()
            conn.close()
            with st.form("edit_staff_form"):
                name = st.text_input("Name", s['name'])
                staff_type = st.selectbox("Type", ["Teaching", "Non-Teaching"], index=0 if s['staff_type'] == "Teaching" else 1)
                position = st.text_input("Position", s['position'])
                hire_date = st.date_input("Hire Date", s['hire_date'])
                submit = st.form_submit_button("Update")
            if submit:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT normalized_name FROM staff WHERE id != %s", (staff_id,))
                existing = [r['normalized_name'] for r in cur.fetchall()]
                is_dup, match = is_near_duplicate(name, existing)
                if is_dup:
                    st.error(f"Similar staff: {match}")
                else:
                    normalized = normalize_text(name)
                    cur.execute("""
                        UPDATE staff SET name=%s, normalized_name=%s, staff_type=%s, position=%s, hire_date=%s WHERE id=%s
                    """, (name, normalized, staff_type, position, hire_date, staff_id))
                    conn.commit()
                    st.success("Updated")
                    log_action("edit_staff", name, user['username'])
                    safe_rerun()
                cur.close()
                conn.close()
    with tab_delete:
        require_role(["Admin"])
        st.subheader("Delete Staff")
        conn = get_db_connection()
        staff = pd.read_sql("SELECT id, name FROM staff ORDER BY name", conn)
        conn.close()
        if staff.empty:
            st.info("No staff")
        else:
            selected = st.selectbox("Staff", staff['name'])
            staff_id = staff[staff['name'] == selected]['id'].iloc[0]
            confirm = st.checkbox(f"Confirm delete {selected}")
            if confirm and st.button("Delete"):
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("DELETE FROM staff WHERE id = %s", (staff_id,))
                conn.commit()
                st.success("Deleted")
                log_action("delete_staff", selected, user['username'])
                safe_rerun()
                cur.close()
                conn.close()
    with tab_view:
        st.subheader("View Staff")
        conn = get_db_connection()
        staff = pd.read_sql("SELECT name, staff_type, position, hire_date FROM staff ORDER BY name", conn)
        conn.close()
        st.dataframe(staff)

# ---------------------------
# Reports
# ---------------------------
if page == "Reports":
    st.header("Reports")
    tab_statements, tab_overall = st.tabs(["Student Statements", "Overall Reports"])
    with tab_statements:
        st.subheader("Student Fee Statements")
        conn = get_db_connection()
        students = pd.read_sql("SELECT id, name FROM students ORDER BY name", conn)
        conn.close()
        if students.empty:
            st.info("No students")
        else:
            selected = st.selectbox("Student", students['name'])
            student_id = students[students['name'] == selected]['id'].iloc[0]
            conn = get_db_connection()
            invoices = pd.read_sql("SELECT * FROM invoices WHERE student_id=%s ORDER BY issue_date", conn, params=(student_id,))
            payments = pd.read_sql("SELECT * FROM payments WHERE invoice_id IN (SELECT id FROM invoices WHERE student_id=%s) ORDER BY payment_date", conn, params=(student_id,))
            conn.close()
            if invoices.empty:
                st.info("No invoices")
            else:
                for _, inv in invoices.iterrows():
                    st.markdown(f"### {inv['invoice_number']} - {inv['term']} {inv['academic_year']}")
                    st.write(f"Total: {inv['total_amount']:,} Paid: {inv['paid_amount']:,} Balance: {inv['balance_amount']:,} Status: {inv['status']}")
                    inv_payments = payments[payments['invoice_id'] == inv['id']]
                    if not inv_payments.empty:
                        st.dataframe(inv_payments)
                    with st.form(f"pay_form_{inv['id']}"):
                        amount = st.number_input("Amount", min_value=0.0, max_value=float(inv['balance_amount']))
                        method = st.selectbox("Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
                        ref = st.text_input("Reference")
                        notes = st.text_area("Notes")
                        submit = st.form_submit_button("Pay")
                    if submit:
                        if amount > inv['balance_amount']:
                            st.error("Exceeds balance")
                        else:
                            conn = get_db_connection()
                            cur = conn.cursor()
                            receipt_no = generate_receipt_number()
                            new_paid = inv['paid_amount'] + amount
                            new_balance = inv['total_amount'] - new_paid
                            status = 'Fully Paid' if new_balance <= 0 else 'Partially Paid'
                            cur.execute("""
                                INSERT INTO payments (invoice_id, receipt_number, payment_date, amount, payment_method, reference_number, received_by, notes, created_by)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (inv['id'], receipt_no, date.today(), amount, method, ref, user['username'], notes, user['username']))
                            cur.execute("""
                                UPDATE invoices SET paid_amount=%s, balance_amount=%s, status=%s WHERE id=%s
                            """, (new_paid, new_balance, status, inv['id']))
                            conn.commit()
                            st.success(f"Paid. Receipt {receipt_no}")
                            log_action("payment", receipt_no, user['username'])
                            safe_rerun()
                            cur.close()
                            conn.close()
    with tab_overall:
        st.subheader("Overall Reports")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT t.academic_year, t.term, COALESCE(SUM(p.amount), 0) as total_payments FROM terms t LEFT JOIN invoices i ON i.academic_year = t.academic_year AND i.term = t.term LEFT JOIN payments p ON p.invoice_id = i.id GROUP BY t.academic_year, t.term ORDER BY t.academic_year DESC
        """)
        reports = pd.DataFrame(cur.fetchall())
        cur.close()
        conn.close()
        st.dataframe(reports)

# ---------------------------
# Audit Log
# ---------------------------
if page == "Audit Log":
    require_role(["Admin"])
    st.header("Audit Log")
    conn = get_db_connection()
    logs = pd.read_sql("SELECT * FROM audit_log ORDER BY performed_at DESC LIMIT 200", conn)
    conn.close()
    st.dataframe(logs)

# ---------------------------
# User Management
# ---------------------------
if page == "User Management":
    require_role(["Admin"])
    st.header("User Management")
    with st.form("add_user_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        role = st.selectbox("Role", ["Admin", "Accountant", "Clerk"])
        full_name = st.text_input("Full Name")
        submit = st.form_submit_button("Add User")
    if submit:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (%s, %s, %s, %s)", (username, hash_password(password), role, full_name))
        conn.commit()
        st.success("Added")
        log_action("add_user", username, user['username'])
        safe_rerun()
        cur.close()
        conn.close()
    conn = get_db_connection()
    users = pd.read_sql("SELECT username, role, full_name FROM users ORDER BY username", conn)
    conn.close()
    st.dataframe(users)

# ---------------------------
# User Settings
# ---------------------------
if page == "User Settings":
    st.header("User Settings")
    tab_profile, tab_password = st.tabs(["Profile", "Change Password"])
    with tab_profile:
        with st.form("profile_form"):
            full_name = st.text_input("Full Name", user['full_name'])
            submit = st.form_submit_button("Save")
        if submit:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE users SET full_name=%s WHERE id=%s", (full_name, user['id']))
            conn.commit()
            st.session_state.user['full_name'] = full_name
            st.success("Updated")
            log_action("update_profile", "", user['username'])
            safe_rerun()
            cur.close()
            conn.close()
    with tab_password:
        with st.form("password_form"):
            current = st.text_input("Current Password", type="password")
            new = st.text_input("New Password", type="password")
            confirm = st.text_input("Confirm", type="password")
            submit = st.form_submit_button("Change")
        if submit:
            if new != confirm:
                st.error("Don't match")
            else:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT password_hash FROM users WHERE id=%s", (user['id'],))
                stored = cur.fetchone()['password_hash']
                if verify_password(stored, current):
                    cur.execute("UPDATE users SET password_hash=%s WHERE id=%s", (hash_password(new), user['id']))
                    conn.commit()
                    st.success("Changed")
                    log_action("change_password", "", user['username'])
                else:
                    st.error("Incorrect current")
                cur.close()
                conn.close()

# ---------------------------
# Logout
# ---------------------------
if page == "Logout":
    log_action("logout", "", user['username'])
    st.session_state.user = None
    safe_rerun()

# Footer
st.markdown("---")
st.caption(f"© COSNA School Management System • {datetime.now().year}")
st.caption("Developed for Cosna Daycare, Nursery, Day and Boarding Primary School Kiyinda-Mityana")
