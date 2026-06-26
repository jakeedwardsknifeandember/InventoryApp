# routes/inventory.py - Stock Inventory Module Blueprint
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
import pandas as pd
from datetime import datetime

inventory_bp = Blueprint('inventory', __name__)

@inventory_bp.route('/portal/<username>/inventory', methods=['GET', 'POST'])
def web_inventory_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    
    feedback_msg = None
    alert_type = "success"
    
    # ===== POST METHODS: BULK OPERATIONAL WAREHOUSE MUTATIONS =====
    if request.method == 'POST':
        action = request.form.get('action_type')
        date_str = datetime.now().strftime("%Y-%m-%d")
        
        ingredients_df = client_db.read_tab('Ingredients')
        audit_ledger_df = client_db.read_tab('Inventory_Audit_Log')
        
        if audit_ledger_df is None or audit_ledger_df.empty:
            audit_ledger_df = pd.DataFrame(columns=['Audit_ID', 'Date', 'Ingredient_Name', 'Theoretical', 'Physical', 'Variance', 'Notes'])

        if not ingredients_df.empty:
            ingredients_df['Ingredient_ID'] = ingredients_df['Ingredient_ID'].astype(str)
            ingredients_df['Current_Stock'] = pd.to_numeric(ingredients_df['Current_Stock'], errors='coerce').fillna(0.0)

            # 1. PROCESS SUPPLY DELIVERIES
            if action == 'receive_stock':
                ing_ids = request.form.getlist('ingredient_id[]')
                quantities = request.form.getlist('quantity[]')
                supplier = request.form.get('supplier', '').strip()
                received_by = request.form.get('received_by', '').strip()
                delivery_notes = request.form.get('delivery_notes', '').strip()
                
                if not supplier or not received_by:
                    return redirect(f"/portal/{username}/inventory?error=Compliance Error: Supplier name and Receiver identity are mandatory.")
                
                logged_count = 0
                meta_notes = f"Supplier: {supplier} (Rec'd by: {received_by}) | Notes: {delivery_notes}".strip(" | Notes: ")
                
                for i_id, q_val in zip(ing_ids, quantities):
                    if not q_val or float(q_val or 0) <= 0: continue
                    qty = float(q_val)
                    
                    idx = ingredients_df[ingredients_df['Ingredient_ID'] == str(i_id)].index
                    if not idx.empty:
                        current_amt = float(ingredients_df.loc[idx[0], 'Current_Stock'])
                        ingredients_df.loc[idx[0], 'Current_Stock'] = current_amt + qty
                        
                        new_row = {
                            'Audit_ID': f"RCV{datetime.now().strftime('%M%S')}{logged_count}",
                            'Date': date_str,
                            'Ingredient_Name': ingredients_df.loc[idx[0], 'Ingredient_Name'],
                            'Theoretical': current_amt,
                            'Physical': current_amt + qty,
                            'Variance': qty,
                            'Notes': meta_notes
                        }
                        audit_ledger_df = pd.concat([audit_ledger_df, pd.DataFrame([new_row])], ignore_index=True)
                        logged_count += 1
                
                if logged_count > 0:
                    client_db.save_tab('Ingredients', ingredients_df)
                    client_db.save_tab('Inventory_Audit_Log', audit_ledger_df)
                    feedback_msg = f"🚚 Success: Received delivery for {logged_count} items from supplier: {supplier}."
                    alert_type = "success"

            # 2. PROCESS ENHANCED BIFURCATED WASTE ENGINE
            elif action == 'log_waste':
                waste_target = request.form.get('waste_target_type')
                wasted_by = request.form.get('wasted_by', '').strip()
                waste_reason = request.form.get('waste_reason', '').strip()
                additional_notes = request.form.get('operational_note', '').strip()
                
                if not wasted_by or not waste_reason:
                    return redirect(f"/portal/{username}/inventory?error=Security Policy: Personnel identity and main Waste Reason are mandatory fields.")
                
                meta_notes = f"Reason: {waste_reason} (Logged by: {wasted_by}) | Notes: {additional_notes}".strip(" | Notes: ")
                logged_count = 0
                
                if waste_target == 'ingredients':
                    ing_ids = request.form.getlist('ingredient_id[]')
                    quantities = request.form.getlist('quantity[]')
                    
                    for i_id, q_val in zip(ing_ids, quantities):
                        if not q_val or float(q_val or 0) <= 0: continue
                        qty = float(q_val)
                        
                        idx = ingredients_df[ingredients_df['Ingredient_ID'] == str(i_id)].index
                        if not idx.empty:
                            current_amt = float(ingredients_df.loc[idx[0], 'Current_Stock'])
                            new_amt = max(0.0, current_amt - qty)
                            ingredients_df.loc[idx[0], 'Current_Stock'] = new_amt
                            
                            new_row = {
                                'Audit_ID': f"WST{datetime.now().strftime('%M%S')}{logged_count}",
                                'Date': date_str,
                                'Ingredient_Name': ingredients_df.loc[idx[0], 'Ingredient_Name'],
                                'Theoretical': current_amt,
                                'Physical': new_amt,
                                'Variance': -qty,
                                'Notes': meta_notes
                            }
                            audit_ledger_df = pd.concat([audit_ledger_df, pd.DataFrame([new_row])], ignore_index=True)
                            logged_count += 1
                            
                elif waste_target == 'products':
                    prod_ids = request.form.getlist('product_id[]')
                    prod_quantities = request.form.getlist('product_quantity[]')
                    products_df = client_db.get_all_products()
                    
                    for p_id, p_qty_str in zip(prod_ids, prod_quantities):
                        if not p_qty_str or float(p_qty_str or 0) <= 0: continue
                        p_qty = float(p_qty_str)
                        
                        recipe_df = client_db.get_product_recipes(p_id)
                        p_name = p_id
                        if products_df is not None and not products_df.empty:
                            p_match = products_df[products_df['Product_ID'] == p_id]
                            if not p_match.empty:
                                p_name = p_match['Product_Name'].values[0]
                        
                        if recipe_df is not None and not recipe_df.empty:
                            # Generate a single batch ID for the entire product reduction run
                            batch_id = f"PRD{datetime.now().strftime('%H%M%S')}_{p_id}"
                            
                            for _, rec_row in recipe_df.iterrows():
                                ing_id = str(rec_row['Ingredient_ID'])
                                req_qty = float(rec_row['Quantity_Required'] or 0)
                                total_wasted_ing = req_qty * p_qty
                                
                                idx = ingredients_df[ingredients_df['Ingredient_ID'] == ing_id].index
                                if not idx.empty:
                                    current_amt = float(ingredients_df.loc[idx[0], 'Current_Stock'])
                                    new_amt = max(0.0, current_amt - total_wasted_ing)
                                    ingredients_df.loc[idx[0], 'Current_Stock'] = new_amt
                                    
                                    new_row = {
                                        'Audit_ID': batch_id,
                                        'Date': date_str,
                                        'Ingredient_Name': ingredients_df.loc[idx[0], 'Ingredient_Name'],
                                        'Theoretical': current_amt,
                                        'Physical': new_amt,
                                        'Variance': -total_wasted_ing,
                                        'Notes': f"Product Waste: {int(p_qty) if p_qty % 1 == 0 else p_qty}x {p_name} | {meta_notes}"
                                    }
                                    audit_ledger_df = pd.concat([audit_ledger_df, pd.DataFrame([new_row])], ignore_index=True)
                                    logged_count += 1
                
                if logged_count > 0:
                    client_db.save_tab('Ingredients', ingredients_df)
                    client_db.save_tab('Inventory_Audit_Log', audit_ledger_df)
                    feedback_msg = f"🗑️ Waste Log Complete: Deducted stock components successfully."
                    alert_type = "warning"

            # 3. PROCESS PHYSICAL RECONCILIATION AUDITS
            elif action == 'reconcile_stock':
                ing_ids = request.form.getlist('ingredient_id[]')
                quantities = request.form.getlist('quantity[]')
                reconcile_by = request.form.get('reconcile_by', '').strip()
                reconcile_reason = request.form.get('reconcile_reason', '').strip()
                
                if not reconcile_by or not reconcile_reason:
                    return redirect(f"/portal/{username}/inventory?error=Compliance Error: Auditor identity and Verification Scope are required fields.")
                
                meta_notes = f"Physical Count by {reconcile_by} ({reconcile_reason})"
                logged_count = 0
                
                for i_id, q_val in zip(ing_ids, quantities):
                    if not q_val or q_val.strip() == "": continue
                    physical_count = float(q_val)
                    
                    idx = ingredients_df[ingredients_df['Ingredient_ID'] == str(i_id)].index
                    if not idx.empty:
                        ing_name = ingredients_df.loc[idx[0], 'Ingredient_Name']
                        theoretical_count = float(ingredients_df.loc[idx[0], 'Current_Stock'])
                        variance = physical_count - theoretical_count
                        
                        ingredients_df.loc[idx[0], 'Current_Stock'] = physical_count
                        
                        new_audit_row = {
                            'Audit_ID': f"AUD{datetime.now().strftime('%M%S')}{logged_count}",
                            'Date': date_str,
                            'Ingredient_Name': ing_name,
                            'Theoretical': theoretical_count,
                            'Physical': physical_count,
                            'Variance': variance,
                            'Notes': meta_notes
                        }
                        audit_ledger_df = pd.concat([audit_ledger_df, pd.DataFrame([new_audit_row])], ignore_index=True)
                        logged_count += 1
                
                if logged_count > 0:
                    client_db.save_tab('Ingredients', ingredients_df)
                    client_db.save_tab('Inventory_Audit_Log', audit_ledger_df)
                    feedback_msg = f"⚖️ Inventory Reconciled: Balance adjustments permanently recorded."
                    alert_type = "info"
                    
            client_db.update_all_product_costs()
            return redirect(f"/portal/{username}/inventory?msg={feedback_msg}&alert_type={alert_type}")

    # ===== GET METHOD: RENDER DATA LAYOUT FILTERS =====
    inventory_df = client_db.get_inventory_status()
    products_df = client_db.get_all_products()
    
    search_query = request.args.get('search', '').lower().strip()
    category_filter = request.args.get('category', 'All')
    filter_date = request.args.get('filter_date', '').strip() # NEW: Activity Date Filter Form Input
    
    categories = []
    inventory_list = []
    products_list = []
    
    if not inventory_df.empty:
        if 'Category' in inventory_df.columns:
            categories = sorted([c for c in inventory_df['Category'].dropna().unique() if c])
        if search_query:
            inventory_df = inventory_df[inventory_df['Ingredient_Name'].str.lower().str.contains(search_query) | 
                                         inventory_df['Ingredient_ID'].str.lower().str.contains(search_query)]
        if category_filter != 'All':
            inventory_df = inventory_df[inventory_df['Category'] == category_filter]
            
        inventory_list = inventory_df.to_dict(orient='records')
        
    if products_df is not None and not products_df.empty:
        products_list = products_df.to_dict(orient='records')

    # TWO-WAY HISTORICAL TIMELINE ACCORDION PRE-COMPILER
    audit_df = client_db.read_tab('Inventory_Audit_Log')
    delivery_history_list = []
    waste_history_list = []
    
    if audit_df is not None and not audit_df.empty:
        # Sort log entries dynamically by latest index insertion
        audit_df = audit_df.sort_index(ascending=False)
        
        # FIXED: Apply structural historical date filters to ledger sets exclusively
        if filter_date:
            audit_df = audit_df[audit_df['Date'] == filter_date]
        
        # Temporary group tracking maps to collapse recipe lines into single product cards
        processed_prd_batches = {}
        
        for _, row in audit_df.iterrows():
            a_id = str(row['Audit_ID'])
            date_val = str(row['Date'])
            ing_name = str(row['Ingredient_Name'])
            variance = float(row['Variance'] or 0)
            notes = str(row['Notes'] or '')
            
            # Grouping A: Deliveries / Audits Panel
            if a_id.startswith('RCV') or a_id.startswith('AUD'):
                delivery_history_list.append({
                    'Audit_ID': a_id,
                    'Date': date_val,
                    'Ingredient_Name': ing_name,
                    'Variance': variance,
                    'Notes': notes
                })
                
            # Grouping B: Standard Raw Ingredient Spoilage Line
            elif a_id.startswith('WST'):
                waste_history_list.append({
                    'is_product': False,
                    'Audit_ID': a_id,
                    'Date': date_val,
                    'Ingredient_Name': ing_name,
                    'Variance': variance,
                    'Notes': notes
                })
                
            # Grouping C: FIXED ACCORDION BUNDLING ENGINE: Merges loose ingredients under product tags (Img 1 Fix)
            elif a_id.startswith('PRD'):
                # Extract clean title name text from structured fields
                title_header = "Wasted Product"
                if "Product Waste:" in notes:
                    title_header = notes.split('|')[0].replace("Product Waste:", "").strip()
                
                # Bundle multi-line rows sharing a unified Date + Title composite signature
                group_composite_key = f"{date_val}_{title_header}"
                
                if group_composite_key not in processed_prd_batches:
                    clean_notes = notes.split('|')[-1].strip() if '|' in notes else notes
                    
                    group_shell = {
                        'is_product': True,
                        'Audit_ID': a_id,
                        'Date': date_val,
                        'Title': title_header,
                        'Notes': clean_notes,
                        'components': []
                    }
                    processed_prd_batches[group_composite_key] = group_shell
                    waste_history_list.append(group_shell)
                
                # Append raw recipe ingredient lines down under the matched single accordion header node
                processed_prd_batches[group_composite_key]['components'].append({
                    'name': ing_name,
                    'variance': variance
                })

    return render_template(
        'inventory.html',
        username=username,
        inventory_status=inventory_list,
        all_products=products_list,
        categories=categories,
        delivery_history=delivery_history_list,
        waste_history=waste_history_list,
        msg=feedback_msg,
        alert_type=alert_type,
        current_search=search_query,
        current_category=category_filter,
        current_filter_date=filter_date # Pass date value back down to preserve form context fields
    )