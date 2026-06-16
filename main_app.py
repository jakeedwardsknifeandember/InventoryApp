# main_app.py - Upgraded to support SQLite Database (.db)
import os
import sys
import traceback
import customtkinter as ctk

def setup_environment():
    """Setup Python environment"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    
    print("=" * 50)
    print("🚀 INVENTORY MANAGER - Starting...")
    print("=" * 50)

def main():
    """Main application entry point"""
    try:
        setup_environment()
        
        # Import modules
        from config import config  # Import the Config class instance
        from modules.database import InventoryDB
        from modules.gui_builder import InventoryGUI
        
        print("✅ Modules imported successfully")
        
        # Get config
        app_config = config.config  # This is the settings dictionary
        
        print(f"🏢 Business: {app_config.get('business_name', 'Unknown')}")
        
        # Initialize database 
        # (It passes the file string from your config.py, which is now our .db file!)
        db = InventoryDB(app_config['excel_file'])
        print(f"💾 Database: {app_config['excel_file']}")
        
        # Store config in db for SettingsGUI to access
        db.config = config  # Store the Config object
        
        # Setup GUI
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        # Create window
        window = ctk.CTk()
        window.title(f"Inventory Manager - {app_config['business_name']}")
        
        # Create app - pass the config DICTIONARY
        app = InventoryGUI(window, db, app_config)
        
        print("\n" + "=" * 50)
        print("✅ APPLICATION READY!")
        print("=" * 50)
        print("📊 Dashboard loaded successfully\n")
        
        # Start application
        window.mainloop()
        
    except FileNotFoundError as e:
        print(f"\n❌ FILE ERROR: {e}")
        # 🌟 WE CHANGED THIS TEXT: It now tells users to check for the .db file instead of the old excel sheet!
        print("Please check if data/inventory.db exists")
        
    except ImportError as e:
        print(f"\n❌ IMPORT ERROR: {e}")
        print("Required packages: pip install customtkinter pandas openpyxl")
        
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        traceback.print_exc()
        
    finally:
        if 'app' not in locals():
            input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()