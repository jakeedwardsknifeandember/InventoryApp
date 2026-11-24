# routes/recipes.py - 3-Tab Recipes Studio (Bar, Kitchen Plating, Kitchen Prep) with Station Routing & Custom Print Templates
from flask import Blueprint, request, redirect, session, render_template, flash
from werkzeug.utils import secure_filename
from modules.database import InventoryDB
import pandas as pd
import sqlite3
import json
import os
import time

recipes_bp = Blueprint('recipes', __name__)

UPLOAD_FOLDER = os.path.join('static', 'uploads', 'recipes')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def ensure_recipe_guides_table(db_path):
    """Creates/migrates Recipe_Guides and Store_Settings tables safely without altering core tables."""
    conn = sqlite3.connect(db_path, timeout=20.0)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Recipe_Guides (
            Target_ID TEXT PRIMARY KEY,
            Recipe_Type TEXT DEFAULT 'product',
            Description TEXT DEFAULT '',
            Procedures TEXT DEFAULT '',
            Image_Path TEXT DEFAULT '',
            Storage TEXT DEFAULT '',
            Shelf_Life TEXT DEFAULT '',
            Prep_Time TEXT DEFAULT '',
            Steps_JSON TEXT DEFAULT '[]'
        )
    """)
    cursor.execute("PRAGMA table_info(Recipe_Guides)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    migrations = {
        'Description': "TEXT DEFAULT ''",
        'Storage': "TEXT DEFAULT ''",
        'Shelf_Life': "TEXT DEFAULT ''",
        'Prep_Time': "TEXT DEFAULT ''",
        'Steps_JSON': "TEXT DEFAULT '[]'"
    }
    for col, col_def in migrations.items():
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE Recipe_Guides ADD COLUMN {col} {col_def}")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Store_Settings (
            Setting_Key TEXT PRIMARY KEY,
            Setting_Value TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_bar_categories(db_path, all_categories):
    """Retrieves the list of categories assigned to the Bar tab. Auto-detects beverage categories on first run."""
    ensure_recipe_guides_table(db_path)
    conn = sqlite3.connect(db_path, timeout=20.0)
    cursor = conn.cursor()
    cursor.execute("SELECT Setting_Value FROM Store_Settings WHERE Setting_Key = 'bar_categories_json'")
    row = cursor.fetchone()
    conn.close()

    if row and row[0] is not None:
        try:
            saved = json.loads(row[0])
            if isinstance(saved, list):
                return saved
        except Exception:
            pass

    # First-time smart default: auto-assign beverage/coffee categories to Bar
    bar_keywords = ['coffee', 'espresso', 'tea', 'beverage', 'drink', 'frappe', 'milk', 'bar', 'latte', 'soda', 'juice']
    default_bar = [c for c in all_categories if any(kw in c.lower() for kw in bar_keywords)]
    return default_bar

def save_bar_categories(db_path, bar_cat_list):
    ensure_recipe_guides_table(db_path)
    conn = sqlite3.connect(db_path, timeout=20.0)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO Store_Settings (Setting_Key, Setting_Value) VALUES ('bar_categories_json', ?)",
        (json.dumps(bar_cat_list),)
    )
    conn.commit()
    conn.close()

def get_recipe_guides_map(db_path):
    ensure_recipe_guides_table(db_path)
    conn = sqlite3.connect(db_path, timeout=20.0)
    cursor = conn.cursor()
    cursor.execute("SELECT Target_ID, Description, Procedures, Image_Path, Storage, Shelf_Life, Prep_Time, Steps_JSON FROM Recipe_Guides")
    rows = cursor.fetchall()
    conn.close()

    guides = {}
    for r in rows:
        steps_list = []
        try:
            parsed = json.loads(r[7] or '[]')
            if isinstance(parsed, list):
                steps_list = parsed
        except Exception:
            steps_list = []

        # Fallback: if Steps_JSON is empty but legacy Procedures text exists, convert lines to steps
        if not steps_list and r[2]:
            steps_list = [{'text': line.strip(), 'image': ''} for line in str(r[2]).splitlines() if line.strip()]

        guides[str(r[0])] = {
            'description': r[1] or '',
            'procedures': r[2] or '',
            'image_path': r[3] or '',
            'storage': r[4] or '',
            'shelf_life': r[5] or '',
            'prep_time': r[6] or '',
            'steps': steps_list
        }
    return guides

def save_recipe_guide_meta(db_path, target_id, recipe_type, description, procedures, image_path=None, storage='', shelf_life='', prep_time='', steps_list=None):
    ensure_recipe_guides_table(db_path)
    conn = sqlite3.connect(db_path, timeout=20.0)
    cursor = conn.cursor()
    cursor.execute("SELECT Image_Path, Storage, Shelf_Life, Prep_Time, Steps_JSON FROM Recipe_Guides WHERE Target_ID = ?", (str(target_id),))
    existing = cursor.fetchone()

    final_img = image_path if image_path is not None else (existing[0] if existing else '')
    final_storage = storage if recipe_type == 'prep' else (existing[1] if existing else '')
    final_shelf = shelf_life if recipe_type == 'prep' else (existing[2] if existing else '')
    final_prep_time = prep_time if recipe_type == 'prep' else (existing[3] if existing else '')

    if steps_list is not None:
        final_steps_json = json.dumps(steps_list)
        final_procs = "\n".join([s['text'] for s in steps_list if s.get('text')])
    else:
        final_steps_json = existing[4] if existing else '[]'
        final_procs = procedures.strip()

    cursor.execute("""
        INSERT OR REPLACE INTO Recipe_Guides
        (Target_ID, Recipe_Type, Description, Procedures, Image_Path, Storage, Shelf_Life, Prep_Time, Steps_JSON)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(target_id), recipe_type, description.strip(), final_procs, final_img,
        final_storage.strip(), final_shelf.strip(), final_prep_time.strip(), final_steps_json
    ))
    conn.commit()
    conn.close()

