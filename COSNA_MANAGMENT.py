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
    # Core tables
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
    cur.execute('''
        CREATE TABLE IF NOT EXISTS expense_categories (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE,
            category_type TEXT DEFAULT 'Expense' CHECK(category_type IN ('Expense','Income'))
        )
    ''')
    cur.execute('CREATE TABLE IF NOT EXISTS classes (id SERIAL PRIMARY KEY, name TEXT UNIQUE)')
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
    cur.execute('''
        CREATE TABLE IF NOT EXISTS uniform_categories (
            id SERIAL PRIMARY KEY,
            category TEXT UNIQUE,
            normalized_category TEXT,
            gender TEXT,
            is_shared INTEGER DEFAULT 0
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS uniforms (
            id SERIAL PRIMARY KEY,
            category_id INTEGER UNIQUE REFERENCES uniform_categories(id),
            stock INTEGER DEFAULT 0,
            unit_price REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
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
    cur.execute('''
        CREATE TABLE IF NOT EXISTS audit_log (
            id SERIAL PRIMARY KEY,
            action TEXT,
            details TEXT,
            performed_by TEXT,
            performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
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
    cur.execute("SELECT COUNT(*) AS cnt FROM users")
    row = cur.fetchone()
    if row['cnt'] == 0:
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
    # Seed Uniform Categories
    uniform_seeds = [
        ('Boys Main Shorts', 'boys', 0),
        ('Button Shirts Main', 'shared', 1),
        ('Girls Skirts', 'girls', 0),
        # Add full list from u1 if more
    ]
    for category, gender, is_shared in uniform_seeds:
        normalized = normalize_text(category)
        cur.execute("""
            INSERT INTO uniform_categories (category, normalized_category, gender, is_shared)
            VALUES (%s, %s, %s, %s) ON CONFLICT (category) DO NOTHING
        """, (category, normalized, gender, is_shared))
        conn.commit()
        cur.execute("SELECT id FROM uniform_categories WHERE category = %s", (category,))
        row = cur.fetchone()
        if row:
            cat_id = row['id']
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
    cur.execute("INSERT INTO audit_log (action, details, performed_by) VALUES (%s, %s, %s)", (action, details, user))
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
            log_action("login", "", db_user['username'])
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
pages = ["Students", "Uniforms", "Finances", "Reports", "Staff", "Audit Log"]
if role == "Admin":
    pages += ["User Management"]
pages += ["User Settings", "Logout"]
page = st.sidebar.selectbox("Select Section", pages)

def require_role(roles):
    if role not in roles:
        st.error("Access denied")
        st.stop()

# ---------------------------
# Students Section
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
            if not class_name.strip():
                st.error("Class name cannot be empty")
            else:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT name FROM classes")
                existing = [r["name"] for r in cur.fetchall()]
                is_dup, match = is_near_duplicate(class_name, existing)
                if is_dup:
                    st.error(f"Similar class exists: {match}")
                else:
                    try:
                        cur.execute("INSERT INTO classes (name) VALUES (%s)", (class_name.strip(),))
                        conn.commit()
                        st.success("Class added successfully")
                        log_action("add_class", class_name, user['username'])
                        safe_rerun()
                    except Exception as e:
                        st.error(f"Error adding class: {str(e)}")
                cur.close()
                conn.close()

    with tab_add:
        st.subheader("Add Student")
        conn = get_db_connection()
        classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
        conn.close()
        if classes.empty:
            st.info("No classes defined. Add classes first.")
        else:
            with st.form("add_student_form"):
                name = st.text_input("Full Name")
                age = st.number_input("Age", min_value=0, value=5)
                enrollment_date = st.date_input("Enrollment Date", date.today())
                class_name = st.selectbox("Class", classes["name"].tolist())
                class_id = classes[classes["name"] == class_name]["id"].iloc[0]
                student_type = st.selectbox("Type", ["New", "Returning"])
                registration_fee_paid = st.checkbox("Registration Fee Paid")
                add_student = st.form_submit_button("Add Student")
            if add_student:
                if not name.strip():
                    st.error("Name cannot be empty")
                else:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("SELECT normalized_name FROM students")
                    existing = [r["normalized_name"] for r in cur.fetchall()]
                    is_dup, match = is_near_duplicate(name, existing)
                    if is_dup:
                        st.error(f"Similar student exists: {match}")
                    else:
                        try:
                            normalized = normalize_text(name)
                            reg_paid = 1 if registration_fee_paid else 0
                            cur.execute("""
                                INSERT INTO students (name, normalized_name, age, enrollment_date, class_id, student_type, registration_fee_paid)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """, (name.strip(), normalized, age, enrollment_date, class_id, student_type, reg_paid))
                            conn.commit()
                            st.success("Student added successfully")
                            log_action("add_student", name, user['username'])
                            safe_rerun()
                        except Exception as e:
                            st.error(f"Error adding student: {str(e)}")
                    cur.close()
                    conn.close()

    with tab_edit:
        st.subheader("Edit Student")
        conn = get_db_connection()
        students = pd.read_sql("SELECT s.id, s.name, c.name as class_name FROM students s JOIN classes c ON s.class_id = c.id ORDER BY s.name", conn)
        if students.empty:
            st.info("No students to edit")
        else:
            selected = st.selectbox("Select Student", students.apply(lambda x: f"{x['name']} - {x['class_name']} (ID: {x['id']})", axis=1), key="edit_student_select")
            student_id = int(selected.split("(ID: ")[1].replace(")", ""))
            cur = conn.cursor()
            cur.execute("SELECT * FROM students WHERE id = %s", (student_id,))
            student = cur.fetchone()
            classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
            cur.close()
            conn.close()
            with st.form("edit_student_form"):
                name = st.text_input("Full Name", value=student["name"])
                age = st.number_input("Age", min_value=0, value=student["age"])
                enrollment_date = st.date_input("Enrollment Date", value=student["enrollment_date"])
                class_name = st.selectbox("Class", classes["name"].tolist(), index=classes[classes["id"] == student["class_id"]].index[0])
                class_id = classes[classes["name"] == class_name]["id"].iloc[0]
                student_type = st.selectbox("Type", ["New", "Returning"], index=0 if student["student_type"] == "New" else 1)
                registration_fee_paid = st.checkbox("Registration Fee Paid", value=bool(student["registration_fee_paid"]))
                edit_student = st.form_submit_button("Update Student")
            if edit_student:
                if not name.strip():
                    st.error("Name cannot be empty")
                else:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("SELECT normalized_name FROM students WHERE id != %s", (student_id,))
                    existing = [r["normalized_name"] for r in cur.fetchall()]
                    is_dup, match = is_near_duplicate(name, existing)
                    if is_dup:
                        st.error(f"Similar student exists: {match}")
                    else:
                        try:
                            normalized = normalize_text(name)
                            reg_paid = 1 if registration_fee_paid else 0
                            cur.execute("""
                                UPDATE students SET name = %s, normalized_name = %s, age = %s, enrollment_date = %s, class_id = %s, student_type = %s, registration_fee_paid = %s
                                WHERE id = %s
                            """, (name.strip(), normalized, age, enrollment_date, class_id, student_type, reg_paid, student_id))
                            conn.commit()
                            st.success("Student updated successfully")
                            log_action("edit_student", f"Updated student {student_id}", user['username'])
                            safe_rerun()
                        except Exception as e:
                            st.error(f"Error updating student: {str(e)}")
                    cur.close()
                    conn.close()

    with tab_delete:
        require_role(["Admin"])
        st.subheader("Delete Student")
        st.warning("This action is permanent and cannot be undone. Related records will remain in the system.")
        conn = get_db_connection()
        students = pd.read_sql("SELECT id, name FROM students ORDER BY name", conn)
        if students.empty:
            st.info("No students to delete")
        else:
            selected = st.selectbox("Select Student to Delete", students["name"].tolist(), key="del_student_select")
            student_id = students[students["name"] == selected]["id"].iloc[0]
            confirm = st.checkbox(f"Yes, permanently delete student {selected}")
            if confirm and st.button("Confirm Delete", type="primary"):
                try:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM students WHERE id = %s", (student_id,))
                    conn.commit()
                    st.success(f"Student {selected} deleted successfully")
                    log_action("delete_student", f"Deleted student {selected} (ID: {student_id})", user['username'])
                    safe_rerun()
                except Exception as e:
                    st.error(f"Error deleting student: {str(e)}")
        conn.close()

    with tab_view:
        st.subheader("All Students")
        conn = get_db_connection()
        students = pd.read_sql("""
            SELECT s.id, s.name, s.age, s.enrollment_date, c.name as class_name, s.student_type, 
                   CASE WHEN s.registration_fee_paid = 1 THEN 'Yes' ELSE 'No' END as reg_fee_paid
            FROM students s JOIN classes c ON s.class_id = c.id ORDER BY s.name
        """, conn)
        conn.close()
        if students.empty:
            st.info("No students registered")
        else:
            st.dataframe(students)
            excel_buf = BytesIO()
            students.to_excel(excel_buf, index=False)
            st.download_button("Download Excel", excel_buf.getvalue(), "students.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            pdf_buf = BytesIO()
            c = canvas.Canvas(pdf_buf, pagesize=landscape(letter))
            if os.path.exists(LOGO_FILENAME):
                img = ImageReader(LOGO_FILENAME)
                c.drawImage(img, 50, 500, width=100, height=100)
            c.drawString(160, 550, SCHOOL_NAME)
            c.drawString(160, 530, SCHOOL_ADDRESS)
            c.drawString(160, 510, SCHOOL_EMAIL)
            c.drawString(300, 480, "All Students Report")
            data = [students.columns.tolist()] + students.values.tolist()
            table_width = 700
            col_widths = [table_width / len(data[0]) for _ in data[0]]
            y = 450
            for row in data:
                x = 50
                for cell, width in zip(row, col_widths):
                    c.drawString(x, y, str(cell))
                    x += width
                y -= 20
                if y < 50:
                    c.showPage()
                    y = 550
            c.save()
            pdf_buf.seek(0)
            st.download_button("Download PDF", pdf_buf, "students.pdf", mime="application/pdf")

# ---------------------------
# Uniforms Section
# ---------------------------
if page == "Uniforms":
    st.header("Uniform Management")
    tab_categories, tab_inventory, tab_sales = st.tabs(["Categories", "Inventory", "Sales"])

    with tab_categories:
        st.subheader("Manage Uniform Categories")
        conn = get_db_connection()
        categories = pd.read_sql("SELECT id, category, gender, CASE WHEN is_shared = 1 THEN 'Yes' ELSE 'No' END as shared FROM uniform_categories ORDER BY category", conn)
        conn.close()
        if not categories.empty:
            st.dataframe(categories)
        with st.form("add_category_form"):
            category = st.text_input("Category Name")
            gender = st.selectbox("Gender", ["boys", "girls", "shared"])
            is_shared = 1 if gender == "shared" else 0
            add_category = st.form_submit_button("Add Category")
        if add_category:
            if not category.strip():
                st.error("Category name cannot be empty")
            else:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT normalized_category, category FROM uniform_categories")
                existing = [(r["normalized_category"], r["category"]) for r in cur.fetchall()]
                existing_norm = [ex[0] for ex in existing]
                is_dup, match = is_near_duplicate(category, existing_norm)
                if is_dup:
                    original = next(ex[1] for ex in existing if ex[0] == match)
                    st.error(f"Similar category exists: {original}")
                else:
                    try:
                        normalized = normalize_text(category)
                        cur.execute("""
                            INSERT INTO uniform_categories (category, normalized_category, gender, is_shared)
                            VALUES (%s, %s, %s, %s)
                        """, (category.strip(), normalized, gender, is_shared))
                        conn.commit()
                        cur.execute("SELECT currval('uniform_categories_id_seq') AS cat_id")
                        row = cur.fetchone()
                        cat_id = row["cat_id"]
                        cur.execute("INSERT INTO uniforms (category_id) VALUES (%s)", (cat_id,))
                        conn.commit()
                        st.success("Category added successfully")
                        log_action("add_uniform_category", category, user['username'])
                        safe_rerun()
                    except Exception as e:
                        st.error(f"Error adding category: {str(e)}")
                cur.close()
                conn.close()

    with tab_inventory:
        st.subheader("Update Inventory")
        conn = get_db_connection()
        uniforms = pd.read_sql("""
            SELECT u.id, uc.category, u.stock, u.unit_price 
            FROM uniforms u JOIN uniform_categories uc ON u.category_id = uc.id ORDER BY uc.category
        """, conn)
        conn.close()
        if uniforms.empty:
            st.info("No categories defined")
        else:
            selected_cat = st.selectbox("Select Category", uniforms["category"].tolist())
            uniform_row = uniforms[uniforms["category"] == selected_cat].iloc[0]
            with st.form("update_inventory_form"):
                stock = st.number_input("Stock", min_value=0, value=int(uniform_row["stock"]))
                unit_price = st.number_input("Unit Price (USh)", min_value=0.0, value=float(uniform_row["unit_price"]), step=100.0)
                update_inv = st.form_submit_button("Update")
            if update_inv:
                conn = get_db_connection()
                cur = conn.cursor()
                try:
                    cur.execute("UPDATE uniforms SET stock = %s, unit_price = %s WHERE id = %s", (stock, unit_price, uniform_row["id"]))
                    conn.commit()
                    st.success("Inventory updated successfully")
                    log_action("update_uniform_inventory", f"{selected_cat} stock to {stock}, price to {unit_price}", user['username'])
                    safe_rerun()
                except Exception as e:
                    st.error(f"Error updating inventory: {str(e)}")
                cur.close()
                conn.close()
            st.dataframe(uniforms)

    with tab_sales:
        st.subheader("Record Uniform Sale")
        conn = get_db_connection()
        students = pd.read_sql("SELECT id, name FROM students ORDER BY name", conn)
        uniforms = pd.read_sql("""
            SELECT u.id, uc.category, u.stock, u.unit_price 
            FROM uniforms u JOIN uniform_categories uc ON u.category_id = uc.id WHERE u.stock > 0 ORDER BY uc.category
        """, conn)
        conn.close()
        if students.empty or uniforms.empty:
            st.info("No students or stock available")
        else:
            with st.form("sale_form"):
                student_name = st.selectbox("Student", students["name"].tolist())
                student_id = students[students["name"] == student_name]["id"].iloc[0]
                category = st.selectbox("Uniform Category", uniforms["category"].tolist())
                uniform_row = uniforms[uniforms["category"] == category].iloc[0]
                quantity = st.number_input("Quantity", min_value=1, max_value=int(uniform_row["stock"]), value=1)
                amount = quantity * float(uniform_row["unit_price"])
                payment_method = st.selectbox("Payment Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
                description = st.text_area("Description")
                sale_date = st.date_input("Sale Date", date.today())
                record_sale = st.form_submit_button("Record Sale")
            if record_sale:
                if quantity > uniform_row["stock"]:
                    st.error("Insufficient stock")
                else:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    try:
                        receipt_no = generate_receipt_number()
                        cur.execute("""
                            INSERT INTO incomes (date, receipt_number, amount, source, category_id, description, payment_method, payer, student_id, received_by, created_by)
                            VALUES (%s, %s, %s, 'Uniform Sale', (SELECT id FROM expense_categories WHERE name = 'Uniform Sales' LIMIT 1), %s, %s, %s, %s, %s, %s)
                        """, (sale_date, receipt_no, amount, f"Sold {quantity} {category}", payment_method, student_name, student_id, user['username'], user['username']))
                        cur.execute("UPDATE uniforms SET stock = stock - %s WHERE id = %s", (quantity, uniform_row["id"]))
                        conn.commit()
                        st.success(f"Sale recorded successfully. Receipt: {receipt_no}")
                        log_action("uniform_sale", f"{student_name} bought {category} x{quantity}", user['username'])
                        safe_rerun()
                    except Exception as e:
                        conn.rollback()
                        st.error(f"Error recording sale: {str(e)}")
                    cur.close()
                    conn.close()

# ---------------------------
# Finances Section
# ---------------------------
if page == "Finances":
    st.header("Finance Management")
    tab_incomes, tab_expenses, tab_cashbook, tab_fees, tab_generate, tab_edit_inv, tab_delete_inv = st.tabs(["Incomes", "Expenses", "Cashbook", "Fee Structures", "Generate Invoice", "Edit Invoice", "Delete Invoice"])

    with tab_incomes:
        st.subheader("Record Income")
        conn = get_db_connection()
        categories = pd.read_sql("SELECT id, name FROM expense_categories WHERE category_type = 'Income' ORDER BY name", conn)
        students = pd.read_sql("SELECT id, name FROM students ORDER BY name", conn)
        conn.close()
        with st.form("income_form"):
            date_val = st.date_input("Date", date.today())
            amount = st.number_input("Amount (USh)", min_value=0.0, step=1000.0)
            category_name = st.selectbox("Category", categories["name"].tolist())
            category_id = categories[categories["name"] == category_name]["id"].iloc[0]
            source = st.text_input("Source")
            payer = st.text_input("Payer")
            student_name = st.selectbox("Associated Student (optional)", ["None"] + students["name"].tolist())
            student_id = None if student_name == "None" else students[students["name"] == student_name]["id"].iloc[0]
            payment_method = st.selectbox("Payment Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
            description = st.text_area("Description")
            attachment = st.file_uploader("Attachment (optional)", type=["pdf", "jpg", "png"])
            record_income = st.form_submit_button("Record Income")
        if record_income:
            attachment_path = None
            if attachment:
                os.makedirs("attachments", exist_ok=True)
                attachment_path = f"attachments/{attachment.name}"
                with open(attachment_path, "wb") as f:
                    f.write(attachment.getbuffer())
            conn = get_db_connection()
            cur = conn.cursor()
            try:
                receipt_no = generate_receipt_number()
                cur.execute("""
                    INSERT INTO incomes (date, receipt_number, amount, source, category_id, description, payment_method, payer, student_id, attachment_path, received_by, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (date_val, receipt_no, amount, source, category_id, description, payment_method, payer, student_id, attachment_path, user['username'], user['username']))
                conn.commit()
                st.success(f"Income recorded successfully. Receipt: {receipt_no}")
                log_action("record_income", f"{amount} from {payer}", user['username'])
                safe_rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Error recording income: {str(e)}")
            cur.close()
            conn.close()

    with tab_expenses:
        require_role(["Admin", "Accountant"])
        st.subheader("Record Expense")
        conn = get_db_connection()
        categories = pd.read_sql("SELECT id, name FROM expense_categories WHERE category_type = 'Expense' ORDER BY name", conn)
        conn.close()
        with st.form("expense_form"):
            date_val = st.date_input("Date", date.today())
            amount = st.number_input("Amount (USh)", min_value=0.0, step=1000.0)
            category_name = st.selectbox("Category", categories["name"].tolist())
            category_id = categories[categories["name"] == category_name]["id"].iloc[0]
            payee = st.text_input("Payee")
            payment_method = st.selectbox("Payment Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
            description = st.text_area("Description")
            attachment = st.file_uploader("Attachment (optional)", type=["pdf", "jpg", "png"])
            record_expense = st.form_submit_button("Record Expense")
        if record_expense:
            attachment_path = None
            if attachment:
                os.makedirs("attachments", exist_ok=True)
                attachment_path = f"attachments/{attachment.name}"
                with open(attachment_path, "wb") as f:
                    f.write(attachment.getbuffer())
            conn = get_db_connection()
            cur = conn.cursor()
            try:
                voucher_no = generate_voucher_number()
                cur.execute("""
                    INSERT INTO expenses (date, voucher_number, amount, category_id, description, payment_method, payee, attachment_path, approved_by, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (date_val, voucher_no, amount, category_id, description, payment_method, payee, attachment_path, user['username'], user['username']))
                conn.commit()
                st.success(f"Expense recorded successfully. Voucher: {voucher_no}")
                log_action("record_expense", f"{amount} to {payee}", user['username'])
                safe_rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Error recording expense: {str(e)}")
            cur.close()
            conn.close()

    with tab_cashbook:
        st.subheader("Cashbook View")
        start_date = st.date_input("Start Date", date.today().replace(month=1, day=1))
        end_date = st.date_input("End Date", date.today())
        conn = get_db_connection()
        incomes = pd.read_sql("""
            SELECT date, receipt_number as ref, payer as entity, description, amount as income, 0 as expense 
            FROM incomes WHERE date BETWEEN %s AND %s ORDER BY date
        """, conn, params=(start_date, end_date))
        expenses = pd.read_sql("""
            SELECT date, voucher_number as ref, payee as entity, description, 0 as income, amount as expense 
            FROM expenses WHERE date BETWEEN %s AND %s ORDER BY date
        """, conn, params=(start_date, end_date))
        conn.close()
        cashbook = pd.concat([incomes, expenses]).sort_values("date").reset_index(drop=True)
        cashbook["balance"] = (cashbook["income"] - cashbook["expense"]).cumsum()
        st.dataframe(cashbook)
        excel_buf = BytesIO()
        cashbook.to_excel(excel_buf, index=False)
        st.download_button("Download Excel", excel_buf.getvalue(), "cashbook.xlsx")
        pdf_buf = BytesIO()
        c = canvas.Canvas(pdf_buf, pagesize=landscape(letter))
        if os.path.exists(LOGO_FILENAME):
            img = ImageReader(LOGO_FILENAME)
            c.drawImage(img, 50, 500, width=100, height=100)
        c.drawString(160, 550, SCHOOL_NAME)
        c.drawString(160, 530, f"Cashbook from {start_date} to {end_date}")
        data = [cashbook.columns.tolist()] + cashbook.values.tolist()
        table_width = 700
        col_widths = [table_width / len(data[0]) for _ in data[0]]
        y = 450
        for row in data:
            x = 50
            for cell, width in zip(row, col_widths):
                c.drawString(x, y, str(cell))
                x += width
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
            st.info("No classes defined")
        else:
            with st.form("fee_structure_form"):
                class_name = st.selectbox("Class", classes["name"].tolist())
                class_id = classes[classes["name"] == class_name]["id"].iloc[0]
                term = st.selectbox("Term", ["Term 1", "Term 2", "Term 3"])
                academic_year = st.text_input("Academic Year (e.g., 2025/2026)")
                tuition_fee = st.number_input("Tuition Fee", min_value=0.0, value=0.0, step=100.0)
                uniform_fee = st.number_input("Uniform Fee", min_value=0.0, value=0.0, step=100.0)
                activity_fee = st.number_input("Activity Fee", min_value=0.0, value=0.0, step=100.0)
                exam_fee = st.number_input("Exam Fee", min_value=0.0, value=0.0, step=100.0)
                library_fee = st.number_input("Library Fee", min_value=0.0, value=0.0, step=100.0)
                other_fee = st.number_input("Other Fee", min_value=0.0, value=0.0, step=100.0)
                create_fee = st.form_submit_button("Create/Update Fee Structure")
            if create_fee:
                total_fee = tuition_fee + uniform_fee + activity_fee + exam_fee + library_fee + other_fee
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("""
                    SELECT id FROM fee_structure WHERE class_id = %s AND term = %s AND academic_year = %s
                """, (class_id, term, academic_year))
                existing = cur.fetchone()
                if existing:
                    cur.execute("""
                        UPDATE fee_structure SET tuition_fee = %s, uniform_fee = %s, activity_fee = %s, exam_fee = %s, library_fee = %s, other_fee = %s, total_fee = %s
                        WHERE id = %s
                    """, (tuition_fee, uniform_fee, activity_fee, exam_fee, library_fee, other_fee, total_fee, existing["id"]))
                    conn.commit()
                    st.success("Fee structure updated successfully")
                    log_action("update_fee_structure", f"Updated for {class_name} {term} {academic_year}", user['username'])
                    safe_rerun()
                else:
                    cur.execute("""
                        INSERT INTO fee_structure (class_id, term, academic_year, tuition_fee, uniform_fee, activity_fee, exam_fee, library_fee, other_fee, total_fee)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (class_id, term, academic_year, tuition_fee, uniform_fee, activity_fee, exam_fee, library_fee, other_fee, total_fee))
                    conn.commit()
                    st.success("Fee structure created successfully")
                    log_action("create_fee_structure", f"Created for {class_name} {term} {academic_year}", user['username'])
                    safe_rerun()
                cur.close()
                conn.close()

    with tab_generate:
        st.subheader("Generate Invoice")
        conn = get_db_connection()
        students = pd.read_sql("SELECT s.id, s.name, c.name as class_name FROM students s JOIN classes c ON s.class_id = c.id ORDER BY s.name", conn)
        if students.empty:
            st.info("No students to invoice")
        else:
            selected = st.selectbox("Select Student", students.apply(lambda x: f"{x['name']} - {x['class_name']} (ID: {x['id']})", axis=1), key="select_student_inv")
            student_id = int(selected.split("(ID: ")[1].replace(")", ""))
            fee_options = pd.read_sql("SELECT fs.id, fs.term, fs.academic_year, fs.total_fee FROM fee_structure fs WHERE class_id = (SELECT class_id FROM students WHERE id = %s) ORDER BY academic_year DESC", conn, params=(student_id,))
            if fee_options.empty:
                st.info("No fee structure for this student's class")
            else:
                chosen = st.selectbox("Choose Fee Structure", fee_options.apply(lambda x: f"{x['academic_year']} - {x['term']} (USh {x['total_fee']:,.0f})", axis=1), key="select_fee_inv")
                fee_row = fee_options[fee_options.apply(lambda x: f"{x['academic_year']} - {x['term']} (USh {x['total_fee']:,.0f})", axis=1) == chosen].iloc[0]
                issue_date = st.date_input("Issue Date", date.today())
                due_date = st.date_input("Due Date", date.today())
                notes = st.text_area("Notes")
                if st.button("Create Invoice"):
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT id FROM invoices WHERE student_id = %s AND term = %s AND academic_year = %s
                    """, (student_id, fee_row['term'], fee_row['academic_year']))
                    existing = cur.fetchone()
                    if existing:
                        st.error("Invoice already exists for this student, term, and year")
                    else:
                        inv_no = generate_invoice_number()
                        total_amount = float(fee_row['total_fee'])
                        balance = total_amount
                        cur.execute("""
                            INSERT INTO invoices (invoice_number, student_id, issue_date, due_date, academic_year, term, total_amount, balance_amount, notes, created_by)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (inv_no, student_id, issue_date, due_date, fee_row['academic_year'], fee_row['term'], total_amount, balance, notes, user['username']))
                        conn.commit()
                        st.success(f"Invoice {inv_no} created successfully for USh {total_amount:,.0f}")
                        log_action("create_invoice", f"{inv_no} for student {student_id}", user['username'])
                        safe_rerun()
                    cur.close()
        conn.close()

    with tab_edit_inv:
        st.subheader("Edit Invoice")
        conn = get_db_connection()
        invoices = pd.read_sql("SELECT i.id, i.invoice_number, s.name as student_name FROM invoices i JOIN students s ON i.student_id = s.id ORDER BY i.issue_date DESC", conn)
        if invoices.empty:
            st.info("No invoices available to edit")
        else:
            selected_inv = st.selectbox("Select Invoice", invoices["invoice_number"].tolist(), key="edit_inv_select")
            cur = conn.cursor()
            cur.execute("SELECT * FROM invoices WHERE invoice_number = %s", (selected_inv,))
            inv_row = cur.fetchone()
            cur.close()
            with st.form("edit_invoice_form"):
                issue_date = st.date_input("Issue Date", value=inv_row["issue_date"])
                due_date = st.date_input("Due Date", value=inv_row["due_date"])
                total_amount = st.number_input("Total Amount (USh)", min_value=0.0, value=float(inv_row["total_amount"]), step=1000.0)
                notes = st.text_area("Notes", value=inv_row["notes"] or "")
                submit_edit = st.form_submit_button("Update Invoice")
            if submit_edit:
                try:
                    new_balance = total_amount - float(inv_row["paid_amount"] or 0)
                    new_status = 'Fully Paid' if new_balance <= 0 else 'Partially Paid' if inv_row["paid_amount"] > 0 else 'Pending'
                    cur = conn.cursor()
                    cur.execute("""
                        UPDATE invoices 
                        SET issue_date = %s, due_date = %s, total_amount = %s, balance_amount = %s, status = %s, notes = %s
                        WHERE id = %s
                    """, (issue_date, due_date, total_amount, new_balance, new_status, notes, inv_row["id"]))
                    conn.commit()
                    st.success("Invoice updated successfully")
                    log_action("edit_invoice", f"Updated invoice {selected_inv} to {total_amount}", user['username'])
                    safe_rerun()
                except Exception as e:
                    st.error(f"Error updating invoice: {str(e)}")
        conn.close()

    with tab_delete_inv:
        require_role(["Admin"])
        st.subheader("Delete Invoice")
        st.warning("This action is permanent and cannot be undone. Related payments will remain in the system.")
        conn = get_db_connection()
        invoices = pd.read_sql("SELECT id, invoice_number FROM invoices ORDER BY issue_date DESC", conn)
        if invoices.empty:
            st.info("No invoices to delete")
        else:
            selected_inv = st.selectbox("Select Invoice to Delete", invoices["invoice_number"].tolist(), key="del_inv_select")
            inv_id = invoices[invoices["invoice_number"] == selected_inv]["id"].iloc[0]
            confirm = st.checkbox(f"Yes, permanently delete invoice {selected_inv}")
            if confirm and st.button("Confirm Delete", type="primary"):
                try:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM invoices WHERE id = %s", (inv_id,))
                    conn.commit()
                    st.success(f"Invoice {selected_inv} deleted successfully")
                    log_action("delete_invoice", f"Deleted invoice {selected_inv} (ID: {inv_id})", user['username'])
                    safe_rerun()
                except Exception as e:
                    st.error(f"Error deleting invoice: {str(e)}")
        conn.close()

# ---------------------------
# Reports Section
# ---------------------------
if page == "Reports":
    st.header("Reports")
    tab_student_statements, tab_overall = st.tabs(["Student Fee Statements", "Overall Reports"])

    with tab_student_statements:
        st.subheader("Student Fee Statements")
        conn = get_db_connection()
        students = pd.read_sql("SELECT id, name FROM students ORDER BY name", conn)
        if students.empty:
            st.info("No students")
        else:
            selected_student = st.selectbox("Select Student", students["name"].tolist())
            student_id = students[students["name"] == selected_student]["id"].iloc[0]
            invoices = pd.read_sql("SELECT * FROM invoices WHERE student_id = %s ORDER BY issue_date DESC", conn, params=(student_id,))
            payments = pd.read_sql("SELECT * FROM payments WHERE invoice_id IN (SELECT id FROM invoices WHERE student_id = %s) ORDER BY payment_date", conn, params=(student_id,))
            if invoices.empty:
                st.info("No invoices for this student")
            else:
                for _, inv in invoices.iterrows():
                    st.markdown(f"### Invoice {inv['invoice_number']} - {inv['term']} {inv['academic_year']}")
                    st.write(f"Total: USh {inv['total_amount']:,.0f} | Paid: USh {inv['paid_amount']:,.0f} | Balance: USh {inv['balance_amount']:,.0f} | Status: {inv['status']}")
                    inv_payments = payments[payments["invoice_id"] == inv["id"]]
                    if not inv_payments.empty:
                        st.dataframe(inv_payments[["payment_date", "receipt_number", "amount", "payment_method"]])
                    with st.form(f"pay_{inv['id']}"):
                        amount = st.number_input("Payment Amount", min_value=0.0, max_value=float(inv["balance_amount"]), step=1000.0)
                        payment_method = st.selectbox("Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
                        reference = st.text_input("Reference")
                        notes = st.text_area("Notes")
                        pay = st.form_submit_button("Record Payment")
                    if pay:
                        if amount <= 0:
                            st.error("Amount must be positive")
                        elif amount > inv["balance_amount"]:
                            st.error("Amount exceeds balance")
                        else:
                            try:
                                cur = conn.cursor()
                                receipt_no = generate_receipt_number()
                                new_paid = float(inv["paid_amount"]) + amount
                                new_balance = float(inv["total_amount"]) - new_paid
                                new_status = "Fully Paid" if new_balance <= 0 else "Partially Paid"
                                cur.execute("""
                                    INSERT INTO payments (invoice_id, receipt_number, payment_date, amount, payment_method, reference_number, received_by, notes, created_by)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """, (inv["id"], receipt_no, date.today(), amount, payment_method, reference, user['username'], notes, user['username']))
                                cur.execute("""
                                    UPDATE invoices SET paid_amount = %s, balance_amount = %s, status = %s WHERE id = %s
                                """, (new_paid, new_balance, new_status, inv["id"]))
                                conn.commit()
                                st.success(f"Payment recorded. Receipt: {receipt_no}")
                                log_action("record_payment", f"{amount} for invoice {inv['invoice_number']}", user['username'])
                                safe_rerun()
                            except Exception as e:
                                conn.rollback()
                                st.error(f"Error recording payment: {str(e)}")
        conn.close()

    with tab_overall:
        st.subheader("Overall Financial Reports")
        conn = get_db_connection()
        incomes = pd.read_sql("SELECT * FROM incomes ORDER BY date DESC", conn)
        expenses = pd.read_sql("SELECT * FROM expenses ORDER BY date DESC", conn)
        conn.close()
        st.markdown("### Incomes")
        st.dataframe(incomes)
        st.markdown("### Expenses")
        st.dataframe(expenses)
        excel_buf = BytesIO()
        with pd.ExcelWriter(excel_buf, engine="xlsxwriter") as writer:
            incomes.to_excel(writer, sheet_name="Incomes", index=False)
            expenses.to_excel(writer, sheet_name="Expenses", index=False)
        st.download_button("Download Excel Report", excel_buf.getvalue(), "financial_report.xlsx")

# ---------------------------
# Staff Section
# ---------------------------
if page == "Staff":
    st.header("Staff Management")
    tab_add, tab_trans, tab_view = st.tabs(["Add Staff", "Transactions", "View Staff"])

    with tab_add:
        st.subheader("Add Staff")
        with st.form("add_staff_form"):
            name = st.text_input("Full Name")
            staff_type = st.selectbox("Type", ["Teaching", "Non-Teaching"])
            position = st.text_input("Position")
            hire_date = st.date_input("Hire Date", date.today())
            add_staff = st.form_submit_button("Add Staff")
        if add_staff:
            if not name.strip():
                st.error("Name cannot be empty")
            else:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT normalized_name, name FROM staff")
                existing = [(r["normalized_name"], r["name"]) for r in cur.fetchall()]
                existing_norm = [ex[0] for ex in existing]
                is_dup, match = is_near_duplicate(name, existing_norm)
                if is_dup:
                    original = next(ex[1] for ex in existing if ex[0] == match)
                    st.error(f"Similar staff exists: {original}")
                else:
                    try:
                        normalized = normalize_text(name)
                        cur.execute("""
                            INSERT INTO staff (name, normalized_name, staff_type, position, hire_date)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (name.strip(), normalized, staff_type, position, hire_date))
                        conn.commit()
                        st.success("Staff added successfully")
                        log_action("add_staff", name, user['username'])
                        safe_rerun()
                    except Exception as e:
                        st.error(f"Error adding staff: {str(e)}")
                cur.close()
                conn.close()

    with tab_trans:
        st.subheader("Staff Transactions")
        conn = get_db_connection()
        staff = pd.read_sql("SELECT id, name FROM staff ORDER BY name", conn)
        conn.close()
        if staff.empty:
            st.info("No staff")
        else:
            selected_staff = st.selectbox("Select Staff", staff["name"].tolist())
            staff_id = staff[staff["name"] == selected_staff]["id"].iloc[0]
            with st.form("staff_trans_form"):
                date_val = st.date_input("Date", date.today())
                trans_type = st.selectbox("Type", ["Salary", "Allowance", "Advance", "Other"])
                amount = st.number_input("Amount", min_value=0.0, step=1000.0)
                description = st.text_area("Description")
                payment_method = st.selectbox("Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
                record_trans = st.form_submit_button("Record Transaction")
            if record_trans:
                conn = get_db_connection()
                cur = conn.cursor()
                try:
                    voucher_no = generate_voucher_number()
                    cur.execute("""
                        INSERT INTO staff_transactions (staff_id, date, transaction_type, amount, description, payment_method, voucher_number, approved_by, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (staff_id, date_val, trans_type, amount, description, payment_method, voucher_no, user['username'], user['username']))
                    conn.commit()
                    st.success("Transaction recorded successfully")
                    log_action("staff_transaction", f"{trans_type} {amount} for {selected_staff}", user['username'])
                    safe_rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"Error recording transaction: {str(e)}")
                cur.close()
                conn.close()

    with tab_view:
        st.subheader("All Staff")
        conn = get_db_connection()
        staff = pd.read_sql("SELECT id, name, staff_type, position, hire_date FROM staff ORDER BY name", conn)
        conn.close()
        if staff.empty:
            st.info("No staff")
        else:
            st.dataframe(staff)

# ---------------------------
# Audit Log
# ---------------------------
if page == "Audit Log":
    require_role(["Admin"])
    st.header("Audit Log")
    conn = get_db_connection()
    logs = pd.read_sql("SELECT * FROM audit_log ORDER BY performed_at DESC LIMIT 500", conn)
    conn.close()
    st.dataframe(logs)

# ---------------------------
# User Management
# ---------------------------
if page == "User Management":
    require_role(["Admin"])
    st.header("User Management")
    tab_add, tab_view = st.tabs(["Add User", "View Users"])

    with tab_add:
        st.subheader("Add User")
        with st.form("add_user_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            role = st.selectbox("Role", ["Admin", "Accountant", "Clerk"])
            full_name = st.text_input("Full Name")
            add_user = st.form_submit_button("Add User")
        if add_user:
            if not username.strip() or not password:
                st.error("Username and password required")
            else:
                conn = get_db_connection()
                cur = conn.cursor()
                try:
                    cur.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (%s, %s, %s, %s)", (username.strip(), hash_password(password), role, full_name))
                    conn.commit()
                    st.success("User added successfully")
                    log_action("add_user", username, user['username'])
                    safe_rerun()
                except Exception as e:
                    st.error(f"Error adding user: {str(e)}")
                cur.close()
                conn.close()

    with tab_view:
        st.subheader("All Users")
        conn = get_db_connection()
        users = pd.read_sql("SELECT id, username, role, full_name, created_at FROM users ORDER BY username", conn)
        conn.close()
        st.dataframe(users)

# ---------------------------
# User Settings
# ---------------------------
if page == "User Settings":
    st.header("User Settings")
    st.markdown("Manage your account preferences and security.")

    conn = get_db_connection()
    user = st.session_state.user
    user_id = user["id"]
    current_username = user["username"]
    current_full_name = user.get("full_name", current_username)

    tab_profile, tab_password = st.tabs(["Profile", "Change Password"])

    with tab_profile:
        st.subheader("Update Profile")
        with st.form("update_profile_form"):
            new_full_name = st.text_input("Full Name / Display Name", value=current_full_name)
            submit_profile = st.form_submit_button("Save Profile Changes")

        if submit_profile:
            if not new_full_name.strip():
                st.error("Full name cannot be empty")
            else:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE users SET full_name = %s WHERE id = %s",
                        (new_full_name.strip(), user_id)
                    )
                    conn.commit()
                    st.session_state.user["full_name"] = new_full_name.strip()
                    st.success("Profile updated successfully")
                    log_action("update_profile", f"Changed full name to {new_full_name}", current_username)
                    safe_rerun()
                except Exception as e:
                    st.error(f"Error updating profile: {str(e)}")

    with tab_password:
        st.subheader("Change Password")
        with st.form("change_password_form"):
            current_password = st.text_input("Current Password", type="password")
            new_password = st.text_input("New Password", type="password")
            confirm_password = st.text_input("Confirm New Password", type="password")

            submit_password = st.form_submit_button("Change Password")

        if submit_password:
            if not current_password or not new_password or not confirm_password:
                st.error("All password fields are required")
            elif new_password != confirm_password:
                st.error("New password and confirmation do not match")
            elif len(new_password) < 6:
                st.error("New password must be at least 6 characters long")
            else:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT password_hash FROM users WHERE id = %s",
                        (user_id,)
                    )
                    db_user = cur.fetchone()
                    if db_user and verify_password(db_user["password_hash"], current_password):
                        new_hash = hash_password(new_password)
                        cur.execute(
                            "UPDATE users SET password_hash = %s WHERE id = %s",
                            (new_hash, user_id)
                        )
                        conn.commit()
                        st.success("Password changed successfully! Please log in again with the new password.")
                        log_action("change_password", "Changed password", current_username)
                    else:
                        st.error("Current password is incorrect")
                except Exception as e:
                    st.error(f"Error changing password: {str(e)}")

    conn.close()
    st.markdown("---")
    st.caption("For security reasons, major account changes (role, username) can only be performed by an Administrator.")

# ---------------------------
# Logout
# ---------------------------
if page == "Logout":
    log_action("logout", "", user["username"])
    st.session_state.user = None
    safe_rerun()

# Footer
st.markdown("---")
st.caption(f"© COSNA School Management System • {datetime.now().year}")
st.caption("Developed for Cosna Daycare, Nursery, Day and Boarding Primary School Kiyinda-Mityana")
