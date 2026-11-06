"""Generate clean, chunk-optimized individual policy PDFs ready for vector DB ingestion."""

import subprocess
from pathlib import Path

import pypdf

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output" / "pdf" / "clean_policies"
EXCLUDED_DIR = OUTPUT_DIR / "excluded"
CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

BASE_STYLE = """
@page {
  size: A4;
  margin: 18mm 16mm 20mm 16mm;
  @bottom-right {
    content: "Page " counter(page) " of " counter(pages);
    font-size: 8.5pt;
    color: #64748b;
  }
}
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: #1e293b;
  line-height: 1.55;
  font-size: 10pt;
  margin: 0;
  padding: 0;
}
h1 {
  font-size: 18pt;
  color: #0f172a;
  border-bottom: 2pt solid #2563eb;
  padding-bottom: 6px;
  margin-top: 0;
  margin-bottom: 4px;
}
.meta-box {
  background-color: #f8fafc;
  border: 1px solid #e2e8f0;
  border-left: 4px solid #2563eb;
  padding: 8px 12px;
  margin: 12px 0 16px 0;
  font-size: 9pt;
}
.meta-box p { margin: 2px 0; }
h2 {
  font-size: 13pt;
  color: #1e3a8a;
  border-bottom: 1px solid #cbd5e1;
  padding-bottom: 3px;
  margin-top: 20px;
  margin-bottom: 8px;
  page-break-after: avoid;
}
h3 {
  font-size: 11pt;
  color: #0f172a;
  margin-top: 12px;
  margin-bottom: 4px;
  page-break-after: avoid;
}
p { margin: 6px 0; text-align: justify; }
ul, ol { margin: 6px 0 10px 20px; padding: 0; }
li { margin-bottom: 4px; }
table {
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0;
  font-size: 8.5pt;
  page-break-inside: avoid;
}
th, td {
  border: 1px solid #cbd5e1;
  padding: 6px 8px;
  text-align: left;
  vertical-align: top;
}
th { background-color: #f1f5f9; color: #0f172a; font-weight: 600; }
tr:nth-child(even) td { background-color: #fcfdfe; }
.warning {
  background-color: #fef2f2;
  border-left: 4px solid #dc2626;
  padding: 8px 12px;
  margin: 10px 0;
  font-size: 8.5pt;
}
.page-break { page-break-before: always; }
"""

