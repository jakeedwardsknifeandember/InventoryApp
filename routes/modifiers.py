from flask import Blueprint, request, redirect, session, render_template, flash
from modules.database import InventoryDB
import pandas as pd

modifiers_bp = Blueprint('modifiers', __name__)

@modifiers_bp.route('/portal/<username>/modifiers', methods=['GET', 'POST'])
def web_modifiers_tab(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username: 
        return redirect('/login')

    if session.get('staff_role') != 'Platform Owner Admin':
        flash('Unauthorized access: Modifiers management is strictly reserved for Platform Owner Admins.', 'danger')
        return redirect(f"/portal/{username}")
    
    db = InventoryDB(f"data/client_{username}.db")
    
    if request.method == 'POST':
        action = request.form.get('action_type')
        
        if action == 'add_modifier':
            mod_name = request.form.get('modifier_name', '').strip()
            price = float(request.form.get('price', 0.0))
            
            mods_df = db.read_tab('Modifiers')
            mod_id = f"MOD{len(mods_df) + 1:03d}"
            new_row = {'Modifier_ID': mod_id, 'Modifier_Name': mod_name, 'Price': price, 'Active': 'Yes'}
            mods_df = pd.concat([mods_df, pd.DataFrame([new_row])], ignore_index=True)
            db.save_tab('Modifiers', mods_df)
            db.log_user_action(username, "ADD_MODIFIER", "Modifiers", f"Created modifier '{mod_name}' (PHP {price:.2f})")
            flash(f"Modifier '{mod_name}' added successfully.", 'success')

        elif action == 'delete_modifier':
            mod_id = request.form.get('modifier_id')
            mods_df = db.read_tab('Modifiers')
            mods_df = mods_df[mods_df['Modifier_ID'] != mod_id]
            db.save_tab('Modifiers', mods_df)
            flash("Modifier deleted successfully.", 'info')

        return redirect(f"/portal/{username}/modifiers")

    mods_df = db.read_tab('Modifiers')
    modifiers_list = mods_df.to_dict('records') if not mods_df.empty else []

    return render_template(
        'modifiers.html',
        username=username,
        modifiers=modifiers_list
    )