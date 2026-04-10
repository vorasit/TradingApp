from django.db import models
from decimal import Decimal

class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('BUY', 'ซื้อสินค้า (นำเข้า)'),
        ('SELL', 'ขายสินค้า (ส่งออก)'),
        ('INCOME', 'รายรับอื่นๆ'),
        ('EXPENSE', 'รายจ่ายอื่นๆ'),
    ]

    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES, verbose_name="ประเภทรายการ")
    title = models.CharField(max_length=200, verbose_name="ชื่อรายการ/สินค้า")
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="จำนวนเงิน (ไม่รวม VAT)")
    has_vat = models.BooleanField(default=False, verbose_name="คิด VAT 7%")
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ยอด VAT")
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ยอดสุทธิ (รวม VAT)")
    date = models.DateField(verbose_name="วันที่ทำรายการ")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.has_vat:
            self.vat_amount = round(self.price * Decimal('0.07'), 2)
        else:
            self.vat_amount = Decimal('0.00')
        self.total_price = self.price + self.vat_amount
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.date} - {self.get_transaction_type_display()} - {self.title}"
