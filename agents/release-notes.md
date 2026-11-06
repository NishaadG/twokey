# Quillpay pricing rules: release notes

## 2.4.1

Pricing rules can now be edited in the Quillpay dashboard.

Known issue: the dashboard exports `bulk_discount_percent` as text such as `"15%"`.
Customers' services read this field as a number, so it must be written as `15`.

Fix to ship: release 2.4.2, with `bulk_discount_percent` as a number and `version`
set to `2.4.2`. Nothing else in `pricing.json` changes.
