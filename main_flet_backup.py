import os
import ssl
import sqlite3
import flet as ft
import threading

# Bypass SSL certificates
os.environ['PYTHONHTTPSVERIFY'] = '0'
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

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
    conn.commit(); conn.close()

init_database()

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
        conn.commit(); conn.close()
    except Exception:
        pass

init_database()

def get_products():
    conn = sqlite3.connect("billing_system.db")
    rows = conn.execute("SELECT id, name, price FROM products ORDER BY name ASC").fetchall()
    conn.close(); return rows

def add_product(name, price):
    try:
        conn = sqlite3.connect("billing_system.db")
        conn.execute("INSERT INTO products (name, price) VALUES (?, ?)", (name, price))
        conn.commit(); conn.close()
        return True, "Product added successfully!"
    except sqlite3.IntegrityError:
        return False, "This product name already exists."
    except Exception as e:
        return False, f"Error: {str(e)}"

def delete_product(pid):
    conn = sqlite3.connect("billing_system.db")
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit(); conn.close()

def update_product_db(pid, name, price):
    try:
        conn = sqlite3.connect("billing_system.db")
        conn.execute("UPDATE products SET name=?, price=? WHERE id=?", (name, price, pid))
        conn.commit(); conn.close()
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
    conn.commit(); conn.close(); return oid

def get_orders():
    conn = sqlite3.connect("billing_system.db")
    rows = conn.execute("SELECT id, customer_name, total_amount, timestamp FROM orders ORDER BY id DESC").fetchall()
    conn.close(); return rows

def get_order_items(oid):
    conn = sqlite3.connect("billing_system.db")
    rows = conn.execute("SELECT product_name, qty, price FROM order_items WHERE order_id=?", (oid,)).fetchall()
    conn.close(); return rows

def print_via_bluetooth(receipt_text, is_android):
    if not is_android:
        print("\n=== MOCK BLUETOOTH PRINT ===")
        print(receipt_text)
        print("============================\n")
        return True, "Mock printed successfully (Not on Android)"

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
        
        # Look for typical printer names
        for d in devices:
            name = d.getName().lower()
            if any(keyword in name for keyword in ["print", "mpt", "pos", "thermal", "rpp"]):
                printer_device = d
                break
            
        if not printer_device:
            return False, "No paired Bluetooth printer found (make sure printer name contains POS, Print, or Thermal)"

        # Standard UUID for SPP (Serial Port Profile) Bluetooth printers
        spp_uuid = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")
        socket = printer_device.createRfcommSocketToServiceRecord(spp_uuid)
        socket.connect()
        
        out_stream = socket.getOutputStream()
        # Initialize printer
        out_stream.write(bytes([27, 64])) 
        # Send raw receipt text
        out_stream.write(receipt_text.encode('utf-8'))
        # Feed line and cut
        out_stream.write(bytes([10, 10, 10, 29, 86, 48]))
        out_stream.flush()
        socket.close()
        return True, "Printed successfully!"
    except Exception as e:
        return False, f"Print error: {str(e)}"

def check_bluetooth_printer(is_android):
    if not is_android:
        return True, "Mock Printer"

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
            
        return False, "No paired Bluetooth printer found (make sure printer name contains POS, Print, or Thermal)"
    except Exception as e:
        return False, f"Bluetooth check error: {str(e)}"

