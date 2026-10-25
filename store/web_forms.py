"""Public-site forms; all stock writes still go through phase-2 services."""
from django import forms
from django.db.models import Q

from .admin_forms import IssueStockForm, ReceiveStockForm
from .models import Category, Product, UnitOfMeasure


class StoreStyleMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            widget.attrs["class"] = (
                "st-check" if isinstance(widget, forms.CheckboxInput) else "st-input"
            )
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 3)
            if field.help_text:
                widget.attrs["aria-describedby"] = f"id_{name}_help"


class WebReceiveForm(StoreStyleMixin, ReceiveStockForm):
    pass


class WebIssueForm(StoreStyleMixin, IssueStockForm):
    pass


class CatalogFilterForm(StoreStyleMixin, forms.Form):
    q = forms.CharField(
        label="اسم المنتج أو الباركود", max_length=100, required=False,
        widget=forms.TextInput(attrs={"placeholder": "ابحث عن منتج..."}),
    )
    category = forms.ModelChoiceField(
        label="القسم", queryset=Category.objects.none(),
        empty_label="كل الأقسام", required=False,
    )
    state = forms.ChoiceField(
        label="الحالة", required=False,
        choices=[("", "كل المنتجات"), ("low", "مخزون منخفض"),
                 ("expiring", "قرب انتهاء الصلاحية"),
                 ("expired", "به دفعات منتهية")],
    )
    include_inactive = forms.BooleanField(
        label="إظهار الموقوف أيضًا", required=False,
    )

    def __init__(self, *args, include_inactive_allowed=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.all() if include_inactive_allowed else Category.objects.filter(is_active=True)
        if not include_inactive_allowed:
            self.fields.pop("include_inactive")


class ProductForm(StoreStyleMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "category", "unit", "barcode", "image", "minimum_stock",
                  "requires_expiry_date", "expiry_warning_days", "description", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3}),
                   "image": forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
                   "minimum_stock": forms.NumberInput(attrs={"min": "0", "step": "0.001"})}
        help_texts = {
            "minimum_stock": "يظهر التنبيه عند هذه الكمية أو أقل، بوحدة المنتج.",
            "barcode": "اختياري. اكتب الكود كما هو مع الأصفار في بدايته.",
            "image": "JPG / PNG / WebP - حتى 5 ميجابايت.",
            "is_active": "إيقاف المنتج يُخفيه عن الرهبان، ويحتفظ بسجله.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, model in (("category", Category), ("unit", UnitOfMeasure)):
            current_id = getattr(self.instance, f"{name}_id", None)
            self.fields[name].queryset = model.objects.filter(Q(is_active=True) | Q(pk=current_id))
        if self.instance.pk and self.instance.batches.exists():
            self.fields["unit"].disabled = True
            self.fields["unit"].help_text = "وحدة المنتج ثابتة بعد تسجيل دفعات له."

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image and hasattr(image, "image"):
            if image.size > 5 * 1024 * 1024:
                raise forms.ValidationError("حجم الصورة لا يتجاوز 5 ميجابايت.")
            if image.image.format not in ("JPEG", "PNG", "WEBP"):
                raise forms.ValidationError("اختر صورة JPG أو PNG أو WebP.")
        return image


class CategoryForm(StoreStyleMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "description", "sort_order", "is_active"]


class UnitForm(StoreStyleMixin, forms.ModelForm):
    class Meta:
        model = UnitOfMeasure
        fields = ["name", "symbol", "allow_fractions", "is_active"]
