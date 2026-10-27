from django import forms

from .models import Category


class StoreReportFilterForm(forms.Form):
    STATE_CHOICES = [
        ("all", "كل المنتجات"),
        ("low", "مخزون منخفض"),
        ("expiring", "قرب انتهاء الصلاحية"),
        ("expired", "منتهي الصلاحية"),
    ]

    category = forms.ModelChoiceField(
        queryset=Category.objects.none(),
        required=False,
        empty_label="كل الأقسام",
        label="القسم",
    )

    state = forms.ChoiceField(
        choices=STATE_CHOICES,
        required=False,
        initial="all",
        label="نوع التقرير",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["category"].queryset = (
            Category.objects
            .filter(is_active=True)
            .order_by("name")
        )