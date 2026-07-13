# modules/auth_guard.py - Centralized SaaS Session & RBAC Gate Check
from flask import session, redirect, flash

def enforce_clearance(username, allowed_roles):
    """
    Verifies tenant isolation and validates user role clearance levels.
    Returns (True, None) if authorized, or (False, redirect_url) if blocked.
    """
    username = username.lower().strip()
    
    # Gate 1: Check Tenant Isolation Boundary
    if session.get('logged_in_user') != username:
        return False, '/login'
        
    # Fetch active user role session token (Defaults to Crew if empty)
    user_role = session.get('staff_role', 'Barista / Kitchen Crew')
    
    # Gate 2: Validate Security Level Clearance
    if user_role not in allowed_roles:
        # Gracefully kick unauthorized staff back to their allowed dashboard view with an alert banner
        return False, f"/portal/{username}?error=Access Denied: Your account role ({user_role}) does not have clearance to view that module."
        
    return True, None