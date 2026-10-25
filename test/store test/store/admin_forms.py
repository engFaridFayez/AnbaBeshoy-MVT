"""نماذج العمليات داخل Django Admin، دون تعديل الموديلات."""
from decimal import Decimal

from django import forms
from django.utils import timezone

from .models import StockBatch, validate_unit_quantity


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class QuantityForm(forms.Form):
    quantity = forms.DecimalField(
        label="الكمية",
        min_value=Decimal("0.001"),
        max_digits=12,
        decimal_places=3,
        widget=forms.NumberInput(attrs={"step": "0.001", "min": "0.001"}),
    )
    reference = forms.CharField(
        label="رقم إذن أو فاتورة",
        max_length=100,
        required=False,
    )
    notes = forms.CharField(
        label="ملاحظات",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, product, **kwargs):
        super().__init__(*args, **kwargs)
        self.product = product
        self.fields["quantity"].label = f"الكمية ({product.unit.name})"
        if not product.unit.allow_fractions:
            self.fields["quantity"].widget.attrs.update(step="1", min="1")

    def clean_quantity(self):
        value = self.cleaned_data["quantity"]
        validate_unit_quantity(value, self.product.unit)
        return value


class ReceiveStockForm(QuantityForm):
    received_date = forms.DateField(
        label="تاريخ الاستلام",
        initial=timezone.localdate,
        widget=DateInput(),
    )
    production_date = forms.DateField(
        label="تاريخ الإنتاج",
        required=False,
        widget=DateInput(),
    )
    expiry_date = forms.DateField(
        label="تاريخ الانتهاء",
        required=False,
        widget=DateInput(),
    )
    source = forms.ChoiceField(
        label="نوع الوارد",
        choices=StockBatch.Source.choices,
        initial=StockBatch.Source.PURCHASE,
    )
    supplier_name = forms.CharField(
        label="المورد / جهة التبرع", max_length=160, required=False,
    )
    supplier_batch_number = forms.CharField(
        label="رقم التشغيلة", max_length=100, required=False,
    )
    storage_location = forms.CharField(
        label="مكان التخزين", max_length=120, required=False,
    )

    field_order = [
        "quantity", "received_date", "production_date", "expiry_date",
        "source", "supplier_name", "supplier_batch_number",
        "storage_location", "reference", "notes",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expiry_date"].required = self.product.requires_expiry_date


class IssueStockForm(QuantityForm):
    recipient = forms.CharField(
        label="المستلم / جهة الصرف",
        max_length=160,
        help_text="مثال: المطبخ أو اسم المستلم.",
    )
    field_order = ["quantity", "recipient", "reference", "notes"]
