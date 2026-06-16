# app.py - Multi-Client Separate Database Engine
from flask import Flask, render_template_string
from modules.database import InventoryDB
import os

app = Flask(__name__)

@app.route('/')
def welcome():
    """The central login gateway page"""
    html_page = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Knife and Ember Gate</title>
        <style>
            body { font-family: Arial, sans-serif; background-color: #1e1e2e; color: #cdd6f4; text-align: center; padding: 50px; }
            .card { background: #313244; display: inline-block; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }
            a { display: inline-block; background: #f38ba8; color: #1e1e2e; padding: 12px 24px; margin: 10px; border-radius: 6px; text-decoration: none; font-weight: bold; }
            a.client2 { background: #89b4fa; }
            a:hover { opacity: 0.9; }
        </style>
    </head>
    <body>
        <h1>🔥 Knife & Ember SaaS Platform 🔥</h1>
        <div class="card">
            <h2>Select a Client Portal Demo:</h2>
            <p>Each link boots up a completely isolated SQLite file!</p>
            <a href="/portal/bakery">Client 1: Bakery Shop Portal</a>
            <a href="/portal/kitchen" class="client2">Client 2: Fire Kitchen Portal</a>
        </div>
    </body>
    </html>
    """
    return render_template_string(html_page)


@app.route('/portal/<username>')
def client_portal(username):
    """Dynamically boots up a separate file based on the username in the link"""
    username = username.lower().strip()
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    
    try:
        ingredients_df = client_db.get_all_ingredients()
        
        if ingredients_df.empty:
            if username == "bakery":
                client_db.add_ingredient({'Ingredient_ID': 'ING001', 'Ingredient_Name': 'Premium Flour', 'Unit': 'kg', 'Current_Stock': 50, 'Active': 'Yes'})
            else:
                client_db.add_ingredient({'Ingredient_ID': 'ING001', 'Ingredient_Name': 'Chef Knives', 'Unit': 'pcs', 'Current_Stock': 12, 'Active': 'Yes'})
            
            ingredients_df = client_db.get_all_ingredients()

        item_list = ""
        for _, row in ingredients_df.iterrows():
            item_list += f"<li>📦 <b>{row['Ingredient_Name']}</b> — Stock: {row['Current_Stock']} {row['Unit']}</li>"
            
    except Exception as e:
        item_list = f"<li>Error loading client database: {e}</li>"

    html_page = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{username.capitalize()} Inventory</title>
        <style>
            body {{ font-family: Arial, sans-serif; background-color: #1a1a26; color: #a6adc8; padding: 40px; }}
            .container {{ max-width: 600px; margin: 0 auto; background: #242535; padding: 30px; border-radius: 10px; border-left: 5px solid {"#f38ba8" if username == "bakery" else "#89b4fa"}; }}
            h1 {{ color: #ffffff; text-transform: capitalize; margin-top: 0; }}
            ul {{ list-style-type: none; padding: 0; }}
            li {{ padding: 12px; background: #2e3047; margin: 8px 0; border-radius: 6px; color: #cdd6f4; }}
            .back-btn {{ display: inline-block; margin-top: 20px; color: #f38ba8; text-decoration: none; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>{username.capitalize()} Inventory Control</h1>
            <p>Database Source File Path: <code>{client_db_path}</code></p>
            <hr style="border: 0; border-top: 1px solid #45475a; margin: 20px 0;">
            <h3>Active Stock Records:</h3>
            <ul>
                {item_list}
            </ul>
            <a href="/" class="back-btn">← Back to SaaS Gateway</a>
        </div>
    </body>
    </html>
    """
    return render_template_string(html_page)

if __name__ == '__main__':
    app.run(debug=True)