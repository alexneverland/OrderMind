import os
import pandas as pd

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")
os.makedirs(FIXTURES_DIR, exist_ok=True)

# 1. Sample Customers
customers_data = [
    {
        "ΚΩΔΙΚΟΣ_ΠΕΛΑΤΗ": "CUST-4531",
        "ΕΠΩΝΥΜΙΑ_ΠΕΛΑΤΗ": "ΑΒΓ Διανομές Α.Ε.",
        "EMAIL": "orders@avg-dianomes.test",
        "ΤΗΛΕΦΩΝΟ": "2101234567",
        "ΚΑΤΑΣΤΑΣΗ": "ΕΝΕΡΓΟΣ"
    },
    {
        "ΚΩΔΙΚΟΣ_ΠΕΛΑΤΗ": "CUST-1022",
        "ΕΠΩΝΥΜΙΑ_ΠΕΛΑΤΗ": "Μαρκάκης & Σία Ο.Ε.",
        "EMAIL": "info@markakis-foods.test",
        "ΤΗΛΕΦΩΝΟ": "2310987654",
        "ΚΑΤΑΣΤΑΣΗ": "ΕΝΕΡΓΟΣ"
    },
    {
        "ΚΩΔΙΚΟΣ_ΠΕΛΑΤΗ": "CUST-8840",
        "ΕΠΩΝΥΜΙΑ_ΠΕΛΑΤΗ": "Εστίαση Βορείου Ελλάδος",
        "EMAIL": "supply@estiasi-north.test",
        "ΤΗΛΕΦΩΝΟ": "2410555666",
        "ΚΑΤΑΣΤΑΣΗ": "ΕΝΕΡΓΟΣ"
    },
    {
        "ΚΩΔΙΚΟΣ_ΠΕΛΑΤΗ": "CUST-9999",
        "ΕΠΩΝΥΜΙΑ_ΠΕΛΑΤΗ": "Παντοπωλείο Η Γωνιά",
        "EMAIL": "gonia@fakemail.test",
        "ΤΗΛΕΦΩΝΟ": "2810112233",
        "ΚΑΤΑΣΤΑΣΗ": "ΕΝΕΡΓΟΣ"
    }
]
df_customers = pd.DataFrame(customers_data)
customers_path = os.path.join(FIXTURES_DIR, "sample_customers.xlsx")
df_customers.to_excel(customers_path, index=False)
print(f"Generated: {customers_path}")

# 2. Sample Products
products_data = [
    {
        "ΚΩΔΙΚΟΣ_ΕΙΔΟΥΣ": "SKU-7843",
        "ΠΕΡΙΓΡΑΦΗ": "Γαλοπούλα Καπνιστή 1kg",
        "BARCODE": "5201234567890",
        "ΜΟΝΑΔΑ_ΜΕΤΡΗΣΗΣ": "τεμάχιο",
        "ΕΝΕΡΓΟ": "ΝΑΙ"
    },
    {
        "ΚΩΔΙΚΟΣ_ΕΙΔΟΥΣ": "SKU-5001",
        "ΠΕΡΙΓΡΑΦΗ": "Ζαμπόν Βραστό 500g",
        "BARCODE": "5201234567891",
        "ΜΟΝΑΔΑ_ΜΕΤΡΗΣΗΣ": "τεμάχιο",
        "ΕΝΕΡΓΟ": "ΝΑΙ"
    },
    {
        "ΚΩΔΙΚΟΣ_ΕΙΔΟΥΣ": "SKU-5002",
        "ΠΕΡΙΓΡΑΦΗ": "Ζαμπόν Toast 500g",
        "BARCODE": "5201234567892",
        "ΜΟΝΑΔΑ_ΜΕΤΡΗΣΗΣ": "τεμάχιο",
        "ΕΝΕΡΓΟ": "ΝΑΙ"
    },
    {
        "ΚΩΔΙΚΟΣ_ΕΙΔΟΥΣ": "SKU-3300",
        "ΠΕΡΙΓΡΑΦΗ": "Σαλάμι Αέρος 300g",
        "BARCODE": "5201234567893",
        "ΜΟΝΑΔΑ_ΜΕΤΡΗΣΗΣ": "τεμάχιο",
        "ΕΝΕΡΓΟ": "ΝΑΙ"
    },
    {
        "ΚΩΔΙΚΟΣ_ΕΙΔΟΥΣ": "SKU-1200",
        "ΠΕΡΙΓΡΑΦΗ": "Τυρί Gouda Φέτες 1kg",
        "BARCODE": "5201234567894",
        "ΜΟΝΑΔΑ_ΜΕΤΡΗΣΗΣ": "τεμάχιο",
        "ΕΝΕΡΓΟ": "ΝΑΙ"
    }
]
df_products = pd.DataFrame(products_data)
products_path = os.path.join(FIXTURES_DIR, "sample_products.xlsx")
df_products.to_excel(products_path, index=False)
print(f"Generated: {products_path}")

