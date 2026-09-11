# routes/inventory.py - Stock Inventory Module with Dynamic Packaging & Dual-Input Yield Prep Engine
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
import pandas as pd
import json
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

            # 1. PROCESS SUPPLY DELIVERIES (WITH DYNAMIC PACK OVERRIDE & ADAPTIVE COSTING)
            if action == 'receive_stock':
                ing_ids = request.form.getlist('ingredient_id[]')
                quantities = request.form.getlist('quantity[]')
                purchase_prices = request.form.getlist('purchase_price[]') 
                pack_sizes = request.form.getlist('pack_size[]')
                
                supplier = request.form.get('supplier', '').strip()
                received_by = request.form.get('received_by', '').strip()
                delivery_notes = request.form.get('delivery_notes', '').strip()
                payment_method = request.form.get('payment_method', 'Invoice/Terms').strip()
                
                if not supplier or not received_by:
                    return redirect(f"/portal/{username}/inventory?type={current_type}&error=Compliance Error: Supplier name and Receiver identity are mandatory.")
                
                logged_count = 0
                total_delivery_expense = 0.0
                item_summaries = []
                meta_notes = f"Supplier: {supplier} (Rec'd by: {received_by}) | Pay-Method: {payment_method} | Notes: {delivery_notes}".strip(" | Notes: ")
                
                cost_price_col = 'Cost_Per_Unit' if 'Cost_Per_Unit' in ingredients_df.columns else ('Cost_Price' if 'Cost_Price' in ingredients_df.columns else 'Cost_Per_Unit')
                
                for idx_entry, (i_id, q_val, p_val) in enumerate(zip(ing_ids, quantities, purchase_prices)):
                    if not q_val or float(q_val or 0) <= 0: 
                        continue
                        
                    packs_received = float(q_val)
                    total_line_cost = float(p_val or 0.0)
                    
                    idx = ingredients_df[ingredients_df['Ingredient_ID'] == str(i_id)].index
                    if not idx.empty:
                        row_idx = idx[0]
                        current_stock_bal = float(ingredients_df.loc[row_idx, 'Current_Stock'])
                        ing_name = ingredients_df.loc[row_idx, 'Ingredient_Name']
                        base_unit = str(ingredients_df.loc[row_idx, 'Unit'] if 'Unit' in ingredients_df.columns else 'pcs')
                        purchase_unit = str(ingredients_df.loc[row_idx, 'Purchase_Unit'] if 'Purchase_Unit' in ingredients_df.columns and pd.notna(ingredients_df.loc[row_idx, 'Purchase_Unit']) else 'pack')
                        
                        default_pack_size = 1.0
                        try:
                            default_pack_size = float(ingredients_df.loc[row_idx, 'Pack_Size']) if 'Pack_Size' in ingredients_df.columns and pd.notna(ingredients_df.loc[row_idx, 'Pack_Size']) else 1.0
                            if default_pack_size <= 0: 
                                default_pack_size = 1.0
                        except Exception:
                            default_pack_size = 1.0
                            
                        # Dynamic packaging override
                        pack_size = default_pack_size
                        if idx_entry < len(pack_sizes) and str(pack_sizes[idx_entry]).strip():
                            try:
                                user_override = float(pack_sizes[idx_entry])
                                if user_override > 0:
                                    pack_size = user_override
                            except (ValueError, TypeError):
                                pack_size = default_pack_size
                                
                        base_qty = packs_received * pack_size
                        incoming_unit_price = total_line_cost / base_qty if base_qty > 0 else 0.0
                        
                        try:
                            old_unit_cost = float(pd.to_numeric(ingredients_df.loc[row_idx, cost_price_col], errors='coerce') or 0.0)
                        except Exception:
                            old_unit_cost = 0.0
                        
                        # Moving weighted-average adaptive costing per base unit
                        if current_stock_bal <= 0 or old_unit_cost <= 0:
                            new_weighted_cost = incoming_unit_price
                        else:
                            total_old_value = current_stock_bal * old_unit_cost
                            new_weighted_cost = (total_old_value + total_line_cost) / (current_stock_bal + base_qty)
                        
                        ingredients_df.loc[row_idx, cost_price_col] = round(new_weighted_cost, 4)
                        ingredients_df.loc[row_idx, 'Current_Stock'] = current_stock_bal + base_qty
                        
                        if 'Purchase_Cost' in ingredients_df.columns:
                            ingredients_df.loc[row_idx, 'Purchase_Cost'] = round(new_weighted_cost * default_pack_size, 2)
                        
                        total_delivery_expense += total_line_cost
                        
                        display_qty = int(packs_received) if packs_received % 1 == 0 else packs_received
                        is_override = abs(pack_size - default_pack_size) > 0.001
                        override_note = f" (Substitute: {pack_size:g} {base_unit})" if is_override else ""
                        item_summaries.append(f"{display_qty:,}x {purchase_unit} of {ing_name}{override_note} (Total: PHP {total_line_cost:,.2f})")
                        
                        new_row = {
                            'Audit_ID': f"RCV{datetime.now().strftime('%M%S')}{logged_count}",
                            'Date': date_str,
                            'Ingredient_Name': ing_name,
                            'Theoretical': current_stock_bal,
                            'Physical': current_stock_bal + base_qty,
                            'Variance': base_qty,
                            'Notes': f"Intake Cost: PHP {incoming_unit_price:,.4f}/{base_unit} ({display_qty} {purchase_unit} = {base_qty:g} {base_unit}){override_note} | {meta_notes}"
                        }
                        audit_ledger_df = pd.concat([audit_ledger_df, pd.DataFrame([new_row])], ignore_index=True)
                        logged_count += 1
                
                if logged_count > 0:
                    client_db.save_tab('Ingredients', ingredients_df)
                    client_db.save_tab('Inventory_Audit_Log', audit_ledger_df)
                    
                    if total_delivery_expense > 0:
                        description_string = f"Automated: Stock Intake from {supplier} ({', '.join(item_summaries)})"
                        client_db.add_expense({
                            'Expense_Date': date_str,
                            'Expense_Type': 'Operational',
                            'Description': description_string,
                            'Amount': total_delivery_expense,
                            'Category': 'Supplier Deliveries',
                            'Payment_Method': payment_method,
                            'Notes': f"Auto-weighted cost matrix recalculated cleanly via column handle: {cost_price_col} with pack-to-base conversion."
                        })
                    
                    feedback_msg = f"Success: Processed delivery for {logged_count} items from supplier: {supplier}. Financial invoice total of PHP {total_delivery_expense:,.2f} pushed to accounting."
                    alert_type = "success"

            # 2. DUAL-INPUT PROPORTIONAL YIELD KITCHEN PREP ENGINE
            elif action == 'log_production_prep':
                prep_ing_id = request.form.get('prep_ingredient_id')
                prepped_by = request.form.get('prepped_by', '').strip()
                actual_produced_str = request.form.get('actual_yield_produced', '').strip()
                prep_batches_str = request.form.get('prep_quantity', '').strip()
                
                if not prep_ing_id or not prepped_by:
                    return redirect(f"/portal/{username}/inventory?type=PREPPED&error=Production Error: Target portion item and cook identity are mandatory.")
                
                prep_recipes_df = client_db.read_tab('Prep_Recipes')
                formula_df = prep_recipes_df[prep_recipes_df['Prepped_Ingredient_ID'] == str(prep_ing_id)] if prep_recipes_df is not None and not prep_recipes_df.empty else pd.DataFrame()
                
                if formula_df.empty:
                    return redirect(f"/portal/{username}/inventory?type=PREPPED&error=Configuration Error: No recipe formula found for this item. Build its sub-recipe blueprint first.")
                
                # Determine standard master recipe yield
                standard_yield = 0.0
                if 'Batch_Yield' in formula_df.columns and pd.notna(formula_df['Batch_Yield'].iloc[0]) and float(formula_df['Batch_Yield'].iloc[0] or 0) > 0:
                    standard_yield = float(formula_df['Batch_Yield'].iloc[0])
                else:
                    standard_yield = pd.to_numeric(formula_df['Quantity_Required'], errors='coerce').fillna(0.0).sum()
                    if standard_yield <= 0:
                        standard_yield = 1.0

                # Compute exact scaling ratio based on actual yield produced vs batch multiplier
                total_yield_produced = 0.0
                prep_batches = 0.0
                
                try:
                    actual_val = float(actual_produced_str) if actual_produced_str else 0.0
                except ValueError:
                    actual_val = 0.0
                    
                try:
                    batches_val = float(prep_batches_str) if prep_batches_str else 0.0
                except ValueError:
                    batches_val = 0.0
                    
                if actual_val > 0:
                    total_yield_produced = actual_val
                    prep_batches = actual_val / standard_yield if standard_yield > 0 else 1.0
                elif batches_val > 0:
                    prep_batches = batches_val
                    total_yield_produced = batches_val * standard_yield
                else:
                    return redirect(f"/portal/{username}/inventory?type=PREPPED&error=Input Error: Provide either actual yield produced or number of batches.")

                # Check inventory availability across all constituent components
                insufficient_stocks = []
                for _, row in formula_df.iterrows():
                    raw_id = str(row['Raw_Ingredient_ID'])
                    req_qty = float(pd.to_numeric(row['Quantity_Required'], errors='coerce') or 0.0)
                    total_needed = req_qty * prep_batches
                    
                    raw_idx = ingredients_df[ingredients_df['Ingredient_ID'] == raw_id].index
                    if not raw_idx.empty:
                        avail = float(ingredients_df.loc[raw_idx[0], 'Current_Stock'])
                        unit_str = str(ingredients_df.loc[raw_idx[0], 'Unit'] if 'Unit' in ingredients_df.columns else '')
                        if avail < total_needed:
                            r_name = ingredients_df.loc[raw_idx[0], 'Ingredient_Name']
                            insufficient_stocks.append(f"{r_name} (Need: {total_needed:,.2f} {unit_str}, Available: {avail:,.2f} {unit_str})")
                    else:
                        insufficient_stocks.append(f"Raw Component ID {raw_id} missing from register.")
                
                if insufficient_stocks:
                    error_details = "; ".join(insufficient_stocks)
                    return redirect(f"/portal/{username}/inventory?type=PREPPED&error=Shortage Warning: Cannot complete prep run. Deficits: {error_details}")
                
                target_idx = ingredients_df[ingredients_df['Ingredient_ID'] == str(prep_ing_id)].index
                target_name = ingredients_df.loc[target_idx[0], 'Ingredient_Name'] if not target_idx.empty else "Prepped Item"
                target_unit = ingredients_df.loc[target_idx[0], 'Unit'] if not target_idx.empty and 'Unit' in ingredients_df.columns else "units"
                
                logged_count = 0
                batch_id = f"PRP{datetime.now().strftime('%H%M%S')}"
                meta_notes = f"Prepped by {prepped_by}"
                
                # Deduct raw ingredients proportionally
                for _, row in formula_df.iterrows():
                    raw_id = str(row['Raw_Ingredient_ID'])
                    req_qty = float(pd.to_numeric(row['Quantity_Required'], errors='coerce') or 0.0)
                    total_deducted = req_qty * prep_batches
                    
                    raw_idx = ingredients_df[ingredients_df['Ingredient_ID'] == raw_id].index
                    current_raw_stock = float(ingredients_df.loc[raw_idx[0], 'Current_Stock'])
                    raw_unit = str(ingredients_df.loc[raw_idx[0], 'Unit'] if 'Unit' in ingredients_df.columns else '')
                    ingredients_df.loc[raw_idx[0], 'Current_Stock'] = current_raw_stock - total_deducted
                    
                    raw_log_row = {
                        'Audit_ID': batch_id,
                        'Date': date_str,
                        'Ingredient_Name': ingredients_df.loc[raw_idx[0], 'Ingredient_Name'],
                        'Theoretical': current_raw_stock,
                        'Physical': current_raw_stock - total_deducted,
                        'Variance': -total_deducted,
                        'Notes': f"Consumed {total_deducted:,.2f} {raw_unit} to produce {total_yield_produced:,.2f} {target_unit} ({prep_batches:.3f} batch eq.) of {target_name} | {meta_notes}"
                    }
                    audit_ledger_df = pd.concat([audit_ledger_df, pd.DataFrame([raw_log_row])], ignore_index=True)
                    logged_count += 1
                
                # Credit the finished prepped component balance
                current_prep_stock = float(ingredients_df.loc[target_idx[0], 'Current_Stock'])
                ingredients_df.loc[target_idx[0], 'Current_Stock'] = current_prep_stock + total_yield_produced
                
                prep_credit_row = {
                    'Audit_ID': batch_id,
                    'Date': date_str,
                    'Ingredient_Name': target_name,
                    'Theoretical': current_prep_stock,
                    'Physical': current_prep_stock + total_yield_produced,
                    'Variance': total_yield_produced,
                    'Notes': f"Yielded output +{total_yield_produced:,.2f} {target_unit} ({prep_batches:.3f} batch eq.) | {meta_notes}"
                }
                audit_ledger_df = pd.concat([audit_ledger_df, pd.DataFrame([prep_credit_row])], ignore_index=True)
                logged_count += 1
                
                if logged_count > 0:
                    client_db.save_tab('Ingredients', ingredients_df)
                    client_db.save_tab('Inventory_Audit_Log', audit_ledger_df)
                    feedback_msg = f"Kitchen Prep Logged: Successfully produced {total_yield_produced:,.2f} {target_unit} of {target_name} ({prep_batches:.3f} batch equivalent)."
                    alert_type = "success"

            # 3. PROCESS BIFURCATED SPOILAGE DISCARD ENGINE
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
                            unit_label = ingredients_df.loc[idx[0], 'Unit'] if 'Unit' in ingredients_df.columns else ''
                            new_amt = max(0.0, current_amt - qty)
                            ingredients_df.loc[idx[0], 'Current_Stock'] = new_amt
                            
                            new_row = {
                                'Audit_ID': f"WST{datetime.now().strftime('%M%S')}{logged_count}",
                                'Date': date_str,
                                'Ingredient_Name': ingredients_df.loc[idx[0], 'Ingredient_Name'],
                                'Theoretical': current_amt,
                                'Physical': new_amt,
                                'Variance': -qty,
                                'Notes': f"Direct Loss: {qty:g} {unit_label} | {meta_notes}"
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
                                        'Notes': f"Product Waste: {p_qty:g}x {p_name} | {meta_notes}"
                                    }
                                    audit_ledger_df = pd.concat([audit_ledger_df, pd.DataFrame([new_row])], ignore_index=True)
                                    logged_count += 1
                
                if logged_count > 0:
                    client_db.save_tab('Ingredients', ingredients_df)
                    client_db.save_tab('Inventory_Audit_Log', audit_ledger_df)
                    feedback_msg = "Waste Log Complete: Deducted stock components successfully."
                    alert_type = "warning"

            # 4. PROCESS PHYSICAL RECONCILIATION AUDITS
            elif action == 'reconcile_stock':
                ing_ids = request.form.getlist('ingredient_id[]')
                quantities = request.form.getlist('quantity[]')
                variance_reasons = request.form.getlist('variance_reason[]')
                reconcile_by = request.form.get('reconcile_by', '').strip()
                reconcile_reason = request.form.get('reconcile_reason', '').strip()
                
                if not reconcile_by or not reconcile_reason:
                    return redirect(f"/portal/{username}/inventory?type={current_type}&error=Compliance Error: Auditor identity and Verification Scope are required fields.")
                
                meta_notes = f"Physical Count by {reconcile_by} ({reconcile_reason})"
                logged_count = 0
                
                for i_id, q_val, v_reason in zip(ing_ids, quantities, variance_reasons):
                    if not q_val or q_val.strip() == "": continue
                    physical_count = float(q_val)
                    
                    idx = ingredients_df[ingredients_df['Ingredient_ID'] == str(i_id)].index
                    if not idx.empty:
                        ing_name = ingredients_df.loc[idx[0], 'Ingredient_Name']
                        theoretical_count = float(ingredients_df.loc[idx[0], 'Current_Stock'])
                        variance = physical_count - theoretical_count
                        
                        item_notes = meta_notes
                        if abs(variance) > 0.001:
                            justification = v_reason.strip() if v_reason.strip() else "No reason provided."
                            item_notes += f" | Variance Justification: {justification}"
                        
                        ingredients_df.loc[idx[0], 'Current_Stock'] = physical_count
                        
                        new_audit_row = {
                            'Audit_ID': f"AUD{datetime.now().strftime('%M%S')}{logged_count}",
                            'Date': date_str,
                            'Ingredient_Name': ing_name,
                            'Theoretical': theoretical_count,
                            'Physical': physical_count,
                            'Variance': variance,
                            'Notes': item_notes
                        }
                        audit_ledger_df = pd.concat([audit_ledger_df, pd.DataFrame([new_audit_row])], ignore_index=True)
                        logged_count += 1
                
                if logged_count > 0:
                    client_db.save_tab('Ingredients', ingredients_df)
                    client_db.save_tab('Inventory_Audit_Log', audit_ledger_df)
                    feedback_msg = "Inventory Reconciled: Balance adjustments permanently recorded with variance justifications."
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
            
        inventory_df = inventory_df[inventory_df['Ingredient_Type'] == current_type]
        
        if 'Category' in inventory_df.columns:
            categories = sorted([c for c in inventory_df['Category'].dropna().unique() if str(c).strip()])
        if search_query:
            inventory_df = inventory_df[inventory_df['Ingredient_Name'].astype(str).str.lower().str.contains(search_query) | 
                                         inventory_df['Ingredient_ID'].astype(str).str.lower().str.contains(search_query)]
        if category_filter != 'All':
            inventory_df = inventory_df[inventory_df['Category'] == category_filter]
            
        inventory_list = inventory_df.to_dict(orient='records')
        
    if products_df is not None and not products_df.empty:
        products_list = products_df.to_dict(orient='records')

    # HISTORICAL TIMELINE ACCORDION PRE-COMPILER
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
            variance = float(row['Variance'] or 0.0)
            notes = str(row['Notes'] or '')
            
            if a_id.startswith('RCV') or a_id.startswith('AUD'):
                delivery_history_list.append({
                    'Audit_ID': a_id, 'Date': date_val, 'Ingredient_Name': ing_name, 'Variance': variance, 'Notes': notes
                })
                
            elif a_id.startswith('WST'):
                waste_history_list.append({
                    'is_product': False, 'Audit_ID': a_id, 'Date': date_val, 'Ingredient_Name': ing_name, 'Variance': variance, 'Notes': notes
                })
                
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

    # ENRICHED PREPPED COMPONENT PAYLOAD FOR DUAL-INPUT SCALING
    full_ingredients_pool = client_db.read_tab('Ingredients')
    prep_recipes_df = client_db.read_tab('Prep_Recipes')
    prepped_dropdown_options = []
    
    if not full_ingredients_pool.empty:
        prepped_rows = full_ingredients_pool[full_ingredients_pool['Ingredient_Type'] == 'PREPPED']
        for _, p_row in prepped_rows.iterrows():
            p_id = str(p_row['Ingredient_ID'])
            p_name = str(p_row['Ingredient_Name'])
            p_unit = str(p_row.get('Unit', 'g'))
            p_yield = 1.0
            p_components = []
            
            if prep_recipes_df is not None and not prep_recipes_df.empty:
                f_df = prep_recipes_df[prep_recipes_df['Prepped_Ingredient_ID'] == p_id]
                if not f_df.empty:
                    if 'Batch_Yield' in f_df.columns and pd.notna(f_df['Batch_Yield'].iloc[0]) and float(f_df['Batch_Yield'].iloc[0] or 0) > 0:
                        p_yield = float(f_df['Batch_Yield'].iloc[0])
                    else:
                        p_yield = pd.to_numeric(f_df['Quantity_Required'], errors='coerce').fillna(0.0).sum()
                        if p_yield <= 0:
                            p_yield = 1.0
                            
                    for _, comp in f_df.iterrows():
                        raw_id = str(comp['Raw_Ingredient_ID'])
                        raw_match = full_ingredients_pool[full_ingredients_pool['Ingredient_ID'] == raw_id]
                        c_name = raw_match['Ingredient_Name'].values[0] if not raw_match.empty else raw_id
                        c_stock = float(raw_match['Current_Stock'].values[0]) if not raw_match.empty else 0.0
                        c_unit = str(raw_match['Unit'].values[0]) if not raw_match.empty and 'Unit' in raw_match.columns else str(comp.get('Unit', ''))
                        
                        p_components.append({
                            'raw_id': raw_id,
                            'name': c_name,
                            'qty_per_batch': float(comp.get('Quantity_Required', 0.0) or 0.0),
                            'unit': c_unit,
                            'current_stock': c_stock
                        })

            prepped_dropdown_options.append({
                'Ingredient_ID': p_id,
                'Ingredient_Name': p_name,
                'Unit': p_unit,
                'Batch_Yield': p_yield,
                'has_formula': len(p_components) > 0,
                'components': p_components
            })

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
        prepped_options_json=json.dumps(prepped_dropdown_options),
        current_type=current_type,
        msg=request.args.get('msg', feedback_msg),
        alert_type=alert_type,
        current_search=search_query,
        current_category=category_filter,
        current_filter_date=filter_date
    )