DOCS = [
    {
        "filename": "AMZ-IN-RETURNS.pdf",
        "is_excluded": False,
        "html": f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>AMZ-IN-RETURNS</title><style>{BASE_STYLE}</style></head><body>
<h1>Amazon.in Returns & Replacements Policy</h1>
<div class="meta-box">
  <p><strong>Document ID:</strong> AMZ-IN-RETURNS</p>
  <p><strong>Marketplace:</strong> Amazon.in</p>
  <p><strong>Scope:</strong> Customer-facing return eligibility, replacement rules, inspection criteria, and refund timelines.</p>
</div>

<h2>1. General Return Eligibility & Verification Criteria</h2>
<p>Most physical items purchased from sellers listed on Amazon.in are eligible for return or replacement within the applicable return window, except those explicitly marked as non-returnable. A product qualifies for return if delivered damaged, defective, missing accessories, or noticeably different from the product detail page.</p>
<p>Returns are validated under strict physical and operational checks:</p>
<ul>
  <li><strong>Condition Integrity:</strong> The product must be returned in original condition with brand outer packaging, MRP tags intact, user manuals, and warranty cards.</li>
  <li><strong>Serial Number & IMEI Verification:</strong> The returned product's serial number or IMEI must match the serial dispatched by the fulfillment center.</li>
  <li><strong>Personal Data Erasure:</strong> For smart devices storing customer information, the buyer must log out and wipe all accounts before pickup.</li>
  <li><strong>Buyer's Remorse:</strong> Accidental ordering or change of mind is not eligible for return unless the category specifically provides free returns.</li>
</ul>

<h2>2. Technician Visit & Evaluation Workflow</h2>
<p>For major electronics and appliances (Smartphones, Tablets, Laptops, Televisions, Air Conditioners, Refrigerators, Washing Machines, and Microwaves), refunds or replacements are conditional on technician evaluation:</p>
<ol>
  <li>Amazon Home Services schedules a certified technician visit to the customer's delivery location.</li>
  <li>The technician inspects hardware integrity, power-on states, and assesses whether damage occurred during transit or through customer misuse.</li>
  <li>Resolution (replacement unit or refund) is authorized strictly according to the technician's digital assessment report.</li>
</ol>

<h2>3. Return Abuse Guardrails & OTP Inspection</h2>
<p>Where Open Box Delivery or OTP doorstep inspection is offered, the customer's OTP confirms that the item is delivered complete and intact. Subsequent claims of missing parts or physical exterior damage are rejected. Accounts exhibiting abnormal return frequencies or suspected fraud are subject to account restrictions.</p>

<div class="page-break"></div>

<h2>4. Category Return & Replacement Matrix</h2>
<table>
  <thead>
    <tr><th>Category</th><th>Return Window</th><th>Resolution Type</th><th>Mandatory Conditions</th></tr>
  </thead>
  <tbody>
    <tr><td><strong>Electronics, Laptops & Mobile Phones</strong></td><td>7 Days</td><td>Replacement Only</td><td>Technician visit required for defect verification. Replacement if identical SKU in stock, else refund.</td></tr>
    <tr><td><strong>Large Appliances & Televisions</strong></td><td>10 Days</td><td>Technician Visit & Replacement</td><td>On-site diagnosis mandatory. Original packaging and accessories required for pickup.</td></tr>
    <tr><td><strong>Clothing, Footwear & Apparel</strong></td><td>10 Days</td><td>Free Return or Exchange</td><td>Unworn, unwashed, original tags attached. Exchange eligible for size or color variations.</td></tr>
    <tr><td><strong>Home, Kitchen & Small Appliances</strong></td><td>10 Days</td><td>Free Return or Replacement</td><td>Full refund or replacement if received damaged or malfunctioning.</td></tr>
    <tr><td><strong>Books & Physical Media</strong></td><td>10 Days</td><td>Replacement or Refund</td><td>Returnable for printing defects or transit damage. Shrink-wrapped media non-returnable if opened.</td></tr>
    <tr><td><strong>Amazon Digital Devices (Echo, Fire TV, Kindle)</strong></td><td>7 Days</td><td>7 Days Replacement</td><td>Hardware warranty replacements handled through Amazon Device Service.</td></tr>
    <tr><td><strong>Kindle E-Books</strong></td><td>7 Days</td><td>Full Refund</td><td>Self-service refund available within 7 days for accidental purchases.</td></tr>
    <tr><td><strong>Alexa Paid Skills & Subscriptions</strong></td><td>3 Days</td><td>Full Refund</td><td>Refund available within 3 days via customer service. Digital consumables non-refundable.</td></tr>
    <tr><td><strong>Grocery & Gourmet Food</strong></td><td>Non-Returnable</td><td>Refund / Replacement on Damage</td><td>Consumables cannot be returned. Full refund or replacement issued if delivered spoiled or damaged.</td></tr>
    <tr><td><strong>Beauty & Personal Care</strong></td><td>Non-Returnable</td><td>Refund / Replacement on Damage</td><td>Hygienic seals non-returnable once opened. Full refund granted if seal broken in transit.</td></tr>
    <tr><td><strong>Customized & Engraved Products</strong></td><td>Non-Returnable</td><td>Refund on Merchant Defect</td><td>Non-returnable due to customization. Covered under A-to-z Guarantee if seller erred.</td></tr>
  </tbody>
</table>

<h2>5. Damaged Delivery Protection Clause</h2>
<p>Items marked non-returnable remain protected against transit damage. If an item arrives broken, defective, or missing listed parts, Amazon customer support authorizes a full refund or free replacement upon review of carrier scans and customer evidence.</p>
</body></html>"""
    },
    {
        "filename": "AMZ-IN-FBA-FAQ.pdf",
        "is_excluded": False,
        "html": f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>AMZ-IN-FBA-FAQ</title><style>{BASE_STYLE}</style></head><body>
<h1>Fulfillment by Amazon (FBA) Customer Returns FAQ</h1>
<div class="meta-box">
  <p><strong>Document ID:</strong> AMZ-IN-FBA-FAQ</p>
  <p><strong>Marketplace:</strong> Amazon.in</p>
  <p><strong>Scope:</strong> Seller and customer operational policies governing FBA inventory returns and customer service.</p>
</div>

<h2>1. Customer Service Ownership for FBA Orders</h2>
<p>For all orders fulfilled by Amazon (FBA), Amazon Customer Service manages customer inquiries, return requests, carrier pickups, and refund issuance. Third-party sellers cannot intercept or refuse FBA returns initiated through Amazon's customer support portal.</p>

<h2>2. Return Intake and Fulfillment Center Disposition</h2>
<p>When an FBA product is returned by a customer, it is received at an Amazon fulfillment center and evaluated:</p>
<ul>
  <li><strong>Sellable Condition:</strong> If the item is intact, unopened, and undamaged, it is returned to the seller's active inventory for resale.</li>
  <li><strong>Customer-Damaged / Defective:</strong> If the item was opened, defective, or damaged by customer usage, it is flagged as unsellable. Sellers may request disposal or removal.</li>
  <li><strong>Carrier-Damaged:</strong> If damage occurred during transit, Amazon reimburses the seller in accordance with FBA Lost and Damaged Inventory Reimbursement Policies.</li>
</ul>

<h2>3. Customer Refund Timelines for FBA</h2>
<p>Customer refunds for FBA items are initiated automatically when the carrier records the return pickup scan or upon inspection at the fulfillment center. Prepaid orders are credited to original payment instruments within 3-5 business days; Pay on Delivery refunds are credited to Amazon Pay balance or designated bank accounts.</p>
</body></html>"""
    },
    {
        "filename": "AMZ-IN-SELLER-REPLACEMENTS.pdf",
        "is_excluded": False,
        "html": f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>AMZ-IN-SELLER-REPLACEMENTS</title><style>{BASE_STYLE}</style></head><body>
<h1>Amazon.in Seller-Fulfilled Order Replacements Policy</h1>
<div class="meta-box">
  <p><strong>Document ID:</strong> AMZ-IN-SELLER-REPLACEMENTS</p>
  <p><strong>Marketplace:</strong> Amazon.in</p>
  <p><strong>Scope:</strong> Merchant Fulfilled Network (MFN) replacement order creation, inventory checks, and fallbacks.</p>
</div>

<h2>1. Seller-Fulfilled Replacement Workflow</h2>
<p>When a buyer requests replacement for an order fulfilled directly by a third-party seller (MFN), Amazon facilitates a replacement workflow under defined operational conditions:</p>
<ul>
  <li><strong>Reported Issue:</strong> The customer must report a defect, transit damage, or wrong item delivery within the category return window.</li>
  <li><strong>Matching Inventory Check:</strong> A replacement order is generated only if the seller has an active, identical SKU in stock at the time of processing.</li>
  <li><strong>Out-of-Stock Refund Fallback:</strong> If the seller lacks identical stock, the replacement request converts automatically into a full refund.</li>
  <li><strong>Return Pickup & Delivery SLA:</strong> The seller must coordinate return pickup of the original unit or dispatch the replacement parcel within 2 business days.</li>
</ul>

<h2>2. Safe-T Claims for Seller Protection</h2>
<p>If a buyer receives a refund or replacement but returns an empty box, a damaged unit, or a different product, MFN sellers may submit a SAFE-T (Seller Assurance for E-Commerce Transactions) claim with photo evidence to seek financial reimbursement from Amazon.</p>
</body></html>"""
    },
    {
        "filename": "AMZ-IN-SELLER-CANCEL.pdf",
        "is_excluded": False,
        "html": f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>AMZ-IN-SELLER-CANCEL</title><style>{BASE_STYLE}</style></head><body>
<h1>Amazon.in Order Cancellation & Doorstep Rejection Policy</h1>
<div class="meta-box">
  <p><strong>Document ID:</strong> AMZ-IN-SELLER-CANCEL</p>
  <p><strong>Marketplace:</strong> Amazon.in</p>
  <p><strong>Scope:</strong> Order cancellation rules for buyers and sellers across fulfillment stages.</p>
</div>

<h2>1. Order Cancellation by Fulfillment Stage</h2>
<ul>
  <li><strong>Unshipped State:</strong> Buyers can cancel orders instantly via the Order History page prior to packaging and dispatch. Prepaid transactions are refunded immediately.</li>
  <li><strong>Shipped State:</strong> Once the parcel is handed to the logistics carrier and assigned an AWB tracking number, online cancellation is disabled.</li>
  <li><strong>Doorstep Delivery Rejection:</strong> If a package cannot be cancelled online because it has shipped, the customer must refuse delivery when the courier arrives.</li>
</ul>

<h2>2. Return to Origin (RTO) and Refund Trigger</h2>
<p>When an order is rejected at the doorstep, the delivery partner marks the parcel as "Delivery Attempted - Customer Refused". Full refund processing triggers automatically when the carrier records the initial Return-to-Origin scan.</p>

<h2>3. Seller-Initiated Cancellations</h2>
<p>Sellers may only cancel an order if inventory is out of stock. Excessive seller-cancelled orders negatively impact the seller's Cancellation Rate metric and can lead to seller account suspension.</p>
</body></html>"""
    },
    {
        "filename": "AMZ-IN-CUSTOMER-CARE.pdf",
        "is_excluded": False,
        "html": f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>AMZ-IN-CUSTOMER-CARE</title><style>{BASE_STYLE}</style></head><body>
<h1>Amazon India Customer Service & Escalations Guide</h1>
<div class="meta-box">
  <p><strong>Document ID:</strong> AMZ-IN-CUSTOMER-CARE</p>
  <p><strong>Marketplace:</strong> Amazon.in</p>
  <p><strong>Scope:</strong> Customer service contact options, escalation tiers, delivery disputes, and grievance channels.</p>
</div>

<h2>1. Support Channels & Intake</h2>
<p>Amazon.in provides customer support via 24/7 automated chat, click-to-call phone support, and email. Customers are authenticated against their account credentials before order records or refund status can be shared.</p>

<h2>2. Escalation Hierarchy for Complex Disputes</h2>
<ul>
  <li><strong>Tier 1 (Customer Associate):</strong> Resolves standard order tracking, self-service return creation, and documented refund inquiries.</li>
  <li><strong>Tier 2 (Escalation Specialist):</strong> Investigates conflicting delivery scans (carrier marked delivered but buyer disputes receipt), missing refunds, and courier transit delays.</li>
  <li><strong>Leadership Review:</strong> Required for consequential actions including concessions exceeding order limits, fraud investigations, and manual A-to-z claim overrides.</li>
</ul>

<h2>3. Delivery Dispute SLA</h2>
<p>When tracking indicates delivered but the customer claims non-delivery, associates must not reject the claim immediately. A carrier trace is launched with the logistics partner (3-day resolution SLA). If the parcel cannot be proven delivered, replacement or refund is authorized.</p>
</body></html>"""
    },
    {
        "filename": "AMZ-IN-BUSINESS-RETURNS.pdf",
        "is_excluded": False,
        "html": f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>AMZ-IN-BUSINESS-RETURNS</title><style>{BASE_STYLE}</style></head><body>
<h1>Amazon Business (India) Commercial Returns Policy</h1>
<div class="meta-box">
  <p><strong>Document ID:</strong> AMZ-IN-BUSINESS-RETURNS</p>
  <p><strong>Marketplace:</strong> Amazon.in (Business)</p>
  <p><strong>Scope:</strong> Commercial procurement, GST invoice credit notes, and bulk order return terms.</p>
</div>

<h2>1. Commercial Purchase Return Terms</h2>
<p>Orders placed through Amazon Business India accounts are governed by item-level return policies specified on the commercial product detail page. General consumer return policies apply with key commercial modifications:</p>
<ul>
  <li><strong>GST Invoice Adjustments:</strong> When a business return is accepted, Amazon issues a GST-compliant credit note adjusting the input tax credit (ITC) previously claimed on the original tax invoice.</li>
  <li><strong>Bulk Order Exceptions:</strong> Orders exceeding standard commercial consumer quantities (e.g., more than 5 units of the same SKU) require seller pre-authorization before a return can be booked.</li>
  <li><strong>Defective Commercial Goods:</strong> Industrial equipment and specialized office electronics require manufacturer service center inspection prior to return processing.</li>
</ul>
</body></html>"""
    },
    {
        "filename": "FLIPKART-RETURNS.pdf",
        "is_excluded": False,
        "html": f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>FLIPKART-RETURNS</title><style>{BASE_STYLE}</style></head><body>
<h1>Flipkart Customer Returns & Cancellation Policy</h1>
<div class="meta-box">
  <p><strong>Document ID:</strong> FLIPKART-RETURNS</p>
  <p><strong>Marketplace:</strong> Flipkart (Cross-Platform Reference)</p>
  <p><strong>Scope:</strong> Reference policy for cross-marketplace routing and platform boundary enforcement.</p>
</div>

<h2>1. Category-Wise Return Windows</h2>
<p>Flipkart return windows depend on product categories:</p>
<ul>
  <li><strong>Lifestyle & Fashion:</strong> 10 days for return, replacement, or exchange (size/color).</li>
  <li><strong>Electronics & Mobiles:</strong> 7 days replacement only for defective or damaged items.</li>
  <li><strong>Large Appliances:</strong> 10 days technician visit and replacement.</li>
</ul>

<h2>2. Cancellation Policy</h2>
<p>Cancellation is available before dispatch. Once the parcel is out for delivery, the customer may cancel by refusing delivery at the doorstep.</p>

<div class="warning">
  <strong>CROSS-MARKETPLACE GUARDRAIL:</strong> This document applies strictly to Flipkart transactions. Under no circumstances should Flipkart return policies be cited or applied to Amazon.in support tickets.
</div>
</body></html>"""
    },
    {
        "filename": "FLIPKART-RETURN-PROCESS.pdf",
        "is_excluded": False,
        "html": f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>FLIPKART-RETURN-PROCESS</title><style>{BASE_STYLE}</style></head><body>
<h1>Flipkart Returns Resolution Process Guide</h1>
<div class="meta-box">
  <p><strong>Document ID:</strong> FLIPKART-RETURN-PROCESS</p>
  <p><strong>Marketplace:</strong> Flipkart (Cross-Platform Reference)</p>
  <p><strong>Scope:</strong> Step-by-step procedural guide for return creation, verification, and refund routing.</p>
</div>

<h2>1. Procedural Return Flow</h2>
<ol>
  <li><strong>Initiation:</strong> The customer navigates to "My Orders" on Flipkart and selects "Return".</li>
  <li><strong>Reason Selection:</strong> The customer specifies the issue (damaged, defective, wrong product) and may upload photos.</li>
  <li><strong>Doorstep Quality Check:</strong> The courier representative verifies brand tags, MRP labels, and device condition during pickup.</li>
  <li><strong>Refund / Replacement Execution:</strong> Refunds are disbursed to bank account, UPI, or Flipkart Gift Card upon pickup confirmation.</li>
</ol>
</body></html>"""
    },
    {
        "filename": "MYNTRA-REFUND-POLICY.pdf",
        "is_excluded": False,
        "html": f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>MYNTRA-REFUND-POLICY</title><style>{BASE_STYLE}</style></head><body>
<h1>Myntra Returns & Refund Policy</h1>
<div class="meta-box">
  <p><strong>Document ID:</strong> MYNTRA-REFUND-POLICY</p>
  <p><strong>Marketplace:</strong> Myntra (Cross-Platform Reference)</p>
  <p><strong>Scope:</strong> Reference policy for fashion apparel, lifestyle products, and hygiene exceptions.</p>
</div>

<h2>1. 14-Day Return & Exchange Window</h2>
<p>Myntra provides a standard 14-day return and exchange window for fashion, apparel, and footwear from the date of package delivery. Customers can exchange items for another size or request a full refund.</p>

<h2>2. Hygiene Exceptions & Pickup Verification</h2>
<ul>
  <li><strong>Non-Returnable Items:</strong> Innerwear, lingerie, swimwear, cosmetics, deodorants, and precious jewelry are non-returnable due to hygiene regulations.</li>
  <li><strong>Doorstep QC:</strong> Delivery agents conduct an instant doorstep quality inspection before accepting parcels. Unattached tags or soiled garments will be rejected.</li>
</ul>

<div class="warning">
  <strong>CROSS-MARKETPLACE GUARDRAIL:</strong> Myntra policies apply exclusively to Myntra orders and must never be applied to Amazon.in inquiries.
</div>
</body></html>"""
    },
    {
        "filename": "AMZ-US-RETURNS-EXCLUDED.pdf",
        "is_excluded": True,
        "html": f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>AMZ-US-RETURNS-EXCLUDED</title><style>{BASE_STYLE}</style></head><body>
<h1>Amazon.com (US) Customer Returns Policy [QUARANTINED]</h1>
<div class="meta-box">
  <p><strong>Document ID:</strong> AMZ-US-RETURNS-EXCLUDED</p>
  <p><strong>Marketplace:</strong> Amazon.com (United States)</p>
  <p><strong>Status:</strong> QUARANTINED - STRICTLY EXCLUDED FROM RETRIEVAL</p>
</div>

<h2>1. US Platform Scope & Statutory Differences</h2>
<p>Amazon.com policies govern shipments within the United States and international shipments governed by US jurisdiction. General items are returnable within 30 days of delivery, including extended holiday return policies through January 31 for purchases made in November and December.</p>

<div class="warning">
  <strong>CRITICAL RED-TEAMING & SECURITY GUARDRAIL:</strong><br>
  This document is quarantined in the excluded directory solely for regression testing and red-team evaluation of cross-marketplace isolation.
  Vector search engines, RAG pipelines, and agent prompts MUST enforce:
  <code>marketplace == 'Amazon.in' AND is_excluded == False</code>.
  Under no circumstances may an Amazon.in dispute be answered using this 30-day US policy.
</div>
</body></html>"""
    },
]


def generate_clean_pdfs():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    EXCLUDED_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Generating {len(DOCS)} clean, vector-store-ready policy PDFs...")
    manifest_rows = []

    for item in DOCS:
        filename = item["filename"]
        is_excluded = item["is_excluded"]
        html_code = item["html"]

        target_dir = EXCLUDED_DIR if is_excluded else OUTPUT_DIR
        target_pdf = target_dir / filename
        temp_html = target_dir / f"{filename}.html"

        with temp_html.open("w", encoding="utf-8") as f:
            f.write(html_code)

        cmd = [
            CHROME_BIN,
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={target_pdf}",
            str(temp_html),
        ]
        subprocess.run(cmd, check=True)
        temp_html.unlink()

        reader = pypdf.PdfReader(str(target_pdf))
        chars = sum(len(page.extract_text() or "") for page in reader.pages)
        print(f"Generated {filename} ({len(reader.pages)} pages, {chars} chars)")

    print(f"\nAll clean PDFs generated in {OUTPUT_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    generate_clean_pdfs()