# ── APP ───────────────────────────────────────────────────────────────────────
def main(page: ft.Page):
    page.title = "Store Billing & Inventory System"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = "white"
    page.padding = 0

    active_bill_items = []
    products_map = {}

    # Define on_product_change
    def on_product_change(e):
        sid = product_dropdown.value
        if sid == "ADD_NEW_PROD":
            product_dropdown.value = None
            show_quick_add_dialog()
        elif sid:
            # Look up product by string key in products_map
            sid_str = str(sid)
            if sid_str in products_map:
                price_input.value = f"{products_map[sid_str]['price']:.2f}"
                price_input.update()

    # ── CONTROLS ──────────────────────────────────────────────────────────────
    saved_shop_name = get_setting("shop_name", "My Store")
    shop_name_input = ft.TextField(
        label="Shop Name", 
        value=saved_shop_name, 
        border_radius=8, 
        expand=True
    )
    
    def on_shop_name_change(e):
        save_setting("shop_name", shop_name_input.value.strip())
        
    shop_name_input.on_change = on_shop_name_change

    customer_input   = ft.TextField(label="Customer Name", value="Walk-in Customer",
                                    border_radius=8, expand=True)
    product_dropdown = ft.Dropdown(label="Select Product", border_radius=8, expand=True)
    product_dropdown.on_select = on_product_change
    price_input      = ft.TextField(label="Price (₹)", value="0.00", width=110,
                                    keyboard_type=ft.KeyboardType.NUMBER, border_radius=8,
                                    input_filter=ft.InputFilter(regex_string=r"[0-9.]", allow=True))
    qty_input        = ft.TextField(label="Qty", value="1", width=75,
                                    keyboard_type=ft.KeyboardType.NUMBER, border_radius=8,
                                    input_filter=ft.InputFilter(regex_string=r"[0-9]", allow=True))
    billing_status   = ft.Text("", size=13, weight=ft.FontWeight.BOLD)
    total_text       = ft.Text("Total: ₹0.00", size=18, weight=ft.FontWeight.BOLD, color="blue800")

    bill_table = ft.DataTable(column_spacing=18, columns=[
        ft.DataColumn(ft.Text("Item",   weight=ft.FontWeight.BOLD)),
        ft.DataColumn(ft.Text("Price",  weight=ft.FontWeight.BOLD), numeric=True),
        ft.DataColumn(ft.Text("Qty",    weight=ft.FontWeight.BOLD), numeric=True),
        ft.DataColumn(ft.Text("Total",  weight=ft.FontWeight.BOLD), numeric=True),
        ft.DataColumn(ft.Text("",       weight=ft.FontWeight.BOLD)),
    ], rows=[])

    prod_name_input  = ft.TextField(label="Product Name", border_radius=8)
    prod_price_input = ft.TextField(label="Price (₹)", keyboard_type=ft.KeyboardType.NUMBER,
                                    border_radius=8, width=130,
                                    input_filter=ft.InputFilter(regex_string=r"[0-9.]", allow=True))
    prod_status = ft.Text("", size=13, weight=ft.FontWeight.BOLD)

    products_table = ft.DataTable(column_spacing=18, columns=[
        ft.DataColumn(ft.Text("ID",           weight=ft.FontWeight.BOLD)),
        ft.DataColumn(ft.Text("Product Name", weight=ft.FontWeight.BOLD)),
        ft.DataColumn(ft.Text("Price",        weight=ft.FontWeight.BOLD), numeric=True),
        ft.DataColumn(ft.Text("Actions",      weight=ft.FontWeight.BOLD)),
    ], rows=[])

    history_table = ft.DataTable(column_spacing=18, columns=[
        ft.DataColumn(ft.Text("Order ID",    weight=ft.FontWeight.BOLD)),
        ft.DataColumn(ft.Text("Customer",    weight=ft.FontWeight.BOLD)),
        ft.DataColumn(ft.Text("Total",       weight=ft.FontWeight.BOLD), numeric=True),
        ft.DataColumn(ft.Text("Date & Time", weight=ft.FontWeight.BOLD)),
        ft.DataColumn(ft.Text("Details",     weight=ft.FontWeight.BOLD)),
    ], rows=[])

    # ── DATA REFRESH ──────────────────────────────────────────────────────────
    def update_billing_dropdown():
        nonlocal products_map
        prods = get_products()
        products_map = {str(p[0]): {"name": p[1], "price": p[2]} for p in prods}
        opts = [ft.dropdown.Option(key="ADD_NEW_PROD", text="➕ Add New Product...")]
        opts += [ft.dropdown.Option(key=str(p[0]), text=f"{p[1]}  (₹{p[2]:.2f})") for p in prods]
        product_dropdown.options = opts
        product_dropdown.value = None
        page.update()

    def update_bill_table():
        bill_table.rows.clear()
        grand = 0.0
        for idx, item in enumerate(active_bill_items):
            grand += item['total']
            bill_table.rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(item['name'])),
                ft.DataCell(ft.Text(f"₹{item['price']:.2f}")),
                ft.DataCell(ft.Text(str(item['qty']))),
                ft.DataCell(ft.Text(f"₹{item['total']:.2f}")),
                ft.DataCell(ft.IconButton(
                    icon=ft.Icons.DELETE_OUTLINE, icon_color="red400",
                    on_click=lambda e, i=idx: (active_bill_items.pop(i), update_bill_table())
                )),
            ]))
        total_text.value = f"Total: ₹{grand:.2f}"
        page.update()

    def update_products_list():
        prods = get_products()
        products_table.rows.clear()
        for pid, name, price in prods:
            products_table.rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(str(pid))),
                ft.DataCell(ft.Text(name)),
                ft.DataCell(ft.Text(f"₹{price:.2f}")),
                ft.DataCell(ft.Row([
                    ft.IconButton(icon=ft.Icons.EDIT, icon_color="blue700", tooltip="Edit",
                                  on_click=lambda e, p=pid, n=name, pr=price: show_edit_dialog(p, n, pr)),
                    ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color="red400", tooltip="Delete",
                                  on_click=lambda e, p=pid: (delete_product(p), update_products_list(), update_billing_dropdown())),
                ], tight=True, spacing=0)),
            ]))
        page.update()

    def update_history_list():
        history_table.rows.clear()
        for oid, cust, total, ts in get_orders():
            history_table.rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(f"#{oid}")),
                ft.DataCell(ft.Text(cust)),
                ft.DataCell(ft.Text(f"₹{total:.2f}")),
                ft.DataCell(ft.Text(ts)),
                ft.DataCell(ft.IconButton(
                    icon=ft.Icons.REMOVE_RED_EYE, icon_color="blue700",
                    on_click=lambda e, o=oid, c=cust, t=total, d=ts: show_order_details(o, c, t, d)
                )),
            ]))
        page.update()

    # ── HANDLERS ──────────────────────────────────────────────────────────────
    # def on_product_change(e):
    #     sid = product_dropdown.value
    #     if sid == "ADD_NEW_PROD":
    #         product_dropdown.value = None
    #         show_quick_add_dialog()
    #     elif sid and sid in products_map:
    #         price_input.value = f"{products_map[sid]['price']:.2f}"
    #         page.update()

    # product_dropdown.on_change = on_product_change

    def add_to_bill(e):
        sid = product_dropdown.value
        if not sid or sid == "ADD_NEW_PROD":
            billing_status.value = "❌ Please select a product."; billing_status.color = "red700"; page.update(); return
        try:
            qty = int(qty_input.value or "0")
            if qty <= 0: raise ValueError
        except ValueError:
            billing_status.value = "❌ Quantity must be a positive number."; billing_status.color = "red700"; page.update(); return
        try:
            price = float(price_input.value or "0")
            if price < 0: raise ValueError
        except ValueError:
            billing_status.value = "❌ Price must be valid."; billing_status.color = "red700"; page.update(); return
        name = products_map[sid]["name"]
        existing = next((i for i in active_bill_items if i["name"] == name), None)
        if existing:
            existing["qty"] += qty; existing["price"] = price; existing["total"] = existing["qty"] * price
        else:
            active_bill_items.append({"name": name, "qty": qty, "price": price, "total": qty * price})
        billing_status.value = f"✅ Added {name} ×{qty}"; billing_status.color = "green700"
        qty_input.value = "1"; price_input.value = "0.00"; product_dropdown.value = None
        update_bill_table()

    def generate_receipt_text(shop_name, items):
        # 32 columns standard for 58mm thermal printers
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
            
            # Print item name on its own line if long, or fit it
            receipt.append(f"{name}\n")
            # Layout line: Qty x Price = Total
            line_details = f"  {qty} x Rs.{price:.2f}"
            total_str = f"Rs.{total:.2f}"
            spaces = 32 - len(line_details) - len(total_str)
            receipt.append(f"{line_details}{' ' * max(1, spaces)}{total_str}\n")
            
        receipt.append("-" * 32 + "\n")
        
        # Totals
        qty_line = f"Total Qty: {total_qty}"
        total_line = f"Grand Total: Rs.{grand_total:.2f}"
        receipt.append(f"{qty_line}\n")
        receipt.append(f"{total_line}\n")
        receipt.append("-" * 32 + "\n")
        receipt.append(f"{'Thank you!'.center(32)}\n")
        return "".join(receipt)

    def save_and_print_bill(e):
        if not active_bill_items:
            billing_status.value = "❌ Add at least one item first."; billing_status.color = "red700"; page.update(); return
            
        shop_name = shop_name_input.value.strip() or "My Store"
        cust = customer_input.value.strip() or "Walk-in Customer"
        total = sum(i['total'] for i in active_bill_items)
        
        # Detect if we are running on Android using Flet's page.platform
        is_android = page.platform == ft.PagePlatform.ANDROID
        
        # Check printer status synchronously first
        printer_ok, printer_msg = check_bluetooth_printer(is_android)
        
        # Generate receipt text before clearing items
        receipt_text = generate_receipt_text(shop_name, active_bill_items)
        
        # Save to database
        oid = save_order(cust, active_bill_items, total)
        active_bill_items.clear(); customer_input.value = "Walk-in Customer"
        
        # If no printer is connected, update UI to warning instantly
        if not printer_ok:
            billing_status.value = f"⚠️ Order #{oid} saved but Print Failed: {printer_msg}"
            billing_status.color = "orange700"
            update_bill_table()
            return
            
        # If printer exists, set status to printing and start printing thread
        billing_status.value = f"✅ Order #{oid} saved! Printing..."; billing_status.color = "blue700"
        update_bill_table()
        
        # Print using Bluetooth in background thread so the app UI does not freeze
        def run_printing():
            ok, msg = print_via_bluetooth(receipt_text, is_android)

            if ok:
                billing_status.value = f"✅ Order #{oid} saved & Printed!"; billing_status.color = "green700"
            else:
                billing_status.value = f"⚠️ Order #{oid} saved but Print Failed: {msg}"; billing_status.color = "orange700"
            page.update()
            
        threading.Thread(target=run_printing, daemon=True).start()

    def add_product_action(e):
        name = prod_name_input.value.strip()
        if not name:
            prod_status.value = "❌ Name cannot be blank."; prod_status.color = "red700"; page.update(); return
        try:
            price = float(prod_price_input.value or "0")
            if price < 0: raise ValueError
        except ValueError:
            prod_status.value = "❌ Price must be valid."; prod_status.color = "red700"; page.update(); return
        ok, msg = add_product(name, price)
        if ok:
            prod_status.value = f"✅ {msg}"; prod_status.color = "green700"
            prod_name_input.value = ""; prod_price_input.value = ""
            update_products_list(); update_billing_dropdown()
        else:
            prod_status.value = f"❌ {msg}"; prod_status.color = "red700"; page.update()

    # ── DIALOGS ───────────────────────────────────────────────────────────────
    def show_edit_dialog(pid, cur_name, cur_price):
        ef_name  = ft.TextField(label="Product Name", value=cur_name, border_radius=8)
        ef_price = ft.TextField(label="Price (₹)", value=str(cur_price),
                                keyboard_type=ft.KeyboardType.NUMBER, border_radius=8,
                                input_filter=ft.InputFilter(regex_string=r"[0-9.]", allow=True))
        ef_err = ft.Text("", color="red700", size=12)
        def do_save(e):
            n = ef_name.value.strip()
            if not n: ef_err.value = "❌ Name blank."; page.update(); return
            try:
                p = float(ef_price.value); assert p >= 0
            except Exception:
                ef_err.value = "❌ Invalid price."; page.update(); return
            ok, msg = update_product_db(pid, n, p)
            if ok:
                dlg.open = False; update_products_list(); update_billing_dropdown(); page.update()
            else:
                ef_err.value = f"❌ {msg}"; page.update()
        dlg = ft.AlertDialog(
            title=ft.Text(f"Edit Product #{pid}"),
            content=ft.Column([ef_name, ef_price, ef_err], tight=True, spacing=10),
            actions=[ft.TextButton("Cancel", on_click=lambda e: (setattr(dlg, 'open', False), page.update())),
                     ft.FilledButton("Save", on_click=do_save, bgcolor="blue700")],
            actions_alignment=ft.MainAxisAlignment.END)
        page.show_dialog(dlg)

    def show_order_details(oid, cust, total, ts):
        items = get_order_items(oid)
        rows = [ft.Text(f"Customer: {cust}", weight=ft.FontWeight.BOLD),
                ft.Text(f"Date: {ts}", size=12, color="grey600"),
                ft.Divider(), ft.Text("Items:", weight=ft.FontWeight.BOLD)]
        for name, qty, price in items:
            rows.append(ft.Text(f"• {name} ×{qty} @ ₹{price:.2f} = ₹{qty*price:.2f}"))
        rows += [ft.Divider(),
                 ft.Text(f"Grand Total: ₹{total:.2f}", size=16, weight=ft.FontWeight.BOLD, color="green700")]
        page.show_dialog(ft.AlertDialog(
            title=ft.Text(f"Order #{oid} Details"),
            content=ft.Column(rows, tight=True, spacing=8, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Close", on_click=lambda e: page.pop_dialog())]))

    def show_quick_add_dialog():
        qn = ft.TextField(label="Product Name", border_radius=8)
        qp = ft.TextField(label="Price (₹)", keyboard_type=ft.KeyboardType.NUMBER, border_radius=8,
                          input_filter=ft.InputFilter(regex_string=r"[0-9.]", allow=True))
        qe = ft.Text("", color="red700", size=12)
        def do_add(e):
            name = qn.value.strip()
            if not name: qe.value = "❌ Name blank."; page.update(); return
            try:
                price = float(qp.value); assert price >= 0
            except Exception:
                qe.value = "❌ Invalid price."; page.update(); return
            ok, msg = add_product(name, price)
            if ok:
                page.pop_dialog(); update_products_list(); update_billing_dropdown()
                new_id = next((str(p[0]) for p in get_products() if p[1] == name), None)
                if new_id:
                    product_dropdown.value = new_id; price_input.value = f"{price:.2f}"
                billing_status.value = f"✅ '{name}' added!"; billing_status.color = "green700"; page.update()
            else:
                qe.value = f"❌ {msg}"; page.update()
        page.show_dialog(ft.AlertDialog(
            title=ft.Text("Quick Add Product"),
            content=ft.Column([qn, qp, qe], tight=True, spacing=10),
            actions=[ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog()),
                     ft.FilledButton("Add", on_click=do_add, bgcolor="blue700")],
            actions_alignment=ft.MainAxisAlignment.END))

    # ── TABLE CARD ────────────────────────────────────────────────────────────
    def table_card(table):
        return ft.Container(
            content=ft.Row([table], scroll=ft.ScrollMode.AUTO),
            border=ft.Border(
                top=ft.BorderSide(1, "black12"), right=ft.BorderSide(1, "black12"),
                bottom=ft.BorderSide(1, "black12"), left=ft.BorderSide(1, "black12")),
            border_radius=8, padding=8)

    # ── TAB PAGE CONTENTS ─────────────────────────────────────────────────────
    billing_page = ft.Column([
        ft.Text("Create New Invoice", size=20, weight=ft.FontWeight.BOLD, color="blue800"),
        ft.Row([shop_name_input, customer_input], spacing=8),
        ft.Divider(),
        ft.Row([product_dropdown], spacing=0),
        ft.Row([price_input, qty_input,
                ft.FilledButton("Add to Bill", icon=ft.Icons.ADD, bgcolor="blue700",
                                color="white", on_click=add_to_bill, height=48)],
               spacing=8, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        billing_status,
        ft.Divider(),
        ft.Text("Active Bill Items", size=16, weight=ft.FontWeight.BOLD),
        table_card(bill_table),
        ft.Row([total_text,
                ft.FilledButton("Print & Save Invoice", icon=ft.Icons.PRINT,
                                bgcolor="green700", color="white",
                                on_click=save_and_print_bill, height=48)],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
    ], spacing=14, scroll=ft.ScrollMode.AUTO)

    products_page = ft.Column([
        ft.Text("Add New Product", size=20, weight=ft.FontWeight.BOLD, color="blue800"),
        prod_name_input,
        ft.Row([prod_price_input,
                ft.FilledButton("Save Product", icon=ft.Icons.SAVE, bgcolor="blue700",
                                color="white", on_click=add_product_action, height=48)],
               spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        prod_status,
        ft.Divider(),
        ft.Text("Current Inventory", size=18, weight=ft.FontWeight.BOLD),
        table_card(products_table),
    ], spacing=14, scroll=ft.ScrollMode.AUTO)

    history_page = ft.Column([
        ft.Text("Sales History Log", size=20, weight=ft.FontWeight.BOLD, color="blue800"),
        table_card(history_table),
    ], spacing=14, scroll=ft.ScrollMode.AUTO)

    # ── TABS — correct Flet 0.85.3 API ───────────────────────────────────────
    # ft.Tab only accepts: label, icon, height, icon_margin
    # Tab content goes in ft.TabBarView(controls=[...])
    # ft.Tabs wraps TabBar + TabBarView via content=ft.Column([...])

    def on_tab_change(e):
        idx = tabs.selected_index
        if idx == 1:   update_products_list()
        elif idx == 2: update_history_list()
        else:          update_billing_dropdown()

    tab_bar = ft.TabBar(tabs=[
        ft.Tab(label="Billing Desk",      icon=ft.Icons.RECEIPT_LONG),
        ft.Tab(label="Product Inventory", icon=ft.Icons.INVENTORY),
        ft.Tab(label="Sales History",     icon=ft.Icons.HISTORY),
    ])

    h = page.height or 600
    tab_bar_view = ft.TabBarView(
        controls=[
            ft.Container(content=billing_page,  padding=14, expand=True),
            ft.Container(content=products_page, padding=14, expand=True),
            ft.Container(content=history_page,  padding=14, expand=True),
        ],
        height=h - 160,
    )

    tabs = ft.Tabs(
        length=3,
        selected_index=0,
        animation_duration=300,
        on_change=on_tab_change,
        content=ft.Column([tab_bar, tab_bar_view], spacing=0),
        height=h - 100,
    )

    def on_resize(e):
        nh = page.height or 600
        tab_bar_view.height = nh - 160
        tabs.height = nh - 100
        page.update()

    page.on_resize = on_resize

    # ── PAGE ROOT ─────────────────────────────────────────────────────────────
    page.add(ft.Column([
        ft.Row([
            ft.Icon(ft.Icons.STOREFRONT, size=26, color="blue800"),
            ft.Text("Store Billing System", size=21, weight=ft.FontWeight.BOLD, color="blue800"),
        ], alignment=ft.MainAxisAlignment.CENTER),
        ft.Divider(height=1),
        tabs,
    ], spacing=4, expand=True))

    update_billing_dropdown()
    update_products_list()

ft.run(main)
