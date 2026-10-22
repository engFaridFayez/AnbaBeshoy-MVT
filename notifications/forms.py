from datetime import timedelta

from django import forms
from django.utils import timezone

from kitchen.models import DailyMenu
from .models import MenuAudience
from .services import eligible_users


class UserChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, user):
        return (getattr(user, "display_name", "") or user.username) + f" ({user.username})"


class MenuChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, menu):
        return f"{menu.date:%Y-%m-%d} — {menu.get_meal_type_display()}"


class AudienceForm(forms.Form):
    mode = forms.ChoiceField(
        label="إلى من؟", choices=MenuAudience.Mode.choices,
        widget=forms.RadioSelect,
    )
    users = UserChoiceField(
        label="المستخدمون", queryset=None, required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["users"].queryset = eligible_users()

    def clean(self):
        data = super().clean()
        if data.get("mode") == MenuAudience.Mode.SELECTED and not data.get("users"):
            self.add_error("users", "اختَر مستخدمًا واحدًا على الأقل، أو اختَر الكل.")
        return data

    def recipients(self):
        if self.cleaned_data["mode"] == MenuAudience.Mode.ALL:
            return eligible_users()
        return self.cleaned_data["users"]


class ComposeForm(AudienceForm):
    title = forms.CharField(
        label="عنوان الإشعار", max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "مثال: الغداء متاح الآن"}),
    )
    body = forms.CharField(
        label="نص الإشعار", max_length=600,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    menu = MenuChoiceField(label="ربط بوجبة — اختياري", queryset=None, required=False)
    token = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["menu"].queryset = DailyMenu.objects.filter(
            date__gte=timezone.localdate() - timedelta(days=7),
        ).order_by("-date", "meal_type")


class AutoAudienceForm(AudienceForm):
    enabled = forms.BooleanField(label="إرسال تلقائي عند الفتح والإغلاق", required=False)
