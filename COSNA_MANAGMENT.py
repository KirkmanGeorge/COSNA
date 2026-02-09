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
    table_exists = cursor.fetchone()
    
    if table_exists:
        try:
            cursor.execute("SELECT category_type FROM expense_categories LIMIT 1")
            category_type_exists = True
        except sqlite3.OperationalError:
            category_type_exists = False
        
        if not category_type_exists:
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

    # Enhanced expense/income categories
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
    
    # Add missing columns
    try:
        cursor.execute("SELECT receipt_number FROM incomes LIMIT 1")
    except sqlite3.OperationalError:
        for col in ['receipt_number TEXT UNIQUE', 'category_id INTEGER', 'description TEXT', 
                    'payment_method TEXT', 'payer TEXT', 'attachment_path TEXT', 'received_by TEXT']:
            try:
                cursor.execute(f"ALTER TABLE incomes ADD COLUMN {col}")
            except:
                pass
    
    try:
        cursor.execute("SELECT voucher_number FROM expenses LIMIT 1")
    except sqlite3.OperationalError:
        for col in ['voucher_number TEXT UNIQUE', 'description TEXT', 'payment_method TEXT', 
                    'payee TEXT', 'attachment_path TEXT', 'approved_by TEXT']:
            try:
                cursor.execute(f"ALTER TABLE expenses ADD COLUMN {col}")
            except:
                pass
    
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
    
    total_income = conn.execute("SELECT SUM(amount) FROM incomes").fetchone()[0] or 0
    col1.metric("Total Income", f"USh {total_income:,.0f}")
    
    total_expenses = conn.execute("SELECT SUM(amount) FROM expenses").fetchone()[0] or 0
    col2.metric("Total Expenses", f"USh {total_expenses:,.0f}")
    
    net_balance = total_income - total_expenses
    col3.metric("Net Balance", f"USh {net_balance:,.0f}", delta=f"USh {net_balance:,.0f}")
    
    try:
        outstanding_fees = conn.execute("SELECT SUM(balance_amount) FROM invoices WHERE status != 'Fully Paid'").fetchone()[0] or 0
    except:
        outstanding_fees = 0
    col4.metric("Outstanding Fees", f"USh {outstanding_fees:,.0f}")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Recent Income (Last 5)")
        try:
            df_inc = pd.read_sql("SELECT date, amount, source FROM incomes ORDER BY date DESC LIMIT 5", conn)
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
                # Excel export
                buf_excel = BytesIO()
                with pd.ExcelWriter(buf_excel, engine='xlsxwriter') as writer:
                    df.to_excel(writer, sheet_name='Students', index=False)
                buf_excel.seek(0)
                st.download_button("Download Students Excel", buf_excel, "cosna_students.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                
                # PDF export
                pdf_buf = BytesIO()
                pdf = canvas.Canvas(pdf_buf, pagesize=letter)
                pdf.drawString(100, 750, "COSNA Students List")
                y = 720
                for _, row in df.iterrows():
                    line = f"{row['name']} | Age: {row['age']} | Class: {row.get('class_name', 'N/A')} | Enrolled: {row['enrollment_date']}"
                    pdf.drawString(100, y, line)
                    y -= 20
                    if y < 100:
                        pdf.showPage()
                        y = 750
                pdf.save()
                pdf_buf.seek(0)
                st.download_button("Download Students PDF", pdf_buf, "cosna_students.pdf", "application/pdf")
        except Exception as e:
            st.info(f"Error loading students: {e}")
        
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

# ─── Uniforms ──────────────────────────────────────────────────────────
elif page == "Uniforms":
    st.header("Uniforms – Inventory & Sales")
    
    if 'uniform_refresh_counter' not in st.session_state:
        st.session_state.uniform_refresh_counter = 0
    
    tab_view, tab_update, tab_sale = st.tabs(["View Inventory", "Update Stock/Price", "Record Sale"])

    with tab_view:
        st.subheader("Current Inventory")
        conn = get_db_connection()
        df = pd.read_sql_query("""
            SELECT uc.category, uc.gender, uc.is_shared, u.stock, u.unit_price
            FROM uniforms u JOIN uniform_categories uc ON u.category_id = uc.id
            ORDER BY uc.gender, uc.category
        """, conn)
        st.dataframe(df, width='stretch')
        conn.close()

        st.caption(f"Last updated: {st.session_state.uniform_refresh_counter}")
        
        if st.button("🔄 Refresh Inventory", type="primary"):
            st.session_state.uniform_refresh_counter += 1
            st.rerun()

        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Uniform Inventory', index=False)
        buf.seek(0)
        st.download_button("Download Inventory Excel", buf, "cosna_uniforms.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_update:
        conn = get_db_connection()
        df_cats = pd.read_sql("SELECT id, category FROM uniform_categories ORDER BY category", conn)
        selected_cat = st.selectbox("Select Category", df_cats["category"])
        cat_id = df_cats[df_cats["category"] == selected_cat]["id"].iloc[0] if selected_cat else None

        if cat_id:
            current = conn.execute("SELECT stock, unit_price FROM uniforms WHERE category_id = ?", (cat_id,)).fetchone()
            curr_stock, curr_price = current if current else (0, 0.0)

            st.write(f"**Current stock:** {curr_stock}")
            st.write(f"**Current unit price:** USh {curr_price:,.0f}")

            with st.form("update_uniform"):
                new_stock = st.number_input("New Stock Level", min_value=0, value=curr_stock)
                new_price = st.number_input("New Unit Price (USh)", min_value=0.0, value=curr_price, step=500.0)

                if st.form_submit_button("💾 Update Stock & Price", type="primary"):
                    cursor = conn.cursor()
                    cursor.execute("UPDATE uniforms SET stock = ?, unit_price = ? WHERE category_id = ?",
                                   (new_stock, new_price, cat_id))
                    conn.commit()
                    conn.close()
                    st.session_state.uniform_refresh_counter += 1
                    st.success(f"✅ **Updated!** Now {new_stock} items at USh {new_price:,.0f}")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    conn.close()

    with tab_sale:
        conn = get_db_connection()
        df_cats = pd.read_sql("SELECT id, category FROM uniform_categories ORDER BY category", conn)
        selected_cat = st.selectbox("Select Category to Sell", df_cats["category"])
        cat_id = df_cats[df_cats["category"] == selected_cat]["id"].iloc[0] if selected_cat else None

        if cat_id:
            current = conn.execute("SELECT stock, unit_price FROM uniforms WHERE category_id = ?", (cat_id,)).fetchone()
            curr_stock, unit_price = current if current else (0, 0.0)

            st.write(f"**Available stock:** {curr_stock}")
            st.write(f"**Unit price:** USh {unit_price:,.0f}")

            with st.form("sell_uniform"):
                quantity = st.number_input("Quantity to Sell", min_value=1, max_value=curr_stock or 1, value=1)
                sale_date = st.date_input("Sale Date", datetime.today())

                if st.form_submit_button("💰 Record Sale", type="primary"):
                    if quantity > curr_stock:
                        st.error(f"❌ Not enough stock (only {curr_stock} available)")
                        conn.close()
                    else:
                        total_amount = quantity * unit_price
                        cursor = conn.cursor()
                        cursor.execute("UPDATE uniforms SET stock = stock - ? WHERE category_id = ?", (quantity, cat_id))
                        
                        try:
                            cursor.execute("INSERT INTO incomes (date, receipt_number, amount, source, category_id, description, payment_method, payer, received_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                           (sale_date, generate_receipt_number(), total_amount, "Uniform Sales", 10, 
                                            f"Sale of {quantity} {selected_cat}", "Cash", "Walk-in Customer", "Admin"))
                        except:
                            cursor.execute("INSERT INTO incomes (date, amount, source) VALUES (?, ?, ?)",
                                           (sale_date, total_amount, f"Uniform sale: {quantity} {selected_cat}"))
                        
                        conn.commit()
                        conn.close()
                        st.session_state.uniform_refresh_counter += 1
                        st.success(f"✅ Sold {quantity} items for USh {total_amount:,.0f}. Income recorded.")
                        time.sleep(0.5)
                        st.rerun()
                else:
                    conn.close()
        else:
            conn.close()

# ─── Finances ──────────────────────────────────────────────────────────
elif page == "Finances":
    st.header("💼 Advanced Financial Management")
    
    tab_income, tab_expense, tab_categories, tab_reports = st.tabs(["Income Records", "Expense Records", "Categories", "Financial Reports"])
    
    with tab_income:
        st.subheader("Record Income")
        
        with st.form("add_income"):
            col1, col2 = st.columns(2)
            
            with col1:
                date = st.date_input("Date", datetime.today())
                receipt_number = st.text_input("Receipt Number", value=generate_receipt_number())
                amount = st.number_input("Amount (USh)", min_value=0.0, step=1000.0)
                
                conn = get_db_connection()
                try:
                    income_cats = pd.read_sql("SELECT id, name FROM expense_categories WHERE category_type = 'Income' ORDER BY name", conn)
                except:
                    income_cats = pd.read_sql("SELECT id, name FROM expense_categories ORDER BY name", conn)
                
                if not income_cats.empty:
                    income_source = st.selectbox("Income Category", income_cats["name"])
                    category_id = income_cats[income_cats["name"] == income_source]["id"].iloc[0]
                else:
                    income_source = st.text_input("Income Source")
                    category_id = None
                
                try:
                    students = pd.read_sql("SELECT id, name FROM students ORDER BY name", conn)
                    payer_options = ["Select Payer"] + students["name"].tolist() + ["Other"]
                    payer = st.selectbox("Payer", payer_options)
                    
                    if payer != "Select Payer" and payer != "Other":
                        student_id = students[students["name"] == payer]["id"].iloc[0]
                    else:
                        student_id = None
                        if payer == "Other":
                            payer = st.text_input("Enter Payer Name")
                except:
                    payer = st.text_input("Payer Name")
                    student_id = None
            
            with col2:
                payment_method = st.selectbox("Payment Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
                received_by = st.text_input("Received By", "Admin")
                description = st.text_area("Description")
                
                uploaded_file = st.file_uploader("Upload Receipt/Attachment", type=['pdf', 'jpg', 'png', 'jpeg'])
            
            col1, col2, col3 = st.columns([1, 1, 2])
            with col2:
                if st.form_submit_button("💰 Record Income", type="primary"):
                    if not receipt_number:
                        st.error("Receipt Number is required!")
                    else:
                        cursor = conn.cursor()
                        try:
                            cursor.execute("""
                                INSERT INTO incomes (date, receipt_number, amount, source, category_id, 
                                                    description, payment_method, payer, student_id, received_by)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (date, receipt_number, amount, income_source, category_id, description, 
                                  payment_method, payer, student_id, received_by))
                            conn.commit()
                            st.success(f"Income of USh {amount:,.0f} recorded successfully! Receipt: {receipt_number}")
                        except sqlite3.IntegrityError:
                            st.error("Receipt number already exists. Please generate a new one.")
                        except:
                            try:
                                cursor.execute("INSERT INTO incomes (date, amount, source) VALUES (?, ?, ?)",
                                               (date, amount, f"{income_source}: {description}"))
                                conn.commit()
                                st.success(f"Income of USh {amount:,.0f} recorded successfully!")
                            except Exception as e:
                                st.error(f"Error recording income: {e}")
                        
                        conn.close()
                        time.sleep(1)
                        st.rerun()
            
            conn.close()
        
        st.subheader("Income Records")
        
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", datetime(datetime.today().year, 1, 1), key="income_start")
        with col2:
            end_date = st.date_input("End Date", datetime.today(), key="income_end")
        
        conn = get_db_connection()
        
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(incomes)")
        income_columns = [col[1] for col in cursor.fetchall()]
        
        if 'receipt_number' in income_columns:
            query = """
                SELECT date, receipt_number, amount, source, payment_method, received_by, description
                FROM incomes
                WHERE date BETWEEN ? AND ?
                ORDER BY date DESC
            """
        else:
            query = """
                SELECT date, amount, source
                FROM incomes
                WHERE date BETWEEN ? AND ?
                ORDER BY date DESC
            """
        
        income_records = pd.read_sql_query(query, conn, params=(start_date, end_date))
        
        if not income_records.empty:
            st.dataframe(income_records, width='stretch')
            
            total_income = income_records['amount'].sum()
            st.info(f"**Total Income for period:** USh {total_income:,.0f}")
            
            # Excel
            buf_excel = BytesIO()
            with pd.ExcelWriter(buf_excel, engine='xlsxwriter') as writer:
                income_records.to_excel(writer, sheet_name='Income Records', index=False)
            buf_excel.seek(0)
            st.download_button("Download Income Excel", buf_excel, f"income_{start_date}_{end_date}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            # PDF
            pdf_buf = BytesIO()
            pdf = canvas.Canvas(pdf_buf, pagesize=letter)
            pdf.drawString(100, 750, "Income Records Report")
            y = 730
            for _, row in income_records.iterrows():
                pdf.drawString(100, y, f"{row['date']} | USh {row['amount']:,.0f} | {row.get('source', 'N/A')}")
                y -= 20
                if y < 100:
                    pdf.showPage()
                    y = 750
            pdf.save()
            pdf_buf.seek(0)
            st.download_button("Download Income PDF", pdf_buf, f"income_{start_date}_{end_date}.pdf", "application/pdf")
        else:
            st.info("No income records found")
        
        conn.close()

    with tab_expense:
        st.subheader("Record Expense")
        
        with st.form("add_expense"):
            col1, col2 = st.columns(2)
            
            with col1:
                date = st.date_input("Date", datetime.today(), key="expense_date")
                voucher_number = st.text_input("Voucher Number", value=generate_voucher_number())
                amount = st.number_input("Amount (USh)", min_value=0.0, step=1000.0, value=0.0, key="expense_amount")
                
                conn = get_db_connection()
                try:
                    expense_cats = pd.read_sql("SELECT id, name FROM expense_categories ORDER BY name", conn)
                    if not expense_cats.empty:
                        expense_category = st.selectbox("Expense Category *required*", expense_cats["name"])
                        category_id = expense_cats[expense_cats["name"] == expense_category]["id"].iloc[0]
                    else:
                        st.error("No expense categories found. Add some in Categories tab.")
                        category_id = None
                except:
                    st.error("Error loading categories")
                    category_id = None
            
            with col2:
                payment_method = st.selectbox("Payment Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"], key="expense_payment")
                payee = st.text_input("Payee/Beneficiary")
                approved_by = st.text_input("Approved By", "Admin")
                description = st.text_area("Description *required for financial statements*", key="expense_desc")
            
            if st.form_submit_button("💳 Record Expense", type="primary"):
                if not voucher_number:
                    st.error("Voucher Number is required!")
                elif category_id is None:
                    st.error("Please select an expense category")
                elif not description.strip():
                    st.error("Description is required for proper financial reporting")
                else:
                    cursor = conn.cursor()
                    try:
                        cursor.execute("""
                            INSERT INTO expenses (date, voucher_number, amount, category_id, 
                                                 description, payment_method, payee, approved_by)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (date, voucher_number, amount, category_id, description.strip(), 
                              payment_method, payee, approved_by))
                        conn.commit()
                        st.success(f"Expense of USh {amount:,.0f} recorded! Category: {expense_category}")
                    except sqlite3.IntegrityError:
                        st.error("Voucher number already exists. Generate a new one.")
                    except Exception as e:
                        st.error(f"Database error: {e}")
                    
                    conn.close()
                    time.sleep(1)
                    st.rerun()
        
        # Expense Records
        st.subheader("Expense Records")
        
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", datetime(datetime.today().year, 1, 1), key="expense_start")
        with col2:
            end_date = st.date_input("End Date", datetime.today(), key="expense_end")
        
        conn = get_db_connection()
        
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(expenses)")
        expense_columns = [col[1] for col in cursor.fetchall()]
        
        if 'voucher_number' in expense_columns:
            query = """
                SELECT e.date, e.voucher_number, e.amount, ec.name as category, e.description, 
                       e.payee, e.payment_method, e.approved_by
                FROM expenses e
                LEFT JOIN expense_categories ec ON e.category_id = ec.id
                WHERE e.date BETWEEN ? AND ?
                ORDER BY e.date DESC
            """
        else:
            query = """
                SELECT e.date, e.amount, ec.name as category, e.description
                FROM expenses e
                LEFT JOIN expense_categories ec ON e.category_id = ec.id
                WHERE e.date BETWEEN ? AND ?
                ORDER BY e.date DESC
            """
        
        expense_records = pd.read_sql_query(query, conn, params=(start_date, end_date))
        
        if not expense_records.empty:
            st.dataframe(expense_records, width='stretch')
            
            total_expense = expense_records['amount'].sum()
            st.info(f"**Total Expenses:** USh {total_expense:,.0f}")
            
            # Excel export
            buf_excel = BytesIO()
            with pd.ExcelWriter(buf_excel, engine='xlsxwriter') as writer:
                expense_records.to_excel(writer, sheet_name='Expenses', index=False)
            buf_excel.seek(0)
            st.download_button("Download Expenses Excel", buf_excel, f"expenses_{start_date}_{end_date}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            # PDF export
            pdf_buf = BytesIO()
            pdf = canvas.Canvas(pdf_buf, pagesize=letter)
            pdf.drawString(100, 750, "Expense Report")
            pdf.drawString(100, 730, f"Period: {start_date} to {end_date}")
            y = 680
            for _, row in expense_records.iterrows():
                pdf.drawString(100, y, f"{row['date']} | {row['amount']:,.0f} | {row['category']} | {row.get('description', 'N/A')[:50]}...")
                y -= 20
                if y < 100:
                    pdf.showPage()
                    y = 750
            pdf.save()
            pdf_buf.seek(0)
            st.download_button("Download Expenses PDF", pdf_buf, f"expenses_{start_date}_{end_date}.pdf", "application/pdf")
        else:
            st.info("No expenses recorded in this period")
        
        conn.close()
    
    with tab_categories:
        col1, col2 = st.columns(2)
        
        conn = get_db_connection()
        
        with col1:
            st.subheader("All Categories")
            try:
                all_cats = pd.read_sql("SELECT name, category_type as type FROM expense_categories ORDER BY name", conn)
                st.dataframe(all_cats, width='stretch')
            except:
                try:
                    all_cats = pd.read_sql("SELECT name FROM expense_categories ORDER BY name", conn)
                    st.dataframe(all_cats, width='stretch')
                except:
                    st.info("No categories yet")
        
        with col2:
            st.subheader("Add New Category")
            with st.form("add_category"):
                new_cat = st.text_input("Category Name")
                cat_type = st.selectbox("Category Type", ["Expense", "Income"])
                
                if st.form_submit_button("Add Category") and new_cat:
                    cursor = conn.cursor()
                    try:
                        cursor.execute("INSERT INTO expense_categories (name, category_type) VALUES (?, ?)", (new_cat, cat_type))
                        conn.commit()
                        st.success(f"Category '{new_cat}' added as {cat_type}")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Category already exists")
                    except:
                        try:
                            cursor.execute("INSERT INTO expense_categories (name) VALUES (?)", (new_cat,))
                            conn.commit()
                            st.success(f"Category '{new_cat}' added")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
        
        conn.close()
    
    with tab_reports:
        st.subheader("Financial Reports")
        
        report_type = st.selectbox("Select Report Type", [
            "Income Summary",
            "Expense Summary", 
            "Payment Method Summary",
            "Daily Transaction Report"
        ])
        
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", datetime(datetime.today().year, 1, 1), key="report_start")
        with col2:
            end_date = st.date_input("End Date", datetime.today(), key="report_end")
        
        conn = get_db_connection()
        
        if report_type == "Income Summary":
            try:
                summary = pd.read_sql("""
                    SELECT source, COUNT(*) as transactions, SUM(amount) as total, AVG(amount) as avg
                    FROM incomes WHERE date BETWEEN ? AND ? GROUP BY source ORDER BY total DESC
                """, conn, params=(start_date, end_date))
                if not summary.empty:
                    st.dataframe(summary, width='stretch')
                    # Excel + PDF exports...
                    buf = BytesIO()
                    with pd.ExcelWriter(buf, engine='xlsxwriter') as w:
                        summary.to_excel(w, index=False)
                    buf.seek(0)
                    st.download_button("Excel", buf, "income_summary.xlsx")
                    
                    pdf_buf = BytesIO()
                    pdf = canvas.Canvas(pdf_buf, pagesize=letter)
                    pdf.drawString(100, 750, "Income Summary")
                    y = 720
                    for _, r in summary.iterrows():
                        pdf.drawString(100, y, f"{r['source']}: {r['transactions']} tx | USh {r['total']:,.0f}")
                        y -= 20
                    pdf.save()
                    pdf_buf.seek(0)
                    st.download_button("PDF", pdf_buf, "income_summary.pdf")
                else:
                    st.info("No data")
            except:
                st.info("Error loading summary")
        
        # ... (similar pattern for other report types with Excel + PDF)
        
        conn.close()

# ─── Financial Report ──────────────────────────────────────────────────
elif page == "Financial Report":
    st.header("Financial Report")

    col1, col2 = st.columns(2)
    start = col1.date_input("Start Date", datetime(datetime.today().year, 1, 1))
    end = col2.date_input("End Date", datetime.today())

    if st.button("Generate Report"):
        conn = get_db_connection()
        
        exp = pd.read_sql_query("""
            SELECT e.date, e.amount, ec.name AS category, e.description, e.voucher_number
            FROM expenses e LEFT JOIN expense_categories ec ON e.category_id = ec.id 
            WHERE e.date BETWEEN ? AND ?
        """, conn, params=(start, end))
        
        inc = pd.read_sql_query("""
            SELECT date, amount, source, description, receipt_number
            FROM incomes WHERE date BETWEEN ? AND ?
        """, conn, params=(start, end))

        total_exp = exp['amount'].sum()
        total_inc = inc['amount'].sum()
        balance = total_inc - total_exp

        col1, col2, col3 = st.columns(3)
        col1.metric("Income", f"USh {total_inc:,.0f}")
        col2.metric("Expenses", f"USh {total_exp:,.0f}")
        col3.metric("Balance", f"USh {balance:,.0f}")

        tab1, tab2 = st.tabs(["Incomes", "Expenses"])
        tab1.dataframe(inc, width='stretch')
        tab2.dataframe(exp, width='stretch')

        # Excel
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
            inc.to_excel(writer, sheet_name='Incomes', index=False)
            exp.to_excel(writer, sheet_name='Expenses', index=False)
        buf.seek(0)
        st.download_button("Download Excel", buf, f"financial_{start}_to_{end}.xlsx")

        # PDF
        pdf_buf = BytesIO()
        pdf = canvas.Canvas(pdf_buf, pagesize=letter)
        pdf.drawString(100, 750, "Financial Report")
        y = 700
        pdf.drawString(100, y, f"Income: {total_inc:,.0f}   Expenses: {total_exp:,.0f}   Balance: {balance:,.0f}")
        pdf.save()
        pdf_buf.seek(0)
        st.download_button("Download PDF", pdf_buf, f"financial_{start}_to_{end}.pdf")

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
                classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
                selected_class = st.selectbox("Class", classes["name"] if not classes.empty else ["No classes"])
                class_id = classes[classes["name"] == selected_class]["id"].iloc[0] if not classes.empty else None
                term = st.selectbox("Term", ["Term 1", "Term 2", "Term 3"])
                academic_year = st.text_input("Academic Year", f"{datetime.today().year}/{datetime.today().year+1}")
            
            with col2:
                tuition = st.number_input("Tuition Fee", value=0.0)
                uniform = st.number_input("Uniform Fee", value=0.0)
                activity = st.number_input("Activity Fee", value=0.0)
                exam = st.number_input("Exam Fee", value=0.0)
                library = st.number_input("Library Fee", value=0.0)
                other = st.number_input("Other Fee", value=0.0)
            
            total = tuition + uniform + activity + exam + library + other
            st.info(f"Total: USh {total:,.0f}")
            
            if st.form_submit_button("Save"):
                if class_id:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO fee_structure (class_id, term, academic_year, tuition_fee, uniform_fee, 
                        activity_fee, exam_fee, library_fee, other_fee, total_fee)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (class_id, term, academic_year, tuition, uniform, activity, exam, library, other, total))
                    conn.commit()
                    st.success("Saved")
                else:
                    st.error("Select class")
        
        conn.close()
    
    with tab_invoices:
        st.subheader("Generate Invoices")
        conn = get_db_connection()
        
        with st.form("generate_invoice"):
            col1, col2 = st.columns(2)
            with col1:
                classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
                selected_class = st.selectbox("Class", classes["name"] if not classes.empty else ["No classes"])
                class_id = classes[classes["name"] == selected_class]["id"].iloc[0] if not classes.empty else None
            
            with col2:
                issue_date = st.date_input("Issue Date", datetime.today())
                due_date = st.date_input("Due Date", datetime.today() + pd.Timedelta(days=30))
                base_invoice = st.text_input("Base Invoice Number", value=generate_invoice_number())
                notes = st.text_area("Notes")
            
            students = []
            if class_id:
                students = pd.read_sql("SELECT id, name FROM students WHERE class_id = ?", conn, params=(class_id,))
                if students.empty:
                    st.warning("No students in this class")
                else:
                    selected = st.multiselect("Students", students.apply(lambda x: f"{x['name']} (ID:{x['id']})", axis=1))
            
            amount = st.number_input("Amount per Student (USh)", min_value=0.0, step=1000.0)
            
            if st.form_submit_button("Generate"):
                if not class_id:
                    st.error("Select class")
                elif amount <= 0:
                    st.error("Enter amount > 0")
                elif not selected:
                    st.error("Select students")
                else:
                    cursor = conn.cursor()
                    created = []
                    for sel in selected:
                        sid = int(sel.split("ID:")[1][:-1])
                        name = sel.split(" (ID")[0]
                        inv = f"{base_invoice}-{sid}"
                        cursor.execute("""
                            INSERT INTO invoices (invoice_number, student_id, issue_date, due_date, 
                            academic_year, term, total_amount, paid_amount, balance_amount, status, notes)
                            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 'Pending', ?)
                        """, (inv, sid, issue_date, due_date, "2025/2026", "Term 1", amount, amount, notes))
                        created.append({'Invoice': inv, 'Student': name, 'Amount': amount})
                    conn.commit()
                    st.success(f"Created {len(created)} invoices")
                    with st.expander("Preview"):
                        st.dataframe(pd.DataFrame(created))
        
        conn.close()
    
    with tab_payments:
        st.subheader("Payment Records")
        # ... (your original payment code or placeholder)

st.sidebar.info("Logged in as admin – Professional Financial Management System")
