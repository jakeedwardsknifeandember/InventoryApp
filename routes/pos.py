# routes/pos.py - Live Counter POS Terminal & Instant Ledger Engine with Dynamic Thermal Printing, Shift Lifecycle & Xprinter XP-237B Integration
from flask import Blueprint, request, jsonify, render_template, session, redirect
from modules.database import InventoryDB
from datetime import datetime
import pandas as pd
import sqlite3
import json
import ctypes
from ctypes import wintypes
import os

pos_bp = Blueprint('pos', __name__)

def get_db_connection(db_path, timeout=30.0):
    """Creates a SQLite connection with WAL mode and 30s busy timeout to eliminate database locks."""
    conn = sqlite3.connect(db_path, timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def ensure_pos_tables_exist(db_path, username="STORE"):
    """Ensures Sales, Shift_Logs, Cash_Drawer_Logs, Recipes, Ingredients, Modifiers, Modifier_Groups, Product_Modifiers, Staff_Accounts, and Store_Settings exist with automatic column migrations."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Shift_Logs (
            Shift_ID TEXT PRIMARY KEY,
            Cashier_Open TEXT,
            Cashier_Close TEXT,
            Date TEXT,
            Time_Opened TEXT,
            Time_Closed TEXT,
            Starting_Float REAL DEFAULT 0.0,
            Cash_Sales REAL DEFAULT 0.0,
            Cash_Paid_Outs REAL DEFAULT 0.0,
            Expected_Cash REAL DEFAULT 0.0,
            Actual_Counted_Cash REAL DEFAULT 0.0,
            Discrepancy_Over_Short REAL DEFAULT 0.0,
            Total_Net_Sales REAL DEFAULT 0.0,
            Total_Transactions INTEGER DEFAULT 0,
            Status TEXT DEFAULT 'OPEN',
            Notes TEXT
        )
    """)
    cursor.execute("PRAGMA table_info(Shift_Logs)")
    existing_shift_cols = {row[1] for row in cursor.fetchall()}
    needed_shift_cols = {
        'Cashier_Close': 'TEXT',
        'Date': 'TEXT',
        'Time_Opened': 'TEXT',
        'Time_Closed': 'TEXT',
        'Starting_Float': 'REAL DEFAULT 0.0',
        'Cash_Sales': 'REAL DEFAULT 0.0',
        'Cash_Paid_Outs': 'REAL DEFAULT 0.0',
        'Expected_Cash': 'REAL DEFAULT 0.0',
        'Actual_Counted_Cash': 'REAL DEFAULT 0.0',
        'Discrepancy_Over_Short': 'REAL DEFAULT 0.0',
        'Total_Net_Sales': 'REAL DEFAULT 0.0',
        'Total_Transactions': 'INTEGER DEFAULT 0',
        'Status': "TEXT DEFAULT 'OPEN'",
        'Notes': 'TEXT'
    }
    for col_name, col_type in needed_shift_cols.items():
        if col_name not in existing_shift_cols:
            cursor.execute(f"ALTER TABLE Shift_Logs ADD COLUMN {col_name} {col_type}")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Sales (
            Sale_ID TEXT PRIMARY KEY,
            Sale_Date TEXT,
            Sale_Time TEXT,
            Product_ID TEXT,
            Product_Name TEXT,
            Quantity REAL,
            Price REAL,
            Total_Amount REAL,
            Reason TEXT,
            Recorded_By TEXT
        )
    """)
    cursor.execute("PRAGMA table_info(Sales)")
    existing_sales_cols = {row[1] for row in cursor.fetchall()}
    needed_sales_cols = {
        'Sale_Date': 'TEXT',
        'Sale_Time': 'TEXT',
        'Product_ID': 'TEXT',
        'Product_Name': 'TEXT',
        'Quantity': 'REAL',
        'Price': 'REAL',
        'Total_Amount': 'REAL',
        'Reason': 'TEXT',
        'Recorded_By': 'TEXT'
    }
    for col_name, col_type in needed_sales_cols.items():
        if col_name not in existing_sales_cols:
            cursor.execute(f"ALTER TABLE Sales ADD COLUMN {col_name} {col_type}")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Cash_Drawer_Logs (
            Drawer_Tx_ID TEXT PRIMARY KEY,
            Batch_ID TEXT,
            Date TEXT,
            Time TEXT,
            Starting_Float REAL DEFAULT 0.0,
            Cash_Sales REAL DEFAULT 0.0,
            Cash_Paid_Outs REAL DEFAULT 0.0,
            Expected_Cash REAL DEFAULT 0.0,
            Actual_Counted_Cash REAL DEFAULT 0.0,
            Discrepancy_Over_Short REAL DEFAULT 0.0,
            GCash_Sales REAL DEFAULT 0.0,
            Maya_Sales REAL DEFAULT 0.0,
            Card_Sales REAL DEFAULT 0.0,
            Grab_Gross REAL DEFAULT 0.0,
            Grab_Commission REAL DEFAULT 0.0,
            Grab_Net REAL DEFAULT 0.0,
            Foodpanda_Gross REAL DEFAULT 0.0,
            Foodpanda_Commission REAL DEFAULT 0.0,
            Foodpanda_Net REAL DEFAULT 0.0,
            Total_Settled_Tenders REAL DEFAULT 0.0,
            Tender_Variance REAL DEFAULT 0.0,
            Explanation_Notes TEXT,
            Recorded_By TEXT
        )
    """)
    cursor.execute("PRAGMA table_info(Cash_Drawer_Logs)")
    existing_drawer_cols = {row[1] for row in cursor.fetchall()}
    needed_drawer_cols = {
        'Batch_ID': 'TEXT',
        'Date': 'TEXT',
        'Time': 'TEXT',
        'Starting_Float': 'REAL DEFAULT 0.0',
        'Cash_Sales': 'REAL DEFAULT 0.0',
        'Cash_Paid_Outs': 'REAL DEFAULT 0.0',
        'Expected_Cash': 'REAL DEFAULT 0.0',
        'Actual_Counted_Cash': 'REAL DEFAULT 0.0',
        'Discrepancy_Over_Short': 'REAL DEFAULT 0.0',
        'GCash_Sales': 'REAL DEFAULT 0.0',
        'Maya_Sales': 'REAL DEFAULT 0.0',
        'Card_Sales': 'REAL DEFAULT 0.0',
        'Grab_Gross': 'REAL DEFAULT 0.0',
        'Grab_Commission': 'REAL DEFAULT 0.0',
        'Grab_Net': 'REAL DEFAULT 0.0',
        'Foodpanda_Gross': 'REAL DEFAULT 0.0',
        'Foodpanda_Commission': 'REAL DEFAULT 0.0',
        'Foodpanda_Net': 'REAL DEFAULT 0.0',
        'Total_Settled_Tenders': 'REAL DEFAULT 0.0',
        'Tender_Variance': 'REAL DEFAULT 0.0',
        'Explanation_Notes': 'TEXT',
        'Recorded_By': 'TEXT'
    }
    for col_name, col_type in needed_drawer_cols.items():
        if col_name not in existing_drawer_cols:
            cursor.execute(f"ALTER TABLE Cash_Drawer_Logs ADD COLUMN {col_name} {col_type}")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Inventory_Audit_Log (
            Audit_ID TEXT,
            Date TEXT,
            Ingredient_Name TEXT,
            Theoretical REAL,
            Physical REAL,
            Variance REAL,
            Notes TEXT
        )
    """)
    cursor.execute("PRAGMA table_info(Inventory_Audit_Log)")
    existing_audit_cols = {row[1] for row in cursor.fetchall()}
    needed_audit_cols = {
        'Audit_ID': 'TEXT',
        'Date': 'TEXT',
        'Ingredient_Name': 'TEXT',
        'Theoretical': 'REAL',
        'Physical': 'REAL',
        'Variance': 'REAL',
        'Notes': 'TEXT'
    }
    for col_name, col_type in needed_audit_cols.items():
        if col_name not in existing_audit_cols:
            cursor.execute(f"ALTER TABLE Inventory_Audit_Log ADD COLUMN {col_name} {col_type}")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Modifier_Groups (
            Group_ID TEXT PRIMARY KEY,
            Group_Name TEXT NOT NULL,
            Selection_Type TEXT DEFAULT 'multiple',
            Active TEXT DEFAULT 'Yes'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Modifiers (
            Modifier_ID TEXT PRIMARY KEY,
            Group_ID TEXT DEFAULT '',
            Modifier_Name TEXT,
            Category TEXT DEFAULT 'General',
            Price REAL DEFAULT 0.0,
            Active TEXT DEFAULT 'Yes'
        )
    """)

    cursor.execute("PRAGMA table_info(Modifiers)")
    cols = [col[1] for col in cursor.fetchall()]
    if 'Group_ID' not in cols:
        cursor.execute("ALTER TABLE Modifiers ADD COLUMN Group_ID TEXT DEFAULT ''")
    if 'Category' not in cols:
        cursor.execute("ALTER TABLE Modifiers ADD COLUMN Category TEXT DEFAULT 'General'")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Modifier_Recipes (
            Modifier_ID TEXT,
            Ingredient_ID TEXT,
            Quantity_Required REAL DEFAULT 0.0,
            Unit TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Product_Modifiers (
            Product_ID TEXT,
            Group_ID TEXT,
            PRIMARY KEY (Product_ID, Group_ID)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Staff_Accounts (
            Staff_ID TEXT PRIMARY KEY,
            Full_Name TEXT,
            Display_Name TEXT,
            Username TEXT UNIQUE,
            Password TEXT,
            PIN TEXT DEFAULT '1234',
            Role TEXT,
            Active TEXT DEFAULT 'Yes'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Store_Settings (
            Setting_Key TEXT PRIMARY KEY,
            Setting_Value TEXT
        )
    """)

    default_settings = {
        'receipt_header_name': username.upper(),
        'receipt_tagline': 'FOOD & BEVERAGE SERVICES',
        'receipt_address': 'San Jose del Monte, Bulacan',
        'receipt_contact': '+63 900 000 0000',
        'receipt_tin': 'TIN: 000-000-000-000 Non-VAT',
        'receipt_title': 'OFFICIAL ACKNOWLEDGMENT RECEIPT',
        'receipt_footer': 'Thank you for dining with us! Have a great day!',
        'receipt_wifi': 'WiFi: CafeGuest / Pass: coffee2026',
        'receipt_policy_note': 'Items served are non-refundable.',
        'receipt_width': '80mm',
        'receipt_feed_lines': '4',
        'receipt_show_tin': 'yes',
        'receipt_show_wifi': 'no',
        'receipt_show_signature': 'no',
        'master_admin_pin': '9999',
        'label_width_mm': '40',
        'label_height_mm': '30',
        'label_gap_mm': '2.25',
        'label_printer_port': 'COM7',
        'auto_print_labels': 'yes'
    }
    for k, v in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO Store_Settings (Setting_Key, Setting_Value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()

def get_receipt_config(db_path, username="STORE"):
    """Retrieves all customized receipt and hardware formatting options from Store_Settings."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT Setting_Key, Setting_Value FROM Store_Settings")
    settings = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return settings

def verify_supervisor_pin(conn, entered_pin):
    """Validates entered PIN against Master Admin PIN in Store_Settings or active Store Manager PIN in Staff_Accounts."""
    pin = str(entered_pin or '').strip()
    if not pin:
        return False, "PIN cannot be empty."

    cur = conn.cursor()
    cur.execute("SELECT Setting_Value FROM Store_Settings WHERE Setting_Key = 'master_admin_pin'")
    row = cur.fetchone()
    master_pin = row[0] if row and row[0] else '9999'
    if pin == master_pin:
        return True, "Master Security PIN Override"

    cur.execute("""
        SELECT Display_Name, Role FROM Staff_Accounts 
        WHERE PIN = ? AND (Role LIKE '%Manager%' OR Role LIKE '%Owner%' OR Role LIKE '%Admin%')
          AND (Active = 'Yes' OR Active = 'YES')
    """, (pin,))
    mgr = cur.fetchone()
    if mgr:
        return True, f"Authorized by {mgr[1]} ({mgr[0]})"

    return False, "Invalid Master Security PIN or Manager PIN."

def get_active_shift(conn):
    """Returns the currently OPEN shift dictionary if active, else None."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT Shift_ID, Cashier_Open, Date, Time_Opened, Starting_Float, Cash_Sales, Cash_Paid_Outs, Total_Net_Sales, Total_Transactions, Status
        FROM Shift_Logs 
        WHERE Status = 'OPEN' 
        ORDER BY Shift_ID DESC LIMIT 1
    """)
    row = cursor.fetchone()
    if row:
        return {
            'Shift_ID': row[0],
            'Cashier_Open': row[1],
            'Date': row[2],
            'Time_Opened': row[3],
            'Starting_Float': float(row[4] or 0.0),
            'Cash_Sales': float(row[5] or 0.0),
            'Cash_Paid_Outs': float(row[6] or 0.0),
            'Total_Net_Sales': float(row[7] or 0.0),
            'Total_Transactions': int(row[8] or 0),
            'Status': row[9]
        }
    return None

def send_tspl_to_windows_com(port_name, tspl_text):
    """
    Directly streams raw TSPL bytes to the Windows Bluetooth Serial Port (e.g., COM7)
    using Win32 CreateFileW without SetCommState/baudrate handshake conflicts.
    """
    if os.name != 'nt':
        return False, "Direct COM write is supported on Windows host."

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    device_path = f"\\\\.\\{port_name.upper().strip()}"

    handle = kernel32.CreateFileW(
        device_path,
        0x40000000,  # GENERIC_WRITE
        0,           # Exclusive access
        None,
        3,           # OPEN_EXISTING
        0x80,        # FILE_ATTRIBUTE_NORMAL
        None
    )

    if handle == -1:
        err = ctypes.get_last_error()
        return False, f"Could not open {port_name} (WinError {err}). Verify printer is ON and paired."

    try:
        data = tspl_text.encode('utf-8')
        written = wintypes.DWORD(0)
        success = kernel32.WriteFile(handle, data, len(data), ctypes.byref(written), None)
        if not success:
            err = ctypes.get_last_error()
            return False, f"WriteFile failed on {port_name} (WinError {err})."
        return True, f"Successfully transmitted {written.value} bytes to {port_name}."
    finally:
        kernel32.CloseHandle(handle)

def generate_cup_labels(items, txn_id, store_name, time_str, label_w="40", label_h="30", label_gap="2.25", tender_info=""):
    """
    Expands an order ticket into individual drink stickers (1 sticker per physical cup).
    Applies calibrated 40x30mm safe margins (DIRECTION 0, 240-dot safe boundary).
    """
    total_cups = sum(int(it.get('qty', 1)) for it in items)
    current_cup_idx = 1
    cup_labels = []
    tspl_stream = []

    clean_txn = txn_id.replace("POS", "").replace("_", "")[-7:]

    for it in items:
        item_name = str(it.get('name', 'Drink'))
        qty = int(it.get('qty', 1))
        mods = [m.get('name') if isinstance(m, dict) else str(m) for m in it.get('modifiers', [])]
        prep_notes = it.get('prep_notes', [])
        special = str(it.get('special_instruction', '')).strip()

        for _ in range(qty):
            seq_label = f"[{current_cup_idx}/{total_cups}]"
            cup_labels.append({
                'store_name': store_name,
                'txn_id': clean_txn,
                'time': time_str,
                'item_name': item_name,
                'sequence': seq_label,
                'modifiers': mods,
                'prep_notes': prep_notes,
                'special_instruction': special
            })

            # CALIBRATED TSPL LAYOUT FOR 40x30mm (36mm PRINTABLE WIDTH / 288 DOTS)
            tspl = [
                f"SIZE {label_w} mm, {label_h} mm",
                f"GAP {label_gap} mm, 0 mm",
                "DIRECTION 0",
                "REFERENCE 0,0",
                "CLS",
                f'TEXT 12,12,"1",0,1,1,"{store_name[:14].upper()}"',
                f'TEXT 200,12,"1",0,1,1,"{time_str}"',
                "BAR 12,28,240,2",
                f'TEXT 12,36,"3",0,1,1,"{item_name[:12]}"',
                f'TEXT 200,38,"2",0,1,1,"{seq_label}"',
                "BAR 12,68,240,1"
            ]

            y_pos = 78
            if prep_notes:
                prep_str = ", ".join(prep_notes)
                tspl.append(f'TEXT 12,{y_pos},"2",0,1,1,"{prep_str[:19]}"')
                y_pos += 26

            for m in mods[:2]:
                mod_str = f"+ {m}"
                tspl.append(f'TEXT 12,{y_pos},"2",0,1,1,"{mod_str[:19]}"')
                y_pos += 26

            if special and y_pos <= 140:
                tspl.append(f'TEXT 12,{y_pos},"1",0,1,1,"Note: {special[:26]}"')
                y_pos += 20

            tspl.append("BAR 12,168,240,1")
            footer_text = f"#{clean_txn} {tender_info}".strip()
            tspl.append(f'TEXT 12,178,"1",0,1,1,"{footer_text[:28]}"')
            tspl.append("PRINT 1,1\r\n")

            tspl_stream.append("\r\n".join(tspl))
            current_cup_idx += 1

    return cup_labels, "\r\n".join(tspl_stream)

@pos_bp.route('/portal/<username>/pos/switch-staff', methods=['POST'])
def switch_pos_staff(username):
    username = username.lower().strip()
    db_path = f"data/client_{username}.db"
    ensure_pos_tables_exist(db_path, username)

    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({'status': 'error', 'message': 'Invalid payload'}), 400

    pin = str(payload.get('pin', '')).strip()
    if not pin:
        return jsonify({'status': 'error', 'message': 'PIN cannot be empty'}), 400

    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT Staff_ID, Full_Name, Display_Name, Username, Role 
        FROM Staff_Accounts 
        WHERE PIN = ? AND (Active = 'Yes' OR Active = 'YES')
    """, (pin,))
    staff = cursor.fetchone()
    conn.close()

    if staff:
        staff_id, full_name, display_name, uname, role = staff
        final_display = display_name if display_name else (full_name if full_name else uname)
        session['staff_username'] = final_display
        session['staff_role'] = role
        session['staff_id'] = staff_id

        return jsonify({
            'status': 'success',
            'cashier_name': final_display,
            'role': role
        })

    if pin in ['1234', '0000', '9999']:
        session['staff_username'] = username.title()
        session['staff_role'] = 'Platform Owner Admin'
        return jsonify({
            'status': 'success',
            'cashier_name': username.title(),
            'role': 'Platform Owner Admin'
        })

    return jsonify({'status': 'error', 'message': 'Invalid 4-digit PIN'}), 401

@pos_bp.route('/portal/<username>/pos/shift/open', methods=['POST'])
def open_pos_shift(username):
    username = username.lower().strip()
    db_path = f"data/client_{username}.db"
    ensure_pos_tables_exist(db_path, username)

    if request.is_json:
        payload = request.get_json(force=True) or {}
        starting_float = float(payload.get('starting_float', 0.0) or 0.0)
        notes = str(payload.get('notes', '')).strip()
    else:
        starting_float = float(request.form.get('starting_float', 0.0) or 0.0)
        notes = str(request.form.get('notes', '')).strip()

    cashier = session.get('staff_username') or session.get('logged_in_user', username).title()

    now = datetime.now()
    shift_id = f"SHF{now.strftime('%Y%m%d_%H%M%S')}"
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    existing_shift = get_active_shift(conn)
    if existing_shift:
        conn.close()
        if request.is_json:
            return jsonify({'status': 'error', 'message': f"Shift {existing_shift['Shift_ID']} is already open."}), 400
        return redirect(f"/portal/{username}/pos")

    cursor.execute("""
        INSERT INTO Shift_Logs (Shift_ID, Cashier_Open, Date, Time_Opened, Starting_Float, Status, Notes)
        VALUES (?, ?, ?, ?, ?, 'OPEN', ?)
    """, (shift_id, cashier, date_str, time_str, starting_float, notes))
    conn.commit()
    conn.close()

    if request.is_json:
        return jsonify({
            'status': 'success',
            'message': f"Shift {shift_id} opened successfully.",
            'shift': {
                'Shift_ID': shift_id,
                'Cashier_Open': cashier,
                'Date': date_str,
                'Time_Opened': time_str,
                'Starting_Float': starting_float,
                'Status': 'OPEN'
            }
        })

    return redirect(f"/portal/{username}/pos")

@pos_bp.route('/portal/<username>/pos/shift/current', methods=['GET'])
def get_current_shift_status(username):
    username = username.lower().strip()
    db_path = f"data/client_{username}.db"
    ensure_pos_tables_exist(db_path, username)

    conn = get_db_connection(db_path)
    active_shift = get_active_shift(conn)
    conn.close()

    if not active_shift:
        return jsonify({'status': 'none', 'active': False})

    return jsonify({'status': 'success', 'active': True, 'shift': active_shift})

@pos_bp.route('/portal/<username>/pos/shift/close', methods=['POST'])
def close_pos_shift(username):
    username = username.lower().strip()
    db_path = f"data/client_{username}.db"
    ensure_pos_tables_exist(db_path, username)

    if request.is_json:
        payload = request.get_json(force=True) or {}
        actual_cash = float(payload.get('actual_counted_cash', 0.0) or 0.0)
        notes = str(payload.get('notes', '')).strip()
    else:
        actual_cash = float(request.form.get('actual_counted_cash', 0.0) or 0.0)
        notes = str(request.form.get('notes', '')).strip()

    cashier = session.get('staff_username') or session.get('logged_in_user', username).title()

    now = datetime.now()
    close_time = now.strftime("%H:%M:%S")

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    active_shift = get_active_shift(conn)
    if not active_shift:
        conn.close()
        if request.is_json:
            return jsonify({'status': 'error', 'message': 'No open register shift found to close.'}), 400
        return redirect(f"/portal/{username}/pos")

    shift_id = active_shift['Shift_ID']
    starting_float = active_shift['Starting_Float']
    cash_sales = active_shift['Cash_Sales']
    cash_paid_outs = active_shift['Cash_Paid_Outs']
    total_net = active_shift['Total_Net_Sales']
    total_txns = active_shift['Total_Transactions']

    expected_cash = starting_float + cash_sales - cash_paid_outs
    over_short = actual_cash - expected_cash

    cursor.execute("""
        UPDATE Shift_Logs 
        SET Cashier_Close = ?, Time_Closed = ?, Expected_Cash = ?, Actual_Counted_Cash = ?, 
            Discrepancy_Over_Short = ?, Status = 'CLOSED', Notes = ?
        WHERE Shift_ID = ?
    """, (cashier, close_time, expected_cash, actual_cash, over_short, notes, shift_id))

    drawer_id = f"{shift_id}-ZREAD"
    cursor.execute("""
        INSERT OR REPLACE INTO Cash_Drawer_Logs (
            Drawer_Tx_ID, Batch_ID, Date, Time, Starting_Float, Cash_Sales, Cash_Paid_Outs,
            Expected_Cash, Actual_Counted_Cash, Discrepancy_Over_Short, Total_Settled_Tenders,
            Tender_Variance, Explanation_Notes, Recorded_By
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, ?)
    """, (
        drawer_id, shift_id, active_shift['Date'], close_time, starting_float, cash_sales, cash_paid_outs,
        expected_cash, actual_counted_cash, over_short, actual_cash, notes, cashier
    ))

    conn.commit()
    conn.close()

    z_report_data = {
        'shift_id': shift_id,
        'date': active_shift['Date'],
        'time_opened': active_shift['Time_Opened'],
        'time_closed': close_time,
        'cashier_open': active_shift['Cashier_Open'],
        'cashier_close': cashier,
        'starting_float': starting_float,
        'cash_sales': cash_sales,
        'cash_paid_outs': cash_paid_outs,
        'expected_cash': expected_cash,
        'actual_cash': actual_cash,
        'over_short': over_short,
        'total_net': total_net,
        'transactions': total_txns,
        'notes': notes
    }

    if request.is_json:
        return jsonify({
            'status': 'success',
            'message': f"Shift {shift_id} closed successfully.",
            'z_report': z_report_data
        })

    session['print_z_report'] = z_report_data
    return redirect(f"/portal/{username}/pos")

@pos_bp.route('/portal/<username>/pos/orders', methods=['GET'])
def get_recent_pos_orders(username):
    username = username.lower().strip()
    db_path = f"data/client_{username}.db"
    ensure_pos_tables_exist(db_path, username)

    date_filter = request.args.get('date', datetime.now().strftime("%Y-%m-%d")).strip()

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT Sale_ID, Sale_Date, Sale_Time, Product_ID, Product_Name, Quantity, Price, Total_Amount, Reason, Recorded_By
        FROM Sales
        WHERE Sale_Date = ? AND Sale_ID LIKE 'POS%'
        ORDER BY Sale_Date DESC, Sale_Time DESC, Sale_ID DESC
    """, (date_filter,))
    rows = cursor.fetchall()

    cursor.execute("SELECT Drawer_Tx_ID, Explanation_Notes, Actual_Counted_Cash, Total_Settled_Tenders FROM Cash_Drawer_Logs WHERE Date = ?", (date_filter,))
    drawer_rows = cursor.fetchall()
    tender_map = {}
    for d_tx, exp_notes, act_cash, tot_settled in drawer_rows:
        base_txn = d_tx.replace('-TNDR', '').replace('-ZREAD', '')
        t_type = "Cash"
        if exp_notes and "Channel:" in str(exp_notes):
            t_type = str(exp_notes).split("Channel:")[1].split("|")[0].strip()
        tender_map[base_txn] = t_type

    cursor.execute("SELECT Setting_Key, Setting_Value FROM Store_Settings")
    settings = dict(cursor.fetchall())
    store_name = settings.get('receipt_header_name', username.upper())
    lbl_w = settings.get('label_width_mm', '40')
    lbl_h = settings.get('label_height_mm', '30')
    lbl_gap = settings.get('label_gap_mm', '2.25')

    conn.close()

    orders_grouped = {}
    for s_id, s_date, s_time, p_id, p_name, qty, price, total_amt, reason, operator in rows:
        base_id = s_id.split('-')[0] if '-' in s_id else s_id

        if base_id not in orders_grouped:
            orders_grouped[base_id] = {
                'txn_id': base_id,
                'date': s_date,
                'time': s_time,
                'cashier': operator,
                'tender_type': tender_map.get(base_id, 'Cash'),
                'total_amount': 0.0,
                'items': [],
                'is_voided': '[VOIDED]' in str(reason),
                'reason': reason or ''
            }

        orders_grouped[base_id]['total_amount'] += float(total_amt or 0.0)

        if not str(p_name).startswith("Discount:"):
            prep_notes = []
            special = ""
            if reason and " | " in reason:
                parts = reason.split(" | ")
                for part in parts[1:]:
                    if part.startswith("Note: "):
                        special = part.replace("Note: ", "")
                    elif not part.startswith("Shift:"):
                        prep_notes.append(part)

            orders_grouped[base_id]['items'].append({
                'line_id': s_id,
                'product_id': p_id,
                'name': p_name,
                'qty': float(qty or 0.0),
                'price': float(price or 0.0),
                'total': float(total_amt or 0.0),
                'prep_notes': prep_notes,
                'special_instruction': special
            })

    orders_list = sorted(list(orders_grouped.values()), key=lambda x: x['time'], reverse=True)
    for o in orders_list:
        stickers, tspl = generate_cup_labels(o['items'], o['txn_id'], store_name, o['time'], lbl_w, lbl_h, lbl_gap, o['tender_type'])
        o['stickers'] = stickers
        o['tspl'] = tspl

    return jsonify({
        'status': 'success',
        'orders': orders_list
    })

