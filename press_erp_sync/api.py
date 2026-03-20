import frappe
from frappe import _
import json

@frappe.whitelist(allow_guest=True)
def handle_press_event():
    """
    Main webhook handler for events from Frappe Press.
    Expected headers: X-Press-Secret
    """
    if frappe.request.method != "POST":
        frappe.throw(_("Only POST requests are allowed"), frappe.PermissionError)

    verify_secret()

    try:
        data = json.loads(frappe.request.data)
    except Exception:
        frappe.throw(_("Invalid JSON payload"), frappe.ValidationError)

    event_type = data.get("event")
    payload = data.get("payload", {})

    # Log the incoming request
    log_entry = frappe.get_doc({
        "doctype": "Press Subscription Log",
        "event_type": event_type,
        "payload": json.dumps(data, indent=4),
        "status": "Processing"
    }).insert(ignore_permissions=True)
    
    frappe.db.commit()

    try:
        if event_type in ["payment_success", "signup", "renewal"]:
            process_sync(payload)
            log_entry.status = "Success"
        else:
            log_entry.status = "Ignored"
            log_entry.error_message = f"Unhandled event type: {event_type}"
    except Exception as e:
        log_entry.status = "Failed"
        log_entry.error_message = frappe.get_traceback()
        frappe.log_error(f"Press Sync Error: {str(e)}", "Press Sync")
    
    log_entry.save(ignore_permissions=True)
    frappe.db.commit()

    return {"status": "ok"}

def verify_secret():
    """Verify the X-Press-Secret header against Press Sync Settings."""
    incoming_secret = frappe.get_request_header("X-Press-Secret")

    # Retrieve stored secret using get_password (required for 'Password' field types)
    settings = frappe.get_single("Press Sync Settings")
    stored_secret = settings.get_password("api_secret") if settings else None

    if not stored_secret:
        frappe.log_error("Press Sync: API Secret is not set in Press Sync Settings", "Press Sync Auth")
        frappe.throw(_("API Secret not configured in ERPNext"), frappe.ValidationError)

    # Clean secrets
    incoming_clean = incoming_secret.strip() if incoming_secret else ""
    stored_clean = stored_secret.strip() if stored_secret else ""

    if incoming_clean != stored_clean:
        # Log limited debug info (first 3 chars) to help identify mismatch without exposing secret
        debug_msg = f"Secret Mismatch. Incoming starts with '{incoming_clean[:3]}...', Stored starts with '{stored_clean[:3]}...'"
        frappe.log_error(debug_msg, "Press Sync Auth")
        frappe.throw(_("Invalid API Secret"), frappe.AuthenticationError)

def process_sync(payload):
    """
    Orchestrates the creation of Customer, Subscription, Invoice, and Payment.
    """
    customer_data = payload.get("customer", {})
    subscription_data = payload.get("subscription", {})
    payment_data = payload.get("payment", {})

    # 1. Handle Customer
    customer = sync_customer(customer_data)

    # 2. Handle Subscription
    subscription = sync_subscription(customer, subscription_data)

    # 3. Handle Invoice & Payment if payment data exists
    if payment_data:
        invoice = create_invoice(customer, payment_data, subscription)
        create_payment_entry(invoice, payment_data)

def sync_customer(data):
    """Creates or updates a Customer record."""
    email = data.get("email")
    if not email:
        frappe.throw(_("Customer email is missing in payload"))

    name = data.get("name") or email
    
    customer_name = frappe.db.get_value("Customer", {"email_id": email}, "name")
    
    if customer_name:
        doc = frappe.get_doc("Customer", customer_name)
    else:
        doc = frappe.new_doc("Customer")
        doc.email_id = email
        doc.customer_group = frappe.db.get_single_value("Press Sync Settings", "default_customer_group") or "All Customer Groups"
        doc.territory = data.get("territory") or "All Territories"

    doc.customer_name = name
    doc.save(ignore_permissions=True)
    return doc.name

def sync_subscription(customer, data):
    """Creates or updates a Subscription record in ERPNext."""
    plan_id = data.get("plan_id")
    if not plan_id:
        return None

    # Logic to map Press plan_id to ERPNext Subscription Plan
    # For now, we assume the plan exists with the same ID or name
    
    sub_name = frappe.db.get_value("Subscription", {"customer": customer, "press_subscription_id": data.get("id")}, "name")
    
    if sub_name:
        doc = frappe.get_doc("Subscription", sub_name)
    else:
        doc = frappe.new_doc("Subscription")
        doc.customer = customer
        doc.press_subscription_id = data.get("id") # Custom field required

    doc.status = data.get("status", "Active")
    doc.start_date = data.get("start_date")
    doc.end_date = data.get("end_date")
    
    # Add plans
    doc.set("plans", [{"plan": plan_id, "qty": 1}])
    
    doc.save(ignore_permissions=True)
    return doc.name

def create_invoice(customer, payment, subscription):
    """Creates and submits a Sales Invoice."""
    si = frappe.new_doc("Sales Invoice")
    si.customer = customer
    si.posting_date = frappe.utils.today()
    si.due_date = frappe.utils.today()
    
    # Map subscription to items or use a generic "Service" item
    item_code = frappe.db.get_single_value("Press Sync Settings", "default_item") or "Subscription"
    
    si.append("items", {
        "item_code": item_code,
        "qty": 1,
        "rate": payment.get("amount", 0)
    })
    
    si.insert(ignore_permissions=True)
    si.submit()
    return si

def create_payment_entry(invoice, payment):
    """Creates and submits a Payment Entry for the Invoice."""
    pe = frappe.new_doc("Payment Entry")
    pe.payment_type = "Receive"
    pe.party_type = "Customer"
    pe.party = invoice.customer
    pe.received_amount = payment.get("amount", 0)
    pe.target_exchange_rate = 1.0
    pe.paid_amount = payment.get("amount", 0)
    
    pe.append("references", {
        "reference_doctype": "Sales Invoice",
        "reference_name": invoice.name,
        "total_amount": invoice.grand_total,
        "outstanding_amount": invoice.grand_total,
        "allocated_amount": invoice.grand_total
    })
    
    pe.insert(ignore_permissions=True)
    pe.submit()
    return pe
