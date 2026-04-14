from django.db import models
from decimal import Decimal
from django.contrib.auth.models import User

class Contact(models.Model):
    CONTACT_TYPES = [('CUSTOMER', 'ลูกค้า'), ('SUPPLIER', 'ซัพพลายเออร์')]
    name = models.CharField(max_length=200, verbose_name="ชื่อลูกค้า / ซัพพลายเออร์")
    tax_id = models.CharField(max_length=20, blank=True, null=True, verbose_name="เลขประจำตัวผู้เสียภาษี")
    address = models.TextField(blank=True, null=True, verbose_name="ที่อยู่")
    contact_type = models.CharField(max_length=10, choices=CONTACT_TYPES, default='CUSTOMER', verbose_name="ประเภท")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Product(models.Model):
    code = models.CharField(max_length=50, unique=True, verbose_name="รหัสสินค้า")
    name = models.CharField(max_length=200, verbose_name="ชื่อสินค้า")
    stock_quantity = models.IntegerField(default=0, verbose_name="จำนวนในคลัง")
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ราคากลางต่อหน่วย")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.code}] {self.name} (คงเหลือ: {self.stock_quantity})"

class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('BUY', 'ซื้อสินค้า (นำเข้า)'),
        ('SELL', 'ขายสินค้า (ส่งออก)'),
        ('INCOME', 'รายรับอื่นๆ'),
        ('EXPENSE', 'รายจ่ายอื่นๆ'),
    ]

    PAYMENT_STATUSES = [
        ('PAID', 'จ่ายแล้ว / ได้รับเงินแล้ว'),
        ('PENDING', 'ค้างชำระ / รอวางบิล'),
        ('CANCELLED', 'ยกเลิกรายการ'),
    ]

    CURRENCY_CHOICES = [
        ('THB', 'THB (Thai Baht)'),
        ('USD', 'USD (US Dollar)'),
        ('CNY', 'CNY (Chinese Yuan)'),
        ('JPY', 'JPY (Japanese Yen)'),
        ('EUR', 'EUR (Euro)'),
    ]

    EXPENSE_CATEGORIES = [
        ('N/A', 'ไม่ใช่รายจ่าย (N/A)'),
        ('COGS', 'ต้นทุนขาย (Cost of Goods Sold)'),
        ('OPEX', 'ค่าใช้จ่ายดำเนินงาน (Operational Expense)'),
        ('CAPEX', 'รายจ่ายลงทุน (Capital Expenditure)'),
    ]

    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES, verbose_name="ประเภทรายการ")
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUSES, default='PAID', verbose_name="สถานะการชำระเงิน")
    contact = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="คู่ค้า")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="สินค้าในคลัง")
    quantity = models.IntegerField(default=1, verbose_name="จำนวนหน่วย")
    
    title = models.CharField(max_length=200, verbose_name="ชื่อรายการ/สินค้า")
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='THB', verbose_name="สกุลเงิน")
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, default=1.0, verbose_name="อัตราแลกเปลี่ยน")
    foreign_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ยอดเงินต่างประเทศ")
    
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="จำนวนเงิน (ไม่รวม VAT)")
    has_vat = models.BooleanField(default=False, verbose_name="คิด VAT 7%")
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ยอด VAT")
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ยอดสุทธิ (รวม VAT)")
    expense_category = models.CharField(max_length=10, choices=EXPENSE_CATEGORIES, default='N/A', verbose_name="ประเภทค่าใช้จ่าย")
    tag = models.CharField(max_length=100, blank=True, null=True, verbose_name="แท็ก/หมวดหมู่ย่อย")
    receipt_file = models.FileField(upload_to='receipts/', blank=True, null=True, verbose_name="ไฟล์สลิป/ใบเสร็จ")
    date = models.DateField(verbose_name="วันที่ทำรายการ")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="ผู้บันทึก")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Calculate local THB price if foreign exists
        if self.currency != 'THB':
            self.price = round(self.foreign_price * self.exchange_rate, 2)
        else:
            self.foreign_price = self.price
            self.exchange_rate = Decimal('1.0')

        if self.has_vat:
            self.vat_amount = round(self.price * Decimal('0.07'), 2)
        else:
            self.vat_amount = Decimal('0.00')
        self.total_price = self.price + self.vat_amount
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.date} - {self.get_transaction_type_display()} - {self.title}"

class Quotation(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'ฉบับร่าง (รอพิจารณา)'),
        ('APPROVED', 'อนุมัติแล้ว'),
        ('REJECTED', 'ไม่อนุมัติ'),
    ]

    transaction_type = models.CharField(max_length=10, choices=Transaction.TRANSACTION_TYPES, verbose_name="ประเภทรายการ")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT', verbose_name="สถานะเอกสาร")
    is_converted = models.BooleanField(default=False, verbose_name="แปลงเป็นบิลแล้ว")
    
    contact = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="คู่ค้า")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="สินค้าในคลัง")
    quantity = models.IntegerField(default=1, verbose_name="จำนวนหน่วย")
    
    title = models.CharField(max_length=200, verbose_name="ชื่อรายการ/สินค้า")
    currency = models.CharField(max_length=3, choices=Transaction.CURRENCY_CHOICES, default='THB', verbose_name="สกุลเงิน")
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, default=1.0, verbose_name="อัตราแลกเปลี่ยน")
    foreign_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ยอดเงินต่างประเทศ")
    
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="จำนวนเงิน (ไม่รวม VAT)")
    has_vat = models.BooleanField(default=False, verbose_name="คิด VAT 7%")
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ยอด VAT")
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ยอดสุทธิ (รวม VAT)")
    expense_category = models.CharField(max_length=10, choices=Transaction.EXPENSE_CATEGORIES, default='N/A')
    tag = models.CharField(max_length=100, blank=True, null=True, verbose_name="แท็ก/หมวดหมู่ย่อย")
    receipt_file = models.FileField(upload_to='receipts/', blank=True, null=True, verbose_name="ไฟล์สลิป/อ้างอิง")
    date = models.DateField(verbose_name="วันที่ทำเอกสาร")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.currency != 'THB':
            self.price = round(self.foreign_price * self.exchange_rate, 2)
        else:
            self.foreign_price = self.price
            self.exchange_rate = Decimal('1.0')

        if self.has_vat:
            self.vat_amount = round(self.price * Decimal('0.07'), 2)
        else:
            self.vat_amount = Decimal('0.00')
        self.total_price = self.price + self.vat_amount
        super().save(*args, **kwargs)

    def __str__(self):
        return f"QT-{self.id:04d} ({self.status}) - {self.title}"