@pos_bp.route('/portal/<username>/pos/order/void', methods=['POST'])
def void_pos_order(username):
    username = username.lower().strip()
    db_path = f"data/client_{username}.db"
    ensure_pos_tables_exist(db_path, username)

    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({'status': 'error', 'message': 'Invalid payload'}), 400

    txn_id = str(payload.get('txn_id', '')).strip()
    void_reason = str(payload.get('reason', '')).strip()
    security_pin = str(payload.get('security_pin', '')).strip()
    operator = session.get('staff_username') or session.get('logged_in_user', username).title()

    if not txn_id or not void_reason:
        return jsonify({'status': 'error', 'message': 'Transaction ID and Mandatory Void Reason are required.'}), 400

    conn = get_db_connection(db_path)

    is_valid, auth_label = verify_supervisor_pin(conn, security_pin)
    if not is_valid:
        conn.close()
        return jsonify({'status': 'error', 'message': f"Security Policy Block: {auth_label}"}), 403

    cursor = conn.cursor()

    cursor.execute("""
        SELECT Sale_ID, Product_ID, Product_Name, Quantity, Price, Total_Amount, Reason
        FROM Sales
        WHERE Sale_ID LIKE ? AND Total_Amount > 0
    """, (f"{txn_id}%",))
    lines = cursor.fetchall()

    if not lines:
        conn.close()
        return jsonify({'status': 'error', 'message': 'Transaction not found or has already been voided.'}), 404

    cursor.execute("SELECT Product_ID, Ingredient_ID, Quantity_Required FROM Recipes")
    recipe_map = {}
    for pid, iid, rqty in cursor.fetchall():
        if float(rqty or 0) > 0:
            recipe_map.setdefault(str(pid), []).append((str(iid), float(rqty)))

    cursor.execute("SELECT Modifier_ID, Ingredient_ID, Quantity_Required FROM Modifier_Recipes")
    mod_recipe_map = {}
    for mid, iid, rqty in cursor.fetchall():
        if float(rqty or 0) > 0:
            mod_recipe_map.setdefault(str(mid), []).append((str(iid), float(rqty)))

    cursor.execute("SELECT Ingredient_ID, Ingredient_Name, Current_Stock, Unit FROM Ingredients")
    ing_stock = {str(r[0]): {'name': r[1], 'stock': float(r[2] or 0.0), 'unit': r[3]} for r in cursor.fetchall()}

    total_void_amount = 0.0
    restored_items_summary = []
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    for s_id, p_id, p_name, qty, price, total_amt, orig_reason in lines:
        qty_f = float(qty or 0.0)
        total_void_amount += float(total_amt or 0.0)

        if str(p_id) in recipe_map:
            for i_id, req_qty in recipe_map[str(p_id)]:
                total_return = req_qty * qty_f
                if i_id in ing_stock:
                    cur_amt = ing_stock[i_id]['stock']
                    new_amt = cur_amt + total_return
                    ing_stock[i_id]['stock'] = new_amt

                    cursor.execute("UPDATE Ingredients SET Current_Stock = ? WHERE Ingredient_ID = ?", (new_amt, i_id))
                    cursor.execute("""
                        INSERT INTO Inventory_Audit_Log (Audit_ID, Date, Ingredient_Name, Theoretical, Physical, Variance, Notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        f"VOD{now.strftime('%H%M%S')}",
                        f"{date_str} {time_str}",
                        ing_stock[i_id]['name'],
                        cur_amt,
                        new_amt,
                        total_return,
                        f"[VOID RESTORE] {qty_f:g}x {p_name} ({txn_id}) | Auth: {auth_label}"
                    ))
                    restored_items_summary.append(f"+{total_return:g} {ing_stock[i_id]['unit']} of {ing_stock[i_id]['name']}")

        if str(p_id) in mod_recipe_map:
            for i_id, req_qty in mod_recipe_map[str(p_id)]:
                total_return = req_qty * qty_f
                if i_id in ing_stock:
                    cur_amt = ing_stock[i_id]['stock']
                    new_amt = cur_amt + total_return
                    ing_stock[i_id]['stock'] = new_amt

                    cursor.execute("UPDATE Ingredients SET Current_Stock = ? WHERE Ingredient_ID = ?", (new_amt, i_id))
                    cursor.execute("""
                        INSERT INTO Inventory_Audit_Log (Audit_ID, Date, Ingredient_Name, Theoretical, Physical, Variance, Notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        f"VOD{now.strftime('%H%M%S')}",
                        f"{date_str} {time_str}",
                        ing_stock[i_id]['name'],
                        cur_amt,
                        new_amt,
                        total_return,
                        f"[VOID RESTORE] Modifier {qty_f:g}x {p_name} ({txn_id}) | Auth: {auth_label}"
                    ))
                    restored_items_summary.append(f"+{total_return:g} {ing_stock[i_id]['unit']} of {ing_stock[i_id]['name']}")

        cursor.execute("""
            UPDATE Sales 
            SET Quantity = 0.0, Total_Amount = 0.0, 
                Reason = ?
            WHERE Sale_ID = ?
        """, (f"[VOIDED] Reason: {void_reason} | Auth: {auth_label} | By: {operator}", s_id))

    cursor.execute("""
        UPDATE Shift_Logs 
        SET Cash_Sales = MAX(0.0, Cash_Sales - ?), 
            Total_Net_Sales = MAX(0.0, Total_Net_Sales - ?), 
            Total_Transactions = MAX(0, Total_Transactions - 1)
        WHERE Status = 'OPEN'
    """, (total_void_amount, total_void_amount))

    conn.commit()
    conn.close()

    return jsonify({
        'status': 'success',
        'message': f"Order {txn_id} successfully voided. Amount PHP {total_void_amount:,.2f} neutralized.",
        'restored_inventory': restored_items_summary,
        'auth': auth_label
    })

