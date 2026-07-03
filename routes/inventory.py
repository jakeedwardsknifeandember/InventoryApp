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
    
    # Read active inner sub-tab context selection (Defaults to Bulk Warehouse view)
    current_type = request.args.get('type', 'RAW').upper().strip()
    if current_type not in ['RAW', 'PREPPED']:
        current_type = 'RAW'
    
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
                    return redirect(f"/portal/{username}/inventory?type={current_type}&error=Compliance Error: Supplier name and Receiver identity are mandatory.")
                
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

            # 🌟 2. NEW FEATURE ACTION: PROCESS KITCHEN PRODUCTION PREP LOGS
            elif action == 'log_production_prep':
                prep_ing_id = request.form.get('prep_ingredient_id')
                prep_qty_str = request.form.get('prep_quantity', '0')
                prepped_by = request.form.get('prepped_by', '').strip()
                
                if not prep_ing_id or not prepped_by or float(prep_qty_str or 0) <= 0:
                    return redirect(f"/portal/{username}/inventory?type=PREPPED&error=Production Error: Target portion item, valid count, and cook identity are mandatory.")
                
                prep_qty = float(prep_qty_str)
                prep_recipes_df = client_db.read_tab('Prep_Recipes')
                
                # Fetch formula blueprint rules for this prepped component item
                formula_df = prep_recipes_df[prep_recipes_df['Prepped_Ingredient_ID'] == str(prep_ing_id)] if prep_recipes_df is not None and not prep_recipes_df.empty else pd.DataFrame()
                
                if formula_df.empty:
                    return redirect(f"/portal/{username}/inventory?type=PREPPED&error=Configuration Error: No kitchen prep instructions found for this item. Build its sub-recipe framework first.")
                
                # Validation Loop: Verify warehouse contains sufficient bulk materials before deducting items
                insufficient_stocks = []
                for _, row in formula_df.iterrows():
                    raw_id = str(row['Raw_Ingredient_ID'])
                    req_qty = float(row['Quantity_Required'] or 0)
                    total_needed = req_qty * prep_qty
                    
                    raw_idx = ingredients_df[ingredients_df['Ingredient_ID'] == raw_id].index
                    if not raw_idx.empty:
                        avail = float(ingredients_df.loc[raw_idx[0], 'Current_Stock'])
                        if avail < total_needed:
                            r_name = ingredients_df.loc[raw_idx[0], 'Ingredient_Name']
                            insufficient_stocks.append(f"{r_name} (Need: {total_needed}, Available: {avail})")
                    else:
                        insufficient_stocks.append(f"Raw Material Component ID {raw_id} missing from register.")
                
                if insufficient_stocks:
                    error_details = ", ".join(insufficient_stocks)
                    return redirect(f"/portal/{username}/inventory?type=PREPPED&error=Shortage Warning: Cannot complete prep run. Raw stock deficit: {error_details}")
                
                # Execution Pass A: Deduct raw wholesale inventory balances
                logged_count = 0
                batch_id = f"PRP{datetime.now().strftime('%H%M%S')}"
                meta_notes = f"Batch Production by {prepped_by}"
                
                target_idx = ingredients_df[ingredients_df['Ingredient_ID'] == str(prep_ing_id)].index
                target_name = ingredients_df.loc[target_idx[0], 'Ingredient_Name'] if not target_idx.empty else "Portioned Component"
                
                for _, row in formula_df.iterrows():
                    raw_id = str(row['Raw_Ingredient_ID'])
                    req_qty = float(row['Quantity_Required'] or 0)
                    total_deducted = req_qty * prep_qty
                    
                    raw_idx = ingredients_df[ingredients_df['Ingredient_ID'] == raw_id].index
                    current_raw_stock = float(ingredients_df.loc[raw_idx[0], 'Current_Stock'])
                    ingredients_df.loc[raw_idx[0], 'Current_Stock'] = current_raw_stock - total_deducted
                    
                    raw_log_row = {
                        'Audit_ID': batch_id,
                        'Date': date_str,
                        'Ingredient_Name': ingredients_df.loc[raw_idx[0], 'Ingredient_Name'],
                        'Theoretical': current_raw_stock,
                        'Physical': current_raw_stock - total_deducted,
                        'Variance': -total_deducted,
                        'Notes': f"Consumed to manufacture {int(prep_qty) if prep_qty % 1 == 0 else prep_qty}x {target_name} | {meta_notes}"
                    }
                    audit_ledger_df = pd.concat([audit_ledger_df, pd.DataFrame([raw_log_row])], ignore_index=True)
                    logged_count += 1
                
                # Execution Pass B: Credit portioned kitchen-line count pools
                current_prep_stock = float(ingredients_df.loc[target_idx[0], 'Current_Stock'])
                ingredients_df.loc[target_idx[0], 'Current_Stock'] = current_prep_stock + prep_qty
                
                prep_credit_row = {
                    'Audit_ID': batch_id,
                    'Date': date_str,
                    'Ingredient_Name': target_name,
                    'Theoretical': current_prep_stock,
                    'Physical': current_prep_stock + prep_qty,
                    'Variance': prep_qty,
                    'Notes': f"Yielded output from kitchen prep | {meta_notes}"
                }
                audit_ledger_df = pd.concat([audit_ledger_df, pd.DataFrame([prep_credit_row])], ignore_index=True)
                logged_count += 1
                
                if logged_count > 0:
                    client_db.save_tab('Ingredients', ingredients_df)
                    client_db.save_tab('Inventory_Audit_Log', audit_ledger_df)
                    feedback_msg = f"🍳 Kitchen Prep Logged: Converted warehouse elements into {int(prep_qty) if prep_qty % 1 == 0 else prep_qty}x {target_name} successfully."
                    alert_type = "success"

            # 3. PROCESS ENHANCED BIFURCATED WASTE ENGINE
            elif action == 'log_waste':
                waste_target = request.form.get('waste_target_type')
                wasted_by = request.form.get('wasted_by', '').strip()
                waste_reason = request.form.get('waste_reason', '').strip()
                additional_notes = request.form.get('operational_note', '').strip()
                
                if not wasted_by or not waste_reason:
                    return redirect(f"/portal/{username}/inventory?type={current_type}&error=Security Policy: Personnel identity and main Waste Reason are mandatory fields.")
                
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

            # 4. PROCESS PHYSICAL RECONCILIATION AUDITS
            elif action == 'reconcile_stock':
                ing_ids = request.form.getlist('ingredient_id[]')
                quantities = request.form.getlist('quantity[]')
                reconcile_by = request.form.get('reconcile_by', '').strip()
                reconcile_reason = request.form.get('reconcile_reason', '').strip()
                
                if not reconcile_by or not reconcile_reason:
                    return redirect(f"/portal/{username}/inventory?type={current_type}&error=Compliance Error: Auditor identity and Verification Scope are required fields.")
                
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
            return redirect(f"/portal/{username}/inventory?type={current_type}&msg={feedback_msg}&alert_type={alert_type}")

    # ===== GET METHOD: RENDER DATA LAYOUT FILTERS =====
    inventory_df = client_db.get_inventory_status()
    products_df = client_db.get_all_products()
    
    search_query = request.args.get('search', '').lower().strip()
    category_filter = request.args.get('category', 'All')
    filter_date = request.args.get('filter_date', '').strip() 
    
    categories = []
    inventory_list = []
    products_list = []
    
    if not inventory_df.empty:
        if 'Ingredient_Type' not in inventory_df.columns:
            inventory_df['Ingredient_Type'] = 'RAW'
            
        # Isolate rows to fit context sub-tabs layout rules
        inventory_df = inventory_df[inventory_df['Ingredient_Type'] == current_type]
        
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
    production_history_list = []
    
    if audit_df is not None and not audit_df.empty:
        audit_df = audit_df.sort_index(ascending=False)
        
        if filter_date:
            audit_df = audit_df[audit_df['Date'] == filter_date]
        
        processed_prd_batches = {}
        processed_prp_batches = {}
        
        for _, row in audit_df.iterrows():
            a_id = str(row['Audit_ID'])
            date_val = str(row['Date'])
            ing_name = str(row['Ingredient_Name'])
            variance = float(row['Variance'] or 0)
            notes = str(row['Notes'] or '')
            
            # Grouping A: Supply Receipts / Audits Panel
            if a_id.startswith('RCV') or a_id.startswith('AUD'):
                delivery_history_list.append({
                    'Audit_ID': a_id, 'Date': date_val, 'Ingredient_Name': ing_name, 'Variance': variance, 'Notes': notes
                })
                
            # Grouping B: Standard Raw Ingredient Spoilage Line
            elif a_id.startswith('WST'):
                waste_history_list.append({
                    'is_product': False, 'Audit_ID': a_id, 'Date': date_val, 'Ingredient_Name': ing_name, 'Variance': variance, 'Notes': notes
                })
                
            # Grouping C: Merges recipe raw line mutations into clean product cards
            elif a_id.startswith('PRD'):
                title_header = "Wasted Product"
                if "Product Waste:" in notes:
                    title_header = notes.split('|')[0].replace("Product Waste:", "").strip()
                
                group_composite_key = f"{date_val}_{title_header}"
                if group_composite_key not in processed_prd_batches:
                    clean_notes = notes.split('|')[-1].strip() if '|' in notes else notes
                    group_shell = {
                        'is_product': True, 'Audit_ID': a_id, 'Date': date_val, 'Title': title_header, 'Notes': clean_notes, 'components': []
                    }
                    processed_prd_batches[group_composite_key] = group_shell
                    waste_history_list.append(group_shell)
                
                processed_prd_batches[group_composite_key]['components'].append({
                    'name': ing_name, 'variance': variance
                })
                
            # Grouping D: NEW HISTORICAL RUN: Collapse kitchen prep batches into single summary nodes
            elif a_id.startswith('PRP'):
                group_key = f"{date_val}_{a_id}"
                if group_key not in processed_prp_batches:
                    group_shell = {
                        'Audit_ID': a_id, 'Date': date_val, 'Notes': notes.split('|')[-1].strip() if '|' in notes else notes, 'Lines': []
                    }
                    processed_prp_batches[group_key] = group_shell
                    production_history_list.append(group_shell)
                
                processed_prp_batches[group_key]['Lines'].append({
                    'name': ing_name, 'variance': variance
                })

    # Filter unallocated prepped lines items to power the morning station options dropdowns
    full_ingredients_pool = client_db.read_tab('Ingredients')
    prepped_dropdown_options = []
    if not full_ingredients_pool.empty:
        prepped_dropdown_options = full_ingredients_pool[full_ingredients_pool['Ingredient_Type'] == 'PREPPED'].to_dict(orient='records')

    return render_template(
        'inventory.html',
        username=username,
        inventory_status=inventory_list,
        all_products=products_list,
        categories=categories,
        delivery_history=delivery_history_list,
        waste_history=waste_history_list,
        production_history=production_history_list,
        prepped_options=prepped_dropdown_options,
        current_type=current_type,
        msg=request.args.get('msg', feedback_msg),
        alert_type=request.args.get('alert_type', alert_type),
        current_search=search_query,
        current_category=category_filter,
        current_filter_date=filter_date
    )