# 3. Sample Packaging
packaging_data = [
    {
        "ΚΩΔ_ΕΙΔΟΥΣ": "SKU-7843",
        "ΤΥΠΟΣ_ΣΥΣΚΕΥΑΣΙΑΣ": "Κιβώτιο 10τεμ",
        "ΤΕΜ_ΚΙΒΩΤΙΟ": 10.0,
        "ΒΑΡΟΣ_KG": 10.5,
        "ΜΟΝΑΔΑ": "τεμάχιο",
        "ΚΩΔ_ΣΥΣΚΕΥΑΣΙΑΣ": "BOX-7843-10",
        "BARCODE_ΚΙΒΩΤΙΟΥ": "15201234567897"
    },
    {
        "ΚΩΔ_ΕΙΔΟΥΣ": "SKU-5001",
        "ΤΥΠΟΣ_ΣΥΣΚΕΥΑΣΙΑΣ": "Κιβώτιο 20τεμ",
        "ΤΕΜ_ΚΙΒΩΤΙΟ": 20.0,
        "ΒΑΡΟΣ_KG": 10.2,
        "ΜΟΝΑΔΑ": "τεμάχιο",
        "ΚΩΔ_ΣΥΣΚΕΥΑΣΙΑΣ": "BOX-5001-20",
        "BARCODE_ΚΙΒΩΤΙΟΥ": "15201234567898"
    },
    {
        "ΚΩΔ_ΕΙΔΟΥΣ": "SKU-5002",
        "ΤΥΠΟΣ_ΣΥΣΚΕΥΑΣΙΑΣ": "Κιβώτιο 20τεμ",
        "ΤΕΜ_ΚΙΒΩΤΙΟ": 20.0,
        "ΒΑΡΟΣ_KG": 10.2,
        "ΜΟΝΑΔΑ": "τεμάχιο",
        "ΚΩΔ_ΣΥΣΚΕΥΑΣΙΑΣ": "BOX-5002-20",
        "BARCODE_ΚΙΒΩΤΙΟΥ": "15201234567899"
    },
    {
        "ΚΩΔ_ΕΙΔΟΥΣ": "SKU-3300",
        "ΤΥΠΟΣ_ΣΥΣΚΕΥΑΣΙΑΣ": "Κιβώτιο 15τεμ",
        "ΤΕΜ_ΚΙΒΩΤΙΟ": 15.0,
        "ΒΑΡΟΣ_KG": 4.8,
        "ΜΟΝΑΔΑ": "τεμάχιο",
        "ΚΩΔ_ΣΥΣΚΕΥΑΣΙΑΣ": "BOX-3300-15",
        "BARCODE_ΚΙΒΩΤΙΟΥ": "15201234567890"
    }
]
df_packaging = pd.DataFrame(packaging_data)
packaging_path = os.path.join(FIXTURES_DIR, "sample_packaging.xlsx")
df_packaging.to_excel(packaging_path, index=False)
print(f"Generated: {packaging_path}")
