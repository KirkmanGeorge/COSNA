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
    
    # expense_categories with category_type
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
    
    # Other tables (unchanged from your version)
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
            payment_method TEXT CHECK(payment_method IN ('Cash', 'Bank Transfer', 'Mobile Money', 'Cheque')),
            payee TEXT,
            attachment_path TEXT,
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
            payment_method TEXT CHECK(payment_method IN ('Cash', 'Bank Transfer', 'Mobile Money', 'Cheque')),
            payer TEXT,
            student_id INTEGER DEFAULT NULL,
            attachment_path TEXT,
            received_by TEXT,
            FOREIGN KEY(student_id) REFERENCES students(id),
            FOREIGN KEY(category_id) REFERENCES expense_categories(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fee_structure (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER,
            term TEXT CHECK(term IN ('Term 1', 'Term 2', 'Term 3')),
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
            status TEXT CHECK(status IN ('Pending', 'Partially Paid', 'Fully Paid', 'Overdue')),
            notes TEXT,
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER,
            description TEXT,
            amount REAL,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER,
            receipt_number TEXT UNIQUE,
            payment_date DATE,
            amount REAL,
            payment_method TEXT CHECK(payment_method IN ('Cash', 'Bank Transfer', 'Mobile Money', 'Cheque')),
            reference_number TEXT,
            received_by TEXT,
            notes TEXT,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id)
        )
    ''')
    
    conn.commit()

    # Seed data (your original seeds)
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

    expense_seeds = [
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
        ('Donations', 'Income'),
        ('Other Income', 'Income')
    ]
    for cat, cat_type in expense_seeds:
        cursor.execute("SELECT id FROM expense_categories WHERE name = ?", (cat,))
        if not cursor.fetchone():
            try:
                cursor.execute("INSERT INTO expense_categories (name, category_type) VALUES (?, ?)", (cat, cat_type))
                conn.commit()
            except:
                cursor.execute("INSERT INTO expense_categories (name) VALUES (?)", (cat,))
                conn.commit()

    conn.commit()
    conn.close()

initialize_database()

# ─── Navigation ────────────────────────────────────────────────────────
page = st.sidebar.radio("Menu", ["Dashboard", "Students", "Uniforms", "Finances", "Financial Report", "Fee Management"])

# [Your Dashboard, Students, Uniforms, Finances, Financial Report blocks remain exactly the same]
# I'm skipping pasting them here to save space — keep them unchanged from your current file

# ─── Fee Management (updated with fixes) ───────────────────────────────
elif page == "Fee Management":
    st.header("🎓 Fee Management System")
    
    tab_structure, tab_invoices, tab_payments = st.tabs(["Fee Structure", "Generate Invoices", "Payment Records"])
    
    with tab_structure:
        # Your existing fee structure code (unchanged)
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
                        st.warning("No classes defined yet. Please add classes first.")
                        selected_class = None
                        class_id = None
                except:
                    st.warning("No classes table found")
                    selected_class = None
                    class_id = None
                
                term = st.selectbox("Term", ["Term 1", "Term 2", "Term 3"])
                academic_year = st.text_input("Academic Year", f"{datetime.today().year}/{datetime.today().year+1}")
            
            with col2:
                tuition_fee = st.number_input("Tuition Fee (USh)", min_value=0.0, value=0.0)
                uniform_fee = st.number_input("Uniform Fee (USh)", min_value=0.0, value=0.0)
                activity_fee = st.number_input("Activity Fee (USh)", min_value=0.0, value=0.0)
                exam_fee = st.number_input("Exam Fee (USh)", min_value=0.0, value=0.0)
                library_fee = st.number_input("Library Fee (USh)", min_value=0.0, value=0.0)
                other_fee = st.number_input("Other Fees (USh)", min_value=0.0, value=0.0)
            
            total_fee = tuition_fee + uniform_fee + activity_fee + exam_fee + library_fee + other_fee
            st.info(f"**Total Fee:** USh {total_fee:,.0f}")
            
            if st.form_submit_button("💾 Save Fee Structure") and class_id is not None:
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
                    st.success("✅ Fee structure saved successfully!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Error saving fee structure: {e}")
        
        st.subheader("Existing Fee Structures")
        try:
            fee_structures = pd.read_sql("""
                SELECT fs.id, c.name as class, fs.term, fs.academic_year, 
                       fs.tuition_fee, fs.uniform_fee, fs.activity_fee, 
                       fs.exam_fee, fs.library_fee, fs.other_fee, fs.total_fee
                FROM fee_structure fs
                LEFT JOIN classes c ON fs.class_id = c.id
                ORDER BY fs.academic_year DESC, fs.term, c.name
            """, conn)
            
            if not fee_structures.empty:
                st.dataframe(fee_structures, width='stretch')
            else:
                st.info("No fee structures defined yet")
        except:
            st.info("Fee structure table not yet initialized or no data")
        
        conn.close()
    
    with tab_invoices:
        st.subheader("Generate Student Invoices")
        
        conn = get_db_connection()
        
        with st.form("generate_invoice"):
            col1, col2 = st.columns(2)
            
            with col1:
                try:
                    classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
                    if not classes.empty:
                        selected_class = st.selectbox("Class", classes["name"])
                        class_id = classes[classes["name"] == selected_class]["id"].iloc[0]
                    else:
                        st.warning("No classes defined yet")
                        selected_class = None
                        class_id = None
                except:
                    st.warning("No classes table found")
                    selected_class = None
                    class_id = None
            
            with col2:
                issue_date = st.date_input("Issue Date", datetime.today())
                due_date = st.date_input("Due Date", datetime.today())
                invoice_number = st.text_input("Invoice Number", value=generate_invoice_number())
                notes = st.text_area("Notes")
            
            # Students selection (always shown)
            if class_id:
                students = pd.read_sql("""
                    SELECT id, name FROM students 
                    WHERE class_id = ? 
                    ORDER BY name
                """, conn, params=(class_id,))
                
                if students.empty:
                    st.warning(f"No students found in {selected_class}")
                    selected_students = []
                else:
                    st.write(f"**Students in {selected_class}:** {len(students)} students")
                    selected_students = st.multiselect(
                        "Select Students to Invoice",
                        students.apply(lambda x: f"{x['name']} (ID: {x['id']})", axis=1),
                        default=students.apply(lambda x: f"{x['name']} (ID: {x['id']})", axis=1).tolist()
                    )
            else:
                st.info("Please select a class first")
                selected_students = []
            
            fee_amount = st.number_input("Fee Amount per Student (USh)", min_value=0.0, value=0.0, step=1000.0)
            
            # Submit button always visible
            submit_button = st.form_submit_button("📄 Generate Invoices", type="primary")
            
            if submit_button:
                if class_id is None:
                    st.error("❌ Please select a class first")
                elif fee_amount <= 0:
                    st.error("❌ Please enter a fee amount greater than 0")
                elif not selected_students:
                    st.error("❌ Please select at least one student")
                else:
                    cursor = conn.cursor()
                    invoices_created = 0
                    generated_invoices = []
                    
                    for student_option in selected_students:
                        student_id = int(student_option.split("(ID: ")[1].replace(")", ""))
                        student_name = student_option.split(" (ID:")[0]
                        
                        inv_num = f"{invoice_number}-{student_id}"
                        
                        try:
                            cursor.execute("""
                                INSERT INTO invoices 
                                (invoice_number, student_id, issue_date, due_date, academic_year, 
                                 term, total_amount, paid_amount, balance_amount, status, notes)
                                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 'Pending', ?)
                            """, (
                                inv_num,
                                student_id,
                                issue_date,
                                due_date,
                                f"{datetime.today().year}/{datetime.today().year+1}",
                                "Term 1",
                                fee_amount,
                                fee_amount,
                                notes
                            ))
                            invoices_created += 1
                            
                            generated_invoices.append({
                                'Invoice Number': inv_num,
                                'Student': student_name,
                                'Class': selected_class,
                                'Issue Date': issue_date.strftime("%Y-%m-%d"),
                                'Due Date': due_date.strftime("%Y-%m-%d"),
                                'Total Amount (USh)': fee_amount,
                                'Status': 'Pending'
                            })
                            
                        except Exception as e:
                            st.error(f"Error creating invoice for {student_name}: {e}")
                    
                    conn.commit()
                    
                    if invoices_created > 0:
                        st.success(f"✅ {invoices_created} invoices generated successfully!")
                        
                        with st.expander("📄 Preview Generated Invoices", expanded=True):
                            preview_df = pd.DataFrame(generated_invoices)
                            st.dataframe(preview_df, width='stretch')
                            
                            buf = BytesIO()
                            with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                                preview_df.to_excel(writer, sheet_name='Generated Invoices', index=False)
                            buf.seek(0)
                            st.download_button(
                                "📥 Download Preview as Excel",
                                buf,
                                f"preview_invoices_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            )
                        
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.warning("No invoices created — check errors above.")
        
        conn.close()
    
    with tab_payments:
        # Your existing payment records code (unchanged)
        st.subheader("Payment Records")
        
        conn = get_db_connection()
        
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", datetime(datetime.today().year, 1, 1), key="payment_start")
        with col2:
            end_date = st.date_input("End Date", datetime.today(), key="payment_end")
        
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='payments'")
            if cursor.fetchone():
                query = """
                    SELECT p.payment_date, p.receipt_number, p.amount, p.payment_method, 
                           p.reference_number, p.received_by, p.notes,
                           i.invoice_number
                    FROM payments p
                    LEFT JOIN invoices i ON p.invoice_id = i.id
                    WHERE p.payment_date BETWEEN ? AND ?
                    ORDER BY p.payment_date DESC
                """
                
                payment_records = pd.read_sql_query(query, conn, params=(start_date, end_date))
                
                if not payment_records.empty:
                    st.dataframe(payment_records, width='stretch')
                    
                    total_payments = payment_records['amount'].sum()
                    st.info(f"**Total Payments:** USh {total_payments:,.0f}")
                    
                    # Excel export
                    buf_excel = BytesIO()
                    with pd.ExcelWriter(buf_excel, engine='xlsxwriter') as writer:
                        payment_records.to_excel(writer, sheet_name='Payment Records', index=False)
                    buf_excel.seek(0)
                    st.download_button("📥 Download Excel", buf_excel, f"payments_{start_date}_{end_date}.xlsx",
                                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    
                    # PDF export (simple version)
                    pdf_buf = BytesIO()
                    pdf = canvas.Canvas(pdf_buf, pagesize=letter)
                    pdf.drawString(100, 750, "Payment Records Report")
                    pdf.drawString(100, 730, f"Period: {start_date} to {end_date}")
                    y = 680
                    for _, row in payment_records.head(20).iterrows():
                        pdf.drawString(100, y, f"{row['payment_date']} | {row['receipt_number']} | USh {row['amount']:,.0f} | {row['payment_method']}")
                        y -= 20
                        if y < 100:
                            pdf.showPage()
                            y = 750
                    pdf.save()
                    pdf_buf.seek(0)
                    st.download_button("📥 Download PDF", pdf_buf, f"payments_{start_date}_{end_date}.pdf", "application/pdf")
                else:
                    st.info("No payment records found")
            else:
                st.info("Payment table not yet created")
        except Exception as e:
            st.info(f"Error loading payments: {e}")
        
        conn.close()

st.sidebar.info("Logged in as admin – Professional Financial Management System")
