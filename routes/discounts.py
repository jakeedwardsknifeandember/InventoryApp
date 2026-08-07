from flask import Blueprint, request, redirect, session, render_template, flash
from modules.database import InventoryDB
import pandas as pd

discounts_bp = Blueprint('discounts', __name__)

@discounts_bp.route('/portal/<username>/discounts', methods=['GET', 'POST'])
def web_discounts_tab(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username: 
        return redirect('/login')

    if session.get('staff_role') != 'Platform Owner Admin':
        flash('Unauthorized access: Discounts management is strictly reserved for Platform Owner Admins.', 'danger')
        return redirect(f"/portal/{username}")
    
    db = InventoryDB(f"data/client_{username}.db")
    
    if request.method == 'POST':
        action = request.form.get('action_type')
        
        if action == 'add_discount':
            disc_name = request.form.get('discount_name', '').strip()
            disc_type = request.form.get('discount_type', 'Percentage')
            val = float(request.form.get('value', 0.0))
            
            discs_df = db.read_tab('Discounts')
            disc_id = f"DSC{len(discs_df) + 1:03d}"
            new_row = {'Discount_ID': disc_id, 'Discount_Name': disc_name, 'Discount_Type': disc_type, 'Value': val, 'Active': 'Yes'}
            discs_df = pd.concat([discs_df, pd.DataFrame([new_row])], ignore_index=True)
            db.save_tab('Discounts', discs_df)
            db.log_user_action(username, "ADD_DISCOUNT", "Discounts", f"Created discount '{disc_name}' ({val} {disc_type})")
            flash(f"Discount '{disc_name}' created successfully.", 'success')

        elif action == 'delete_discount':
            disc_id = request.form.get('discount_id')
            discs_df = db.read_tab('Discounts')
            discs_df = discs_df[discs_df['Discount_ID'] != disc_id]
            db.save_tab('Discounts', discs_df)
            flash("Discount deleted successfully.", 'info')

        return redirect(f"/portal/{username}/discounts")

    discs_df = db.read_tab('Discounts')
    discounts_list = discs_df.to_dict('records') if not discs_df.empty else []

    return render_template(
        'discounts.html',
        username=username,
        discounts=discounts_list
    )