def get_store_brand_name(db_path, username):
    try:
        conn = sqlite3.connect(db_path, timeout=20.0)
        cursor = conn.cursor()
        cursor.execute("SELECT Setting_Value FROM Store_Settings WHERE Setting_Key = 'receipt_header_name'")
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return str(row[0]).strip().upper()
    except Exception:
        pass
    return username.upper()

def convert_input_to_base_qty(qty_val, selected_unit, base_unit):
    """Converts user-entered recipe quantity into the ingredient's native base stock unit."""
    sel_u = str(selected_unit or '').strip().lower()
    base_u = str(base_unit or '').strip().lower()

    if (base_u == 'kg' and sel_u == 'g') or (base_u == 'l' and sel_u == 'ml'):
        return qty_val / 1000.0
    elif (base_u == 'g' and sel_u == 'kg') or (base_u == 'ml' and sel_u == 'l'):
        return qty_val * 1000.0
    return qty_val

def convert_base_to_display_qty(stored_qty, recipe_unit, base_unit):
    """Converts stored base-unit quantity back into the recipe's display unit without double-scaling."""
    rec_u = str(recipe_unit or '').strip().lower()
    base_u = str(base_unit or '').strip().lower()

    if (base_u == 'kg' and rec_u == 'g') or (base_u == 'l' and rec_u == 'ml'):
        return stored_qty * 1000.0
    elif (base_u == 'g' and rec_u == 'kg') or (base_u == 'ml' and rec_u == 'l'):
        return stored_qty / 1000.0
    return stored_qty


