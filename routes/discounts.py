# routes/discounts.py - Global Standard POS Discounts & Statutory Compliance Engine
from flask import Blueprint, request, redirect, session, render_template, flash
from modules.database import InventoryDB
import pandas as pd
import sqlite3
import urllib.parse

discounts_bp = Blueprint('discounts', __name__)

def ensure_discounts_schema(conn):
    """
    Auto-migrates the Discounts table to enterprise POS specifications.
    Safely adds classification, compliance approval, and status controls.
    """
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Discounts (
            Discount_ID TEXT PRIMARY KEY,
            Discount_Name TEXT,
            Discount_Type TEXT,
            Value REAL,
            Category TEXT DEFAULT 'Promotional / Marketing',
            Requires_Approval TEXT DEFAULT 'No',
            Active TEXT DEFAULT 'Yes'
        )
    """)
    cursor.execute("PRAGMA table_info(Discounts)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    
    needed_cols = {
        'Category': "TEXT DEFAULT 'Promotional / Marketing'",
        'Requires_Approval': "TEXT DEFAULT 'No'",
        'Active': "TEXT DEFAULT 'Yes'"
    }
    for col_name, col_def in needed_cols.items():
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE Discounts ADD COLUMN {col_name} {col_def}")
            
    # Seed default compliance and operational discount presets if empty
    cursor.execute("SELECT COUNT(*) FROM Discounts")
    if cursor.fetchone()[0] == 0:
        presets = [
            ('DSC001', 'Senior Citizen (SC 20%)', 'Percentage', 20.0, 'Statutory (SC/PWD)', 'Yes', 'Yes'),
            ('DSC002', 'Person With Disability (PWD 20%)', 'Percentage', 20.0, 'Statutory (SC/PWD)', 'Yes', 'Yes'),
            ('DSC003', 'Staff Meal Privilege', 'Percentage', 30.0, 'Staff & Internal', 'Yes', 'Yes'),
            ('DSC004', 'VIP / Partner Courtesy', 'Percentage', 10.0, 'Promotional / Marketing', 'No', 'Yes'),
            ('DSC005', 'Opening Voucher Promo', 'Fixed Amount', 50.0, 'Promotional / Marketing', 'No', 'Yes')
        ]
        cursor.executemany("""
            INSERT INTO Discounts (Discount_ID, Discount_Name, Discount_Type, Value, Category, Requires_Approval, Active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, presets)

    conn.commit()

