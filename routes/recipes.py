# routes/recipes.py - Recipes Module Blueprint
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
import sqlite3

recipes_bp = Blueprint('recipes', __name__)

@recipes_bp.route('/portal/<username>/recipes', methods=['GET', 'POST'])
def web_recipes_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    
    feedback_msg = None

    if request.method == 'POST':
        p_id = request.form.get('product_id')
        i_id = request.form.get('ingredient_id')
        try:
            qty_req = float(request.form.get('quantity_required', 0))
            conn = sqlite3.connect(client_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM Recipes WHERE Product_ID = ? AND Ingredient_ID = ?", (p_id, i_id))
            if cursor.fetchone():
                cursor.execute("UPDATE Recipes SET Quantity_Required = ? WHERE Product_ID = ? AND Ingredient_ID = ?", (qty_req, p_id, i_id))
                feedback_msg = "🔄 Recipe link row updated successfully!"
            else:
                cursor.execute("INSERT INTO Recipes (Product_ID, Ingredient_ID, Quantity_Required) VALUES (?, ?, ?)", (p_id, i_id, qty_req))
                feedback_msg = "💾 New material mapped to product recipe successfully!"
            conn.commit()
            conn.close()
        except ValueError:
            feedback_msg = "❌ Error: Please input a valid numeric quantity value."

    products_df = client_db.get_all_products()
    ingredients_df = client_db.get_inventory_status()
    
    dropdown_p = products_df.to_dict(orient='records') if not products_df.empty else []
    dropdown_i = ingredients_df.to_dict(orient='records') if not ingredients_df.empty else []

    matrix_rows = []
    if not products_df.empty:
        for _, row in products_df.iterrows():
            recipe_df = client_db.get_product_recipes(row['Product_ID'])
            items_list = recipe_df.to_dict(orient='records') if not recipe_df.empty else []
            matrix_rows.append({
                'product_id': row['Product_ID'],
                'product_name': row['Product_Name'],
                'category': row['Category'],
                'recipe_items': items_list
            })

    return render_template(
        'recipes.html',
        username=username,
        dropdown_products=dropdown_p,
        dropdown_ingredients=dropdown_i,
        matrix_rows=matrix_rows,
        msg=feedback_msg
    )