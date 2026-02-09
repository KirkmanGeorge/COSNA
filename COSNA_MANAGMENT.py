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

# ─── Database ──────────────────────────────────────────────────────────
def get_db_connection():
    """Create a new database connection for each query"""
    return sqlite3.connect('cosna_school.db', check_same_thread=False)

def generate_receipt_number(prefix="RCPT"):
    """Generate unique receipt number"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{timestamp}-{random_chars}"

def generate_invoice_number(prefix="INV"):
    """Generate unique invoice number"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{timestamp}-{random_chars}"

def generate_voucher_number(prefix="VCH"):
    """Generate unique voucher number"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{timestamp}-{random_chars}"

# ─── Initialize database ───────────────────────────────────────────────
def initialize_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # First, check if expense_categories table exists and get its structure
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='expense_categories'")
    table_exists = cursor.fetchone()
    
    if table_exists:
        # Check if category_type column exists
        try:
            cursor.execute("SELECT category_type FROM expense_categories LIMIT 1")
            category_type_exists = True
        except sqlite3.OperationalError:
            category_type_exists = False
        
        if not category_type_exists:
            # Create a new table with the correct structure
            cursor.execute('''
                CREATE TABLE expense_categories_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    name TEXT UNIQUE,
                    category_type TEXT DEFAULT 'Expense' CHECK(category_type IN ('Expense', 'Income'))
                )
            ''')
            
            # Copy existing data, defaulting category_type to 'Expense'
            cursor.execute("INSERT INTO expense_categories_new (name, category_type) SELECT name, 'Expense' FROM expense_categories")
            
            # Drop old table and rename new one
            cursor.execute("DROP TABLE expense_categories")
            cursor.execute("ALTER TABLE expense_categories_new RENAME TO expense_categories")
            conn.commit()
    else:
        # Create the table if it doesn't exist
        cursor.execute('''
            CREATE TABLE expense_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                name TEXT UNIQUE,
                category_type TEXT DEFAULT 'Expense' CHECK(category_type IN ('Expense', 'Income'))
            )
        ''')
    
    # Check and create other tables
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
    
    # Enhanced expenses table with voucher numbers
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
    
    # Enhanced incomes table with receipt numbers
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
    
    # Fee structure table
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
    
    # Student invoices table
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
    
    # Invoice items table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER,
            description TEXT,
            amount REAL,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id)
        )
    ''')
    
    # Payments table linking to invoices
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

    # Enhanced expense/income categories - only insert if they don't exist
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
            except sqlite3.IntegrityError:
                cursor.execute("INSERT INTO expense_categories (name) VALUES (?)", (cat,))
                conn.commit()
    
    # Check for existing columns and add if missing
    try:
        cursor.execute("SELECT receipt_number FROM incomes LIMIT 1")
    except sqlite3.OperationalError:
        try:
            cursor.execute("ALTER TABLE incomes ADD COLUMN receipt_number TEXT UNIQUE")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE incomes ADD COLUMN category_id INTEGER")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE incomes ADD COLUMN description TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE incomes ADD COLUMN payment_method TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE incomes ADD COLUMN payer TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE incomes ADD COLUMN attachment_path TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE incomes ADD COLUMN received_by TEXT")
        except:
            pass
    
    try:
        cursor.execute("SELECT voucher_number FROM expenses LIMIT 1")
    except sqlite3.OperationalError:
        try:
            cursor.execute("ALTER TABLE expenses ADD COLUMN voucher_number TEXT UNIQUE")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE expenses ADD COLUMN description TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE expenses ADD COLUMN payment_method TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE expenses ADD COLUMN payee TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE expenses ADD COLUMN attachment_path TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE expenses ADD COLUMN approved_by TEXT")
        except:
            pass
    
    # Add missing columns to old expenses table
    try:
        cursor.execute("SELECT category_id FROM expenses LIMIT 1")
    except sqlite3.OperationalError:
        try:
            cursor.execute("ALTER TABLE expenses ADD COLUMN category_id INTEGER")
        except:
            pass
    
    conn.commit()
    conn.close()

initialize_database()

# ─── Navigation ────────────────────────────────────────────────────────
page = st.sidebar.radio("Menu", ["Dashboard", "Students", "Uniforms", "Finances", "Financial Report", "Fee Management"])

# ─── Dashboard ─────────────────────────────────────────────────────────
if page == "Dashboard":
    conn = get_db_connection()
    st.header("📊 Financial Overview")
    
    col1, col2, col3, col4 = st.columns(4)
    
    # Total Income
    total_income = conn.execute("SELECT SUM(amount) FROM incomes").fetchone()[0] or 0
    col1.metric("Total Income", f"USh {total_income:,.0f}")
    
    # Total Expenses
    total_expenses = conn.execute("SELECT SUM(amount) FROM expenses").fetchone()[0] or 0
    col2.metric("Total Expenses", f"USh {total_expenses:,.0f}")
    
    # Net Balance
    net_balance = total_income - total_expenses
    col3.metric("Net Balance", f"USh {net_balance:,.0f}", delta=f"USh {net_balance:,.0f}")
    
    # Outstanding Fees
    try:
        outstanding_fees = conn.execute("SELECT SUM(balance_amount) FROM invoices WHERE status != 'Fully Paid'").fetchone()[0] or 0
    except:
        outstanding_fees = 0
    col4.metric("Outstanding Fees", f"USh {outstanding_fees:,.0f}")
    
    # Recent Transactions
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Recent Income (Last 5)")
        try:
            df_inc = pd.read_sql("""
                SELECT date, amount, source 
                FROM incomes 
                ORDER BY date DESC LIMIT 5
            """, conn)
            st.dataframe(df_inc, width='stretch')
        except:
            st.info("No income records yet")
    
    with col2:
        st.subheader("Recent Expenses (Last 5)")
        try:
            df_exp = pd.read_sql("""
                SELECT e.date, e.amount, ec.name as category
                FROM expenses e 
                LEFT JOIN expense_categories ec ON e.category_id = ec.id
                ORDER BY e.date DESC LIMIT 5
            """, conn)
            st.dataframe(df_exp, width='stretch')
        except:
            try:
                df_exp = pd.read_sql("SELECT date, amount FROM expenses ORDER BY date DESC LIMIT 5", conn)
                st.dataframe(df_exp, width='stretch')
            except:
                st.info("No expense records yet")
    
    # Monthly Summary
    st.subheader("Monthly Financial Summary")
    try:
        df_monthly = pd.read_sql("""
            SELECT 
                strftime('%Y-%m', date) as month,
                SUM(amount) as total_amount,
                'Income' as type
            FROM incomes
            GROUP BY strftime('%Y-%m', date)
            
            UNION ALL
            
            SELECT 
                strftime('%Y-%m', date) as month,
                SUM(amount) as total_amount,
                'Expense' as type
            FROM expenses
            GROUP BY strftime('%Y-%m', date)
            
            ORDER BY month DESC
            LIMIT 12
        """, conn)
        
        if not df_monthly.empty:
            # Pivot the data
            df_pivot = df_monthly.pivot_table(index='month', columns='type', values='total_amount', aggfunc='sum').fillna(0)
            df_pivot['Net Balance'] = df_pivot.get('Income', 0) - df_pivot.get('Expense', 0)
            st.dataframe(df_pivot, width='stretch')
        else:
            st.info("No financial data available")
    except:
        st.info("No monthly data available")
    
    conn.close()

# ─── Students ──────────────────────────────────────────────────────────
elif page == "Students":
    st.header("Students")
    
    tab_view, tab_add, tab_fees = st.tabs(["View & Export", "Add Student", "Student Fees"])
    
    with tab_view:
        conn = get_db_connection()
        try:
            classes = ["All Classes"] + pd.read_sql("SELECT name FROM classes ORDER BY name", conn)['name'].tolist()
        except:
            classes = ["All Classes"]
        
        selected_class = st.selectbox("Filter by Class", classes)
        
        student_types = ["All Types", "New", "Returning"]
        selected_type = st.selectbox("Filter by Student Type", student_types)

        try:
            # Check if student_type column exists
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(students)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'student_type' in columns:
                query = "SELECT s.id, s.name, s.age, s.enrollment_date, c.name AS class_name, s.student_type, s.registration_fee_paid FROM students s LEFT JOIN classes c ON s.class_id = c.id"
            else:
                query = "SELECT s.id, s.name, s.age, s.enrollment_date, c.name AS class_name FROM students s LEFT JOIN classes c ON s.class_id = c.id"
                
            conditions = []
            params = []
            
            if selected_class != "All Classes":
                conditions.append("c.name = ?")
                params.append(selected_class)
            
            if selected_type != "All Types" and 'student_type' in columns:
                conditions.append("s.student_type = ?")
                params.append(selected_type)
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
                
            df = pd.read_sql_query(query, conn, params=params)
            st.dataframe(df, width='stretch')

            if not df.empty:
                buf = BytesIO()
                with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                    df.to_excel(writer, sheet_name='Students', index=False)
                buf.seek(0)
                st.download_button("Download Filtered Students Excel", buf, "cosna_students.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e:
            st.info("No student records yet or error loading data")
        
        conn.close()

    with tab_add:
        conn = get_db_connection()
        with st.form("add_student"):
            col1, col2 = st.columns(2)
            
            with col1:
                name = st.text_input("Full Name")
                age = st.number_input("Age", 5, 30, 10)
                enroll_date = st.date_input("Enrollment Date", datetime.today())
                
            with col2:
                try:
                    cls_df = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
                    cls_name = st.selectbox("Class", cls_df["name"] if not cls_df.empty else ["No classes yet"])
                    cls_id = cls_df[cls_df["name"] == cls_name]["id"].iloc[0] if not cls_df.empty and cls_name != "No classes yet" else None
                except:
                    cls_df = pd.DataFrame(columns=['id', 'name'])
                    cls_name = "No classes yet"
                    cls_id = None
                
                student_type = st.radio("Student Type", ["New", "Returning"], horizontal=True)
                
                if student_type == "New":
                    st.info("Registration Fee: USh 50,000 (Mandatory for new students)")
                    registration_fee = 50000
                    registration_fee_paid = True
                else:
                    registration_fee = 0
                    registration_fee_paid = False
            
            if st.form_submit_button("Add Student") and name and cls_id is not None:
                cursor = conn.cursor()
                
                cursor.execute("PRAGMA table_info(students)")
                columns = [col[1] for col in cursor.fetchall()]
                
                if 'student_type' in columns and 'registration_fee_paid' in columns:
                    cursor.execute("INSERT INTO students (name, age, enrollment_date, class_id, student_type, registration_fee_paid) VALUES (?, ?, ?, ?, ?, ?)",
                                   (name, age, enroll_date, int(cls_id), student_type, registration_fee_paid))
                else:
                    cursor.execute("INSERT INTO students (name, age, enrollment_date, class_id) VALUES (?, ?, ?, ?)",
                                   (name, age, enroll_date, int(cls_id)))
                
                conn.commit()
                
                student_id = cursor.lastrowid
                
                if student_type == "New" and registration_fee > 0:
                    try:
                        cursor.execute("INSERT INTO incomes (date, receipt_number, amount, source, category_id, description, payment_method, payer, received_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                       (enroll_date, generate_receipt_number(), registration_fee, "Registration Fees", 
                                        9, f"Registration fee for {name}", "Cash", name, "Admin"))
                    except:
                        cursor.execute("INSERT INTO incomes (date, amount, source) VALUES (?, ?, ?)",
                                       (enroll_date, registration_fee, f"Registration fee for {name}"))
                    conn.commit()
                
                success_message = f"✅ Student added successfully!"
                if student_type == "New":
                    success_message += f"\n📝 Registration fee of USh {registration_fee:,.0f} recorded as income."
                
                st.success(success_message)
                conn.close()
                st.rerun()
        conn.close()

    with tab_fees:
        st.subheader("Student Fee Management")
        conn = get_db_connection()
        
        students = pd.read_sql("""
            SELECT s.id, s.name, c.name as class_name 
            FROM students s 
            LEFT JOIN classes c ON s.class_id = c.id 
            ORDER BY s.name
        """, conn)
        
        if not students.empty:
            selected_student = st.selectbox("Select Student", 
                students.apply(lambda x: f"{x['name']} - {x['class_name']} (ID: {x['id']})", axis=1))
            student_id = int(selected_student.split("(ID: ")[1].replace(")", ""))
            
            try:
                invoices = pd.read_sql("""
                    SELECT * FROM invoices 
                    WHERE student_id = ? 
                    ORDER BY issue_date DESC
                """, conn, params=(student_id,))
                
                if not invoices.empty:
                    st.dataframe(invoices[['invoice_number', 'issue_date', 'due_date', 'total_amount', 'paid_amount', 'balance_amount', 'status']], width='stretch')
                    
                    with st.expander("Record Payment"):
                        with st.form("record_payment"):
                            selected_invoice = st.selectbox("Select Invoice", invoices['invoice_number'].tolist())
                            invoice_id = invoices[invoices['invoice_number'] == selected_invoice]['id'].iloc[0]
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                payment_date = st.date_input("Payment Date", datetime.today())
                                amount = st.number_input("Amount (USh)", min_value=0.0, step=1000.0)
                                payment_method = st.selectbox("Payment Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
                            
                            with col2:
                                reference_number = st.text_input("Reference Number")
                                receipt_number = st.text_input("Receipt Number", value=generate_receipt_number())
                                notes = st.text_area("Notes")
                            
                            if st.form_submit_button("Record Payment"):
                                cursor = conn.cursor()
                                cursor.execute("""
                                    UPDATE invoices 
                                    SET paid_amount = paid_amount + ?, 
                                        balance_amount = balance_amount - ?,
                                        status = CASE 
                                            WHEN balance_amount - ? <= 0 THEN 'Fully Paid'
                                            WHEN paid_amount + ? > 0 THEN 'Partially Paid'
                                            ELSE status
                                        END
                                    WHERE id = ?
                                """, (amount, amount, amount, amount, invoice_id))
                                
                                cursor.execute("""
                                    INSERT INTO payments (invoice_id, receipt_number, payment_date, amount, 
                                                         payment_method, reference_number, notes, received_by)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                """, (invoice_id, receipt_number, payment_date, amount, payment_method, reference_number, notes, "Admin"))
                                
                                student_name = students[students['id'] == student_id]['name'].iloc[0]
                                try:
                                    cursor.execute("""
                                        INSERT INTO incomes (date, receipt_number, amount, source, category_id, 
                                                            payment_method, payer, received_by)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                    """, (payment_date, receipt_number, amount, "Tuition Fees", 
                                          8, payment_method, student_name, "Admin"))
                                except:
                                    cursor.execute("""
                                        INSERT INTO incomes (date, amount, source)
                                        VALUES (?, ?, ?)
                                    """, (payment_date, amount, f"Tuition fee from {student_name}"))
                                
                                conn.commit()
                                st.success("Payment recorded successfully!")
                                st.rerun()
                else:
                    st.info("No invoices found for this student")
            except:
                st.info("Invoice system not yet initialized or no invoices")
        
        conn.close()

    with st.expander("Add New Class"):
        conn = get_db_connection()
        with st.form("add_class"):
            new_cls = st.text_input("Class Name")
            if st.form_submit_button("Create Class") and new_cls:
                try:
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO classes (name) VALUES (?)", (new_cls,))
                    conn.commit()
                    st.success(f"Class '{new_cls}' created")
                    conn.close()
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Class already exists")
        conn.close()

# ─── Fee Management ────────────────────────────────────────────────────
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
        
        # View existing fee structures
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

st.sidebar.info("Logged in as admin – Professional Financial Management System")