@discounts_bp.route('/portal/<username>/discounts', methods=['GET', 'POST'])
def web_discounts_tab(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username: 
        return redirect('/login')

    # Safeguard: Recognize master tenant account as Platform Owner Admin
    if not session.get('staff_role') and session.get('logged_in_user') == username:
        session['staff_role'] = 'Platform Owner Admin'

    if session.get('staff_role') != 'Platform Owner Admin':
        flash('Unauthorized access: Discounts management is strictly reserved for Platform Owner Admins.', 'danger')
        return redirect(f"/portal/{username}")
    
    client_db_path = f"data/client_{username}.db"
    db = InventoryDB(client_db_path)
    operator = session.get('logged_in_user', username)

    # Ensure table schema and statutory defaults exist
    conn = sqlite3.connect(client_db_path, timeout=20.0)
    ensure_discounts_schema(conn)
    conn.close()

    if request.method == 'POST':
        action = request.form.get('action_type')
        
        # 1. ADD NEW DISCOUNT
        if action == 'add_discount':
            disc_name = request.form.get('discount_name', '').strip()
            disc_type = request.form.get('discount_type', 'Percentage').strip()
            category = request.form.get('category', 'Promotional / Marketing').strip()
            requires_approval = 'Yes' if request.form.get('requires_approval') == 'Yes' else 'No'
            
            try:
                val = float(request.form.get('value', 0.0) or 0.0)
            except (ValueError, TypeError):
                val = 0.0

            if not disc_name:
                return redirect(f"/portal/{username}/discounts?msg=Input Error: Discount name cannot be blank.&alert_type=danger")
            if val <= 0:
                return redirect(f"/portal/{username}/discounts?msg=Input Error: Discount value must be greater than zero.&alert_type=danger")
            if disc_type == 'Percentage' and val > 100:
                return redirect(f"/portal/{username}/discounts?msg=Validation Error: Percentage discount cannot exceed 100%.&alert_type=danger")

            try:
                conn = sqlite3.connect(client_db_path, timeout=20.0)
                cursor = conn.cursor()
                
                # Check duplicate name collision
                cursor.execute("SELECT Discount_ID FROM Discounts WHERE LOWER(TRIM(Discount_Name)) = LOWER(TRIM(?))", (disc_name,))
                if cursor.fetchone():
                    conn.close()
                    return redirect(f"/portal/{username}/discounts?msg=Collision Error: A discount named '{disc_name}' already exists.&alert_type=danger")

                cursor.execute("SELECT Discount_ID FROM Discounts WHERE Discount_ID LIKE 'DSC%';")
                existing_ids = [r[0] for r in cursor.fetchall() if r and r[0]]
                nums = []
                for did in existing_ids:
                    try:
                        nums.append(int(did.replace('DSC', '')))
                    except ValueError:
                        pass
                next_num = max(nums) + 1 if nums else 1
                disc_id = f"DSC{next_num:03d}"

                cursor.execute("""
                    INSERT INTO Discounts (Discount_ID, Discount_Name, Discount_Type, Value, Category, Requires_Approval, Active)
                    VALUES (?, ?, ?, ?, ?, ?, 'Yes')
                """, (disc_id, disc_name, disc_type, val, category, requires_approval))
                conn.commit()
                conn.close()

                if hasattr(db, 'log_user_action'):
                    try:
                        db.log_user_action(operator, "ADD_DISCOUNT", "Discounts", f"Created discount '{disc_name}' ({disc_id}: {val} {disc_type})")
                    except Exception:
                        pass

                return redirect(f"/portal/{username}/discounts?msg=Success: Created discount rule '{disc_name}' ({disc_id}).&alert_type=success")
            except Exception as e:
                return redirect(f"/portal/{username}/discounts?msg=Database Error: {str(e)}&alert_type=danger")

        # 2. EDIT EXISTING DISCOUNT
        elif action == 'edit_discount':
            disc_id = request.form.get('discount_id', '').strip()
            disc_name = request.form.get('discount_name', '').strip()
            disc_type = request.form.get('discount_type', 'Percentage').strip()
            category = request.form.get('category', 'Promotional / Marketing').strip()
            requires_approval = 'Yes' if request.form.get('requires_approval') == 'Yes' else 'No'
            active_status = 'Yes' if request.form.get('active_status') == 'Yes' else 'No'

            try:
                val = float(request.form.get('value', 0.0) or 0.0)
            except (ValueError, TypeError):
                val = 0.0

            if not disc_id or not disc_name:
                return redirect(f"/portal/{username}/discounts?msg=Input Error: Discount ID and name are required.&alert_type=danger")
            if val <= 0:
                return redirect(f"/portal/{username}/discounts?msg=Input Error: Discount value must be greater than zero.&alert_type=danger")
            if disc_type == 'Percentage' and val > 100:
                return redirect(f"/portal/{username}/discounts?msg=Validation Error: Percentage discount cannot exceed 100%.&alert_type=danger")

            try:
                conn = sqlite3.connect(client_db_path, timeout=20.0)
                cursor = conn.cursor()
                
                cursor.execute("SELECT Discount_ID FROM Discounts WHERE LOWER(TRIM(Discount_Name)) = LOWER(TRIM(?)) AND Discount_ID != ?", (disc_name, disc_id))
                if cursor.fetchone():
                    conn.close()
                    return redirect(f"/portal/{username}/discounts?msg=Collision Error: Another discount named '{disc_name}' already exists.&alert_type=danger")

                cursor.execute("""
                    UPDATE Discounts 
                    SET Discount_Name = ?, Discount_Type = ?, Value = ?, Category = ?, Requires_Approval = ?, Active = ?
                    WHERE Discount_ID = ?
                """, (disc_name, disc_type, val, category, requires_approval, active_status, disc_id))
                conn.commit()
                conn.close()

                if hasattr(db, 'log_user_action'):
                    try:
                        db.log_user_action(operator, "EDIT_DISCOUNT", "Discounts", f"Updated discount '{disc_name}' ({disc_id})")
                    except Exception:
                        pass

                return redirect(f"/portal/{username}/discounts?msg=Success: Discount parameters for '{disc_name}' updated successfully.&alert_type=success")
            except Exception as e:
                return redirect(f"/portal/{username}/discounts?msg=Database Error: {str(e)}&alert_type=danger")

        # 3. TOGGLE ACTIVE STATUS (1-CLICK ARCHIVE / REACTIVATE)
        elif action == 'toggle_status':
            disc_id = request.form.get('discount_id', '').strip()
            if disc_id:
                try:
                    conn = sqlite3.connect(client_db_path, timeout=20.0)
                    cursor = conn.cursor()
                    cursor.execute("SELECT Discount_Name, Active FROM Discounts WHERE Discount_ID = ?", (disc_id,))
                    row = cursor.fetchone()
                    if row:
                        current_status = str(row[1] or 'Yes').strip().capitalize()
                        new_status = 'No' if current_status == 'Yes' else 'Yes'
                        cursor.execute("UPDATE Discounts SET Active = ? WHERE Discount_ID = ?", (new_status, disc_id))
                        conn.commit()
                        conn.close()
                        status_label = "activated" if new_status == 'Yes' else "archived"
                        return redirect(f"/portal/{username}/discounts?msg=Status Updated: '{row[0]}' is now {status_label}.&alert_type=info")
                    conn.close()
                except Exception as e:
                    return redirect(f"/portal/{username}/discounts?msg=Database Error: {str(e)}&alert_type=danger")

        # 4. DELETE DISCOUNT
        elif action == 'delete_discount':
            disc_id = request.form.get('discount_id', '').strip()
            if disc_id:
                try:
                    conn = sqlite3.connect(client_db_path, timeout=20.0)
                    cursor = conn.cursor()
                    cursor.execute("SELECT Discount_Name FROM Discounts WHERE Discount_ID = ?", (disc_id,))
                    row = cursor.fetchone()
                    disc_name = row[0] if row else disc_id
                    cursor.execute("DELETE FROM Discounts WHERE Discount_ID = ?", (disc_id,))
                    conn.commit()
                    conn.close()

                    if hasattr(db, 'log_user_action'):
                        try:
                            db.log_user_action(operator, "DELETE_DISCOUNT", "Discounts", f"Deleted discount '{disc_name}' ({disc_id})")
                        except Exception:
                            pass

                    return redirect(f"/portal/{username}/discounts?msg=Deleted: Discount rule '{disc_name}' removed cleanly.&alert_type=warning")
                except Exception as e:
                    return redirect(f"/portal/{username}/discounts?msg=Database Error: {str(e)}&alert_type=danger")

        return redirect(f"/portal/{username}/discounts")

    # ===== GET METHOD: FETCH DATA =====
    discounts_list = []
    try:
        conn = sqlite3.connect(client_db_path, timeout=20.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Discounts ORDER BY Discount_ID ASC")
        rows = cursor.fetchall()
        for r in rows:
            d = dict(r)
            d['Value'] = float(d.get('Value') or 0.0)
            d['Category'] = str(d.get('Category') or 'Promotional / Marketing')
            d['Requires_Approval'] = str(d.get('Requires_Approval') or 'No')
            d['Active'] = str(d.get('Active') or 'Yes')
            discounts_list.append(d)
        conn.close()
    except Exception as e:
        print(f"Error fetching discounts: {e}")

    return render_template(
        'discounts.html',
        username=username,
        discounts=discounts_list,
        msg=request.args.get('msg', ''),
        alert_type=request.args.get('alert_type', 'success')
    )