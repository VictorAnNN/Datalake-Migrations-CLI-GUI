-- Consolidação Gold BI-ready: Purchase Requisition (Order Tracking dashboard).
SELECT
    po_header_id,
    po_number,
    vendor_id,
    agent_id,
    creation_date AS DATA,
    authorization_status
FROM slv_po_headers
WHERE authorization_status = 'APPROVED'