@recipes_bp.route('/portal/<username>/recipes', methods=['GET', 'POST'])
def web_recipes_tab(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    if session.get('staff_role') != 'Platform Owner Admin':
        flash('Unauthorized access: Recipes management is strictly reserved for Platform Owner Admins.', 'danger')
        return redirect(f"/portal/{username}")
    
    db_path = f"data/client_{username}.db"
    ensure_recipe_guides_table(db_path)
    db = InventoryDB(db_path)
    
    current_tab = request.args.get('tab', 'bar').lower().strip()
    if current_tab == 'product':
        current_tab = 'bar'
    if current_tab not in ['bar', 'kitchen', 'prep']:
        current_tab = 'bar'

    ingredients_df_master = db.read_tab('Ingredients')
    base_unit_map = {}
    if not ingredients_df_master.empty:
        for _, ing in ingredients_df_master.iterrows():
            base_unit_map[str(ing['Ingredient_ID'])] = str(ing.get('Unit', '') or '').strip().lower()

    # ==========================================
    # 1. POST METHOD: COMMIT CONFIGURATIONS
    # ==========================================
    if request.method == 'POST':
        action = request.form.get('action_type')
        recipe_type = request.form.get('recipe_type', current_tab).lower().strip()
        target_id = request.form.get('product_id')

        if action == 'save_station_categories':
            selected_bar_cats = request.form.getlist('bar_categories[]')
            save_bar_categories(db_path, selected_bar_cats)
            return redirect(f"/portal/{username}/recipes?tab={recipe_type}")
        
        if action == 'save_recipe':
            ing_ids = request.form.getlist('ingredient_id[]')
            qtys = request.form.getlist('quantity[]')
            units = request.form.getlist('unit[]')
            description_text = request.form.get('description', '').strip()
            procedures_text = request.form.get('procedures', '').strip()
            
            batch_yield_val = float(request.form.get('batch_yield', 1.0) or 1.0)
            if batch_yield_val <= 0:
                batch_yield_val = 1.0
            
            recipe_items = []
            for i, q, u in zip(ing_ids, qtys, units):
                if i and q:
                    raw_val = float(q)
                    base_u = base_unit_map.get(str(i), '')
                    stored_val = convert_input_to_base_qty(raw_val, u, base_u)
                    recipe_items.append({
                        'ingredient_id': i,
                        'quantity': stored_val,
                        'unit': u
                    })
            
            if recipe_type in ['bar', 'kitchen', 'product']:
                db.save_recipe(target_id, recipe_items)
            elif recipe_type == 'prep':
                prep_df = db.read_tab('Prep_Recipes')
                if not prep_df.empty:
                    prep_df = prep_df[prep_df['Prepped_Ingredient_ID'] != target_id]
                
                new_records = []
                for idx, item in enumerate(recipe_items):
                    new_records.append({
                        'Prep_Recipe_ID': f"{target_id}-PREP{idx+1:03d}",
                        'Prepped_Ingredient_ID': target_id,
                        'Raw_Ingredient_ID': item['ingredient_id'],
                        'Quantity_Required': item['quantity'],
                        'Unit': item['unit'],
                        'Batch_Yield': batch_yield_val
                    })
                
                if new_records:
                    prep_df = pd.concat([prep_df, pd.DataFrame(new_records)], ignore_index=True)
                db.save_tab('Prep_Recipes', prep_df)

            # Main product / plating photo upload (Bar & Kitchen Plating)
            uploaded_img_path = None
            photo_file = request.files.get('recipe_image')
            if photo_file and photo_file.filename and allowed_file(photo_file.filename):
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                ext = photo_file.filename.rsplit('.', 1)[1].lower()
                safe_name = secure_filename(f"{username}_{target_id}_{int(time.time())}.{ext}")
                full_save_path = os.path.join(UPLOAD_FOLDER, safe_name)
                photo_file.save(full_save_path)
                uploaded_img_path = f"/static/uploads/recipes/{safe_name}"

            # Kitchen Prep: metadata + individual step photos
            storage_val = request.form.get('storage', '').strip()
            shelf_life_val = request.form.get('shelf_life', '').strip()
            prep_time_val = request.form.get('prep_time', '').strip()
            steps_payload = None

            if recipe_type == 'prep':
                step_texts = request.form.getlist('step_text[]')
                step_existing_imgs = request.form.getlist('step_existing_img[]')
                step_files = request.files.getlist('step_image[]')
                steps_payload = []

                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                ts_tag = int(time.time())

                for idx, s_txt in enumerate(step_texts):
                    clean_txt = s_txt.strip()
                    existing_img = step_existing_imgs[idx].strip() if idx < len(step_existing_imgs) else ''
                    s_file = step_files[idx] if idx < len(step_files) else None

                    final_step_img = existing_img
                    if s_file and s_file.filename and allowed_file(s_file.filename):
                        ext = s_file.filename.rsplit('.', 1)[1].lower()
                        safe_step_name = secure_filename(f"{username}_{target_id}_step{idx+1}_{ts_tag}.{ext}")
                        s_file.save(os.path.join(UPLOAD_FOLDER, safe_step_name))
                        final_step_img = f"/static/uploads/recipes/{safe_step_name}"

                    if clean_txt or final_step_img:
                        steps_payload.append({
                            'text': clean_txt,
                            'image': final_step_img
                        })

            save_recipe_guide_meta(
                db_path, target_id, recipe_type, description_text, procedures_text,
                image_path=uploaded_img_path,
                storage=storage_val,
                shelf_life=shelf_life_val,
                prep_time=prep_time_val,
                steps_list=steps_payload
            )
            db.update_all_product_costs()
            return redirect(f"/portal/{username}/recipes?tab={recipe_type}&product_id={target_id}")
            
        elif action == 'delete_recipe':
            if recipe_type in ['bar', 'kitchen', 'product']:
                db.delete_recipe(target_id)
            elif recipe_type == 'prep':
                prep_df = db.read_tab('Prep_Recipes')
                if not prep_df.empty:
                    prep_df = prep_df[prep_df['Prepped_Ingredient_ID'] != target_id]
                    db.save_tab('Prep_Recipes', prep_df)
                    
            db.update_all_product_costs()
            return redirect(f"/portal/{username}/recipes?tab={recipe_type}")

        elif action == 'clean_duplicate_prep':
            ing_df = db.read_tab('Ingredients')
            if not ing_df.empty and 'Ingredient_Type' in ing_df.columns:
                ing_df = ing_df.drop_duplicates(subset=['Ingredient_ID'], keep='first')
                db.save_tab('Ingredients', ing_df)
            return redirect(f"/portal/{username}/recipes?tab=prep")
            
        return redirect(f"/portal/{username}/recipes?tab={recipe_type}")

    # ==========================================
    # 2. GET METHOD: COMPUTE & RENDER WORKSPACE
    # ==========================================
    products_df = db.read_tab('Products')
    cats_df = db.read_tab('Categories')
    ingredients_df = ingredients_df_master
    prep_recipes_df = db.read_tab('Prep_Recipes')
    guides_map = get_recipe_guides_map(db_path)

    # Master list of all store product categories for the Bar/Kitchen tickbox modal
    master_cats_set = set()
    if not cats_df.empty and 'Category_Name' in cats_df.columns:
        for c in cats_df['Category_Name'].dropna().unique():
            if str(c).strip():
                master_cats_set.add(str(c).strip())
    if not products_df.empty and 'Category' in products_df.columns:
        for c in products_df['Category'].dropna().unique():
            if str(c).strip():
                master_cats_set.add(str(c).strip())
    all_store_categories = sorted(list(master_cats_set))
    bar_categories = get_bar_categories(db_path, all_store_categories)
    bar_cats_lower = {c.lower().strip() for c in bar_categories}

    ing_lookup = {}
    if not ingredients_df.empty:
        for _, ing in ingredients_df.iterrows():
            ing_lookup[str(ing['Ingredient_ID'])] = {
                'name': ing['Ingredient_Name'],
                'base_unit': str(ing.get('Unit', '') or '').strip(),
                'cost': float(ing['Cost_Per_Unit'] or 0),
                'type': ing.get('Ingredient_Type', 'RAW')
            }

    dropdown_ingredients = []
    if not ingredients_df.empty:
        if current_tab == 'prep':
            filtered_ing_df = ingredients_df[ingredients_df['Ingredient_Type'] != 'PREPPED']
            dropdown_ingredients = filtered_ing_df.to_dict('records')
        else:
            dropdown_ingredients = ingredients_df.to_dict('records')

    all_active_products = []
    if not products_df.empty and 'Active' in products_df.columns:
        active_prod_df = products_df[products_df['Active'].astype(str).str.upper() == 'YES']
        all_active_products = active_prod_df.to_dict('records')

    recipe_data = []
    grouped_recipes = {}
    categories = []
    tab_products_list = []

    # SCENARIO A: BAR OR KITCHEN PLATING TAB
    if current_tab in ['bar', 'kitchen']:
        for p in all_active_products:
            p_cat = str(p.get('Category', 'General') or 'General').strip()
            is_bar_item = (p_cat.lower() in bar_cats_lower)
            if current_tab == 'bar' and not is_bar_item:
                continue
            if current_tab == 'kitchen' and is_bar_item:
                continue
            tab_products_list.append(p)

        categories = sorted(list(set(str(p.get('Category', 'General') or 'General').strip() for p in tab_products_list))) if tab_products_list else []
        
        for p in tab_products_list:
            p_id = str(p['Product_ID'])
            df = db.get_product_recipes(p_id)
            items = []
            total_cost = 0.0
            
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    ing_id = str(row.get('Ingredient_ID'))
                    qty = float(row.get('Quantity_Required', 0))
                    unit = str(row.get('Unit', '') or '').strip()
                    
                    lookup = ing_lookup.get(ing_id, {'name': row.get('Ingredient_Name'), 'base_unit': '', 'cost': float(row.get('Cost_Per_Unit', 0))})
                    cost = lookup['cost']
                    total = qty * cost
                    total_cost += total
                    display_qty = convert_base_to_display_qty(qty, unit, lookup['base_unit'])

                    items.append({
                        'ID': ing_id, 'Name': lookup['name'], 'Qty': display_qty, 
                        'Unit': unit, 'Base_Unit': lookup['base_unit'], 'Cost': cost, 'Total': total
                    })
            
            selling_price = float(p.get('Selling_Price', 0))
            profit = selling_price - total_cost
            margin = (profit / selling_price * 100) if selling_price > 0 else 0
            
            parent_item_name = str(p.get('Parent_Item') or p.get('Product_Name') or 'Uncategorized').strip()
            variant_item_name = str(p.get('Variant_Name') or 'Regular').strip()
            guide_meta = guides_map.get(p_id, {'description': '', 'procedures': '', 'image_path': '', 'steps': []})

            recipe_obj = {
                'Product_Name': p['Product_Name'], 
                'Product_ID': p_id, 
                'Parent_Item': parent_item_name,
                'Variant_Name': variant_item_name,
                'Category': p.get('Category', 'General') or 'General', 
                'Selling_Price': selling_price, 
                'Items': items, 'Total_Cost': total_cost, 'Profit': profit, 'Margin': margin,
                'Description': guide_meta['description'],
                'Procedures': guide_meta['procedures'],
                'Image_Path': guide_meta['image_path'],
                'Steps': guide_meta['steps']
            }

            recipe_data.append(recipe_obj)
            grouped_recipes.setdefault(parent_item_name, []).append(recipe_obj)

    # SCENARIO B: KITCHEN PREP SUB-RECIPES TAB
    elif current_tab == 'prep' and not ingredients_df.empty:
        prepped_ingredients_df = ingredients_df[ingredients_df['Ingredient_Type'] == 'PREPPED']
        categories = sorted(list(set(i.get('Category', 'General') for i in prepped_ingredients_df.to_dict('records') if i.get('Category')))) if not prepped_ingredients_df.empty else []
        
        for _, ing_row in prepped_ingredients_df.iterrows():
            ing_id = str(ing_row['Ingredient_ID'])
            items = []
            total_cost = 0.0
            existing_yield = 1.0
            
            if not prep_recipes_df.empty:
                sub_formula = prep_recipes_df[prep_recipes_df['Prepped_Ingredient_ID'] == ing_id]
                if not sub_formula.empty and 'Batch_Yield' in sub_formula.columns:
                    try:
                        existing_yield = float(sub_formula['Batch_Yield'].iloc[0])
                        if existing_yield <= 0:
                            existing_yield = 1.0
                    except Exception:
                        existing_yield = 1.0

                for _, row in sub_formula.iterrows():
                    raw_id = str(row.get('Raw_Ingredient_ID'))
                    qty = float(row.get('Quantity_Required', 0))
                    unit = str(row.get('Unit', '') or '').strip()
                    
                    lookup = ing_lookup.get(raw_id, {'name': 'Unknown Raw Material', 'base_unit': '', 'cost': 0.0})
                    cost = lookup['cost']
                    total = qty * cost
                    total_cost += total
                    display_qty = convert_base_to_display_qty(qty, unit, lookup['base_unit'])

                    items.append({
                        'ID': raw_id, 'Name': lookup['name'], 'Qty': display_qty, 
                        'Unit': unit, 'Base_Unit': lookup['base_unit'], 'Cost': cost, 'Total': total
                    })
            
            guide_meta = guides_map.get(ing_id, {'description': '', 'procedures': '', 'image_path': '', 'storage': '', 'shelf_life': '', 'prep_time': '', 'steps': []})
            amortized_cost = (total_cost / existing_yield) if existing_yield > 0 else total_cost

            recipe_obj = {
                'Product_Name': ing_row['Ingredient_Name'], 'Product_ID': ing_id, 
                'Parent_Item': ing_row['Ingredient_Name'], 'Variant_Name': f"Batch ({existing_yield:g} {ing_row.get('Unit', '')})",
                'Category': ing_row.get('Category', 'General') or 'General',
                'Selling_Price': float(ing_row['Cost_Per_Unit'] or 0), 
                'Items': items, 'Total_Cost': total_cost, 'Profit': 0.0, 'Margin': 0.0,
                'Batch_Yield': existing_yield,
                'Base_Unit': ing_row.get('Unit', 'pcs'),
                'Amortized_Cost': amortized_cost,
                'Description': guide_meta['description'],
                'Procedures': guide_meta['procedures'],
                'Image_Path': guide_meta['image_path'],
                'Storage': guide_meta['storage'],
                'Shelf_Life': guide_meta['shelf_life'],
                'Prep_Time': guide_meta['prep_time'],
                'Steps': guide_meta['steps']
            }

            recipe_data.append(recipe_obj)
            grouped_recipes[ing_row['Ingredient_Name']] = [recipe_obj]

    return render_template(
        'recipes.html', 
        username=username, 
        recipe_data=recipe_data, 
        grouped_recipes=grouped_recipes,
        all_products=tab_products_list,
        categories=categories,
        all_store_categories=all_store_categories,
        bar_categories=bar_categories,
        current_tab=current_tab,
        ingredients=dropdown_ingredients,
        unallocated_prepped_items=[i for i in ingredients_df.to_dict('records') if i.get('Ingredient_Type') == 'PREPPED'] if not ingredients_df.empty else []
    )


@recipes_bp.route('/portal/<username>/recipes/export-guide', methods=['GET', 'POST'])
def export_recipe_guide(username):
    """Generates Bar (Blueprint / 4-Quadrant Cheat Sheet), Kitchen Plating Guide, or Kitchen Prep Sheet."""
    username = username.lower().strip()
    if session.get('logged_in_user') != username and not session.get('is_admin'):
        return redirect('/login')

    db_path = f"data/client_{username}.db"
    ensure_recipe_guides_table(db_path)
    db = InventoryDB(db_path)

    data_src = request.form if request.method == 'POST' else request.args
    recipe_type = data_src.get('recipe_type', 'bar').lower().strip()
    if recipe_type == 'product':
        recipe_type = 'bar'
    if recipe_type not in ['bar', 'kitchen', 'prep']:
        recipe_type = 'bar'

    template_mode = data_src.get('template', 'cheatsheet').lower().strip()
    if recipe_type == 'kitchen':
        template_mode = 'kitchen_plating'
    elif recipe_type == 'prep':
        template_mode = 'kitchen_prep'
    elif template_mode not in ['blueprint', 'cheatsheet']:
        template_mode = 'cheatsheet'

    scope = data_src.get('scope', 'all').lower().strip()
    target_id = data_src.get('target_id', '').strip()
    target_category = data_src.get('category', 'All').strip()
    selected_ids = request.form.getlist('selected_ids[]') if request.method == 'POST' else request.args.getlist('selected_ids')

    brand_name = get_store_brand_name(db_path, username)
    guides_map = get_recipe_guides_map(db_path)
    ingredients_df = db.read_tab('Ingredients')
    products_df = db.read_tab('Products')
    cats_df = db.read_tab('Categories')

    master_cats_set = set()
    if not cats_df.empty and 'Category_Name' in cats_df.columns:
        master_cats_set.update([str(c).strip() for c in cats_df['Category_Name'].dropna().unique() if str(c).strip()])
    if not products_df.empty and 'Category' in products_df.columns:
        master_cats_set.update([str(c).strip() for c in products_df['Category'].dropna().unique() if str(c).strip()])
    bar_cats_lower = {c.lower().strip() for c in get_bar_categories(db_path, sorted(list(master_cats_set)))}

    ing_meta_map = {}
    if not ingredients_df.empty:
        for _, ing in ingredients_df.iterrows():
            ing_meta_map[str(ing['Ingredient_ID'])] = {
                'name': str(ing['Ingredient_Name']),
                'base_unit': str(ing.get('Unit', '') or '').strip().lower(),
                'category': str(ing.get('Category', '') or '').strip().lower()
            }

    def format_ingredient_qty(qty_raw, rec_unit, base_unit):
        rec_u = str(rec_unit or '').strip()
        rec_u_low = rec_u.lower()
        display_qty = convert_base_to_display_qty(qty_raw, rec_u, base_unit)
        qty_str = f"{display_qty:g}"
        return f"{qty_str}{rec_u}" if rec_u_low in ['g', 'ml', 'kg', 'l'] else f"{qty_str} {rec_u}".strip()

    export_records = []

    if recipe_type in ['bar', 'kitchen']:
        if not products_df.empty:
            if 'Active' in products_df.columns:
                products_df = products_df[products_df['Active'].astype(str).str.upper() == 'YES']

            for _, p in products_df.iterrows():
                p_id = str(p['Product_ID'])
                p_cat = str(p.get('Category', 'General') or 'General').strip()
                is_bar_item = (p_cat.lower() in bar_cats_lower)

                if recipe_type == 'bar' and not is_bar_item:
                    continue
                if recipe_type == 'kitchen' and is_bar_item:
                    continue

                if scope == 'single' and p_id != target_id:
                    continue
                elif scope == 'category' and target_category != 'All' and p_cat != target_category:
                    continue
                elif scope == 'selected' and p_id not in selected_ids:
                    continue

                rec_df = db.get_product_recipes(p_id)
                ing_list = []
                if rec_df is not None and not rec_df.empty:
                    for _, r in rec_df.iterrows():
                        i_id = str(r.get('Ingredient_ID'))
                        meta_i = ing_meta_map.get(i_id, {'name': str(r.get('Ingredient_Name', i_id)), 'base_unit': '', 'category': ''})

                        if meta_i['category'] == 'packaging':
                            continue

                        qty = float(r.get('Quantity_Required', 0))
                        unit = str(r.get('Unit', '') or '').strip()
                        ing_list.append({
                            'name': meta_i['name'],
                            'qty_display': format_ingredient_qty(qty, unit, meta_i['base_unit'])
                        })

                meta = guides_map.get(p_id, {'description': '', 'procedures': '', 'image_path': '', 'steps': []})
                steps = [line.strip() for line in meta['procedures'].splitlines() if line.strip()]

                export_records.append({
                    'id': p_id,
                    'title': str(p['Product_Name']),
                    'parent_item': str(p.get('Parent_Item') or p['Product_Name']).strip(),
                    'variant_name': str(p.get('Variant_Name') or 'Regular').strip(),
                    'category': p_cat,
                    'ingredients': ing_list,
                    'description': meta['description'],
                    'procedures': steps,
                    'image_path': meta['image_path'],
                    'storage': '',
                    'shelf_life': '',
                    'prep_time': '',
                    'steps': meta['steps'],
                    'yield_display': ''
                })
    else:
        prep_recipes_df = db.read_tab('Prep_Recipes')
        if not ingredients_df.empty:
            prepped_df = ingredients_df[ingredients_df['Ingredient_Type'] == 'PREPPED']
            for _, ing_row in prepped_df.iterrows():
                ing_id = str(ing_row['Ingredient_ID'])
                p_cat = str(ing_row.get('Category', 'General') or 'General').strip()

                if scope == 'single' and ing_id != target_id:
                    continue
                elif scope == 'category' and target_category != 'All' and p_cat != target_category:
                    continue
                elif scope == 'selected' and ing_id not in selected_ids:
                    continue

                ing_list = []
                batch_yield = 1.0
                if not prep_recipes_df.empty:
                    sub = prep_recipes_df[prep_recipes_df['Prepped_Ingredient_ID'] == ing_id]
                    if not sub.empty and 'Batch_Yield' in sub.columns:
                        try:
                            batch_yield = float(sub['Batch_Yield'].iloc[0])
                        except Exception:
                            batch_yield = 1.0
                    for _, r in sub.iterrows():
                        raw_id = str(r.get('Raw_Ingredient_ID'))
                        meta_i = ing_meta_map.get(raw_id, {'name': raw_id, 'base_unit': '', 'category': ''})

                        if meta_i['category'] == 'packaging':
                            continue

                        qty = float(r.get('Quantity_Required', 0))
                        unit = str(r.get('Unit', '') or '').strip()
                        ing_list.append({
                            'name': meta_i['name'],
                            'qty_display': format_ingredient_qty(qty, unit, meta_i['base_unit'])
                        })

                meta = guides_map.get(ing_id, {'description': '', 'procedures': '', 'image_path': '', 'storage': '', 'shelf_life': '', 'prep_time': '', 'steps': []})
                base_unit = str(ing_row.get('Unit', 'pcs'))
                has_step_photos = any(bool(s.get('image')) for s in meta['steps'])

                export_records.append({
                    'id': ing_id,
                    'title': str(ing_row['Ingredient_Name']),
                    'parent_item': str(ing_row['Ingredient_Name']),
                    'variant_name': f"{batch_yield:g} {base_unit}",
                    'category': p_cat,
                    'ingredients': ing_list,
                    'description': meta['description'],
                    'procedures': [s['text'] for s in meta['steps'] if s.get('text')],
                    'image_path': meta['image_path'],
                    'storage': meta['storage'] or '—',
                    'shelf_life': meta['shelf_life'] or '—',
                    'prep_time': meta['prep_time'] or '—',
                    'yield_display': f"{batch_yield:g} {base_unit}",
                    'steps': meta['steps'],
                    'has_step_photos': has_step_photos
                })

    # Group Bar items by Parent Item
    grouped_export = []
    parent_buckets = {}
    for rec in export_records:
        parent_buckets.setdefault(rec['parent_item'], []).append(rec)

    for parent_name, variants in parent_buckets.items():
        all_ing_names = []
        for v in variants:
            for item in v['ingredients']:
                if item['name'] not in all_ing_names:
                    all_ing_names.append(item['name'])

        matrix_rows = []
        for ing_name in all_ing_names:
            row_vals = []
            for v in variants:
                match = next((x['qty_display'] for x in v['ingredients'] if x['name'] == ing_name), '—')
                row_vals.append(match)
            matrix_rows.append({'ingredient': ing_name, 'values': row_vals})

        best_desc = next((v['description'] for v in variants if v['description']), '')
        best_img = next((v['image_path'] for v in variants if v['image_path']), '')
        best_procs = next((v['procedures'] for v in variants if v['procedures']), [])

        grouped_export.append({
            'parent_name': parent_name,
            'category': variants[0]['category'],
            'description': best_desc,
            'image_path': best_img,
            'variants': [v['variant_name'] for v in variants],
            'rows': matrix_rows,
            'procedures': best_procs
        })

    cheatsheet_pages = [grouped_export[i:i + 4] for i in range(0, len(grouped_export), 4)]

    return render_template(
        'recipe_guide_print.html',
        username=username,
        brand_name=brand_name,
        template_mode=template_mode,
        recipe_type=recipe_type,
        export_records=export_records,
        grouped_export=grouped_export,
        cheatsheet_pages=cheatsheet_pages
    )