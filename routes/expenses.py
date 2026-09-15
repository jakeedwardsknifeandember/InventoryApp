# routes/expenses.py - Advanced Business Analytics & Filtering Engine
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
from datetime import datetime, timedelta
import pandas as pd
import sqlite3

expenses_bp = Blueprint('expenses', __name__)

STANDARD_FNB_EXPENSE_CATEGORIES = [
    "Utilities",
    "Rent & Lease",
    "Staff Salaries",
    "Packaging & Disposables",
    "Equipment Maintenance",
    "Store Supplies",
    "Logistics & Delivery",
    "Marketing & Promo",
    "Permits & Taxes",
    "Misc Overhead"
]

def ensure_expenses_schema(conn):
    """Safely ensures the Expenses table exists with full metadata attributes."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Expenses (
            Expense_ID TEXT,
            Expense_Date TEXT,
            Expense_Type TEXT DEFAULT 'Operational',
            Description TEXT,
            Amount REAL,
            Category TEXT DEFAULT 'Misc Overhead',
            Payment_Method TEXT DEFAULT 'Petty Cash',
            Notes TEXT
        )
    """)
    cursor.execute("PRAGMA table_info(Expenses)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    needed_cols = {
        'Expense_ID': "TEXT",
        'Expense_Date': "TEXT",
        'Expense_Type': "TEXT DEFAULT 'Operational'",
        'Description': "TEXT",
        'Amount': "REAL",
        'Category': "TEXT DEFAULT 'Misc Overhead'",
        'Payment_Method': "TEXT DEFAULT 'Petty Cash'",
        'Notes': "TEXT"
    }
    for col_name, col_def in needed_cols.items():
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE Expenses ADD COLUMN {col_name} {col_def}")
    conn.commit()

