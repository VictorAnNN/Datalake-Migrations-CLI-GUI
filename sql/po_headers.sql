-- Adaptado de OTBI "Purchase Order Headers" para Spark SQL sobre a TempView Bronze.
SELECT
    po_header_id,
    segment1 AS po_number,
    vendor_id,
    agent_id,
    creation_date,
    authorization_status
FROM brz_po_headers_all
WHERE authorization_status IS NOT NULL
