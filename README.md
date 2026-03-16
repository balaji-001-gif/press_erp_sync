# Press ERP Sync

A custom Frappe application to sync customers, subscriptions, and payments from **Frappe Press** to **ERPNext**.

## Features

- **Webhook Handler**: A whitelisted API endpoint to receive `payment_success`, `signup`, and `renewal` events.
- **Auto-Provisioning**: Automatically creates/updates:
  - `Customer`
  - `Subscription`
  - `Sales Invoice` (Submitted)
  - `Payment Entry` (Submitted)
- **Monitoring**: `Press Subscription Log` doctype to track every incoming webhook and its processing status.
- **Secure**: Validates incoming requests using a shared secret (`X-Press-Secret`).

## Installation

```bash
bench get-app https://github.com/YOUR_USERNAME/press_erp_sync
bench install-app press_erp_sync
```

## Setup

1. Go to **Press Sync Settings** in ERPNext.
2. Set a secure **API Secret**.
3. Enable sync and set default Customer Group/Item.
4. In your **Frappe Press** site, configure webhooks to point to `https://your-erpnext-site.com/api/method/press_erp_sync.api.handle_press_event` with the same secret in the `X-Press-Secret` header.

## License

MIT