@expenses_bp.route('/portal/<username>/expenses', methods=['GET', 'POST'])
def web_expenses_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')

    client_db_path = f"data/client_{username}.db"
    db = InventoryDB(client_db_path)
    operator = session.get('logged_in_user', username)
    feedback_msg = None
    alert_type = "success"

    try:
        conn = sqlite3.connect(client_db_path, timeout=20.0)
        ensure_expenses_schema(conn)
        conn.close()
    except Exception:
        pass

    # ==========================================
    # 1. POST METHOD: DATA WRITE OPERATIONS
    # ==========================================
    if request.method == 'POST':
        action = request.form.get('action_type')
        
        # 1. ADD NEW EXPENSE OUTFLOW
        if action == 'add_expense':
            expense_date = request.form.get('expense_date', datetime.now().strftime("%Y-%m-%d")).strip()
            description = request.form.get('description', '').strip()
            amount_str = request.form.get('amount', '0.0')
            category = request.form.get('category', 'Misc Overhead').strip()
            payment_method = request.form.get('payment_method', 'Petty Cash').strip()
            notes = request.form.get('notes', '').strip()
            
            try:
                amount = float(amount_str)
                if amount <= 0:
                    feedback_msg = "Error: Expense amount must be greater than 0.00."
                    alert_type = "danger"
                elif not description:
                    feedback_msg = "Error: Description field cannot be blank."
                    alert_type = "danger"
                else:
                    success, msg = False, ""
                    if hasattr(db, 'add_expense'):
                        try:
                            success, msg = db.add_expense({
                                'Expense_Date': expense_date,
                                'Expense_Type': 'Operational', 
                                'Description': description,
                                'Amount': amount,
                                'Category': category if category else 'Misc Overhead',
                                'Payment_Method': payment_method if payment_method else 'Petty Cash',
                                'Notes': notes
                            })
                        except Exception:
                            success = False
                    
                    if not success:
                        conn = sqlite3.connect(client_db_path, timeout=20.0)
                        cursor = conn.cursor()
                        cursor.execute("SELECT COUNT(*) FROM Expenses")
                        c_cnt = cursor.fetchone()[0]
                        exp_id = f"EXP{c_cnt + 1:04d}"
                        cursor.execute("""
                            INSERT INTO Expenses (Expense_ID, Expense_Date, Expense_Type, Description, Amount, Category, Payment_Method, Notes)
                            VALUES (?, ?, 'Operational', ?, ?, ?, ?, ?)
                        """, (exp_id, expense_date, description, amount, category, payment_method, notes))
                        conn.commit()
                        conn.close()
                        msg = f"Success: Expense '{description}' (PHP {amount:,.2f}) recorded to ledger."
                        success = True

                    feedback_msg = msg
                    alert_type = "success" if success else "danger"
            except ValueError:
                feedback_msg = "Error: Invalid numeric formatting supplied in Amount field."
                alert_type = "danger"

        # 2. EDIT EXISTING EXPENSE RECORD
        elif action == 'edit_expense':
            expense_rowid = request.form.get('expense_rowid', '').strip()
            expense_id = request.form.get('expense_id', '').strip()
            expense_date = request.form.get('expense_date', datetime.now().strftime("%Y-%m-%d")).strip()
            description = request.form.get('description', '').strip()
            amount_str = request.form.get('amount', '0.0')
            category = request.form.get('category', 'Misc Overhead').strip()
            payment_method = request.form.get('payment_method', 'Petty Cash').strip()
            notes = request.form.get('notes', '').strip()

            try:
                amount = float(amount_str)
                if amount <= 0:
                    feedback_msg = "Error: Expense amount must be greater than 0.00."
                    alert_type = "danger"
                elif not description:
                    feedback_msg = "Error: Description field cannot be blank."
                    alert_type = "danger"
                else:
                    conn = sqlite3.connect(client_db_path, timeout=20.0)
                    cursor = conn.cursor()
                    if expense_rowid:
                        cursor.execute("""
                            UPDATE Expenses 
                            SET Expense_Date = ?, Description = ?, Amount = ?, Category = ?, Payment_Method = ?, Notes = ?
                            WHERE rowid = ?
                        """, (expense_date, description, amount, category, payment_method, notes, expense_rowid))
                    elif expense_id:
                        cursor.execute("""
                            UPDATE Expenses 
                            SET Expense_Date = ?, Description = ?, Amount = ?, Category = ?, Payment_Method = ?, Notes = ?
                            WHERE Expense_ID = ?
                        """, (expense_date, description, amount, category, payment_method, notes, expense_id))
                    conn.commit()
                    conn.close()
                    feedback_msg = f"Success: Expense '{description}' (PHP {amount:,.2f}) updated successfully."
                    alert_type = "success"
            except ValueError:
                feedback_msg = "Error: Invalid numeric formatting supplied in Amount field."
                alert_type = "danger"
            except Exception as e:
                feedback_msg = f"Database Error: {str(e)}"
                alert_type = "danger"

        # 3. VOID EXPENSE OUTFLOW RECORD (AUDIT COMPLIANCE SAFEGUARD)
        elif action == 'void_expense':
            expense_rowid = request.form.get('expense_rowid', '').strip()
            void_reason = request.form.get('void_reason', '').strip() or "Operator void correction"

            if expense_rowid:
                try:
                    conn = sqlite3.connect(client_db_path, timeout=20.0)
                    cursor = conn.cursor()
                    cursor.execute("SELECT Amount, Description FROM Expenses WHERE rowid = ?", (expense_rowid,))
                    rec = cursor.fetchone()
                    if rec:
                        orig_amt, orig_desc = rec
                        new_desc = f"[VOIDED] {orig_desc} | Auth: {operator} | Reason: {void_reason}"
                        cursor.execute("UPDATE Expenses SET Amount = 0.0, Description = ? WHERE rowid = ?", (new_desc, expense_rowid))
                        conn.commit()
                        feedback_msg = f"Success: Expense neutralized to PHP 0.00 in general ledger."
                        alert_type = "warning"
                    conn.close()
                except Exception as e:
                    feedback_msg = f"Database Error: {str(e)}"
                    alert_type = "danger"

        return redirect(f"/portal/{username}/expenses?msg={feedback_msg}&alert_type={alert_type}")

    # ==========================================
    # 2. GET METHOD: DATA RECOVERY & ANALYTICS
    # ==========================================
    url_msg = request.args.get('msg')
    url_alert = request.args.get('alert_type', 'success')
    if url_msg:
        feedback_msg = url_msg
        alert_type = url_alert

    # Dual-layer failsafe fetching with explicit primary rowid
    expenses_df = pd.DataFrame()
    try:
        conn = sqlite3.connect(client_db_path, timeout=20.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT rowid, * FROM Expenses ORDER BY Expense_Date DESC, rowid DESC")
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        if rows:
            expenses_df = pd.DataFrame(rows)
    except Exception:
        expenses_df = db.get_expenses()

    total_this_month = 0.0
    filtered_total = 0.0
    top_burning_category = "None logged"
    top_burn_pct_str = "0.0%"
    cash_ratio = 0.0  
    digital_ratio = 0.0
    avg_outflow = 0.0
    
    categories_list = list(STANDARD_FNB_EXPENSE_CATEGORIES)
    
    search_query = request.args.get('search', '').lower().strip()
    selected_category = request.args.get('category', 'All')
    selected_period = request.args.get('period', 'this_month')
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')

    now = datetime.now()
    current_year = now.year
    current_month = now.month

    if not expenses_df.empty:
        expenses_df['Amount'] = pd.to_numeric(expenses_df['Amount'], errors='coerce').fillna(0.0)
        expenses_df['Expense_Date'] = pd.to_datetime(expenses_df['Expense_Date'], errors='coerce')
        
        if 'Category' in expenses_df.columns:
            db_categories = expenses_df['Category'].dropna().unique().tolist()
            categories_list = sorted(list(set(categories_list + [str(c).strip() for c in db_categories if str(c).strip()])))
        
        # Exclude voided entries from analytics
        is_voided_series = expenses_df['Description'].astype(str).str.contains(r'\[VOIDED\]', case=False, na=False)
        active_expenses_df = expenses_df[~is_voided_series & (expenses_df['Amount'] > 0)].copy()

        # Monthly KPI Outflow calculation (Month-to-Date)
        this_month_mask = (active_expenses_df['Expense_Date'].dt.year == current_year) & (active_expenses_df['Expense_Date'].dt.month == current_month)
        this_month_df = active_expenses_df[this_month_mask]
        total_this_month = float(this_month_df['Amount'].sum())

        # ==========================================
        # 3. DATE RANGE & ADVANCED FILTER ENGINE
        # ==========================================
        today_start = now.date()
        start_bound = None
        end_bound = None

        if selected_period == 'today':
            start_bound = pd.to_datetime(today_start)
            end_bound = pd.to_datetime(today_start) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        elif selected_period in ['this_week', 'week']:
            start_bound = pd.to_datetime(today_start - timedelta(days=today_start.weekday()))
            end_bound = start_bound + pd.Timedelta(days=7) - pd.Timedelta(seconds=1)
        elif selected_period in ['this_month', 'month']:
            start_bound = pd.to_datetime(datetime(current_year, current_month, 1))
            end_bound = start_bound + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        elif selected_period == 'last_month':
            last_month = 12 if current_month == 1 else current_month - 1
            last_year = current_year - 1 if current_month == 1 else current_year
            start_bound = pd.to_datetime(datetime(last_year, last_month, 1))
            end_bound = start_bound + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        elif selected_period == 'custom' and start_date_str and end_date_str:
            try:
                start_bound = pd.to_datetime(start_date_str)
                end_bound = pd.to_datetime(end_date_str) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
            except Exception:
                selected_period = 'this_month'
                start_bound = pd.to_datetime(datetime(current_year, current_month, 1))
                end_bound = start_bound + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        elif selected_period in ['all_time', 'all']:
            start_bound = None
            end_bound = None

        filtered_df = expenses_df.copy()

        if start_bound is not None and end_bound is not None:
            filtered_df = filtered_df[(filtered_df['Expense_Date'] >= start_bound) & (filtered_df['Expense_Date'] <= end_bound)]

        if selected_category != 'All':
            filtered_df = filtered_df[filtered_df['Category'].astype(str) == selected_category]
            
        if search_query:
            filtered_df = filtered_df[
                filtered_df['Description'].astype(str).str.lower().str.contains(search_query) |
                filtered_df['Category'].astype(str).str.lower().str.contains(search_query) |
                filtered_df['Notes'].astype(str).str.lower().str.contains(search_query)
            ]

        # Analytics on active items in filtered scope
        active_filtered = filtered_df[~filtered_df['Description'].astype(str).str.contains(r'\[VOIDED\]', case=False, na=False) & (filtered_df['Amount'] > 0)]
        filtered_total = float(active_filtered['Amount'].sum())

        if not active_filtered.empty:
            cat_group = active_filtered.groupby('Category')['Amount'].sum()
            if not cat_group.empty:
                top_cat_name = cat_group.idxmax()
                top_cat_sum = float(cat_group.max())
                top_burning_category = f"{top_cat_name} (PHP {top_cat_sum:,.2f})"
                top_burn_pct_str = f"{(top_cat_sum / filtered_total * 100):.1f}%" if filtered_total > 0 else "0.0%"

            # Payment Channel Ratios
            pm_series = active_filtered['Payment_Method'].astype(str).str.lower()
            cash_tot = active_filtered[pm_series.str.contains('petty|cash') & ~pm_series.str.contains('card')]['Amount'].sum()
            digital_tot = active_filtered[~pm_series.str.contains('petty|cash') | pm_series.str.contains('card')]['Amount'].sum()
            
            if filtered_total > 0:
                cash_ratio = round((cash_tot / filtered_total) * 100, 1)
                digital_ratio = round(100.0 - cash_ratio, 1)

            avg_outflow = round(filtered_total / len(active_filtered), 2)
        else:
            top_burning_category = "None in period"
            top_burn_pct_str = "0.0%"
            cash_ratio = 50.0
            digital_ratio = 50.0

        final_list = []
        for _, row in filtered_df.iterrows():
            date_str = now.strftime("%Y-%m-%d")
            if pd.notnull(row['Expense_Date']):
                date_str = row['Expense_Date'].strftime("%Y-%m-%d")
                
            p_method = str(row.get('Payment_Method') or 'Petty Cash').strip()
            category_val = str(row.get('Category') or 'Misc Overhead').strip()
            
            if p_method == 'nan' or not p_method: p_method = 'Petty Cash'
            if category_val == 'nan' or not category_val: category_val = 'Misc Overhead'
            
            desc_val = str(row.get('Description') or '').strip()
            is_voided = '[VOIDED]' in desc_val

            final_list.append({
                'rowid': row.get('rowid', ''),
                'Expense_ID': row.get('Expense_ID', ''),
                'Expense_Date': date_str,
                'Description': desc_val,
                'Category': category_val,
                'Payment_Method': p_method,
                'Amount': float(row.get('Amount', 0.0)),
                'Notes': str(row.get('Notes') or '').strip(),
                'is_voided': is_voided
            })
    else:
        final_list = []
        start_bound = pd.to_datetime(datetime(current_year, current_month, 1))
        end_bound = start_bound + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

    formatted_start_str = start_bound.strftime("%Y-%m-%d") if 'start_bound' in locals() and start_bound is not None else ""
    formatted_end_str = end_bound.strftime("%Y-%m-%d") if 'end_bound' in locals() and end_bound is not None else ""

    return render_template(
        'expenses.html',
        username=username,
        expenses=final_list,
        categories=categories_list,
        kpi_month_total=total_this_month,
        kpi_filtered_total=filtered_total,
        kpi_top_burn=top_burning_category,
        kpi_top_burn_pct=top_burn_pct_str,
        kpi_cash_ratio=cash_ratio,
        kpi_digital_ratio=digital_ratio,
        kpi_avg_outflow=avg_outflow,
        msg=feedback_msg,
        alert_type=alert_type,
        current_search=search_query,
        current_category=selected_category,
        current_period=selected_period,
        start_date=start_date_str if start_date_str else formatted_start_str,
        end_date=end_date_str if end_date_str else formatted_end_str,
        current_date=now.strftime("%Y-%m-%d")
    )