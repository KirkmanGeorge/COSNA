import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import time
import random
import string

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

# ─── Database helpers ──────────────────────────────────────────────────
def get_db_connection():
    return sqlite3.connect('cosna_school.db', check_same_thread=False)

def generate_receipt_number(prefix="RCPT"):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{timestamp}-{random_chars}"

def generate_invoice_number(prefix="INV"):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{timestamp}-{random_chars}"

def generate_voucher_number(prefix="VCH"):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{timestamp}-{random_chars}"

# ─── Initialize database ───────────────────────────────────────────────
def initialize_database():
    conn = get_db_connection()
    cursor = conn.cursor()

    # expense_categories
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='expense_categories'")
    if cursor.fetchone():
        try:
            cursor.execute("SELECT category_type FROM expense_categories LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute('''
                CREATE TABLE expense_categories_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    name TEXT UNIQUE,
                    category_type TEXT DEFAULT 'Expense' CHECK(category_type IN ('Expense', 'Income'))
                )
            ''')
            cursor.execute("INSERT INTO expense_categories_new (name, category_type) SELECT name, 'Expense' FROM expense_categories")
            cursor.execute("DROP TABLE expense_categories")
            cursor.execute("ALTER TABLE expense_categories_new RENAME TO expense_categories")
            conn.commit()
    else:
        cursor.execute('''
            CREATE TABLE expense_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                name TEXT UNIQUE,
                category_type TEXT DEFAULT 'Expense' CHECK(category_type IN ('Expense', 'Income'))
            )
        ''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            name TEXT, 
            age INTEGER, 
            enrollment_date DATE, 
            class_id INTEGER,
            student_type TEXT DEFAULT 'Returning',
            registration_fee_paid BOOLEAN DEFAULT 0,
            FOREIGN KEY(class_id) REFERENCES classes(id)
        )
    ''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS uniform_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT UNIQUE, gender TEXT, is_shared INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS uniforms (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER UNIQUE, stock INTEGER DEFAULT 0, unit_price REAL DEFAULT 0.0, FOREIGN KEY(category_id) REFERENCES uniform_categories(id))''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            date DATE, 
            voucher_number TEXT UNIQUE,
            amount REAL, 
            category_id INTEGER,
            description TEXT,
            payment_method TEXT,
            payee TEXT,
            approved_by TEXT,
            FOREIGN KEY(category_id) REFERENCES expense_categories(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS incomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            date DATE, 
            receipt_number TEXT UNIQUE,
            amount REAL, 
            source TEXT,
            category_id INTEGER,
            description TEXT,
            payment_method TEXT,
            payer TEXT,
            student_id INTEGER DEFAULT NULL,
            received_by TEXT,
            FOREIGN KEY(student_id) REFERENCES students(id),
            FOREIGN KEY(category_id) REFERENCES expense_categories(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fee_structure (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER,
            term TEXT,
            academic_year TEXT,
            tuition_fee REAL DEFAULT 0,
            uniform_fee REAL DEFAULT 0,
            activity_fee REAL DEFAULT 0,
            exam_fee REAL DEFAULT 0,
            library_fee REAL DEFAULT 0,
            other_fee REAL DEFAULT 0,
            total_fee REAL DEFAULT 0,
            FOREIGN KEY(class_id) REFERENCES classes(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT UNIQUE,
            student_id INTEGER,
            issue_date DATE,
            due_date DATE,
            academic_year TEXT,
            term TEXT,
            total_amount REAL,
            paid_amount REAL DEFAULT 0,
            balance_amount REAL,
            status TEXT,
            notes TEXT,
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER,
            receipt_number TEXT UNIQUE,
            payment_date DATE,
            amount REAL,
            payment_method TEXT,
            reference_number TEXT,
            received_by TEXT,
            notes TEXT,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id)
        )
    ''')

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

    # Seed categories
    expense_seeds = [
        ('Medical', 'Expense'), ('Salaries', 'Expense'), ('Utilities', 'Expense'),
        ('Maintenance', 'Expense'), ('Supplies', 'Expense'), ('Transport', 'Expense'),
        ('Events', 'Expense'), ('Tuition Fees', 'Income'), ('Registration Fees', 'Income'),
        ('Uniform Sales', 'Income'), ('Donations', 'Income'), ('Other Income', 'Income')
    ]
    for cat, cat_type in expense_seeds:
        cursor.execute("SELECT id FROM expense_categories WHERE name = ?", (cat,))
        if not cursor.fetchone():
            try:
                cursor.execute("INSERT INTO expense_categories (name, category_type) VALUES (?, ?)", (cat, cat_type))
            except:
                cursor.execute("INSERT INTO expense_categories (name) VALUES (?)", (cat,))
            conn.commit()

    conn.commit()
    conn.close()

initialize_database()

# ─── Navigation ────────────────────────────────────────────────────────
page = st.sidebar.radio("Menu", ["Dashboard", "Students", "Uniforms", "Finances", "Financial Report", "Fee Management"])

if page == "Dashboard":
    conn = get_db_connection()
    st.header("Dashboard")
    st.write("Welcome to COSNA School Management")
    conn.close()

elif page == "Students":
    st.header("Students")
    st.write("Student management page - add/view students here")
    # Your full students code would go here...

elif page == "Uniforms":
    st.header("Uniforms")
    st.write("Uniform inventory & sales page")
    # Your uniforms code would go here...

elif page == "Finances":
    st.header("Finances")
    st.write("Income & expense recording page")
    # Your finances code would go here...

elif page == "Financial Report":
    st.header("Financial Report")
    st.write("Financial overview and reports")
    # Your report code would go here...

elif page == "Fee Management":
    st.header("🎓 Fee Management System")
    
    tab_structure, tab_invoices, tab_payments = st.tabs(["Fee Structure", "Generate Invoices", "Payment Records"])
    
    with tab_structure:
        st.subheader("Define Fee Structure")
        conn = get_db_connection()
        
        with st.form("fee_structure_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                try:
                    classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
                    if not classes.empty:
                        selected_class = st.selectbox("Class", classes["name"])
                        class_id = classes[classes["name"] == selected_class]["id"].iloc[0]
                    else:
                        st.warning("No classes defined yet.")
                        class_id = None
                except:
                    st.warning("Classes table not found.")
                    class_id = None
                
                term = st.selectbox("Term", ["Term 1", "Term 2", "Term 3"])
                academic_year = st.text_input("Academic Year", f"{datetime.today().year}/{datetime.today().year+1}")
            
            with col2:
                tuition_fee = st.number_input("Tuition Fee (USh)", value=0.0)
                uniform_fee = st.number_input("Uniform Fee (USh)", value=0.0)
                activity_fee = st.number_input("Activity Fee (USh)", value=0.0)
                exam_fee = st.number_input("Exam Fee (USh)", value=0.0)
                library_fee = st.number_input("Library Fee (USh)", value=0.0)
                other_fee = st.number_input("Other Fees (USh)", value=0.0)
            
            total_fee = tuition_fee + uniform_fee + activity_fee + exam_fee + library_fee + other_fee
            st.info(f"**Total Fee:** USh {total_fee:,.0f}")
            
            if st.form_submit_button("Save Fee Structure") and class_id:
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        INSERT INTO fee_structure 
                        (class_id, term, academic_year, tuition_fee, uniform_fee, activity_fee, 
                         exam_fee, library_fee, other_fee, total_fee)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (class_id, term, academic_year, tuition_fee, uniform_fee, activity_fee, 
                          exam_fee, library_fee, other_fee, total_fee))
                    conn.commit()
                    st.success("Fee structure saved!")
                except Exception as e:
                    st.error(f"Error: {e}")
        
        conn.close()

    with tab_invoices:
        st.subheader("Generate Student Invoices")
        conn = get_db_connection()
        
        with st.form("generate_invoice"):
            col1, col2 = st.columns(2)
            
            with col1:
                try:
                    classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
                    selected_class = st.selectbox("Class", classes["name"] if not classes.empty else ["No classes"])
                    class_id = classes[classes["name"] == selected_class]["id"].iloc[0] if not classes.empty else None
                except:
                    class_id = None
                    st.warning("Classes not loaded.")

            with col2:
                issue_date = st.date_input("Issue Date", datetime.today())
                due_date = st.date_input("Due Date", datetime.today())
                invoice_number = st.text_input("Invoice Number", value=generate_invoice_number())
                notes = st.text_area("Notes")
            
            # Student selection
            if class_id:
                students = pd.read_sql("SELECT id, name FROM students WHERE class_id = ? ORDER BY name", conn, params=(class_id,))
                if students.empty:
                    st.warning(f"No students in {selected_class}")
                    selected_students = []
                else:
                    selected_students = st.multiselect(
                        "Select Students",
                        students.apply(lambda x: f"{x['name']} (ID: {x['id']})", axis=1)
                    )
            else:
                selected_students = []
                st.info("Select a class to see students.")

            fee_amount = st.number_input("Fee per Student (USh)", min_value=0.0, step=1000.0)

            # Submit button - always visible
            if st.form_submit_button("Generate Invoices"):
                if not class_id:
                    st.error("Select a class first")
                elif fee_amount <= 0:
                    st.error("Enter a valid fee amount")
                elif not selected_students:
                    st.error("Select at least one student")
                else:
                    cursor = conn.cursor()
                    created = 0
                    previews = []
                    
                    for opt in selected_students:
                        sid = int(opt.split("(ID: ")[1][:-1])
                        name = opt.split(" (ID:")[0]
                        inv_num = f"{invoice_number}-{sid}"
                        
                        try:
                            cursor.execute("""
                                INSERT INTO invoices 
                                (invoice_number, student_id, issue_date, due_date, academic_year, term, 
                                 total_amount, paid_amount, balance_amount, status, notes)
                                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 'Pending', ?)
                            """, (inv_num, sid, issue_date, due_date, "2025/2026", "Term 1", fee_amount, fee_amount, notes))
                            created += 1
                            previews.append({
                                'Invoice': inv_num,
                                'Student': name,
                                'Amount': fee_amount,
                                'Issue': issue_date,
                                'Due': due_date
                            })
                        except Exception as e:
                            st.error(f"Failed for {name}: {e}")
                    
                    conn.commit()
                    
                    if created > 0:
                        st.success(f"Created {created} invoices")
                        with st.expander("Invoice Preview", expanded=True):
                            st.dataframe(pd.DataFrame(previews))
                    else:
                        st.warning("No invoices created")

        conn.close()

    with tab_payments:
        st.subheader("Payment Records")
        st.write("Payment history goes here...")

st.sidebar.info("Logged in as admin")