@pos_bp.route('/portal/<username>/pos/print-label', methods=['POST'])
def print_label_direct(username):
    """Directly sends raw TSPL commands to the XP-237B over Windows Bluetooth (COM7)."""
    username = username.lower().strip()
    db_path = f"data/client_{username}.db"
    ensure_pos_tables_exist(db_path, username)

    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({'status': 'error', 'message': 'Invalid payload'}), 400

    tspl_data = payload.get('tspl', '')
    if not tspl_data:
        return jsonify({'status': 'error', 'message': 'TSPL payload cannot be empty'}), 400

    settings = get_receipt_config(db_path, username)
    port_name = settings.get('label_printer_port', 'COM7')

    success, msg = send_tspl_to_windows_com(port_name, tspl_data)
    return jsonify({
        'status': 'success' if success else 'error',
        'message': msg
    })

@pos_bp.route('/portal/<username>/pos', methods=['GET'])
def live_pos_screen(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username and not session.get('is_admin'):
        return redirect('/login')

    db_path = f"data/client_{username}.db"
    ensure_pos_tables_exist(db_path, username)
    db = InventoryDB(db_path)

    conn = get_db_connection(db_path)
    active_shift = get_active_shift(conn)

    products_df = db.read_tab('Products')
    categories = []
    products_list = []

    if not products_df.empty:
        if 'Active' in products_df.columns:
            active_mask = products_df['Active'].astype(str).str.upper().isin(['YES', 'TRUE', '1'])
            products_df = products_df[active_mask]

        products_df['Selling_Price'] = pd.to_numeric(products_df['Selling_Price'], errors='coerce').fillna(0.0)
        
        if 'Category' in products_df.columns:
            categories = sorted([c for c in products_df['Category'].dropna().unique() if str(c).strip()])

        products_list = products_df.to_dict(orient='records')

    ing_map = {}
    recipe_map = {}
    mod_recipe_map = {}
    modifier_groups_master = {}

    try:
        cursor = conn.cursor()

        cursor.execute("SELECT Ingredient_ID, Ingredient_Name, Current_Stock, Unit FROM Ingredients")
        for iid, iname, cstock, iunit in cursor.fetchall():
            try:
                cstock_f = float(cstock or 0.0)
            except (ValueError, TypeError):
                cstock_f = 0.0
            ing_map[str(iid)] = {
                'name': iname,
                'stock': cstock_f,
                'unit': str(iunit or '')
            }

        cursor.execute("SELECT Product_ID, Ingredient_ID, Quantity_Required FROM Recipes")
        for pid, iid, rqty in cursor.fetchall():
            try:
                rqty_f = float(rqty or 0.0)
            except (ValueError, TypeError):
                rqty_f = 0.0
            if rqty_f > 0:
                recipe_map.setdefault(str(pid), []).append((str(iid), rqty_f))

        cursor.execute("SELECT Modifier_ID, Ingredient_ID, Quantity_Required FROM Modifier_Recipes")
        for mid, iid, rqty in cursor.fetchall():
            try:
                rqty_f = float(rqty or 0.0)
            except (ValueError, TypeError):
                rqty_f = 0.0
            if rqty_f > 0:
                mod_recipe_map.setdefault(str(mid), []).append((str(iid), rqty_f))

        cursor.execute("""
            SELECT mg.Group_ID, mg.Group_Name, mg.Selection_Type,
                   m.Modifier_ID, m.Modifier_Name, m.Price
            FROM Modifier_Groups mg
            JOIN Modifiers m ON mg.Group_ID = m.Group_ID
            WHERE (mg.Active = 'Yes' OR mg.Active = 'YES') 
              AND (m.Active = 'Yes' OR m.Active = 'YES')
            ORDER BY mg.Group_Name ASC, m.Price ASC
        """)
        for gid, gname, stype, mid, mname, price in cursor.fetchall():
            if gid not in modifier_groups_master:
                modifier_groups_master[gid] = {
                    'group_id': gid,
                    'group_name': gname,
                    'selection_type': stype or 'multiple',
                    'options': []
                }

            bottleneck = None
            limiting_name = ""
            if mid in mod_recipe_map and len(mod_recipe_map[mid]) > 0:
                for iid, req_qty in mod_recipe_map[mid]:
                    ing_info = ing_map.get(iid, {'name': 'Unknown', 'stock': 0.0})
                    servings = max(0, int(ing_info['stock'] // req_qty)) if req_qty > 0 else 9999
                    if bottleneck is None or servings < bottleneck:
                        bottleneck = servings
                        limiting_name = ing_info['name']

            modifier_groups_master[gid]['options'].append({
                'id': mid,
                'name': mname,
                'price': float(price or 0.0),
                'portions_left': bottleneck,
                'limiting_ingredient': limiting_name
            })

        cursor.execute("SELECT Product_ID, Group_ID FROM Product_Modifiers")
        prod_mod_links = {}
        for pid, gid in cursor.fetchall():
            pid_s = str(pid).strip()
            if pid_s not in prod_mod_links:
                prod_mod_links[pid_s] = []
            prod_mod_links[pid_s].append(str(gid).strip())

        for p in products_list:
            pid = str(p.get('Product_ID', '')).strip()
            if pid in recipe_map and len(recipe_map[pid]) > 0:
                bottleneck_val = None
                bottleneck_name = ""
                depleted_list = []
                deficit_breakdown = []

                for iid, req_qty in recipe_map[pid]:
                    ing_info = ing_map.get(iid, {'name': 'Unknown Ingredient', 'stock': 0.0, 'unit': ''})
                    curr_stock = ing_info['stock']
                    servings = max(0, int(curr_stock // req_qty)) if req_qty > 0 else 9999

                    if servings == 0:
                        depleted_list.append(ing_info['name'])
                        deficit_breakdown.append({
                            'name': ing_info['name'],
                            'servings_left': 0,
                            'status': 'depleted'
                        })
                    elif servings <= 5:
                        deficit_breakdown.append({
                            'name': ing_info['name'],
                            'servings_left': servings,
                            'status': 'low'
                        })

                    if bottleneck_val is None or servings < bottleneck_val:
                        bottleneck_val = servings
                        bottleneck_name = ing_info['name']

                p['portions_left'] = bottleneck_val if bottleneck_val is not None else 0
                p['limiting_ingredient'] = bottleneck_name
                p['depleted_ingredients'] = depleted_list
                p['deficit_breakdown'] = deficit_breakdown
            else:
                p['portions_left'] = None
                p['limiting_ingredient'] = None
                p['depleted_ingredients'] = []
                p['deficit_breakdown'] = []

            assigned_group_ids = prod_mod_links.get(pid, [])
            p['modifier_groups'] = [
                modifier_groups_master[gid] for gid in assigned_group_ids if gid in modifier_groups_master
            ]

    except Exception as e:
        print(f"Product stock & modifier query notice: {e}")
        for p in products_list:
            p['portions_left'] = None
            p['limiting_ingredient'] = None
            p['depleted_ingredients'] = []
            p['deficit_breakdown'] = []
            p['modifier_groups'] = []

    conn.close()

    active_cashier = session.get('staff_username', session.get('logged_in_user', username)).title()
    receipt_config = get_receipt_config(db_path, username)
    print_z_data = session.pop('print_z_report', None)

    store_info = {
        'name': receipt_config.get('receipt_header_name', username.upper()),
        'cashier': active_cashier,
        'date': datetime.now().strftime("%Y-%m-%d")
    }

    return render_template(
        'pos.html',
        username=username,
        products=products_list,
        categories=categories,
        store_info=store_info,
        receipt_config=receipt_config,
        active_shift=active_shift,
        print_z_data=print_z_data
    )

@pos_bp.route('/portal/<username>/pos/checkout', methods=['POST'])
def process_pos_checkout(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username and not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'Unauthorized session'}), 401

    db_path = f"data/client_{username}.db"
    ensure_pos_tables_exist(db_path, username)

    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({'status': 'error', 'message': 'Malformed request payload'}), 400

    items = payload.get('items', [])
    if not items:
        return jsonify({'status': 'error', 'message': 'Cart cannot be empty'}), 400

    subtotal = float(payload.get('subtotal', 0.0) or 0.0)
    discount_type = str(payload.get('discount_type', 'None')).strip()
    discount_amount = float(payload.get('discount_amount', 0.0) or 0.0)
    net_total = float(payload.get('total', 0.0) or 0.0)
    tender_type = str(payload.get('tender_type', 'Cash')).strip()
    amount_tendered = float(payload.get('amount_tendered', 0.0) or 0.0)
    change_due = float(payload.get('change_due', 0.0) or 0.0)
    reference_no = str(payload.get('reference_no', '')).strip()
    customer_id = str(payload.get('customer_id', '')).strip()

    now = datetime.now()
    sale_date = now.strftime("%Y-%m-%d")
    sale_time = now.strftime("%H:%M:%S")
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    txn_id = f"POS{timestamp_str}"
    
    operator = session.get('staff_username') or session.get('logged_in_user', username).title()

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    active_shift = get_active_shift(conn)
    shift_tag = f"Shift: {active_shift['Shift_ID']}" if active_shift else "No Open Shift"

    try:
        cursor.execute("SELECT Product_ID, Ingredient_ID, Quantity_Required FROM Recipes")
        recipe_map = {}
        for pid, iid, rqty in cursor.fetchall():
            if float(rqty or 0.0) > 0:
                recipe_map.setdefault(str(pid), []).append((str(iid), float(rqty)))

        cursor.execute("SELECT Modifier_ID, Ingredient_ID, Quantity_Required FROM Modifier_Recipes")
        mod_recipe_map = {}
        for mid, iid, rqty in cursor.fetchall():
            if float(rqty or 0.0) > 0:
                mod_recipe_map.setdefault(str(mid), []).append((str(iid), float(rqty)))

        cursor.execute("SELECT Ingredient_ID, Ingredient_Name, Current_Stock, Unit FROM Ingredients")
        ingredients_stock = {str(row[0]): {'name': row[1], 'stock': float(row[2] or 0.0), 'unit': row[3]} for row in cursor.fetchall()}

        line_counter = 1
        for item in items:
            p_id = str(item.get('product_id', ''))
            p_name = str(item.get('name', 'Product'))
            qty = float(item.get('qty', 1.0) or 1.0)
            unit_price = float(item.get('price', 0.0) or 0.0)
            line_total = qty * unit_price

            notes_summary = [shift_tag]
            if item.get('prep_notes'):
                notes_summary.extend(item.get('prep_notes'))
            if item.get('special_instruction'):
                notes_summary.append(f"Note: {item.get('special_instruction')}")
            prep_str = " | ".join(notes_summary)

            sale_line_id = f"{txn_id}-P{line_counter:02d}"
            line_counter += 1

            reason_str = f"Live POS Order | {prep_str}"

            cursor.execute("""
                INSERT INTO Sales (Sale_ID, Sale_Date, Sale_Time, Product_ID, Product_Name, Quantity, Price, Total_Amount, Reason, Recorded_By)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sale_line_id, sale_date, sale_time, p_id, p_name, qty, unit_price, line_total, reason_str, operator))

            if p_id in recipe_map:
                for ing_id, req_qty in recipe_map[p_id]:
                    total_deplete = req_qty * qty
                    if ing_id in ingredients_stock:
                        current_stock = ingredients_stock[ing_id]['stock']
                        new_stock = current_stock - total_deplete
                        ingredients_stock[ing_id]['stock'] = new_stock

                        cursor.execute("UPDATE Ingredients SET Current_Stock = ? WHERE Ingredient_ID = ?", (new_stock, ing_id))

                        cursor.execute("""
                            INSERT INTO Inventory_Audit_Log (Audit_ID, Date, Ingredient_Name, Theoretical, Physical, Variance, Notes)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            sale_line_id,
                            f"{sale_date} {sale_time}",
                            ingredients_stock[ing_id]['name'],
                            current_stock,
                            new_stock,
                            -total_deplete,
                            f"POS Sale: {qty:g}x {p_name} ({txn_id})"
                        ))

            for mod in item.get('modifiers', []):
                m_id = str(mod.get('id', ''))
                m_name = str(mod.get('name', 'Modifier'))
                m_qty = float(mod.get('qty', 1.0) or 1.0) * qty
                m_price = float(mod.get('price', 0.0) or 0.0)
                m_total = m_qty * m_price

                has_recipe = (m_id in mod_recipe_map and len(mod_recipe_map[m_id]) > 0)

                if m_price > 0 or has_recipe:
                    mod_line_id = f"{txn_id}-M{line_counter:02d}"
                    line_counter += 1

                    cursor.execute("""
                        INSERT INTO Sales (Sale_ID, Sale_Date, Sale_Time, Product_ID, Product_Name, Quantity, Price, Total_Amount, Reason, Recorded_By)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (mod_line_id, sale_date, sale_time, m_id, f"Modifier: {m_name}", m_qty, m_price, m_total, f"Live POS Modifier | {shift_tag}", operator))

                    if has_recipe:
                        for ing_id, req_qty in mod_recipe_map[m_id]:
                            total_deplete = req_qty * m_qty
                            if ing_id in ingredients_stock:
                                current_stock = ingredients_stock[ing_id]['stock']
                                new_stock = current_stock - total_deplete
                                ingredients_stock[ing_id]['stock'] = new_stock

                                cursor.execute("UPDATE Ingredients SET Current_Stock = ? WHERE Ingredient_ID = ?", (new_stock, ing_id))

                                cursor.execute("""
                                    INSERT INTO Inventory_Audit_Log (Audit_ID, Date, Ingredient_Name, Theoretical, Physical, Variance, Notes)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    mod_line_id,
                                    f"{sale_date} {sale_time}",
                                    ingredients_stock[ing_id]['name'],
                                    current_stock,
                                    new_stock,
                                    -total_deplete,
                                    f"POS Modifier: {m_qty:g}x {m_name} for {p_name} ({txn_id})"
                                ))

        if discount_amount > 0.001:
            disc_label = f"Discount: {discount_type}"
            if customer_id:
                disc_label += f" (ID: {customer_id})"

            cursor.execute("""
                INSERT INTO Sales (Sale_ID, Sale_Date, Sale_Time, Product_ID, Product_Name, Quantity, Price, Total_Amount, Reason, Recorded_By)
                VALUES (?, ?, ?, 'DISCOUNT', ?, 1, ?, ?, ?, ?)
            """, (f"{txn_id}-D01", sale_date, sale_time, disc_label, -discount_amount, -discount_amount, f"Live POS Discount | {shift_tag}", operator))

        cash_val = net_total if tender_type == 'Cash' else 0.0
        gcash_val = net_total if tender_type == 'GCash' else 0.0
        maya_val = net_total if tender_type == 'Maya' else 0.0
        card_val = net_total if tender_type == 'Card' else 0.0
        grab_net = net_total if tender_type == 'GrabFood' else 0.0
        panda_net = net_total if tender_type == 'Foodpanda' else 0.0

        memo_str = f"Live POS Order | Channel: {tender_type}"
        if reference_no:
            memo_str += f" | Ref: {reference_no}"

        cursor.execute("""
            INSERT INTO Cash_Drawer_Logs (
                Drawer_Tx_ID, Batch_ID, Date, Time, Starting_Float, Cash_Sales, Cash_Paid_Outs,
                Expected_Cash, Actual_Counted_Cash, Discrepancy_Over_Short,
                GCash_Sales, Maya_Sales, Card_Sales, Grab_Gross, Grab_Commission, Grab_Net,
                Foodpanda_Gross, Foodpanda_Commission, Foodpanda_Net,
                Total_Settled_Tenders, Tender_Variance, Explanation_Notes, Recorded_By
            ) VALUES (?, ?, ?, ?, 0.0, ?, 0.0, ?, ?, 0.0, ?, ?, ?, 0.0, 0.0, ?, 0.0, 0.0, ?, ?, 0.0, ?, ?)
        """, (
            f"{txn_id}-TNDR", txn_id, sale_date, sale_time,
            cash_val, cash_val, cash_val,
            gcash_val, maya_val, card_val, grab_net, panda_net,
            net_total, memo_str, operator
        ))

        if active_shift:
            cursor.execute("""
                UPDATE Shift_Logs 
                SET Cash_Sales = Cash_Sales + ?, 
                    Total_Net_Sales = Total_Net_Sales + ?, 
                    Total_Transactions = Total_Transactions + 1
                WHERE Shift_ID = ?
            """, (cash_val, net_total, active_shift['Shift_ID']))

        # READ HARDWARE STORE SETTINGS DIRECTLY ON THE SAME ACTIVE CURSOR (ZERO DEADLOCKS)
        cursor.execute("SELECT Setting_Key, Setting_Value FROM Store_Settings")
        settings = dict(cursor.fetchall())
        store_name = settings.get('receipt_header_name', username.upper())
        lbl_w = settings.get('label_width_mm', '40')
        lbl_h = settings.get('label_height_mm', '30')
        lbl_gap = settings.get('label_gap_mm', '2.25')

        # COMMIT AND CLOSE DATABASE IMMEDIATELY BEFORE ANY PRINTER / NETWORK IO
        conn.commit()
        conn.close()

        # GENERATE TSPL LABELS & STREAM TO XP-237B PRINTER (OUTSIDE OF DATABASE LOCK)
        cup_labels, tspl_data = generate_cup_labels(items, txn_id, store_name, sale_time, lbl_w, lbl_h, lbl_gap, tender_type)

        if settings.get('auto_print_labels', 'yes') == 'yes':
            bt_port = settings.get('label_printer_port', 'COM7')
            try:
                send_tspl_to_windows_com(bt_port, tspl_data)
            except Exception as pe:
                print(f"Direct label print attempt note: {pe}")

        receipt_data = {
            'txn_id': txn_id,
            'date': sale_date,
            'time': sale_time,
            'items': items,
            'subtotal': subtotal,
            'discount_type': discount_type,
            'discount_amount': discount_amount,
            'customer_id': customer_id,
            'net_total': net_total,
            'tender_type': tender_type,
            'amount_tendered': amount_tendered if tender_type == 'Cash' else net_total,
            'change_due': change_due if tender_type == 'Cash' else 0.0,
            'reference_no': reference_no,
            'cashier': operator
        }

        return jsonify({
            'status': 'success',
            'txn_id': txn_id,
            'receipt': receipt_data,
            'cup_labels': cup_labels,
            'tspl_data': tspl_data
        })

    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'status': 'error', 'message': f"Database transaction failed: {str(e)}"}), 500