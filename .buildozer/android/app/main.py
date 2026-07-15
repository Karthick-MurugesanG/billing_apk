import os
import ssl
import sqlite3
import threading

# Bypass SSL certificates
os.environ['PYTHONHTTPSVERIFY'] = '0'
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

from kivy.metrics import dp
from kivy.lang import Builder
from kivymd.app import MDApp
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.list import TwoLineListItem, ThreeLineListItem
from kivymd.uix.textfield import MDTextField
from kivymd.uix.boxlayout import MDBoxLayout
from kivy.utils import platform

# ── DATABASE ──────────────────────────────────────────────────────────────────
def init_database():
    conn = sqlite3.connect("billing_system.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, price REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT,
        total_amount REAL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER,
        product_name TEXT, qty INTEGER, price REAL,
        FOREIGN KEY(order_id) REFERENCES orders(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, value TEXT)''')
    conn.commit()
    conn.close()

def get_setting(key, default=None):
    try:
        conn = sqlite3.connect("billing_system.db")
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default

def save_setting(key, value):
    try:
        conn = sqlite3.connect("billing_system.db")
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
    except Exception:
        pass

init_database()

def get_products():
    conn = sqlite3.connect("billing_system.db")
    rows = conn.execute("SELECT id, name, price FROM products ORDER BY name ASC").fetchall()
    conn.close()
    return rows

def add_product(name, price):
    try:
        conn = sqlite3.connect("billing_system.db")
        conn.execute("INSERT INTO products (name, price) VALUES (?, ?)", (name, price))
        conn.commit()
        conn.close()
        return True, "Product added successfully!"
    except sqlite3.IntegrityError:
        return False, "This product name already exists."
    except Exception as e:
        return False, f"Error: {str(e)}"

def delete_product(pid):
    conn = sqlite3.connect("billing_system.db")
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit()
    conn.close()

def update_product_db(pid, name, price):
    try:
        conn = sqlite3.connect("billing_system.db")
        conn.execute("UPDATE products SET name=?, price=? WHERE id=?", (name, price, pid))
        conn.commit()
        conn.close()
        return True, "Product updated!"
    except sqlite3.IntegrityError:
        return False, "Product name already exists."
    except Exception as e:
        return False, str(e)

def save_order(customer_name, items, total_amount):
    conn = sqlite3.connect("billing_system.db")
    c = conn.cursor()
    c.execute("INSERT INTO orders (customer_name, total_amount) VALUES (?,?)", (customer_name, total_amount))
    oid = c.lastrowid
    for item in items:
        c.execute("INSERT INTO order_items (order_id, product_name, qty, price) VALUES (?,?,?,?)",
                  (oid, item['name'], item['qty'], item['price']))
    conn.commit()
    conn.close()
    return oid

def get_orders():
    conn = sqlite3.connect("billing_system.db")
    rows = conn.execute("SELECT id, customer_name, total_amount, timestamp FROM orders ORDER BY id DESC").fetchall()
    conn.close()
    return rows

def get_order_items(oid):
    conn = sqlite3.connect("billing_system.db")
    rows = conn.execute("SELECT product_name, qty, price FROM order_items WHERE order_id=?", (oid,)).fetchall()
    conn.close()
    return rows

def check_and_request_bluetooth_permissions():
    if platform != 'android':
        return True, ""
    try:
        from android.permissions import check_permission, Permission, request_permissions
        from android import api_version
        
        sdk_int = api_version
        
        if sdk_int >= 31:
            has_connect = check_permission(Permission.BLUETOOTH_CONNECT)
            has_scan = check_permission(Permission.BLUETOOTH_SCAN)
            
            to_request = []
            if not has_connect:
                to_request.append(Permission.BLUETOOTH_CONNECT)
            if not has_scan:
                to_request.append(Permission.BLUETOOTH_SCAN)
                
            if to_request:
                request_permissions(to_request)
                return False, "Bluetooth permissions are required. Requesting permissions... Please allow and try again."
        return True, ""
    except Exception as e:
        return False, f"Failed to check/request permissions: {str(e)}"

def print_via_bluetooth(receipt_text, is_android):
    if not is_android:
        print("\n=== MOCK BLUETOOTH PRINT ===")
        print(receipt_text)
        print("============================\n")
        return True, "Mock printed successfully (Not on Android)"

    perm_ok, perm_msg = check_and_request_bluetooth_permissions()
    if not perm_ok:
        return False, perm_msg

    try:
        from jnius import autoclass
        from java.util import UUID
        
        BluetoothAdapter = autoclass('android.bluetooth.BluetoothAdapter')
        adapter = BluetoothAdapter.getDefaultAdapter()
        if not adapter:
            return False, "Bluetooth adapter not found"
        if not adapter.isEnabled():
            return False, "Bluetooth is turned off"

        devices = adapter.getBondedDevices().toArray()
        printer_device = None
        
        for d in devices:
            name = d.getName().lower()
            if any(keyword in name for keyword in ["print", "mpt", "pos", "thermal", "rpp"]):
                printer_device = d
                break
            
        if not printer_device:
            return False, "No paired Bluetooth printer found (make sure printer name contains POS, Print, or Thermal)"

        spp_uuid = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")
        socket = printer_device.createRfcommSocketToServiceRecord(spp_uuid)
        socket.connect()
        
        out_stream = socket.getOutputStream()
        out_stream.write(bytes([27, 64])) 
        out_stream.write(receipt_text.encode('utf-8'))
        out_stream.write(bytes([10, 10, 10, 29, 86, 48]))
        out_stream.flush()
        socket.close()
        return True, "Printed successfully!"
    except Exception as e:
        return False, f"Print error: {str(e)}"

def check_bluetooth_printer(is_android):
    if not is_android:
        return True, "Mock Printer"
    
    perm_ok, perm_msg = check_and_request_bluetooth_permissions()
    if not perm_ok:
        return False, perm_msg

    try:
        from jnius import autoclass
        BluetoothAdapter = autoclass('android.bluetooth.BluetoothAdapter')
        adapter = BluetoothAdapter.getDefaultAdapter()
        if not adapter:
            return False, "Bluetooth adapter not found"
        if not adapter.isEnabled():
            return False, "Bluetooth is turned off"

        devices = adapter.getBondedDevices().toArray()
        for d in devices:
            name = d.getName().lower()
            if any(keyword in name for keyword in ["print", "mpt", "pos", "thermal", "rpp"]):
                return True, "Printer found"
            
        return False, "No paired Bluetooth printer found"
    except Exception as e:
        return False, f"Bluetooth check error: {str(e)}"

def generate_receipt_text(shop_name, items):
    receipt = []
    receipt.append(f"{shop_name.center(32)}\n")
    receipt.append("-" * 32 + "\n")
    
    total_qty = 0
    grand_total = 0.0
    
    for item in items:
        name = item['name']
        qty = item['qty']
        price = item['price']
        total = item['total']
        total_qty += qty
        grand_total += total
        
        receipt.append(f"{name}\n")
        line_details = f"  {qty} x Rs.{price:.2f}"
        total_str = f"Rs.{total:.2f}"
        spaces = 32 - len(line_details) - len(total_str)
        receipt.append(f"{line_details}{' ' * max(1, spaces)}{total_str}\n")
        
    receipt.append("-" * 32 + "\n")
    receipt.append(f"Total Qty: {total_qty}\n")
    receipt.append(f"Grand Total: Rs.{grand_total:.2f}\n")
    receipt.append("-" * 32 + "\n")
    receipt.append(f"{'Thank you!'.center(32)}\n")
    return "".join(receipt)


KV = '''
MDScreen:
    MDBoxLayout:
        orientation: 'vertical'
        
        MDTopAppBar:
            title: "Store Billing System"
            elevation: 2
            left_action_items: [["storefront", lambda x: x]]

        MDBottomNavigation:
            id: bottom_nav
            panel_color: app.theme_cls.bg_dark

            MDBottomNavigationItem:
                name: 'screen_billing'
                text: 'Billing'
                icon: 'receipt'
                
                MDBoxLayout:
                    orientation: 'vertical'
                    padding: "10dp"
                    spacing: "10dp"
                    
                    MDTextField:
                        id: shop_name
                        hint_text: "Shop Name"
                        text: app.saved_shop_name
                        on_text: app.save_shop_name(self.text)
                        
                    MDTextField:
                        id: customer_name
                        hint_text: "Customer Name"
                        text: "Walk-in Customer"
                        
                    MDDropDownItem:
                        id: product_dropdown
                        text: "Select Product"
                        on_release: app.menu.open()
                        
                    MDBoxLayout:
                        spacing: "10dp"
                        size_hint_y: None
                        height: "48dp"
                        
                        MDTextField:
                            id: price_input
                            hint_text: "Price (Rs)"
                            input_filter: "float"
                            text: "0"
                            
                        MDTextField:
                            id: qty_input
                            hint_text: "Qty"
                            input_filter: "int"
                            text: "1"
                            
                        MDRaisedButton:
                            text: "Add"
                            on_release: app.add_to_bill()
                            pos_hint: {"center_y": .5}
                            
                    MDLabel:
                        id: billing_status
                        text: "Tap an item below to remove it"
                        theme_text_color: "Primary"
                        size_hint_y: None
                        height: self.texture_size[1]
                        
                    MDScrollView:
                        MDList:
                            id: bill_list
                        
                    MDBoxLayout:
                        size_hint_y: None
                        height: "48dp"
                        
                        MDLabel:
                            id: grand_total
                            text: "Total: Rs.0.00"
                            font_style: "H6"
                            theme_text_color: "Custom"
                            text_color: app.theme_cls.primary_color
                            
                        MDRaisedButton:
                            text: "Print & Save"
                            md_bg_color: "green"
                            on_release: app.save_and_print_bill()

            MDBottomNavigationItem:
                name: 'screen_inventory'
                text: 'Inventory'
                icon: 'package-variant'
                
                MDBoxLayout:
                    orientation: 'vertical'
                    padding: "10dp"
                    spacing: "10dp"
                    
                    MDLabel:
                        text: "Add New Product"
                        font_style: "H6"
                        size_hint_y: None
                        height: self.texture_size[1]
                        
                    MDTextField:
                        id: new_prod_name
                        hint_text: "Product Name"
                        
                    MDBoxLayout:
                        spacing: "10dp"
                        size_hint_y: None
                        height: "48dp"
                        
                        MDTextField:
                            id: new_prod_price
                            hint_text: "Price"
                            input_filter: "float"
                            
                        MDRaisedButton:
                            text: "Save"
                            on_release: app.add_new_product()
                            pos_hint: {"center_y": .5}
                            
                    MDLabel:
                        id: prod_status
                        text: "Tap a product below to Edit or Delete"
                        theme_text_color: "Primary"
                        size_hint_y: None
                        height: self.texture_size[1]
                        
                    MDScrollView:
                        MDList:
                            id: products_list

            MDBottomNavigationItem:
                name: 'screen_history'
                text: 'History'
                icon: 'history'
                
                MDBoxLayout:
                    orientation: 'vertical'
                    padding: "10dp"
                    spacing: "10dp"
                    
                    MDLabel:
                        text: "Tap an order to view purchased items"
                        theme_text_color: "Primary"
                        size_hint_y: None
                        height: self.texture_size[1]
                        
                    MDScrollView:
                        MDList:
                            id: history_list
'''

class BillingApp(MDApp):
    def build(self):
        self.theme_cls.primary_palette = "Blue"
        self.saved_shop_name = get_setting("shop_name", "My Store")
        
        self.active_bill_items = []
        self.products_map = {}
        self.menu = None
        self.dialog = None
        
        return Builder.load_string(KV)

    def on_start(self):
        self.update_products_list()
        self.update_history_list()
        if platform == 'android':
            check_and_request_bluetooth_permissions()
        
    def save_shop_name(self, name):
        save_setting("shop_name", name.strip())

    def update_products_list(self):
        prods = get_products()
        self.products_map = {str(p[0]): {"name": p[1], "price": p[2]} for p in prods}
        
        menu_items = []
        for p in prods:
            menu_items.append({
                "text": f"{p[1]} (Rs.{p[2]:.2f})",
                "viewclass": "OneLineListItem",
                "on_release": lambda x=str(p[0]): self.menu_callback(x),
            })
            
        self.menu = MDDropdownMenu(
            caller=self.root.ids.product_dropdown,
            items=menu_items,
            width_mult=4,
        )
        
        self.root.ids.products_list.clear_widgets()
        for p in prods:
            pid = str(p[0])
            name = p[1]
            price = p[2]
            item = TwoLineListItem(
                text=f"{name}",
                secondary_text=f"Price: Rs.{price:.2f}  |  ID: {pid}",
                on_release=lambda x, p_id=pid: self.show_product_options(p_id)
            )
            self.root.ids.products_list.add_widget(item)

    def update_history_list(self):
        orders = get_orders()
        self.root.ids.history_list.clear_widgets()
        
        for o in orders:
            oid = str(o[0])
            cust = o[1]
            total = o[2]
            date = o[3]
            item = ThreeLineListItem(
                text=f"Order #{oid} - {cust}",
                secondary_text=f"Total: Rs.{total:.2f}",
                tertiary_text=f"{date}",
                on_release=lambda x, o_id=oid: self.show_order_details(o_id)
            )
            self.root.ids.history_list.add_widget(item)

    def menu_callback(self, prod_id):
        self.menu.dismiss()
        self.root.ids.product_dropdown.text = self.products_map[prod_id]["name"]
        self.root.ids.price_input.text = str(self.products_map[prod_id]["price"])
        self.selected_product_id = prod_id

    def add_to_bill(self):
        if self.root.ids.product_dropdown.text == "Select Product":
            self.root.ids.billing_status.text = "Select a product first."
            self.root.ids.billing_status.theme_text_color = "Error"
            return
            
        try:
            qty = int(self.root.ids.qty_input.text)
            price = float(self.root.ids.price_input.text)
            if qty <= 0 or price < 0: raise ValueError
        except ValueError:
            self.root.ids.billing_status.text = "Invalid qty or price."
            self.root.ids.billing_status.theme_text_color = "Error"
            return
            
        name = self.root.ids.product_dropdown.text
        
        existing = next((i for i in self.active_bill_items if i["name"] == name), None)
        if existing:
            existing["qty"] += qty
            existing["price"] = price
            existing["total"] = existing["qty"] * price
        else:
            self.active_bill_items.append({"name": name, "qty": qty, "price": price, "total": qty * price})
            
        self.root.ids.billing_status.text = f"Added {name} x{qty}"
        self.root.ids.billing_status.theme_text_color = "Custom"
        self.root.ids.billing_status.text_color = [0, 0.8, 0, 1]
        
        self.root.ids.qty_input.text = "1"
        self.root.ids.price_input.text = "0"
        self.root.ids.product_dropdown.text = "Select Product"
        self.update_bill_table()

    def update_bill_table(self):
        self.root.ids.bill_list.clear_widgets()
        grand = sum(i['total'] for i in self.active_bill_items)
        
        for i in self.active_bill_items:
            item_name = i['name']
            qty = i['qty']
            price = i['price']
            total = i['total']
            
            list_item = TwoLineListItem(
                text=f"{item_name}",
                secondary_text=f"Rs.{price:.2f} x {qty} = Rs.{total:.2f}",
                on_release=lambda x, n=item_name: self.confirm_remove_bill_item(n)
            )
            self.root.ids.bill_list.add_widget(list_item)
            
        self.root.ids.grand_total.text = f"Total: Rs.{grand:.2f}"

    def confirm_remove_bill_item(self, item_name):
        self.active_bill_items = [i for i in self.active_bill_items if i['name'] != item_name]
        self.update_bill_table()

    def show_product_options(self, pid):
        name = self.products_map.get(pid, {}).get("name", "Unknown")
        price = self.products_map.get(pid, {}).get("price", "0")
        
        self.dialog = MDDialog(
            title=f"Options for {name}",
            type="custom",
            buttons=[
                MDFlatButton(
                    text="CANCEL",
                    on_release=lambda x: self.dialog.dismiss()
                ),
                MDRaisedButton(
                    text="DELETE",
                    md_bg_color="red",
                    on_release=lambda x: self.delete_and_dismiss(pid)
                ),
                MDRaisedButton(
                    text="EDIT",
                    md_bg_color="blue",
                    on_release=lambda x: self.show_edit_product_dialog(pid, name, price)
                ),
            ],
        )
        self.dialog.open()
        
    def show_edit_product_dialog(self, pid, name, price):
        self.dialog.dismiss()
        
        self.edit_name_input = MDTextField(text=name, hint_text="Product Name")
        self.edit_price_input = MDTextField(text=str(price), hint_text="Price", input_filter="float")
        
        box = MDBoxLayout(orientation="vertical", spacing="12dp", size_hint_y=None, height="120dp")
        box.add_widget(self.edit_name_input)
        box.add_widget(self.edit_price_input)
        
        self.dialog = MDDialog(
            title=f"Edit Product",
            type="custom",
            content_cls=box,
            buttons=[
                MDFlatButton(
                    text="CANCEL",
                    on_release=lambda x: self.dialog.dismiss()
                ),
                MDRaisedButton(
                    text="SAVE",
                    on_release=lambda x: self.save_edited_product(pid)
                ),
            ],
        )
        self.dialog.open()
        
    def save_edited_product(self, pid):
        new_name = self.edit_name_input.text.strip()
        try:
            new_price = float(self.edit_price_input.text)
            if not new_name or new_price < 0: raise ValueError
        except:
            self.root.ids.prod_status.text = "Invalid name or price."
            self.root.ids.prod_status.theme_text_color = "Error"
            return
            
        ok, msg = update_product_db(pid, new_name, new_price)
        if ok:
            self.update_products_list()
            self.dialog.dismiss()
            self.root.ids.prod_status.text = "Product updated."
            self.root.ids.prod_status.theme_text_color = "Custom"
            self.root.ids.prod_status.text_color = [0, 0.8, 0, 1]
        else:
            self.root.ids.prod_status.text = msg
            self.root.ids.prod_status.theme_text_color = "Error"
            self.dialog.dismiss()

    def delete_and_dismiss(self, pid):
        delete_product(pid)
        self.update_products_list()
        self.dialog.dismiss()
        self.root.ids.prod_status.text = "Product deleted."
        self.root.ids.prod_status.theme_text_color = "Custom"
        self.root.ids.prod_status.text_color = [0, 0.8, 0, 1]

    def show_order_details(self, oid):
        items = get_order_items(oid)
        details = "\n".join([f"• {name}  (x{qty})  = Rs.{price*qty:.2f}" for name, qty, price in items])
        
        self.dialog = MDDialog(
            title=f"Order #{oid} Items",
            text=details,
            buttons=[
                MDFlatButton(
                    text="CLOSE",
                    on_release=lambda x: self.dialog.dismiss()
                ),
            ],
        )
        self.dialog.open()

    def add_new_product(self):
        name = self.root.ids.new_prod_name.text.strip()
        try:
            price = float(self.root.ids.new_prod_price.text)
            if not name or price < 0: raise ValueError
        except ValueError:
            self.root.ids.prod_status.text = "Invalid name or price."
            self.root.ids.prod_status.theme_text_color = "Error"
            return
            
        ok, msg = add_product(name, price)
        if ok:
            self.root.ids.prod_status.text = msg
            self.root.ids.prod_status.theme_text_color = "Custom"
            self.root.ids.prod_status.text_color = [0, 0.8, 0, 1]
            self.root.ids.new_prod_name.text = ""
            self.root.ids.new_prod_price.text = ""
            self.update_products_list()
        else:
            self.root.ids.prod_status.text = msg
            self.root.ids.prod_status.theme_text_color = "Error"

    def save_and_print_bill(self):
        if not self.active_bill_items:
            self.root.ids.billing_status.text = "Bill is empty."
            self.root.ids.billing_status.theme_text_color = "Error"
            return
            
        shop_name = self.root.ids.shop_name.text.strip() or "My Store"
        cust = self.root.ids.customer_name.text.strip() or "Walk-in Customer"
        total = sum(i['total'] for i in self.active_bill_items)
        
        is_android = platform == 'android'
        printer_ok, printer_msg = check_bluetooth_printer(is_android)
        
        receipt_text = generate_receipt_text(shop_name, self.active_bill_items)
        
        oid = save_order(cust, self.active_bill_items, total)
        self.active_bill_items.clear()
        self.root.ids.customer_name.text = "Walk-in Customer"
        self.update_bill_table()
        self.update_history_list()
        
        if not printer_ok:
            self.root.ids.billing_status.text = f"Order #{oid} saved. Print Failed: {printer_msg}"
            self.root.ids.billing_status.theme_text_color = "Error"
            return
            
        self.root.ids.billing_status.text = f"Order #{oid} saved. Printing..."
        self.root.ids.billing_status.theme_text_color = "Custom"
        self.root.ids.billing_status.text_color = [0, 0, 0.8, 1]
        
        def run_printing():
            ok, msg = print_via_bluetooth(receipt_text, is_android)
            if ok:
                pass 
        
        threading.Thread(target=run_printing, daemon=True).start()

if __name__ == "__main__":
    BillingApp().run()
